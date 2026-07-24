"""Session-scoped state tracking across PostToolUse calls.

Maintains a lightweight JSON file to track recent errors so that when a
fix arrives (Edit/Write), the error-fix pair can be saved as a solution memory.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

SPOOL_DIR = Path(__file__).parent / "spool"
STATE_FILE = SPOOL_DIR / "session_state.json"
MAX_RECENT_ERRORS = 5
MAX_FIX_DISTANCE = 3  # tool calls between error and fix for proximity fallback

ERROR_PATTERNS = [
    re.compile(r"(?i)(traceback|exception|error|failed|fatal|panic)"),
    re.compile(r"(?i)\b(FAIL|FAILED|ERROR)\b"),
    re.compile(r"exit code [1-9]"),
    re.compile(r"(?i)command not found"),
    re.compile(r"(?i)permission denied"),
    re.compile(r"(?i)(ModuleNotFoundError|ImportError|SyntaxError|TypeError|ValueError|KeyError|AttributeError|FileNotFoundError)"),
]

SKIP_BASH_PATTERNS = [
    re.compile(r"^(ls|cat|head|tail|grep|find|wc|echo|pwd|cd|which|type|file)\b"),
    re.compile(r"^git\s+(status|log|diff|show|branch|remote)\b"),
    re.compile(r"^(python3?|node)\s+-c\b"),
    re.compile(r"^curl\s+-s\b.*\bstats\b"),
]

SKIP_FILE_PATTERNS = [
    re.compile(r"package-lock\.json$"),
    re.compile(r"\.d\.ts$"),
    re.compile(r"\.(log|tmp|bak)$"),
    re.compile(r"\.pyc$"),
    re.compile(r"node_modules/"),
    re.compile(r"__pycache__/"),
    re.compile(r"\.DS_Store$"),
]

ACTION_CONFIDENCE = {
    "error_fix": 0.9,
    "test_pass": 0.85,
    "session_error_fix": 0.85,
    "session_decision": 0.7,
    "write_source": 0.5,
    "edit_group": 0.5,
    "agent": 0.6,
}


def _empty_state() -> dict:
    return {
        "session_id": "",
        "recent_errors": [],
        "pending_test_failure": False,
        "tool_count": 0,
        "saved_count": 0,
        "stats_cache": {"n": 0, "ts": 0.0},
        "edit_groups": {},
    }


def load_state() -> dict:
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return _empty_state()


def save_state(state: dict) -> None:
    SPOOL_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    tmp.rename(STATE_FILE)


def clear_state() -> None:
    try:
        STATE_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def record_error(state: dict, tool_name: str, snippet: str, command: str = "") -> dict:
    state["recent_errors"].append({
        "tool": tool_name,
        "error_snippet": snippet[:300],
        "command": command[:200],
        "tool_count_at": state["tool_count"],
    })
    if len(state["recent_errors"]) > MAX_RECENT_ERRORS:
        state["recent_errors"] = state["recent_errors"][-MAX_RECENT_ERRORS:]
    return state


def pop_matching_error(state: dict, file_path: str) -> dict | None:
    if not state["recent_errors"]:
        return None
    stem = Path(file_path).stem.lower()
    name = Path(file_path).name.lower()

    # Match by file stem appearing in error snippet
    for i, err in enumerate(state["recent_errors"]):
        snippet_lower = err["error_snippet"].lower()
        if stem in snippet_lower or name in snippet_lower:
            return state["recent_errors"].pop(i)

    # Proximity fallback: most recent error within MAX_FIX_DISTANCE tool calls
    current = state["tool_count"]
    for i in range(len(state["recent_errors"]) - 1, -1, -1):
        err = state["recent_errors"][i]
        if current - err["tool_count_at"] <= MAX_FIX_DISTANCE:
            return state["recent_errors"].pop(i)

    return None


def is_error_response(response: str) -> bool:
    for pat in ERROR_PATTERNS:
        if pat.search(response):
            return True
    return False


def is_skip_bash(command: str) -> bool:
    cmd = command.strip()
    for pat in SKIP_BASH_PATTERNS:
        if pat.search(cmd):
            return True
    return False


def is_skip_file(file_path: str) -> bool:
    for pat in SKIP_FILE_PATTERNS:
        if pat.search(file_path):
            return True
    return False


def is_test_pass(response: str) -> bool:
    return bool(re.search(r"(?i)\b(passed|(\d+)\s+passed|tests?\s+ok|all\s+green)\b", response))


MAX_EDIT_CHANGES = 10
EDIT_FLUSH_THRESHOLD = 2  # flush after N consecutive non-edit tool calls


def record_edit(state: dict, file_path: str, old_str: str, new_str: str) -> None:
    """Track an Edit operation for grouped saving."""
    groups = state.setdefault("edit_groups", {})
    if file_path not in groups:
        groups[file_path] = {"changes": [], "first_at": state["tool_count"]}
    changes = groups[file_path]["changes"]
    old_preview = (old_str or "")[:80].replace("\n", " ")
    new_preview = (new_str or "")[:80].replace("\n", " ")
    if len(changes) < MAX_EDIT_CHANGES:
        changes.append(f"- {old_preview} → {new_preview}")


def _summarize_edit_group(file_path: str, changes: list[str]) -> tuple[str, str]:
    """LLM call to produce a meaningful title and summary for grouped edits."""
    name = Path(file_path).name
    n = len(changes)
    changes_text = "\n".join(changes)
    fallback_title = f"{n} edit{'s' if n > 1 else ''} to {name}"
    fallback_content = f"Edited {file_path} ({n} change{'s' if n > 1 else ''}):\n{changes_text}"

    try:
        from brain.core.summarizer import _openrouter_chat, SUMMARIZE_MODEL
        raw = _openrouter_chat(SUMMARIZE_MODEL, [{
            "role": "user",
            "content": f"""You are summarizing code edits to a file for a memory system.

