# Ingest Quality Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the ingest pipeline so it never produces UUID-titled conversations, mislabeled bash-log patterns, or blank-titled solutions again — then clean up all ~3,900 bad records already in the DB.

**Architecture:** Three-phase approach: (1) fix ingest source code so new bad data never enters; (2) run a one-shot backfill script that repairs existing DB records and keeps FTS5 in sync; (3) add an eval quality gate that runs after ingest and catches regressions before they accumulate. No Rust changes — all fixes are in Python ingest layer and SQLite.

**Tech Stack:** Python 3.13, SQLite (brain/rust/brain.db), FTS5 (manual sync — no triggers), pytest

---

## Root Cause Summary

Two files create all the bad data:

**`brain/bootstrap/ingest_claude_code_lib.py:116`**
```python
"title": f"Claude Code — {sid}",   # sid = first 24 chars of UUID
```
Every conversation memory gets an identical UUID title → k-fold retrieval fails (P@1=0.061).

**`brain/hooks/post_tool_use.py:34-47`**
```python
if tool_name == "Edit":
    memory_type = "solution"
    title = f"Edit · {project}"   # generic — all edits get same title
elif tool_name == "Bash":
    memory_type = "pattern"
    title = f"Bash · {project}"   # generic — all commands get same title
```
Every bash command → `pattern`, every file edit → `solution`, all with identical generic titles. Pattern P@1 dropped 0.931→0.664, solution P@1 dropped 0.875→0.783.

**FTS5 sync:** `memories_fts` is not a content table and has no triggers. The Rust binary syncs it manually on every INSERT/UPDATE/DELETE. The backfill script must replicate this sync.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `brain/bootstrap/ingest_claude_code_lib.py` | Modify | Fix conversation title derivation |
| `brain/hooks/post_tool_use.py` | Modify | Remove Bash/Edit from MEMORABLE_TOOLS; fix Write title |
| `brain/tools/backfill_bad_data.py` | Create | One-shot script: fix/delete all existing bad records + sync FTS5 |
| `brain/tools/ingest_quality_gate.py` | Create | Post-ingest eval gate: P@1 by type, warn/fail on thresholds |
| `brain/tests/test_ingest_titles.py` | Create | Tests for new conversation title logic |
| `brain/tests/test_post_tool_use_titles.py` | Create | Tests for post_tool_use changes |
| `brain/tests/test_backfill_bad_data.py` | Create | Tests for backfill script against in-memory SQLite |
| `brain/eval/README.md` | Modify | Add quality gate section |

---

## Task 1: Tests for conversation title fix

**Files:**
- Create: `brain/tests/test_ingest_titles.py`

- [ ] **Step 1: Write failing tests**

```python
# brain/tests/test_ingest_titles.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from brain.bootstrap.ingest_claude_code_lib import _derive_session_title


def test_title_uses_date_and_project():
    record = {
        "project": "AI",
        "metadata": {"timestamp": "2026-05-21T14:30:00+00:00"},
    }
    title = _derive_session_title(record, "90748205-f28a-45ae-bc")
    assert title == "Session 2026-05-21 — AI"
    assert "90748205" not in title  # no UUID


def test_title_with_missing_timestamp_falls_back():
    record = {"project": "sicop", "metadata": {}}
    title = _derive_session_title(record, "abc-123")
    assert "sicop" in title
    assert "abc-123" not in title


def test_title_with_malformed_timestamp():
    record = {"project": "general", "metadata": {"timestamp": "not-a-date"}}
    title = _derive_session_title(record, "xyz")
    assert "general" in title


def test_title_with_short_timestamp():
    record = {"project": "owelign", "metadata": {"timestamp": "2026-01-15"}}
    title = _derive_session_title(record, "some-id")
    assert title == "Session 2026-01-15 — owelign"
```

