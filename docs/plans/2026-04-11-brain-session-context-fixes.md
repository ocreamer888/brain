# Brain Session Context Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the session start loading irrelevant memories by adding session summaries, recency, timestamps, and a smarter query.

**Architecture:** At Stop, generate a 3-5 line session summary and save it as a `project_context` memory tagged `session_summary`. At SessionStart, always inject the last 3 summaries for the current project first, then run semantic search using the last summary as the query (not the folder name). Show timestamps on all memories so Claude can reason about staleness.

**Tech Stack:** Python, `brain/core/summarizer.py` (Anthropic Haiku), `brain/api_client.py` (`/save` + `/search`), `~/.claude/settings.json` hooks.

**Important constraints:**
- The Rust brain API `MemoryType` enum only accepts: `solution`, `decision`, `conversation`, `pattern`, `project_context`, `error_lesson`. Use `project_context` + tag `session_summary` for session summaries — do NOT invent a new type.
- `metadata.timestamp` in search results is a RFC3339 string (ISO 8601). Parse with `datetime.fromisoformat()`.
- `session_end.py` and `session_start.py` are called by Claude Code hooks — never crash, always wrap in try/except.
- The Python backend path uses `brain.core.memory.save_memory`. The API backend path uses `brain.api_client.save_memory`. Check `backend_mode()` — but the existing code pattern handles this; just follow the pattern in `session_end.py`.

---

## Task 1: Add `summarize_session` to `brain/core/summarizer.py`

**Files:**
- Modify: `brain/core/summarizer.py`

This adds a new function that takes a list of raw messages and returns a structured dict with `text`, `decisions`, and `next_steps`. Reuses the existing `SUMMARIZE_MODEL` (Haiku) and `get_client()`.

**Step 1: Write the failing test**

Create `brain/tests/test_summarizer_session.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from unittest.mock import patch, MagicMock
from brain.core.summarizer import summarize_session


def test_summarize_session_returns_required_keys():
    """summarize_session must return dict with text, decisions, next_steps."""
    fake_response = MagicMock()
    fake_response.content = [MagicMock(text='{"text": "Worked on brain fixes.", "decisions": ["Use project_context type"], "next_steps": ["Ship it"]}')]

    with patch("brain.core.summarizer.get_client") as mock_client:
        mock_client.return_value.messages.create.return_value = fake_response
        messages = [
            {"role": "user", "content": "fix the session start"},
            {"role": "assistant", "content": "done"},
        ]
        result = summarize_session(messages)

    assert "text" in result
    assert "decisions" in result
    assert "next_steps" in result
    assert isinstance(result["decisions"], list)
    assert isinstance(result["next_steps"], list)


def test_summarize_session_handles_empty_messages():
    """summarize_session must not crash on empty message list."""
    fake_response = MagicMock()
    fake_response.content = [MagicMock(text='{"text": "No activity.", "decisions": [], "next_steps": []}')]

    with patch("brain.core.summarizer.get_client") as mock_client:
        mock_client.return_value.messages.create.return_value = fake_response
        result = summarize_session([])

    assert result["text"] == "No activity."
```

**Step 2: Run test to verify it fails**

```bash
cd /Users/macm1air/Documents/AI
python3 -m pytest brain/tests/test_summarizer_session.py -v
```

Expected: `ImportError` or `AttributeError` — `summarize_session` does not exist yet.

**Step 3: Implement `summarize_session`**

Add to `brain/core/summarizer.py` after the existing `summarize_exchange` function:

```python
def summarize_session(messages: list[dict]) -> dict:
    """Summarize a full session into a short human-readable summary + structured fields."""
    formatted_parts = []
    for m in messages[:40]:
        content = m.get("content", "")
        if isinstance(content, list):
            content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
        role = m.get("role", m.get("type", "unknown"))
        formatted_parts.append(f"{role}: {str(content)[:600]}")
    formatted = "\n".join(formatted_parts) if formatted_parts else "(empty session)"

    response = get_client().messages.create(
        model=SUMMARIZE_MODEL,
        max_tokens=512,
        messages=[{
            "role": "user",
            "content": f"""Summarize this Claude Code session for future reference.

SESSION:
{formatted}

Respond with ONLY valid JSON (no markdown):
{{
  "text": "2-4 sentence summary of what was worked on and accomplished",
  "decisions": ["key decision made (if any)"],
  "next_steps": ["open item or next step (if any)"]
}}"""
        }]
    )
    return _parse_json(response.content[0].text)
```

**Step 4: Run test to verify it passes**

