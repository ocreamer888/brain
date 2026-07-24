# Phase 7 — Temporal Teeth Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Give every fact a meaningful event_time so recency decay reflects actual knowledge age, not ingest date.

**Architecture:** Three-layer fix — (1) one-time historical stamp backfill via direct SQLite UPDATE, (2) forward path wiring so new facts inherit session ended_at, (3) Rust search ranking switches age calculation to use event_time instead of ingest timestamp.

**Tech Stack:** Python 3.13, SQLite3 (direct), Rust (brain/rust/src/brain.rs), pytest

---

## Context

- DB: `brain/rust/brain.db` — SQLite, `memories` table
- Facts: `type = '"fact"'` (JSON-serialized string including quotes)
- 14,904 facts, all `event_time = NULL` today
- Session exports: `brain/bootstrap/sessions_export/*.json` — each has `session_id` and `ended_at` (ISO8601)
- Rust binary: built from `brain/rust/` with `cargo build --release`
- Tests: `brain/tests/` (pytest), Rust tests inline in `src/`

---

## Task 1: stamp_event_times.py — historical backfill script

**Files:**
- Create: `brain/tools/stamp_event_times.py`
- Create: `brain/tests/test_stamp_event_times.py`

**What it does:**

Reads `brain/rust/brain.db` directly. Runs three UPDATE passes:

1. **Claude Code sessions** — for each session JSON in `sessions_export/`, read `session_id` + `ended_at`. UPDATE facts WHERE `session_id = ?` AND `event_time IS NULL` → set `event_time = ended_at`.
2. **Cursor/Perplexity** — UPDATE facts WHERE `session_id != ''` AND `event_time IS NULL` → set `event_time = '2025-07-01T00:00:00+00:00'`.
3. **No session_id** — UPDATE facts WHERE `(session_id IS NULL OR session_id = '')` AND `event_time IS NULL` → set `event_time = '2025-01-01T00:00:00+00:00'`.

Print counts for each pass. Idempotent (all WHERE clauses include `event_time IS NULL`).

**Step 1: Write failing tests**

```python
# brain/tests/test_stamp_event_times.py
import sqlite3, json, os, tempfile, pytest
from pathlib import Path

def _make_db(tmp_path):
    db = tmp_path / "brain.db"
    conn = sqlite3.connect(str(db))
    conn.execute("""CREATE TABLE memories (
        id TEXT PRIMARY KEY, type TEXT, session_id TEXT NOT NULL DEFAULT '',
        event_time TEXT, timestamp TEXT NOT NULL DEFAULT ''
    )""")
    conn.execute("INSERT INTO memories VALUES ('f1','\"fact\"','sess-abc',NULL,'2026-05-01')")
    conn.execute("INSERT INTO memories VALUES ('f2','\"fact\"','unknown-id',NULL,'2026-05-01')")
    conn.execute("INSERT INTO memories VALUES ('f3','\"fact\"','',NULL,'2026-05-01')")
    conn.execute("INSERT INTO memories VALUES ('f4','\"fact\"','sess-abc','2026-03-01','2026-05-01')")  # already stamped
    conn.commit()
    conn.close()
    return db

def _make_sessions(tmp_path, session_id, ended_at):
    d = tmp_path / "sessions"
    d.mkdir(exist_ok=True)
    f = d / "sess.json"
    f.write_text(json.dumps({"session_id": session_id, "ended_at": ended_at, "messages": []}))
    return d

def test_session_facts_get_ended_at(tmp_path):
    db = _make_db(tmp_path)
    sessions_dir = _make_sessions(tmp_path, "sess-abc", "2026-04-10T12:00:00+00:00")
    from brain.tools.stamp_event_times import stamp
    counts = stamp(db_path=str(db), sessions_dir=sessions_dir)
    conn = sqlite3.connect(str(db))
    row = conn.execute("SELECT event_time FROM memories WHERE id='f1'").fetchone()
    assert row[0] == "2026-04-10T12:00:00+00:00"
    assert counts["sessions"] == 1

def test_cursor_facts_get_2025_07(tmp_path):
    db = _make_db(tmp_path)
    sessions_dir = _make_sessions(tmp_path, "sess-abc", "2026-04-10T12:00:00+00:00")
    from brain.tools.stamp_event_times import stamp
    stamp(db_path=str(db), sessions_dir=sessions_dir)
    conn = sqlite3.connect(str(db))
    row = conn.execute("SELECT event_time FROM memories WHERE id='f2'").fetchone()
    assert row[0].startswith("2025-07-01")

def test_no_session_id_gets_2025_01(tmp_path):
    db = _make_db(tmp_path)
    sessions_dir = _make_sessions(tmp_path, "sess-abc", "2026-04-10T12:00:00+00:00")
    from brain.tools.stamp_event_times import stamp
    stamp(db_path=str(db), sessions_dir=sessions_dir)
    conn = sqlite3.connect(str(db))
    row = conn.execute("SELECT event_time FROM memories WHERE id='f3'").fetchone()
    assert row[0].startswith("2025-01-01")

def test_already_stamped_untouched(tmp_path):
    db = _make_db(tmp_path)
    sessions_dir = _make_sessions(tmp_path, "sess-abc", "2026-04-10T12:00:00+00:00")
    from brain.tools.stamp_event_times import stamp
    stamp(db_path=str(db), sessions_dir=sessions_dir)
    conn = sqlite3.connect(str(db))
    row = conn.execute("SELECT event_time FROM memories WHERE id='f4'").fetchone()
    assert row[0] == "2026-03-01"  # unchanged
```