File: {file_path}
Changes ({n}):
{changes_text}

Return ONLY valid JSON:
{{
  "title": "concise description of what was done and why (max 80 chars)",
  "summary": "1-2 sentence explanation of the change purpose and impact (max 300 chars)"
}}

Rules:
- Title should describe the PURPOSE, not just "edited X" (e.g. "Added cubic barrier for corpus self-regulation" not "3 edits to corpus_barrier.py")
- Summary should explain WHY this change matters
- Both must be single-line strings, no newlines"""
        }], max_tokens=256)

        import json as _json
        parsed = _json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
        title = str(parsed.get("title", fallback_title))[:80]
        summary = str(parsed.get("summary", ""))[:300]
        content = f"{summary}\n\nFile: {file_path}\nChanges:\n{changes_text}"
        return title, content
    except Exception:
        return fallback_title, fallback_content


def flush_edit_groups(state: dict) -> list[tuple[str, str, str]]:
    """Flush edit groups idle for EDIT_FLUSH_THRESHOLD tool calls.

    Uses LLM to generate contextual titles and summaries.
    """
    groups = state.get("edit_groups", {})
    current = state["tool_count"]
    to_flush: list[tuple[str, str, str]] = []
    to_remove: list[str] = []

    for fp, group in groups.items():
        last_edit_at = group.get("first_at", 0) + len(group["changes"])
        idle = current - last_edit_at
        if idle >= EDIT_FLUSH_THRESHOLD:
            title, content = _summarize_edit_group(fp, group["changes"])
            to_flush.append((fp, content, title))
            to_remove.append(fp)

    for fp in to_remove:
        del groups[fp]

    return to_flush


def flush_all_edit_groups(state: dict) -> list[tuple[str, str, str]]:
    """Flush ALL pending edit groups. Called at session end. Uses LLM for titles."""
    groups = state.get("edit_groups", {})
    result: list[tuple[str, str, str]] = []

    for fp, group in groups.items():
        changes = group["changes"]
        if not changes:
            continue
        title, content = _summarize_edit_group(fp, changes)
        result.append((fp, content, title))

    state["edit_groups"] = {}
    return result


def get_cached_corpus_size(state: dict) -> int:
    cache = state.get("stats_cache", {"n": 0, "ts": 0.0})
    if time.time() - cache["ts"] < 60.0:
        return cache["n"]
    try:
        from brain.api_client import get_stats
        n = get_stats().get("total_memories", 0)
    except Exception:
        n = 0
    state["stats_cache"] = {"n": n, "ts": time.time()}
    return n
