#!/usr/bin/env python3
"""Cursor hook adapter — translate Cursor stdin JSON into Brain Claude-style hooks.

Cursor and Claude Code send different payloads. This process:
  1. Reads Cursor hook JSON on stdin
  2. Maps it onto session_start / user_prompt_submit / post_tool_use / session_end
  3. Prints Cursor-legal JSON on stdout (never block the agent)

Logs go to stderr only. Always exit 0.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent
SPOOL_DIR = HOOKS_DIR / "spool"
INJECT_FILE = SPOOL_DIR / "cursor_inject.json"

TOOL_NAME_MAP = {
    "Shell": "Bash",
    "Bash": "Bash",
    "Write": "Write",
    "Edit": "Edit",
    "TabWrite": "Edit",
    "Task": "Agent",
    "Agent": "Agent",
}

# Cursor events that should not ingest (policy / noise / duplicates).
SKIP_EVENTS = {
    "preToolUse",
    "beforeShellExecution",
    "beforeMCPExecution",
    "beforeReadFile",
    "beforeTabFileRead",
    "afterMCPExecution",
    "afterShellExecution",  # covered by postToolUse Shell
    "afterAgentThought",
    "afterAgentResponse",
    "preCompact",
    "workspaceOpen",
    "stop",  # per-turn; sessionEnd owns the summary
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_cwd(ctx: dict) -> str:
    cwd = ctx.get("cwd")
    if isinstance(cwd, str) and cwd:
        return cwd
    roots = ctx.get("workspace_roots") or []
    if isinstance(roots, list) and roots:
        return str(roots[0])
    return os.getcwd()


def resolve_session_id(ctx: dict) -> str:
    for key in ("session_id", "conversation_id"):
        val = ctx.get(key)
        if isinstance(val, str) and val:
            return val
    return "unknown"


def event_name(ctx: dict) -> str:
    name = ctx.get("hook_event_name") or ctx.get("event_name") or ""
    if isinstance(name, str) and name:
        return name
    if "prompt" in ctx and "tool_name" not in ctx:
        return "beforeSubmitPrompt"
    if "edits" in ctx and "file_path" in ctx:
        return "afterFileEdit"
    if "tool_output" in ctx or "tool_use_id" in ctx:
        return "postToolUse"
    if ctx.get("reason") and "session_id" in ctx:
        return "sessionEnd"
    if ctx.get("composer_mode") is not None or ctx.get("is_background_agent") is not None:
        return "sessionStart"
    return ""


def _as_dict(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip().startswith("{"):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


def _tool_response(ctx: dict, fallback: str = "") -> str:
    for key in ("tool_response", "tool_output", "output", "result_json", "error_message"):
        val = ctx.get(key)
        if val is None:
            continue
        if isinstance(val, (dict, list)):
            return json.dumps(val)[:4000]
        text = str(val)
        if text:
            return text[:4000]
    return fallback


def normalize_tool_input(ctx: dict, tool_name: str) -> dict:
    tool_input = _as_dict(ctx.get("tool_input"))
    if "path" in tool_input and "file_path" not in tool_input:
        tool_input["file_path"] = tool_input["path"]
    if "contents" in tool_input and "content" not in tool_input:
        tool_input["content"] = tool_input["contents"]
    if tool_name == "Bash" and "command" not in tool_input and ctx.get("command"):
        tool_input["command"] = ctx["command"]
    if tool_name == "Edit":
        if not tool_input.get("file_path") and ctx.get("file_path"):
            tool_input["file_path"] = ctx["file_path"]
        edits = ctx.get("edits") or tool_input.get("edits") or []
        if isinstance(edits, list) and edits:
            first = edits[0] if isinstance(edits[0], dict) else {}
            tool_input.setdefault("old_string", first.get("old_string", ""))
            tool_input.setdefault("new_string", first.get("new_string", ""))
    return tool_input


def claude_post_tool(ctx: dict, *, tool_name: str | None = None, tool_response: str | None = None) -> dict:
    mapped = TOOL_NAME_MAP.get(tool_name or ctx.get("tool_name") or "", tool_name or ctx.get("tool_name") or "")
    return {
        "tool_name": mapped,
        "tool_input": normalize_tool_input(ctx, mapped),
        "tool_response": tool_response if tool_response is not None else _tool_response(ctx),
        "cwd": resolve_cwd(ctx),
        "session_id": resolve_session_id(ctx),
    }


def claude_session_end(ctx: dict) -> dict:
    return {
        "session_id": resolve_session_id(ctx),
        "transcript_path": ctx.get("transcript_path") or ctx.get("agent_transcript_path"),
        "cwd": resolve_cwd(ctx),
        "ended_at": ctx.get("ended_at") or _now(),
        "hook_event_name": "Stop",
    }


def claude_prompt(ctx: dict) -> dict:
    return {
        "prompt": ctx.get("prompt") or "",
        "session_id": resolve_session_id(ctx),
        "cwd": resolve_cwd(ctx),
    }


def dump_out(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.write("\n")
    sys.stdout.flush()


def _stash_inject(session_id: str, text: str) -> None:
    if not text.strip():
        return
    SPOOL_DIR.mkdir(parents=True, exist_ok=True)
    INJECT_FILE.write_text(
        json.dumps({"session_id": session_id, "text": text.strip(), "ts": _now()}),
        encoding="utf-8",
    )


def _pop_inject(session_id: str) -> str:
    try:
        if not INJECT_FILE.exists():
            return ""
        data = json.loads(INJECT_FILE.read_text(encoding="utf-8"))
        if data.get("session_id") and data.get("session_id") != session_id:
            return ""
        INJECT_FILE.unlink(missing_ok=True)
        return str(data.get("text") or "")
    except Exception:
        return ""


def run_brain_hook(script: str, payload: dict, cwd: str) -> str:
    hook_path = HOOKS_DIR / script
    env = os.environ.copy()
    env.setdefault("BRAIN_HOOK_SOURCE", "cursor_hook")
    proc = subprocess.run(
        [sys.executable, str(hook_path)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=cwd or None,
        env=env,
        timeout=120,
    )
    if proc.stderr:
        sys.stderr.write(proc.stderr)
        if not proc.stderr.endswith("\n"):
            sys.stderr.write("\n")
    if proc.returncode not in (0, None):
        print(f"[BRAIN] cursor adapter: {script} exit={proc.returncode}", file=sys.stderr)
    return proc.stdout or ""


def handle(ctx: dict) -> dict:
    event = event_name(ctx)
    cwd = resolve_cwd(ctx)
    session_id = resolve_session_id(ctx)

    if event in SKIP_EVENTS or not event:
        return {}

    if event == "sessionStart":
        text = run_brain_hook("session_start.py", ctx, cwd).strip()
        return {"additional_context": text} if text else {}

    if event == "beforeSubmitPrompt":
        text = run_brain_hook("user_prompt_submit.py", claude_prompt(ctx), cwd).strip()
        _stash_inject(session_id, text)
        return {"continue": True}

    if event == "sessionEnd":
        run_brain_hook("session_end.py", claude_session_end(ctx), cwd)
        return {}

    if event in ("afterFileEdit", "afterTabFileEdit"):
        payload = claude_post_tool(ctx, tool_name="Edit")
        run_brain_hook("post_tool_use.py", payload, cwd)
        return {}

    if event == "postToolUseFailure":
        payload = claude_post_tool(
            ctx,
            tool_response=_tool_response(ctx, fallback="tool failed"),
        )
        if payload["tool_name"] not in {"Bash", "Write", "Edit", "Agent"}:
            payload["tool_name"] = "Bash"
            payload["tool_input"].setdefault("command", ctx.get("tool_name") or "unknown")
        run_brain_hook("post_tool_use.py", payload, cwd)
        return {}

    if event == "subagentStart":
        payload = claude_post_tool(
            {
                **ctx,
                "tool_name": "Agent",
                "tool_input": {"description": ctx.get("task") or ctx.get("description") or ""},
            }
        )
        run_brain_hook("post_tool_use.py", payload, cwd)
        return {}

    if event == "subagentStop":
        if ctx.get("status") in {"error", "aborted"}:
            payload = claude_post_tool(
                {
                    **ctx,
                    "tool_name": "Agent",
                    "tool_input": {"description": ctx.get("task") or ctx.get("description") or ""},
                    "tool_response": ctx.get("summary") or ctx.get("status") or "subagent failed",
                }
            )
            run_brain_hook("post_tool_use.py", payload, cwd)
        return {}

    if event == "postToolUse":
        payload = claude_post_tool(ctx)
        if payload["tool_name"] not in {"Bash", "Write", "Edit", "Agent"}:
            extra = _pop_inject(session_id)
            return {"additional_context": extra} if extra else {}
        run_brain_hook("post_tool_use.py", payload, cwd)
        extra = _pop_inject(session_id)
        return {"additional_context": extra} if extra else {}

    return {}


def main() -> int:
    try:
        raw = sys.stdin.read()
        ctx = json.loads(raw) if raw.strip() else {}
        if not isinstance(ctx, dict):
            dump_out({})
            return 0
        dump_out(handle(ctx))
    except Exception as e:
        print(f"[BRAIN] Cursor adapter failed (non-fatal): {e}", file=sys.stderr)
        dump_out({})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