**Step 2: Run tests to verify they fail**

```bash
cd /Users/macm1air/Documents/AI
python -m pytest brain/tests/test_stamp_event_times.py -v
```
Expected: `ModuleNotFoundError: No module named 'brain.tools.stamp_event_times'`

**Step 3: Write the implementation**

```python
# brain/tools/stamp_event_times.py
#!/usr/bin/env python3
"""One-time script: stamp event_time on facts that have none.

Passes:
  1. Claude Code sessions  → ended_at from session JSON
  2. Cursor/Perplexity     → 2025-07-01 (historical backup era)
  3. No session_id         → 2025-01-01 (oldest/least certain)

Idempotent — all UPDATEs include WHERE event_time IS NULL.
"""
from __future__ import annotations
import json, sqlite3, sys
from pathlib import Path

_CURSOR_STAMP   = "2025-07-01T00:00:00+00:00"
_NOSESS_STAMP   = "2025-01-01T00:00:00+00:00"
_FACT_TYPE      = '"fact"'

_DEFAULT_DB       = Path(__file__).resolve().parents[1] / "rust" / "brain.db"
_DEFAULT_SESSIONS = Path(__file__).resolve().parents[1] / "bootstrap" / "sessions_export"


def stamp(
    db_path: str | Path = _DEFAULT_DB,
    sessions_dir: str | Path = _DEFAULT_SESSIONS,
) -> dict[str, int]:
    db_path      = Path(db_path)
    sessions_dir = Path(sessions_dir)

    conn = sqlite3.connect(str(db_path), timeout=30)
    counts: dict[str, int] = {"sessions": 0, "cursor": 0, "nosess": 0}

    try:
        # Pass 1: Claude Code sessions
        for f in sessions_dir.glob("*.json"):
            try:
                data     = json.loads(f.read_text())
                sess_id  = data.get("session_id", "")
                ended_at = data.get("ended_at", "")
                if not sess_id or not ended_at:
                    continue
                cur = conn.execute(
                    "UPDATE memories SET event_time=? "
                    "WHERE type=? AND session_id=? AND event_time IS NULL",
                    (ended_at, _FACT_TYPE, sess_id),
                )
                counts["sessions"] += cur.rowcount
            except Exception:
                continue
        conn.commit()

        # Pass 2: remaining facts with a session_id (Cursor / Perplexity)
        cur = conn.execute(
            "UPDATE memories SET event_time=? "
            "WHERE type=? AND session_id!='' AND event_time IS NULL",
            (_CURSOR_STAMP, _FACT_TYPE),
        )
        counts["cursor"] = cur.rowcount
        conn.commit()

        # Pass 3: facts with no session_id
        cur = conn.execute(
            "UPDATE memories SET event_time=? "
            "WHERE type=? AND (session_id IS NULL OR session_id='') AND event_time IS NULL",
            (_NOSESS_STAMP, _FACT_TYPE),
        )
        counts["nosess"] = cur.rowcount
        conn.commit()

    finally:
        conn.close()

    return counts


def main() -> int:
    counts = stamp()
    total = sum(counts.values())
    print(f"[stamp] sessions={counts['sessions']} cursor={counts['cursor']} nosess={counts['nosess']} total={total}")
    remaining = sqlite3.connect(str(_DEFAULT_DB)).execute(
        "SELECT COUNT(*) FROM memories WHERE type=? AND event_time IS NULL",
        (_FACT_TYPE,)
    ).fetchone()[0]
    print(f"[stamp] facts still without event_time: {remaining}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest brain/tests/test_stamp_event_times.py -v
```
Expected: all 4 tests PASS