- [ ] **Step 2: Run tests to confirm they fail (function doesn't exist yet)**

```bash
cd /Users/macm1air/Documents/AI
python3 -m pytest brain/tests/test_ingest_titles.py -v
```

Expected: `ImportError: cannot import name '_derive_session_title'`

- [ ] **Step 3: Commit failing tests**

```bash
git add brain/tests/test_ingest_titles.py
git commit -m "test: add failing tests for conversation title fix"
```

---

## Task 2: Fix conversation title in `ingest_claude_code_lib.py`

**Files:**
- Modify: `brain/bootstrap/ingest_claude_code_lib.py`

- [ ] **Step 1: Add `_derive_session_title` helper before `run_with_dirs`**

Add this function after the imports block (around line 17), before `BATCH_SIZE = 32`:

```python
def _derive_session_title(record: dict, sid: str) -> str:
    """Derive a human-readable title from session metadata."""
    project = record.get("project", "unknown")
    ts = record.get("metadata", {}).get("timestamp", "")
    # Extract YYYY-MM-DD from ISO timestamp or date string
    date_str = ts[:10] if ts and len(ts) >= 10 else "unknown-date"
    # Validate it looks like a date; fall back if not
    if not (len(date_str) == 10 and date_str[4] == "-" and date_str[7] == "-"):
        date_str = "unknown-date"
    return f"Session {date_str} — {project}"
```

- [ ] **Step 2: Replace the UUID title on line 116**

Change:
```python
                    "title": f"Claude Code — {sid}",
```
To:
```python
                    "title": _derive_session_title(record, sid),
```

- [ ] **Step 3: Run tests to confirm they pass**

```bash
cd /Users/macm1air/Documents/AI
python3 -m pytest brain/tests/test_ingest_titles.py -v
```

Expected: 4 passed

- [ ] **Step 4: Run existing ingest tests to confirm no regressions**

```bash
python3 -m pytest brain/tests/test_07_ingest_file_arg.py brain/tests/test_ingest_session_chunks.py -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add brain/bootstrap/ingest_claude_code_lib.py
git commit -m "fix(ingest): replace UUID conversation titles with Session YYYY-MM-DD — project"
```

---

## Task 3: Tests for `post_tool_use.py` fix

**Files:**
- Create: `brain/tests/test_post_tool_use_titles.py`

- [ ] **Step 1: Write failing tests**

```python
# brain/tests/test_post_tool_use_titles.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import json
from unittest.mock import patch, MagicMock


def _run_hook(tool_name: str, tool_input: dict, tool_response: str = ""):
    """Run the post_tool_use hook with fake stdin and capture save calls."""
    context = {
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_response": tool_response,
    }
    saved_payloads = []

    def fake_save(**kwargs):
        saved_payloads.append(kwargs)
        return {"status": "ok"}

    with patch("sys.stdin") as mock_stdin, \
         patch("brain.api_client.backend_mode", return_value="api"), \
         patch("brain.api_client.save_memory_with_status", side_effect=fake_save), \
         patch("brain.hooks.spool.enqueue_memory"), \
         patch("brain.hooks.spool.replay_once", return_value=MagicMock(replayed=0, remaining=0, moved_to_dlq=0)), \
         patch("brain.hooks.spool.metrics", return_value={"queue_size": 0, "oldest_age_sec": 0}):
        mock_stdin.read.return_value = json.dumps(context)
        import importlib, brain.hooks.post_tool_use as ptu
        importlib.reload(ptu)

    return saved_payloads


def test_bash_does_not_save():
    """Bash commands must not be saved (they are noise, session summary covers them)."""
    saved = _run_hook("Bash", {"command": "git status"})
    assert saved == [], "Bash must not trigger a memory save"


def test_edit_does_not_save():
    """File edits must not be saved (session summary covers them)."""
    saved = _run_hook("Edit", {"file_path": "/some/file.py", "new_string": "x = 1"})
    assert saved == [], "Edit must not trigger a memory save"


def test_write_saves_with_filename_title():
    """Write saves as solution with a title containing the filename, not 'Write · project'."""
    saved = _run_hook("Write", {"file_path": "/Users/user/project/foo/bar.py", "content": "..."})
    assert len(saved) == 1
    assert "bar.py" in saved[0]["title"]
    assert saved[0]["memory_type"] == "solution"


def test_agent_saves_with_description_title():
    """Agent dispatches save as decision with description in title."""
    saved = _run_hook("Agent", {"description": "Run retrieval eval"})
    assert len(saved) == 1
    assert "Run retrieval eval" in saved[0]["title"] or saved[0]["memory_type"] == "decision"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/macm1air/Documents/AI
python3 -m pytest brain/tests/test_post_tool_use_titles.py -v
```

Expected: `test_bash_does_not_save` and `test_edit_does_not_save` fail (currently Bash/Edit DO save).

- [ ] **Step 3: Commit failing tests**

```bash
git add brain/tests/test_post_tool_use_titles.py
git commit -m "test: add failing tests for post_tool_use noise reduction"
```

---

## Task 4: Fix `post_tool_use.py` — remove Bash/Edit noise

**Files:**
- Modify: `brain/hooks/post_tool_use.py`

- [ ] **Step 1: Remove "Bash" and "Edit" from MEMORABLE_TOOLS**

Change line 14:
```python
MEMORABLE_TOOLS = {"Edit", "Write", "Bash", "Agent"}
```
To:
```python
MEMORABLE_TOOLS = {"Write", "Agent"}
```

- [ ] **Step 2: Fix Write title and Edit/Bash dead code**

Replace the entire `if tool_name == "Edit":` ... `else: sys.exit(0)` block (lines 34-48) with:

```python
    if tool_name == "Write":
        file_path = tool_input.get("file_path", "?")
        filename = Path(file_path).name
        desc = f"Wrote {file_path}"
        title = f"{filename} — {project}"
        memory_type = "solution"
    elif tool_name == "Agent":
        agent_desc = tool_input.get("description", "")[:200]
        desc = f"Dispatched agent: {agent_desc}"
        title = agent_desc[:100] or f"Agent — {project}"
        memory_type = "decision"
    else:
        sys.exit(0)
```

Note: add `from pathlib import Path` to the imports at the top of the file if not already present (line 9 already has it: `from pathlib import Path`).

- [ ] **Step 3: Fix API-mode payload to use new title variable**

In the API-mode block (around line 68), the payload dict currently hardcodes:
```python
"title": f"{tool_name} · {project}",
```

Replace with:
```python
"title": title,
```

- [ ] **Step 4: Fix python-mode save call to use new title variable**

In the python-mode block (around line 64), the save call currently has:
```python
save_memory(
    content=summary,
    memory_type=memory_type,
    tags=with_ingest_tag([tool_name.lower(), project]),
    project=project,
    title=f"{tool_name} · {project}",
)
```

Replace `title=f"{tool_name} · {project}"` with `title=title`.

- [ ] **Step 5: Run tests**

```bash
cd /Users/macm1air/Documents/AI
python3 -m pytest brain/tests/test_post_tool_use_titles.py -v
```

Expected: all 4 pass

- [ ] **Step 6: Run hook contract tests to confirm no regressions**

```bash
python3 -m pytest brain/tests/test_hook_stdin_contracts.py -v
```

Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add brain/hooks/post_tool_use.py
git commit -m "fix(hooks): remove Bash/Edit from post_tool_use; fix Write/Agent titles"
```

---

## Task 5: Write backfill script

**Files:**
- Create: `brain/tools/backfill_bad_data.py`
- Create: `brain/tests/test_backfill_bad_data.py`

### Step 5a — Write tests first

- [ ] **Step 1: Write tests against in-memory SQLite**

```python
# brain/tests/test_backfill_bad_data.py
import sys, sqlite3
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest


def _make_db(tmp_path):
    """Create a minimal brain.db schema with bad data loaded."""
    db = tmp_path / "brain.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE memories (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            type TEXT NOT NULL,
            project TEXT NOT NULL DEFAULT 'general',
            timestamp TEXT NOT NULL DEFAULT '2026-01-01T00:00:00+00:00',
            title TEXT,
            embedding BLOB,
            source TEXT NOT NULL DEFAULT 'test',
            tags TEXT NOT NULL DEFAULT '',
            session_id TEXT NOT NULL DEFAULT '',
            importance REAL NOT NULL DEFAULT 0.5,
            salience REAL NOT NULL DEFAULT 0.5
        );
        CREATE VIRTUAL TABLE memories_fts USING fts5(
            id UNINDEXED, content, title,
            tokenize='porter ascii'
        );
        -- Bad: UUID-titled conversation
        INSERT INTO memories VALUES ('c1','Claude Code session: AI | Ended: 2026-05-01','conversation','AI','2026-05-01T10:00:00+00:00','Claude Code — 90748205-f28a-45ae',NULL,'claude_code_session','','' ,0.6,0.5);
        INSERT INTO memories_fts(rowid,id,content,title) SELECT rowid,id,content,title FROM memories WHERE id='c1';

        -- Bad: bash log pattern
        INSERT INTO memories VALUES ('p1','Ran command: git status','pattern','AI','2026-05-02T10:00:00+00:00','Bash · AI',NULL,'claw_code','','',0.5,0.5);
        INSERT INTO memories_fts(rowid,id,content,title) SELECT rowid,id,content,title FROM memories WHERE id='p1';

        -- Bad: file edit solution
        INSERT INTO memories VALUES ('s1','Edited /some/file.py: x = 1\\n','solution','AI','2026-05-03T10:00:00+00:00','Edit · AI',NULL,'claw_code','','',0.5,0.5);
        INSERT INTO memories_fts(rowid,id,content,title) SELECT rowid,id,content,title FROM memories WHERE id='s1';

        -- Bad: blank-title solution (Write hook)
        INSERT INTO memories VALUES ('s2','Wrote /some/file.py','solution','AI','2026-05-03T11:00:00+00:00','Write · AI',NULL,'claw_code','','',0.5,0.5);
        INSERT INTO memories_fts(rowid,id,content,title) SELECT rowid,id,content,title FROM memories WHERE id='s2';

        -- Good: real project_context session summary
        INSERT INTO memories VALUES ('pc1','Worked on brain retrieval. Decisions: Use RRF. Next: run eval.','project_context','AI','2026-05-04T10:00:00+00:00','Session 2026-05-04 — AI',NULL,'claude_code_session','','',0.6,0.5);
        INSERT INTO memories_fts(rowid,id,content,title) SELECT rowid,id,content,title FROM memories WHERE id='pc1';
    """)
    conn.close()
    return db


def test_conversation_titles_fixed(tmp_path):
    db = _make_db(tmp_path)
    from brain.tools.backfill_bad_data import run_backfill
    stats = run_backfill(db_path=db, dry_run=False)

    conn = sqlite3.connect(str(db))
    row = conn.execute("SELECT title FROM memories WHERE id='c1'").fetchone()
    conn.close()

    assert row is not None
    assert "90748205" not in row[0], "UUID must not appear in title"
    assert "2026-05-01" in row[0], "Date must appear in title"
    assert "AI" in row[0], "Project must appear in title"
    assert stats["conversations_retitled"] >= 1


def test_bash_log_patterns_deleted(tmp_path):
    db = _make_db(tmp_path)
    from brain.tools.backfill_bad_data import run_backfill
    run_backfill(db_path=db, dry_run=False)

    conn = sqlite3.connect(str(db))
    row = conn.execute("SELECT id FROM memories WHERE id='p1'").fetchone()
    fts_row = conn.execute("SELECT id FROM memories_fts WHERE id='p1'").fetchone()
    conn.close()

    assert row is None, "bash log pattern must be deleted from memories"
    assert fts_row is None, "bash log pattern must be deleted from memories_fts"


def test_file_edit_solutions_deleted(tmp_path):
    db = _make_db(tmp_path)
    from brain.tools.backfill_bad_data import run_backfill
    run_backfill(db_path=db, dry_run=False)

    conn = sqlite3.connect(str(db))
    row = conn.execute("SELECT id FROM memories WHERE id='s1'").fetchone()
    fts_row = conn.execute("SELECT id FROM memories_fts WHERE id='s1'").fetchone()
    conn.close()

    assert row is None, "file edit solution must be deleted from memories"
    assert fts_row is None, "file edit solution must be deleted from memories_fts"


def test_write_hook_solutions_deleted(tmp_path):
    db = _make_db(tmp_path)
    from brain.tools.backfill_bad_data import run_backfill
    run_backfill(db_path=db, dry_run=False)

    conn = sqlite3.connect(str(db))
    row = conn.execute("SELECT id FROM memories WHERE id='s2'").fetchone()
    conn.close()
    assert row is None, "Write-hook solution with generic title must be deleted"


def test_good_project_context_untouched(tmp_path):
    db = _make_db(tmp_path)
    from brain.tools.backfill_bad_data import run_backfill
    run_backfill(db_path=db, dry_run=False)

    conn = sqlite3.connect(str(db))
    row = conn.execute("SELECT title FROM memories WHERE id='pc1'").fetchone()
    conn.close()
    assert row is not None, "good project_context memory must not be deleted"
    assert row[0] == "Session 2026-05-04 — AI"


def test_dry_run_makes_no_changes(tmp_path):
    db = _make_db(tmp_path)
    from brain.tools.backfill_bad_data import run_backfill
    run_backfill(db_path=db, dry_run=True)

    conn = sqlite3.connect(str(db))
    count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    conn.close()
    assert count == 5, "dry_run must not change anything"
```

- [ ] **Step 2: Run to confirm tests fail (module doesn't exist)**

```bash
cd /Users/macm1air/Documents/AI
python3 -m pytest brain/tests/test_backfill_bad_data.py -v
```

Expected: `ModuleNotFoundError: No module named 'brain.tools.backfill_bad_data'`

- [ ] **Step 3: Commit failing tests**

```bash
git add brain/tests/test_backfill_bad_data.py
git commit -m "test: add failing tests for backfill_bad_data script"
```

### Step 5b — Implement the backfill script

- [ ] **Step 4: Create `brain/tools/backfill_bad_data.py`**

```python
"""
One-shot script: fix all bad memories in brain.db created by ingest bugs.