```bash
python3 -m pytest brain/tests/test_summarizer_session.py -v
```

Expected: 2 tests PASS.

**Step 5: Commit**

```bash
git add brain/core/summarizer.py brain/tests/test_summarizer_session.py
git commit -m "feat(brain): add summarize_session to summarizer"
```

---

## Task 2: Save session summary at session end

**Files:**
- Modify: `brain/hooks/session_end.py`

At the end of the Stop hook, after the existing transcript export and reflection, generate a session summary and save it as a `project_context` memory tagged `session_summary`. The title includes date + project so it's easy to retrieve and display.

**Step 1: Write the failing test**

Create `brain/tests/test_session_end_summary.py`:

```python
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from unittest.mock import patch, MagicMock, mock_open


def _run_save_session_summary(messages, project, session_id, ended_at):
    """Extract and call just the summary-saving logic we'll add."""
    from brain.hooks.session_end import save_session_summary
    save_session_summary(messages=messages, project=project, session_id=session_id, ended_at=ended_at)


def test_save_session_summary_calls_save_memory():
    """save_session_summary must call save_memory with correct type and tag."""
    fake_summary = {"text": "Worked on brain.", "decisions": ["Use project_context"], "next_steps": []}

    with patch("brain.core.summarizer.get_client"), \
         patch("brain.hooks.session_end.summarize_session", return_value=fake_summary) as mock_sum, \
         patch("brain.hooks.session_end.save_memory_fn") as mock_save:

        _run_save_session_summary(
            messages=[{"role": "user", "content": "hi"}],
            project="AI",
            session_id="abc-123",
            ended_at="2026-04-11T10:00:00+00:00",
        )

        mock_save.assert_called_once()
        call_kwargs = mock_save.call_args[1]
        assert call_kwargs["memory_type"] == "project_context"
        assert "session_summary" in call_kwargs["tags"]
        assert "2026-04-11" in call_kwargs["title"]
        assert "AI" in call_kwargs["title"]
```

**Step 2: Run test to verify it fails**

```bash
python3 -m pytest brain/tests/test_session_end_summary.py -v
```

Expected: `ImportError` — `save_session_summary` doesn't exist yet in `session_end.py`.

**Step 3: Implement in `session_end.py`**

Read `brain/hooks/session_end.py` first. Then add the following changes:

At the top of the file, add imports after the existing ones:
```python
from brain.core.summarizer import summarize_session
```

Add this function near the top (before `if __name__` or `if __name__ == "__main__"`):
```python
def save_memory_fn(**kwargs):
    """Thin wrapper so tests can patch it easily."""
    from brain.api_client import backend_mode, save_memory as api_save
    from brain.core.memory import save_memory as py_save
    if backend_mode() == "python":
        return py_save(**kwargs)
    return api_save(**kwargs)


def save_session_summary(*, messages: list, project: str, session_id: str, ended_at: str):
    """Generate a session summary and persist it as a project_context memory."""
    try:
        summary = summarize_session(messages)
    except Exception:
        return  # non-fatal

    lines = [summary.get("text", "")]
    decisions = summary.get("decisions", [])
    next_steps = summary.get("next_steps", [])
    if decisions:
        lines.append("Decisions: " + "; ".join(decisions))
    if next_steps:
        lines.append("Next: " + "; ".join(next_steps))
    content = "\n".join(lines)

    # Extract date for title (ended_at is RFC3339)
    try:
        date_str = ended_at[:10]  # "YYYY-MM-DD"
    except Exception:
        date_str = "unknown-date"

    try:
        save_memory_fn(
            content=content,
            memory_type="project_context",
            tags=["session_summary", project],
            project=project,
            session_id=session_id,
            source="claude_code_session",
            title=f"Session {date_str} — {project}",
        )
    except Exception:
        pass  # non-fatal
```

At the end of the existing `on_session_end` / main logic, after reflection, call:
```python
save_session_summary(
    messages=messages,  # the list already parsed from transcript
    project=project,
    session_id=session_id,
    ended_at=ended_at,
)
```

Look at the existing code to find where `messages`, `project`, `session_id`, and `ended_at` are available and insert the call there.

**Step 4: Run test to verify it passes**

```bash
python3 -m pytest brain/tests/test_session_end_summary.py -v
```

Expected: 1 test PASS.

**Step 5: Verify existing session_end behavior still works**

```bash
echo '{"session_id":"test-123","transcript_path":"/nonexistent","cwd":"/Users/macm1air/Documents/AI","ended_at":"2026-04-11T00:00:00+00:00"}' | python3 brain/hooks/session_end.py
```