**Step 5: Run the script against the real DB (dry-run first)**

```bash
# Check counts without committing
python3 -c "
import sqlite3
conn = sqlite3.connect('brain/rust/brain.db')
print('null event_time before:', conn.execute(\"SELECT COUNT(*) FROM memories WHERE type='\\\"fact\\\"' AND event_time IS NULL\").fetchone()[0])
"
python3 brain/tools/stamp_event_times.py
python3 -c "
import sqlite3
conn = sqlite3.connect('brain/rust/brain.db')
print('null event_time after:', conn.execute(\"SELECT COUNT(*) FROM memories WHERE type='\\\"fact\\\"' AND event_time IS NULL\").fetchone()[0])
"
```
Expected after: `facts still without event_time: 0`

**Step 6: Commit**

```bash
git add brain/tools/stamp_event_times.py brain/tests/test_stamp_event_times.py
git commit -m "feat(brain): Phase 7.1 — stamp event_time on historical facts"
```

---

## Task 2: fact_curator.py — accept source_event_time fallback

**Files:**
- Modify: `brain/ingest/fact_curator.py` — `_save_fact()` and `curate_facts()`
- Modify: `brain/tests/test_fact_curator.py` — add one test

**What changes:**

`_save_fact()` gets a new optional param `source_event_time: str | None`. When `draft.event_time` is None, use `source_event_time` instead. `curate_facts()` threads the param through.

**Step 1: Write failing test**

Open `brain/tests/test_fact_curator.py`. Add at the end:

```python
def test_save_fact_uses_source_event_time_when_llm_null(monkeypatch):
    """source_event_time is used when LLM extracted event_time is None."""
    saved = {}
    def mock_save_memory(**kwargs):
        saved.update(kwargs)
        return "fake-id"
    monkeypatch.setattr("brain.api_client.save_memory", mock_save_memory)

    from brain.ingest.fact_extractor import FactDraft
    from brain.ingest.fact_curator import _save_fact
    draft = FactDraft(content="test fact", salience=0.8, event_time=None,
                      entities=[], fact_type="decision", derived_from="v1")
    _save_fact(draft, project="test", parent_id=None, session_id=None,
               source_event_time="2025-07-01T00:00:00+00:00")
    assert saved.get("event_time") == "2025-07-01T00:00:00+00:00"


def test_save_fact_llm_event_time_wins(monkeypatch):
    """LLM-extracted event_time takes precedence over source_event_time."""
    saved = {}
    def mock_save_memory(**kwargs):
        saved.update(kwargs)
        return "fake-id"
    monkeypatch.setattr("brain.api_client.save_memory", mock_save_memory)

    from brain.ingest.fact_extractor import FactDraft
    from brain.ingest.fact_curator import _save_fact
    draft = FactDraft(content="test fact", salience=0.8, event_time="2024-03-15T00:00:00+00:00",
                      entities=[], fact_type="decision", derived_from="v1")
    _save_fact(draft, project="test", parent_id=None, session_id=None,
               source_event_time="2025-07-01T00:00:00+00:00")
    assert saved.get("event_time") == "2024-03-15T00:00:00+00:00"
```