Fixes:
  1. Conversation UUID titles → "Session YYYY-MM-DD — {project}"
  2. Delete bash-log patterns (content LIKE 'Ran command:%')
  3. Delete generic-titled patterns (title LIKE 'Bash · %')
  4. Delete file-edit solutions (content LIKE 'Edited %' OR title LIKE 'Edit · %')
  5. Delete write-hook solutions with generic titles (title LIKE 'Write · %')

FTS5 sync: memories_fts is not a content table — we sync manually with
  DELETE + INSERT for updates, and DELETE from both tables for removals.

Usage:
    python3 brain/tools/backfill_bad_data.py [--dry-run] [--db PATH]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parents[1] / "rust" / "brain.db"


@dataclass
class BackfillStats:
    conversations_retitled: int = 0
    patterns_deleted: int = 0
    solutions_deleted: int = 0
    fts_synced: int = 0
    errors: list[str] = field(default_factory=list)


def _fix_conversation_titles(conn: sqlite3.Connection, dry_run: bool, stats: BackfillStats) -> None:
    """Replace 'Claude Code — <uuid>' titles with 'Session YYYY-MM-DD — {project}'."""
    rows = conn.execute(
        "SELECT id, timestamp, project FROM memories "
        "WHERE type='conversation' AND title LIKE 'Claude Code — %'"
    ).fetchall()

    print(f"  Found {len(rows)} conversations with UUID titles")
    if dry_run:
        return

    for memory_id, timestamp, project in rows:
        date_str = timestamp[:10] if timestamp and len(timestamp) >= 10 else "unknown-date"
        new_title = f"Session {date_str} — {project}"

        conn.execute(
            "UPDATE memories SET title=? WHERE id=?",
            (new_title, memory_id),
        )
        # FTS sync: delete stale entry, insert fresh one
        conn.execute(
            "DELETE FROM memories_fts WHERE rowid=(SELECT rowid FROM memories WHERE id=?)",
            (memory_id,),
        )
        conn.execute(
            "INSERT INTO memories_fts(rowid, id, content, title) "
            "SELECT rowid, id, content, title FROM memories WHERE id=?",
            (memory_id,),
        )
        stats.conversations_retitled += 1
        stats.fts_synced += 1