Expected: Exits without crashing (transcript_path doesn't exist so no messages, but no exception).

**Step 6: Commit**

```bash
git add brain/hooks/session_end.py brain/tests/test_session_end_summary.py
git commit -m "feat(brain): save session summary on stop hook"
```

---

## Task 3: Enhance SessionStart — summaries, timestamps, better query

**Files:**
- Modify: `brain/hooks/session_start.py`

Three changes in one file:
1. Always inject last 3 session summaries for the current project (retrieved by `memory_type=project_context` + tag filter `session_summary`)
2. Show timestamps (`YYYY-MM-DD`) on every memory line
3. Use the last session summary text as the semantic query instead of `project_hint`

**Step 1: Write the failing test**

Create `brain/tests/test_session_start_enhanced.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from brain.hooks.session_start import (
    extract_date,
    filter_session_summaries,
    build_query,
)


def test_extract_date_from_rfc3339():
    assert extract_date("2026-04-11T10:30:00+00:00") == "2026-04-11"


def test_extract_date_fallback():
    assert extract_date("") == "unknown"
    assert extract_date(None) == "unknown"


def test_filter_session_summaries_keeps_only_tagged():
    memories = [
        {"content": "summary A", "metadata": {"tags": "session_summary,AI", "timestamp": "2026-04-11T00:00:00Z"}},
        {"content": "unrelated", "metadata": {"tags": "bash,AI", "timestamp": "2026-04-10T00:00:00Z"}},
        {"content": "summary B", "metadata": {"tags": "session_summary,AI", "timestamp": "2026-04-09T00:00:00Z"}},
    ]
    result = filter_session_summaries(memories)
    assert len(result) == 2
    assert all("session_summary" in m["metadata"]["tags"] for m in result)


def test_filter_session_summaries_sorted_newest_first():
    memories = [
        {"content": "old", "metadata": {"tags": "session_summary", "timestamp": "2026-04-09T00:00:00Z"}},
        {"content": "new", "metadata": {"tags": "session_summary", "timestamp": "2026-04-11T00:00:00Z"}},
    ]
    result = filter_session_summaries(memories)
    assert result[0]["content"] == "new"


def test_build_query_uses_summary_text():
    summaries = [
        {"content": "Fixed session context in brain.", "metadata": {"timestamp": "2026-04-11T00:00:00Z"}},
    ]
    query = build_query(summaries, fallback="general")
    assert query == "Fixed session context in brain."


def test_build_query_falls_back_when_no_summaries():
    query = build_query([], fallback="general")
    assert query == "general"
```

**Step 2: Run test to verify it fails**

```bash
python3 -m pytest brain/tests/test_session_start_enhanced.py -v
```

Expected: `ImportError` — these helpers don't exist yet.

**Step 3: Implement helpers and update `session_start.py`**

Read `brain/hooks/session_start.py` in full first. Then replace its content with the updated version below. The key additions are:
- Three helper functions at the top (`extract_date`, `filter_session_summaries`, `build_query`)
- Updated main block that fetches summaries, uses better query, and shows timestamps

```python
#!/usr/bin/env python3
"""
SessionStart hook — loads relevant context from brain at session start.
"""
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

PROJECT_DIR_MAP = {
    "lifehub": "lifehub",
    "LifeHub": "lifehub",
    "wealth": "wealth",
    "Wealth": "wealth",
    "le-chandelier": "le_chandelier",
    "Le Chandelier": "le_chandelier",
    "lechandelier": "le_chandelier",
    "meddefi": "meddefi",
    "MedDeFi": "meddefi",
    "ocreamer": "ocreamer",
    "OCREAMER": "ocreamer",
    "owelign": "owelign",
    "OWELIGN": "owelign",
    "qol": "qol",
    "QOL": "qol",
    "rmt": "rmt",
    "RMT": "rmt",
    "sicop": "sicop",
    "SICOP": "sicop",
    "tayasal": "tayasal",
    "Tayasal": "tayasal",
    "scheduler": "scheduler",
    "inventario": "inventario",
    "AI": "general",
}


def detect_project(cwd: str) -> str | None:
    parts = Path(cwd).parts
    for part in reversed(parts):
        if part in PROJECT_DIR_MAP:
            return PROJECT_DIR_MAP[part]
    return None


def extract_date(timestamp: str | None) -> str:
    """Extract YYYY-MM-DD from an RFC3339 timestamp string."""
    if not timestamp:
        return "unknown"
    try:
        return str(timestamp)[:10]
    except Exception:
        return "unknown"


def filter_session_summaries(memories: list) -> list:
    """Return only session_summary-tagged memories, sorted newest first."""
    summaries = [
        m for m in memories
        if "session_summary" in (m.get("metadata", {}).get("tags") or "")
    ]
    summaries.sort(
        key=lambda m: m.get("metadata", {}).get("timestamp", ""),
        reverse=True,
    )
    return summaries


def build_query(summaries: list, fallback: str) -> str:
    """Use last session summary text as query; fall back to provided string."""
    if summaries:
        return summaries[0]["content"].split("\n")[0][:300]
    return fallback


# ── Background recovery ──────────────────────────────────────────────────────
try:
    import subprocess
    _recovery_script = Path(__file__).resolve().parents[1] / "bootstrap" / "10_ingest_missed_sessions.py"
    if _recovery_script.exists():
        subprocess.Popen(
            [sys.executable, str(_recovery_script)],
            cwd=str(Path(__file__).resolve().parents[2]),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
except Exception:
    pass

# ── Main context injection ───────────────────────────────────────────────────
try:
    cwd = os.getcwd()
    project = detect_project(cwd)
    project_hint = project or Path(cwd).name

    from brain.api_client import search, get_stats

    # 1. Fetch recent session summaries for this project
    raw_summaries = search(query="session summary", n=20, memory_type="project_context", project=project_hint)
    recent_summaries = filter_session_summaries(raw_summaries)[:3]

    # 2. Build a smarter semantic query from last summary
    semantic_query = build_query(recent_summaries, fallback=project_hint)

    # 3. Run semantic search with the better query
    semantic_mems = []
    if project and project != "general":
        semantic_mems.extend(search(query=semantic_query, n=5, project=project))
    general_mems = search(query=semantic_query, n=5)
    seen = {m["content"][:80] for m in recent_summaries + semantic_mems}
    for m in general_mems:
        if m["content"][:80] not in seen:
            semantic_mems.append(m)
            seen.add(m["content"][:80])
    # Exclude summaries from semantic block (already shown above)
    semantic_mems = [
        m for m in semantic_mems
        if "session_summary" not in (m.get("metadata", {}).get("tags") or "")
    ][:5]

    stats = get_stats()

    # 4. Print recent sessions block
    if recent_summaries:
        print(f"\n[BRAIN] Recent sessions for '{project_hint}':")
        for i, m in enumerate(recent_summaries, 1):
            date = extract_date(m["metadata"].get("timestamp"))
            title = m["metadata"].get("title") or f"Session {date}"
            print(f"  [S{i}] ({date}) {title}")
            for line in m["content"].split("\n")[:4]:
                if line.strip():
                    print(f"       {line.strip()}")
        print()

    # 5. Print semantic memories with timestamps
    if semantic_mems:
        print(f"[BRAIN] Relevant memories for '{project_hint}':")
        for i, m in enumerate(semantic_mems, 1):
            meta = m["metadata"]
            src = meta.get("source", "")
            src_label = f" [{src}]" if src else ""
            date = extract_date(meta.get("timestamp"))
            mem_type = meta.get("type", "?")
            print(f"  [{i}] ({mem_type}, {date}{src_label}) {m['content'][:200]}")
        print()

    print(f"[BRAIN] Total: {stats['total_memories']} memories | {stats['total_sessions']} sessions\n")

except Exception as e:
    print(f"[BRAIN] Context load failed (non-fatal): {e}", file=sys.stderr)
```

**Step 4: Run test to verify it passes**

```bash
python3 -m pytest brain/tests/test_session_start_enhanced.py -v
```

Expected: 6 tests PASS.

**Step 5: Smoke test the hook manually**

```bash
cd /Users/macm1air/Documents/AI
python3 brain/hooks/session_start.py
```

Expected: Output starts with `[BRAIN] Recent sessions for '...'` (or falls back gracefully if API is down).

**Step 6: Commit**

```bash
git add brain/hooks/session_start.py brain/tests/test_session_start_enhanced.py
git commit -m "feat(brain): session start shows summaries, timestamps, and uses smarter query"
```

---

## Final verification

Run the full brain test suite to confirm no regressions:

```bash
cd /Users/macm1air/Documents/AI
python3 -m pytest brain/tests/ -v --tb=short 2>&1 | tail -20
```

Expected: All tests pass (new + existing).

Then open a new Claude Code session in this repo and confirm the `[BRAIN]` header shows recent sessions with dates instead of random Perplexity/book chunks.