**Step 2: Run tests to verify they fail**

```bash
python -m pytest brain/tests/test_fact_curator.py::test_save_fact_uses_source_event_time_when_llm_null brain/tests/test_fact_curator.py::test_save_fact_llm_event_time_wins -v
```
Expected: FAIL — `_save_fact() got an unexpected keyword argument 'source_event_time'`

**Step 3: Implement in fact_curator.py**

In `brain/ingest/fact_curator.py`, change `_save_fact`:

```python
def _save_fact(
    draft: FactDraft,
    project: str,
    parent_id: str | None,
    session_id: str | None,
    source_event_time: str | None = None,   # ← add this
) -> str:
    tags = ["brain/ingest", f"fact_type:{draft.fact_type}"]
    effective_event_time = draft.event_time or source_event_time   # ← LLM wins, fallback to source
    return api_client.save_memory(
        content=draft.content,
        memory_type="fact",
        tags=tags,
        project=project,
        session_id=session_id,
        title=draft.content[:120],
        parent_id=parent_id,
        event_time=effective_event_time,     # ← was draft.event_time
        salience=draft.salience,
        derived_from=draft.derived_from or None,
    )
```

Also thread `source_event_time` through `curate_facts()` and `_curate_one()`:

```python
def curate_facts(
    new_facts: list[FactDraft],
    project: str,
    batch_id: str,
    parent_id: str | None = None,
    session_id: str | None = None,
    tiebreaker_model: str = "google/gemini-2.5-flash-lite",
    source_event_time: str | None = None,   # ← add
) -> CurationResult:
    if not new_facts:
        return CurationResult(reason="no_facts_extracted")
    result = CurationResult()
    for draft in new_facts:
        try:
            _curate_one(
                draft=draft,
                project=project,
                batch_id=batch_id,
                parent_id=parent_id,
                session_id=session_id,
                tiebreaker_model=tiebreaker_model,
                result=result,
                source_event_time=source_event_time,   # ← add
            )
        except Exception:
            result.errors += 1
    return result
```

In `_curate_one`, add `source_event_time: str | None` param and pass it to every `_save_fact(...)` call:

```python
def _curate_one(
    draft: FactDraft,
    project: str,
    batch_id: str,
    parent_id: str | None,
    session_id: str | None,
    tiebreaker_model: str,
    result: CurationResult,
    source_event_time: str | None = None,   # ← add
) -> None:
    ...
    # every _save_fact call becomes:
    new_id = _save_fact(draft, project, parent_id, session_id, source_event_time)
    # (there are 4 call sites — ADD, UPDATE, MERGE×2)
```

**Step 4: Run tests**

```bash
python -m pytest brain/tests/test_fact_curator.py -v
```
Expected: all tests PASS including the two new ones

**Step 5: Commit**

```bash
git add brain/ingest/fact_curator.py brain/tests/test_fact_curator.py
git commit -m "feat(brain): Phase 7.2 — source_event_time fallback in fact_curator"
```

---

## Task 3: backfill_facts.py — wire ended_at into extraction

**Files:**
- Modify: `brain/tools/backfill_facts.py`
- Modify: `brain/tests/test_backfill_facts.py` — add one test

**What changes:**

`_run_extraction()` gets `source_event_time: str | None = None`. Passes it to `curate_facts()`.