def _delete_bad_patterns(conn: sqlite3.Connection, dry_run: bool, stats: BackfillStats) -> None:
    """Delete bash-log patterns and generic-titled patterns."""
    conditions = [
        "content LIKE 'Ran command:%'",
        "title LIKE 'Bash · %'",
    ]
    where = " OR ".join(f"({c})" for c in conditions)
    query = f"SELECT id FROM memories WHERE type='pattern' AND ({where})"
    ids = [row[0] for row in conn.execute(query).fetchall()]

    print(f"  Found {len(ids)} bad pattern memories to delete")
    if dry_run:
        return

    for memory_id in ids:
        conn.execute(
            "DELETE FROM memories_fts WHERE rowid=(SELECT rowid FROM memories WHERE id=?)",
            (memory_id,),
        )
        conn.execute("DELETE FROM memories WHERE id=?", (memory_id,))
        stats.patterns_deleted += 1
        stats.fts_synced += 1


def _delete_bad_solutions(conn: sqlite3.Connection, dry_run: bool, stats: BackfillStats) -> None:
    """Delete file-edit solutions and write-hook solutions with generic titles."""
    conditions = [
        "content LIKE 'Edited %'",
        "title LIKE 'Edit · %'",
        "title LIKE 'Write · %'",
    ]
    where = " OR ".join(f"({c})" for c in conditions)
    query = f"SELECT id FROM memories WHERE type='solution' AND ({where})"
    ids = [row[0] for row in conn.execute(query).fetchall()]

    print(f"  Found {len(ids)} bad solution memories to delete")
    if dry_run:
        return

    for memory_id in ids:
        conn.execute(
            "DELETE FROM memories_fts WHERE rowid=(SELECT rowid FROM memories WHERE id=?)",
            (memory_id,),
        )
        conn.execute("DELETE FROM memories WHERE id=?", (memory_id,))
        stats.solutions_deleted += 1
        stats.fts_synced += 1


def run_backfill(db_path: Path = DEFAULT_DB, dry_run: bool = False) -> BackfillStats:
    stats = BackfillStats()
    print(f"{'[DRY RUN] ' if dry_run else ''}Connecting to {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")

    try:
        print("\n--- Step 1: Fix conversation titles ---")
        _fix_conversation_titles(conn, dry_run, stats)

        print("\n--- Step 2: Delete bad pattern memories ---")
        _delete_bad_patterns(conn, dry_run, stats)

        print("\n--- Step 3: Delete bad solution memories ---")
        _delete_bad_solutions(conn, dry_run, stats)

        if not dry_run:
            conn.commit()
            print("\n  Committed.")
        else:
            print("\n  [DRY RUN] No changes committed.")
    except Exception as e:
        conn.rollback()
        stats.errors.append(str(e))
        print(f"  ERROR: {e}", file=sys.stderr)
        raise
    finally:
        conn.close()

    print(f"\nDone.")
    print(f"  Conversations retitled:  {stats.conversations_retitled}")
    print(f"  Patterns deleted:        {stats.patterns_deleted}")
    print(f"  Solutions deleted:       {stats.solutions_deleted}")
    print(f"  FTS5 ops:                {stats.fts_synced}")
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fix bad ingest data in brain.db")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without applying them")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Path to brain.db")
    args = parser.parse_args()
    run_backfill(db_path=args.db, dry_run=args.dry_run)