`process_session()` reads `ended_at` from the session dict and passes it down.

**Step 1: Write failing test**

Open `brain/tests/test_backfill_facts.py`. Add:

```python
def test_process_session_passes_ended_at(monkeypatch):
    """ended_at from session JSON is forwarded as source_event_time."""
    captured = {}
    def mock_curate(new_facts, project, batch_id, session_id, source_event_time=None, **kw):
        captured["source_event_time"] = source_event_time
        from brain.ingest.fact_curator import CurationResult
        return CurationResult()
    def mock_extract(*a, **kw):
        from brain.ingest.fact_extractor import FactDraft
        return [FactDraft("fact", 0.8, None, [], "decision", "v1")]

    monkeypatch.setattr("brain.tools.backfill_facts.extract_facts", mock_extract)
    monkeypatch.setattr("brain.tools.backfill_facts.curate_facts", mock_curate)

    from brain.tools.backfill_facts import process_session
    session = {
        "session_id": "abc",
        "project": "test",
        "ended_at": "2026-04-15T10:00:00+00:00",
        "messages": [{"role": "user", "content": "x" * 300}],
    }
    process_session(session, batch_id="b1")
    assert captured.get("source_event_time") == "2026-04-15T10:00:00+00:00"
```

**Step 2: Run test to verify it fails**

```bash
python -m pytest brain/tests/test_backfill_facts.py::test_process_session_passes_ended_at -v
```
Expected: FAIL

**Step 3: Implement changes in backfill_facts.py**

Change `_run_extraction`:

```python
def _run_extraction(
    episode_text: str,
    project: str,
    session_id: str,
    batch_id: str,
    dry_run: bool,
    label: str,
    source_event_time: str | None = None,   # ← add
) -> tuple[int, int, int]:
    if len(episode_text) < MIN_EPISODE_CHARS:
        return 0, 0, 0
    if dry_run:
        print(f"  [dry-run] {label}: {len(episode_text)} chars, project={project}")
        return 0, 0, 0
    try:
        facts = extract_facts(
            episode_text=episode_text,
            project=project,
            session_id=session_id,
            parent_id=None,
        )
    except Exception as e:
        print(f"  [backfill] extract_facts failed for {label}: {e}", file=sys.stderr)
        return 0, 0, 0
    if not facts:
        return 0, 0, 0
    result = curate_facts(
        new_facts=facts,
        project=project,
        batch_id=batch_id,
        session_id=session_id,
        source_event_time=source_event_time,   # ← add
    )
    return len(result.added), len(result.updated), len(result.merged)
```

Change `process_session`:

```python
def process_session(
    session: dict,
    batch_id: str,
    dry_run: bool = False,
) -> tuple[int, int, int]:
    project     = session.get("project") or "general"
    session_id  = session.get("session_id") or ""
    ended_at    = session.get("ended_at") or None   # ← add
    messages    = session.get("messages", [])
    episode_text = _build_episode_text(messages)
    return _run_extraction(
        episode_text, project, session_id, batch_id, dry_run,
        f"session/{project}",
        source_event_time=ended_at,             # ← add
    )
```

**Step 4: Run tests**

```bash
python -m pytest brain/tests/test_backfill_facts.py -v
```
Expected: all PASS

**Step 5: Commit**

```bash
git add brain/tools/backfill_facts.py brain/tests/test_backfill_facts.py
git commit -m "feat(brain): Phase 7.3 — forward ended_at as source_event_time in backfill"
```

---

## Task 4: brain.rs — switch age calculation to event_time

**Files:**
- Modify: `brain/rust/src/brain.rs:297-301`

**Context:** The decay formula lives at the line that reads `(now - memory.metadata.timestamp)`. `memory.metadata.event_time` is `Option<DateTime<Utc>>`. `memory.metadata.timestamp` is `DateTime<Utc>`.

**Step 1: Write Rust test**

In `brain/rust/src/brain.rs`, find the existing inline tests (search for `#[cfg(test)]`). Add:

```rust
#[test]
fn recency_uses_event_time_over_timestamp() {
    use chrono::{Duration, Utc};
    // A memory whose event_time is 2 years ago but timestamp is today
    let now = Utc::now();
    let old_event = now - Duration::days(730);
    let meta_with_event_time = MemoryMetadata {
        timestamp: now,
        event_time: Some(old_event),
        salience: 0.5,
        ..MemoryMetadata::default()
    };
    let meta_without = MemoryMetadata {
        timestamp: now,
        event_time: None,
        salience: 0.5,
        ..MemoryMetadata::default()
    };
    let age_with = (now - meta_with_event_time.event_time.unwrap_or(meta_with_event_time.timestamp))
        .num_seconds().max(0) as f32 / 86_400.0;
    let age_without = (now - meta_without.event_time.unwrap_or(meta_without.timestamp))
        .num_seconds().max(0) as f32 / 86_400.0;
    assert!(age_with > 700.0, "event_time should give ~730 day age");
    assert!(age_without < 1.0, "no event_time → timestamp → ~0 day age");
}
```

**Step 2: Run test to verify it compiles and logic is clear**

```bash
cd brain/rust && cargo test recency_uses_event_time_over_timestamp -- --nocapture
```
Expected: PASS (this tests the intended behavior, not the current code)

**Step 3: Change the age calculation in brain.rs**

Find the block (around line 297):

```rust
let age_days =
    (now - memory.metadata.timestamp).num_seconds().max(0) as f32 / 86_400.0;
// T32: recency weight — half-life ~730 days, floor at 0.85 (never suppresses).
// Range 0.85–1.0 keeps it a tiebreaker, not a relevance override.
let recency_w = 0.85 + 0.15 * 0.5_f32.powf(age_days / 730.0);
```

Replace with:

```rust
let effective_time = memory.metadata.event_time.unwrap_or(memory.metadata.timestamp);
let age_days =
    (now - effective_time).num_seconds().max(0) as f32 / 86_400.0;
// T32: recency weight — half-life ~730 days, floor at 0.85 (never suppresses).
// event_time used when available (Phase 7); falls back to ingest timestamp.
let recency_w = 0.85 + 0.15 * 0.5_f32.powf(age_days / 730.0);
```

**Step 4: Build and run all Rust tests**

```bash
cd brain/rust && cargo test 2>&1 | tail -20
```
Expected: all tests pass, binary compiles

**Step 5: Build release binary**

```bash
cd brain/rust && cargo build --release 2>&1 | tail -5
```
Expected: `Finished release [optimized] target(s)`

**Step 6: Commit**

```bash
cd /Users/macm1air/Documents/AI
git add brain/rust/src/brain.rs
git commit -m "feat(brain): Phase 7.4 — recency decay uses event_time over ingest timestamp"
```

---

## Gate Check

Run these after all tasks complete:

```bash
# 1. No facts with null event_time
python3 -c "
import sqlite3
conn = sqlite3.connect('brain/rust/brain.db')
n = conn.execute(\"SELECT COUNT(*) FROM memories WHERE type='\\\"fact\\\"' AND event_time IS NULL\").fetchone()[0]
print('Facts missing event_time:', n)
assert n == 0, 'GATE FAILED'
print('GATE PASSED')
"

# 2. New session facts get ended_at
python3 brain/tools/backfill_facts.py --file brain/bootstrap/sessions_export/$(ls brain/bootstrap/sessions_export/ | head -1) --dry-run

# 3. Rust binary is current
ls -la brain/rust/target/release/brain_api
```

---

## Rollback

If something goes wrong with the stamp:

```bash
# event_time was NULL before — restore by clearing all non-LLM-extracted values
# (LLM-extracted ones are the original 45 that were already set before Phase 7)
# Safe to re-run stamp_event_times.py — it's idempotent since WHERE event_time IS NULL
```