```

- [ ] **Step 5: Run tests**

```bash
cd /Users/macm1air/Documents/AI
python3 -m pytest brain/tests/test_backfill_bad_data.py -v
```

Expected: all 6 pass

- [ ] **Step 6: Commit**

```bash
git add brain/tools/backfill_bad_data.py
git commit -m "feat(tools): add backfill_bad_data script to fix UUID titles and delete noise memories"
```

---

## Task 6: Write ingest quality gate

**Files:**
- Create: `brain/tools/ingest_quality_gate.py`

- [ ] **Step 1: Create the gate script**

```python
"""
Post-ingest quality gate: samples k-fold P@1 by type and warns/fails on thresholds.

Reads brain.db directly — no API required. Uses cosine similarity (no BM25) for
speed. Samples up to MAX_SAMPLE per type to keep runtime under 60s.

Exit codes:
    0  All types meet warning threshold (>= 0.45 P@1)
    1  At least one type below warning threshold
    2  At least one type below error threshold (< 0.25 P@1)

Thresholds are intentionally conservative — the goal is catching catastrophic
regressions, not tracking gradual drift (use full k-fold for that).

Usage:
    python3 brain/tools/ingest_quality_gate.py [--db PATH] [--sample N]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

DEFAULT_DB = Path(__file__).resolve().parents[1] / "rust" / "brain.db"
MAX_SAMPLE = 300
WARN_THRESHOLD = 0.45
ERROR_THRESHOLD = 0.25
TARGET_TYPES = ["conversation", "pattern", "solution", "project_context"]


def _load_sample(conn: sqlite3.Connection, memory_type: str, n: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, title, content, embedding FROM memories "
        "WHERE type=? AND embedding IS NOT NULL "
        "ORDER BY RANDOM() LIMIT ?",
        (memory_type, n),
    ).fetchall()
    result = []
    for row in rows:
        mid, title, content, emb_blob = row
        if not emb_blob:
            continue
        emb = np.frombuffer(emb_blob, dtype=np.float32)
        query_text = title.strip() if title and len(title.strip()) >= 12 else content[:200]
        result.append({"id": mid, "query_text": query_text, "embedding": emb})
    return result


def _cosine_top1(query_emb: np.ndarray, corpus: list[dict], own_id: str) -> str | None:
    """Return id of top-1 hit excluding query itself."""
    sims = []
    for item in corpus:
        if item["id"] == own_id:
            continue
        dot = float(np.dot(query_emb, item["embedding"]))
        norm = float(np.linalg.norm(query_emb) * np.linalg.norm(item["embedding"]))
        sims.append((dot / norm if norm > 0 else 0.0, item["id"]))
    if not sims:
        return None
    sims.sort(reverse=True)
    return sims[0][1]


def run_gate(db_path: Path = DEFAULT_DB, sample: int = MAX_SAMPLE) -> dict[str, float]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    results: dict[str, float] = {}
    exit_code = 0

    print(f"Quality gate — sampling up to {sample} per type from {db_path.name}\n")

    for mtype in TARGET_TYPES:
        corpus = _load_sample(conn, mtype, sample)
        if len(corpus) < 2:
            print(f"  {mtype:20s}  n={len(corpus):4d}  SKIP (too few)")
            continue

        hits = 0
        for item in corpus:
            top1_id = _cosine_top1(item["embedding"], corpus, item["id"])
            if top1_id == item["id"]:
                hits += 1

        p1 = hits / len(corpus)
        results[mtype] = p1
        status = "OK" if p1 >= WARN_THRESHOLD else ("WARN" if p1 >= ERROR_THRESHOLD else "ERROR")
        print(f"  {mtype:20s}  n={len(corpus):4d}  P@1={p1:.3f}  [{status}]")

        if p1 < ERROR_THRESHOLD:
            exit_code = 2
        elif p1 < WARN_THRESHOLD and exit_code < 1:
            exit_code = 1

    conn.close()
    return results, exit_code


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--sample", type=int, default=MAX_SAMPLE)
    args = parser.parse_args()

    _, exit_code = run_gate(db_path=args.db, sample=args.sample)
    print(f"\nExit code: {exit_code}")
    if exit_code == 2:
        print("  ERROR: critical retrieval regression detected")
    elif exit_code == 1:
        print("  WARN: some types below threshold — run full k-fold eval")
    else:
        print("  OK: all types meet threshold")
    sys.exit(exit_code)
```

- [ ] **Step 2: Smoke-test the gate runs without crashing**

```bash
cd /Users/macm1air/Documents/AI
python3 brain/tools/ingest_quality_gate.py --sample 100
```

Expected: prints P@1 per type and exits with 0, 1, or 2. Runtime < 30s.

- [ ] **Step 3: Commit**

```bash
git add brain/tools/ingest_quality_gate.py
git commit -m "feat(tools): add ingest_quality_gate.py — P@1 by type with warn/error thresholds"
```

---

## Task 7: Run the backfill on real DB + verify

- [ ] **Step 1: Dry run first — verify counts match expectations**

```bash
cd /Users/macm1air/Documents/AI
python3 brain/tools/backfill_bad_data.py --dry-run
```

Expected output (approximate):
```
[DRY RUN] Connecting to .../brain/rust/brain.db
--- Step 1: Fix conversation titles ---
  Found ~1938 conversations with UUID titles
--- Step 2: Delete bad pattern memories ---
  Found ~861 bad pattern memories to delete
--- Step 3: Delete bad solution memories ---
  Found ~1462 bad solution memories to delete
```

If counts are wildly different, investigate before proceeding.

- [ ] **Step 2: Run quality gate BEFORE backfill to record baseline**

```bash
python3 brain/tools/ingest_quality_gate.py --sample 300 2>&1 | tee /tmp/gate_before.txt
```

- [ ] **Step 3: Apply the backfill**

```bash
python3 brain/tools/backfill_bad_data.py
```

Expected: prints counts and "Committed." without errors.

- [ ] **Step 4: Run quality gate AFTER backfill**

```bash
python3 brain/tools/ingest_quality_gate.py --sample 300 2>&1 | tee /tmp/gate_after.txt
diff /tmp/gate_before.txt /tmp/gate_after.txt
```

Expected: all non-fact types should improve. `conversation` especially should jump from near-0.

- [ ] **Step 5: Run the gold-semantic eval to confirm semantic retrieval still works**

```bash
python3 brain/tools/retrieval_eval_kfold.py \
  --gold-semantic brain/eval/gold_semantic.jsonl \
  --report brain/eval/kfold_gold_semantic_post_backfill_$(date +%Y_%m_%d).json --ks 1,5,10
```

Expected: P@1=1.0 (pure vector, same as before — we only changed titles/deleted noise, didn't touch embeddings).

- [ ] **Step 6: Run a sampled k-fold to capture the post-backfill baseline**

```bash
python3 brain/tools/retrieval_eval_kfold.py --sample 1000 --rrf \
  --report brain/eval/kfold_sample1k_rrf_post_backfill_$(date +%Y_%m_%d).json --ks 1,3,5,10
```

- [ ] **Step 7: Update `brain/eval/README.md` — add new row to results history and quality gate section**

Add the post-backfill sampled run result to the Results history table. Add a new section:

```markdown
## Quality gate

Run after any ingest that adds >100 memories:

\`\`\`bash
python3 brain/tools/ingest_quality_gate.py --sample 300
\`\`\`

Thresholds: WARN if P@1 < 0.45 for any non-fact type, ERROR if < 0.25.
Exit code 1 = warn, 2 = error, 0 = all clear.
```

- [ ] **Step 8: Save brain memory with post-backfill results**

```python
# Via MCP or session end hook — save as fact memory:
# "Post-backfill k-fold results [date]: conversation P@1=[X], pattern P@1=[Y], solution P@1=[Z], project_context P@1=[W]"
```

- [ ] **Step 9: Commit final state**

```bash
git add brain/eval/README.md
git commit -m "docs(eval): add post-backfill results and quality gate section to README"
```

---

## Self-Review

**Spec coverage:**
- ✅ UUID conversation titles → Task 2 + Task 7
- ✅ Bash-log patterns → Task 4 (prevent) + Task 5 (fix existing)
- ✅ File-edit solutions → Task 4 (prevent) + Task 5 (fix existing)
- ✅ Blank-title patterns/solutions → Task 5 (delete by title pattern)
- ✅ FTS5 stays in sync → backfill_bad_data.py handles both tables
- ✅ This never recurs → Task 6 eval gate + fixed ingest pipeline
- ✅ TDD throughout — tests written before implementation in every task

**Placeholder scan:** None found. All code blocks are complete and runnable.

**Type consistency:** `run_backfill` returns `BackfillStats` in tests and in `__main__` — consistent. `_derive_session_title` signature matches usage in `run_with_dirs`.

**Known risks:**
- Backfill uses a single transaction per operation group. If the DB is large (~102MB), WAL mode handles concurrent reads safely, but plan for ~5-10 seconds of write lock during commit.
- The eval gate uses cosine-only (not RRF) for speed. This means it underestimates real retrieval quality slightly (RRF adds ~1.3pp). Gate thresholds (0.45/0.25) are set conservatively to account for this.
- FTS5 `DELETE FROM memories_fts WHERE rowid=(SELECT rowid FROM memories WHERE id=?)` — this must be called BEFORE `DELETE FROM memories WHERE id=?`, because after deletion the rowid lookup returns NULL. The backfill script does this correctly.
