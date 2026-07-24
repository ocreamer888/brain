# Brain Dedup & Pipeline Fix Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove ~4,000 duplicate memories from the brain DB and fix the three root causes that keep creating them.

**Architecture:** Three bugs compound: (1) `session_end.py` exports the full session transcript on every Stop hook fire — same session_id → N timestamp-named files; (2) `ingest_session_chunks.py` checkpoints by filename, not session_id — processes all N files as N separate sessions; (3) no content dedup at save time. Fix = patch all three, migrate checkpoints, SQL-dedup existing DB, restart brain server.

**Tech Stack:** Python 3.13, SQLite (`brain/rust/brain.db`), pytest, launchctl (macOS)

---

## Context: What We Know

```
DB: /Users/macm1air/Documents/AI/brain/rust/brain.db
brain_api: PID managed by launchd label com.brain.api, port 8787
Sessions export dir: brain/bootstrap/sessions_export/  (489 files)
Chunk checkpoint: brain/bootstrap/checkpoint_session_chunks.json
Ingest checkpoint: brain/bootstrap/checkpoint_claude_code.json

Root cause confirmed:
  - Session d18fcfa5 exported 44 times → 44 files, same content
  - ingest_session_chunks.py processed all 44 → 2,250 memories, 95 unique
  - Same pattern: 5 sessions account for ~3,026 memories out of 6,428 total
```

---

## Task 1: Fix `session_end.py` — prevent duplicate export files, keep timestamps

**Problem:** Creates `session_2026-04-03_06-39-10.json` on every Stop. Same session → 44 files with 44 different timestamps.  
**Fix:** Before creating a new file, scan `sessions_export/` for an existing file with the same `session_id`. If found, overwrite it (preserving original timestamp filename). If not found, create new timestamp-named file as before. Timestamps are preserved for timeline context.

**Files:**
- Modify: `brain/hooks/session_end.py`
- Test: `brain/tests/test_session_end_export.py` (create new)

---

**Step 1: Write the failing test**

Create `brain/tests/test_session_end_export.py`:

```python
"""Test that session_end deduplicates exports by session_id while preserving timestamps."""
import json
from pathlib import Path
import tempfile


def _do_export(export_dir: Path, session_id: str, message_count: int) -> Path:
    """Call the extracted find-or-create logic from session_end.py."""
    from brain.hooks.session_end import find_or_create_export_path
    export_file = find_or_create_export_path(export_dir, session_id)
    data = {
        "session_id": session_id,
        "project": "test",
        "cwd": "/test",
        "ended_at": "2026-01-01T00:00:00Z",
        "message_count": message_count,
        "messages": [],
    }
    export_file.write_text(json.dumps(data))
    return export_file


def test_first_export_uses_timestamp_name():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        path = _do_export(p, "abc-123", 10)
        # Should contain timestamp pattern, not just session_id
        assert path.suffix == ".json"
        assert path.name.startswith("session_")
        assert "abc-123" not in path.name  # NOT named by session_id


def test_second_export_same_session_overwrites_original():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        first_path = _do_export(p, "abc-123", 10)
        first_name = first_path.name  # e.g. session_2026-04-10_10-00-00.json

        second_path = _do_export(p, "abc-123", 20)

        files = list(p.glob("session_*.json"))
        assert len(files) == 1, f"Expected 1 file, got {len(files)}: {[f.name for f in files]}"
        assert second_path.name == first_name  # same filename preserved
        data = json.loads(second_path.read_text())
        assert data["message_count"] == 20  # content updated


def test_different_sessions_create_separate_files():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        import time
        _do_export(p, "session-aaa", 5)
        time.sleep(0.01)  # ensure different timestamp
        _do_export(p, "session-bbb", 5)
        files = list(p.glob("session_*.json"))
        assert len(files) == 2
```

**Step 2: Run — confirm it FAILS**

```bash
cd /Users/macm1air/Documents/AI
python3 -m pytest brain/tests/test_session_end_export.py -v
```

Expected: `ImportError: cannot import name 'find_or_create_export_path'`

**Step 3: Implement — extract `find_or_create_export_path` into `session_end.py`**

Add this function at module level in `brain/hooks/session_end.py` (before the `try:` block):

```python
def find_or_create_export_path(export_dir: Path, session_id: str) -> Path:
    """
    Return a Path for this session's export file.
    - If a file for this session_id already exists: return it (overwrite preserves timestamp).
    - If not: create a new timestamp-named file.
    """
    # Scan for existing file with matching session_id
    for existing in export_dir.glob("session_*.json"):
        try:
            data = json.loads(existing.read_text())
            if data.get("session_id") == session_id:
                return existing  # overwrite this file
        except Exception:
            continue
    # No existing file — create new with timestamp
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    return export_dir / f"session_{ts}.json"
```

Then in `session_end.py`, replace:

```python
ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
export_file = export_dir / f"session_{ts}.json"
```

With:

```python
export_file = find_or_create_export_path(export_dir, session_id)
```

**Step 4: Run — confirm it PASSES**

```bash
python3 -m pytest brain/tests/test_session_end_export.py -v
```

Expected: `3 passed`

**Step 5: Commit**

```bash
git add brain/hooks/session_end.py brain/tests/test_session_end_export.py
git commit -m "fix(session_end): overwrite existing session export instead of creating duplicate files"
```

---

## Task 2: Fix `ingest_session_chunks.py` — checkpoint by session_id

**Problem:** Checkpoint key = filename (`f.name`). Same session with 44 filenames → 44 ingests.  
**Fix:** Checkpoint key = session_id from JSON content. One session_id → skip after first ingest.

**Files:**
- Modify: `brain/tools/ingest_session_chunks.py`
- Modify: `brain/tests/test_ingest_session_chunks.py`

---

**Step 1: Write the failing tests**

Add to `brain/tests/test_ingest_session_chunks.py`:

```python
def test_load_checkpoint_reads_session_ids():
    """Checkpoint stores session_ids, not filenames."""
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
        json.dump({"session_ids": ["uuid-1", "uuid-2"]}, f)
        cp_path = Path(f.name)
    from brain.tools.ingest_session_chunks import load_checkpoint
    result = load_checkpoint(cp_path)
    assert "uuid-1" in result
    assert "uuid-2" in result


def test_main_skips_already_processed_session_id(tmp_path, monkeypatch):
    """Two files with same session_id: only first is processed."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    cp_path = tmp_path / "checkpoint.json"

    session_data = {
        "session_id": "dup-session-uuid",
        "project": "test",
        "cwd": "/test",
        "ended_at": "2026-01-01T00:00:00Z",
        "message_count": 2,
        "messages": [
            {"type": "user", "message": {"role": "user", "content": "what is rust exactly?"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Rust is a systems lang."}]}},
        ],
    }
    # Two files, same session_id
    (sessions_dir / "session_2026-04-03_06-39.json").write_text(json.dumps(session_data))
    (sessions_dir / "session_2026-04-03_07-11.json").write_text(json.dumps(session_data))

    saved = []
    monkeypatch.setattr(
        "brain.tools.ingest_session_chunks.save_memory_batch",
        lambda chunks: saved.extend(chunks),
    )
    monkeypatch.setattr("brain.tools.ingest_session_chunks.SESSIONS_EXPORT", sessions_dir)
    monkeypatch.setattr("brain.tools.ingest_session_chunks.CHECKPOINT", cp_path)

    import sys
    monkeypatch.setattr(sys, "argv", ["ingest_session_chunks.py", "--all"])
    from brain.tools.ingest_session_chunks import main
    main()

    # Session has 1 exchange → 1 chunk. Should only be saved ONCE even with 2 files.
    assert len(saved) == 1
```

**Step 2: Run — confirm FAILS**

```bash
python3 -m pytest brain/tests/test_ingest_session_chunks.py -v
```

Expected: failures on the two new tests.

**Step 3: Implement — change checkpoint key from filename to session_id**

Replace `load_checkpoint` and `save_checkpoint` in `brain/tools/ingest_session_chunks.py`:

```python
def load_checkpoint(path: Path | None = None) -> set:
    cp = path or CHECKPOINT
    if cp.exists():
        data = json.loads(cp.read_text())
        # Support old format (filenames under "done") and new format (session_ids)
        return set(data.get("session_ids", data.get("done", [])))
    return set()


def save_checkpoint(done: set, path: Path | None = None) -> None:
    cp = path or CHECKPOINT
    cp.write_text(json.dumps({"session_ids": sorted(done)}))
```

Replace the `--all` branch in `main()`:

```python
    if args.all:
        done_ids = load_checkpoint()
        files = sorted(SESSIONS_EXPORT.glob("session_*.json"))

        to_process: list[tuple[Path, str]] = []
        for f in files:
            try:
                sid = json.loads(f.read_text()).get("session_id", "")
            except Exception:
                continue
            if sid and sid not in done_ids:
                to_process.append((f, sid))

        print(f"[chunks] {len(to_process)}/{len(files)} sessions to process", file=sys.stderr)
        total = 0
        for f, sid in to_process:
            n = ingest_file(f, args.dry_run)
            total += n
            done_ids.add(sid)
            if not args.dry_run:
                save_checkpoint(done_ids)
            print(f"[chunks] {f.name} (sid={sid[:8]}): {n} chunks", file=sys.stderr)
        print(f"[chunks] done — {total} chunks total")
        return 0
```

**Step 4: Run — confirm PASSES**

```bash
python3 -m pytest brain/tests/test_ingest_session_chunks.py -v
```

Expected: all tests pass.

**Step 5: Commit**

```bash
git add brain/tools/ingest_session_chunks.py brain/tests/test_ingest_session_chunks.py
git commit -m "fix(chunks): checkpoint by session_id not filename — prevents 44x re-ingestion"
```

---

## Task 3: Fix `07_ingest_claude_code.py` — checkpoint by session_id from JSON

**Problem:** Checkpoint key = `f.stem` (filename stem like `session_2026-04-03_...`). With new session_id-named files (`session_{uuid}.json`), old checkpoint entries won't match. Also if same session_id produces two files, both get processed.  
**Fix:** Extract session_id from JSON content. Use that as checkpoint key.

**Files:**
- Modify: `brain/bootstrap/07_ingest_claude_code.py`
- Test: `brain/bootstrap/tests/test_claude_code_ingest_checkpoint.py` (create new)

---

**Step 1: Write the failing test**

Create `brain/bootstrap/tests/test_claude_code_ingest_checkpoint.py`:

```python
"""Test that 07_ingest_claude_code checkpoints by session_id from JSON, not filename."""
import json
import sys
from pathlib import Path
import tempfile
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


def make_session_file(directory: Path, filename: str, session_id: str) -> Path:
    data = {
        "session_id": session_id,
        "project": "test",
        "cwd": "/test",
        "ended_at": "2026-01-01T00:00:00Z",
        "message_count": 2,
        "messages": [
            {"role": "user", "content": "hello world, what is rust?"},
            {"role": "assistant", "content": "Rust is a systems language focused on safety."},
        ],
    }
    p = directory / filename
    p.write_text(json.dumps(data))
    return p


def test_checkpoint_uses_session_id_not_filename(tmp_path, monkeypatch):
    """Two files, same session_id — only ONE memory should be saved."""
    sessions_dir = tmp_path / "sessions_export"
    sessions_dir.mkdir()
    cp_path = tmp_path / "checkpoint.json"

    make_session_file(sessions_dir, "session_2026-04-03_06-00-00.json", "real-uuid-abc")
    make_session_file(sessions_dir, "session_2026-04-03_07-00-00.json", "real-uuid-abc")

    saved = []
    monkeypatch.setattr("brain.bootstrap.07_ingest_claude_code.save_memory_batch",  # noqa (import by path)
                        lambda items: saved.extend(items) or {"results": [{"index": i} for i in range(len(items))]})

    from brain.bootstrap.ingest_claude_code_lib import run_with_dirs  # see Step 3
    run_with_dirs(sessions_dir=sessions_dir, checkpoint_path=cp_path, use_llm=False)

    assert len(saved) == 1  # only one save, not two
    cp_data = json.loads(cp_path.read_text())
    assert "real-uuid-abc" in cp_data["processed_ids"]
```

**Step 2: Run — confirm FAILS**

```bash
python3 -m pytest brain/bootstrap/tests/test_claude_code_ingest_checkpoint.py -v
```

Expected: `ModuleNotFoundError` or similar.

**Step 3: Implement — extract `run_with_dirs` and fix checkpoint key**

In `brain/bootstrap/07_ingest_claude_code.py`, change the checkpoint key from `f.stem` to the session_id extracted from the JSON:

Inside `run()`, change:

```python
# OLD
for i, f in enumerate(session_files, 1):
    session_id = f.stem
    if session_id in processed:
        ...
    ...
    processed.add(session_id)
```

To:

```python
# NEW
for i, f in enumerate(session_files, 1):
    # Use the actual session_id from JSON content as checkpoint key
    try:
        raw = json.loads(f.read_text())
        checkpoint_key = raw.get("session_id") or f.stem
    except Exception:
        checkpoint_key = f.stem

    if checkpoint_key in processed:
        print(f"  [{i}/{len(session_files)}] {f.name} (already processed)")
        continue
    ...
    pending_session_ids.append(checkpoint_key)   # was: session_id
```

Also update `flush_pending`:
```python
# processed.add(sid) — no change needed, just ensure pending_session_ids holds keys
```

**Step 4: Run — confirm PASSES**

```bash
python3 -m pytest brain/bootstrap/tests/test_claude_code_ingest_checkpoint.py -v
```

**Step 5: Commit**

```bash
git add brain/bootstrap/07_ingest_claude_code.py brain/bootstrap/tests/test_claude_code_ingest_checkpoint.py
git commit -m "fix(ingest): checkpoint 07_ingest_claude_code by session_id from JSON not filename"
```

---

## Task 4: Migrate checkpoints — populate from DB

**Problem:** Existing checkpoints have filename stems (old format). After fix, they won't match session_id keys. Without migration, all existing sessions would be re-ingested.  
**Fix:** One-off script that reads all session_ids already in the brain DB and writes them as the new checkpoint format.

**Files:**
- Create (one-off): `brain/tools/migrate_checkpoints.py`

---

**Step 1: Write and run the migration script**

Create `brain/tools/migrate_checkpoints.py`:

```python
#!/usr/bin/env python3
"""
One-off: populate ingest checkpoints with session_ids already in DB.
Prevents re-ingesting sessions that are already in the brain.

Run: python3 brain/tools/migrate_checkpoints.py
"""
import json
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "rust" / "brain.db"
CHUNK_CP = Path(__file__).resolve().parents[1] / "bootstrap" / "checkpoint_session_chunks.json"
INGEST_CP = Path(__file__).resolve().parents[1] / "bootstrap" / "checkpoint_claude_code.json"


def main():
    if not DB.exists():
        print(f"DB not found: {DB}")
        return

    conn = sqlite3.connect(str(DB))
    session_ids = {
        r[0] for r in conn.execute(
            "SELECT DISTINCT session_id FROM memories WHERE session_id != '' AND session_id IS NOT NULL"
        ).fetchall()
    }
    conn.close()

    print(f"Found {len(session_ids)} distinct session_ids in DB")

    # Write chunk checkpoint (session_ids format)
    CHUNK_CP.write_text(json.dumps({"session_ids": sorted(session_ids)}, indent=2))
    print(f"Written: {CHUNK_CP}")

    # Write ingest checkpoint (processed_ids format)
    INGEST_CP.write_text(json.dumps({"processed_ids": sorted(session_ids)}, indent=2))
    print(f"Written: {INGEST_CP}")

    print("Done. Re-ingestion of existing sessions is now blocked.")


if __name__ == "__main__":
    main()
```

**Step 2: Run it**

```bash
cd /Users/macm1air/Documents/AI
python3 brain/tools/migrate_checkpoints.py
```

Expected output:
```
Found 2249 distinct session_ids in DB
Written: brain/bootstrap/checkpoint_session_chunks.json
Written: brain/bootstrap/checkpoint_claude_code.json
Done. Re-ingestion of existing sessions is now blocked.
```

**Step 3: Verify dry-run shows 0 new sessions**

```bash
python3 brain/tools/ingest_session_chunks.py --all --dry-run 2>&1 | tail -5
python3 brain/bootstrap/07_ingest_claude_code.py --no-llm 2>&1 | tail -5
```

Expected: both show `0 sessions to process` or `0 chunks total`.

**Step 4: Commit**

```bash
git add brain/tools/migrate_checkpoints.py \
        brain/bootstrap/checkpoint_session_chunks.json \
        brain/bootstrap/checkpoint_claude_code.json
git commit -m "fix(checkpoints): migrate to session_id keys — blocks re-ingestion of existing sessions"
```

---

## Task 5: SQL dedup — remove duplicate memories from DB

**Problem:** 6,428 memories, ~4,000 are duplicates. One session has 197 copies of the same message.  
**Fix:** Keep one row per unique content (earliest rowid). Delete the rest. Backup first.

**Files:**
- Create (one-off): `brain/tools/dedup_db.py`

---

**Step 1: Write the dedup script**

Create `brain/tools/dedup_db.py`:

```python
#!/usr/bin/env python3
"""
One-off: remove duplicate memories from brain.db.
Keeps the earliest copy (MIN rowid) of each unique content.
Creates a backup before deleting.

Run: python3 brain/tools/dedup_db.py
Add --dry-run to preview without deleting.
"""
import shutil
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "rust" / "brain.db"
BACKUP = DB.with_suffix(".db.bak")


def main():
    dry_run = "--dry-run" in sys.argv

    if not DB.exists():
        print(f"DB not found: {DB}")
        sys.exit(1)

    conn = sqlite3.connect(str(DB))
    cur = conn.cursor()

    before = cur.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    dupes = cur.execute("""
        SELECT COUNT(*) FROM memories
        WHERE rowid NOT IN (SELECT MIN(rowid) FROM memories GROUP BY content)
    """).fetchone()[0]

    print(f"Total memories: {before}")
    print(f"Duplicates to remove: {dupes}")
    print(f"Expected after: {before - dupes}")

    if dry_run:
        print("\n[dry-run] No changes made.")
        conn.close()
        return

    # Backup
    shutil.copy2(DB, BACKUP)
    print(f"\nBackup created: {BACKUP}")

    # Delete duplicates
    cur.execute("""
        DELETE FROM memories
        WHERE rowid NOT IN (SELECT MIN(rowid) FROM memories GROUP BY content)
    """)
    conn.commit()

    after = cur.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    conn.close()

    print(f"Done. Before: {before} → After: {after} (removed {before - after})")
    print("Restart brain_api to reload clean vector index.")


if __name__ == "__main__":
    main()
```

**Step 2: Dry-run first**

```bash
cd /Users/macm1air/Documents/AI
python3 brain/tools/dedup_db.py --dry-run
```

Expected output:
```
Total memories: 6428
Duplicates to remove: ~4000
Expected after: ~2400
[dry-run] No changes made.
```

If the duplicate count looks wrong (e.g. < 100 or > 6000), STOP and investigate before proceeding.

**Step 3: Run the dedup**

```bash
python3 brain/tools/dedup_db.py
```

Expected:
```
Backup created: brain/rust/brain.db.bak
Done. Before: 6428 → After: ~2400 (removed ~4000)
Restart brain_api to reload clean vector index.
```

**Step 4: Commit the script** (not the DB — it's not in git)

```bash
git add brain/tools/dedup_db.py
git commit -m "tools: add dedup_db.py — removes duplicate memories, keeps earliest per content"
```

---

## Task 6: Restart brain_api — reload clean vector index

**Why:** brain_api loaded its in-memory VectorIndex from SQLite at startup. After dedup, deleted row IDs still exist in memory. Must restart to reload from clean DB.

**Files:** none (system operation)

---

**Step 1: Stop brain_api**

```bash
launchctl stop com.brain.api
sleep 2
pgrep -f brain_api && echo "still running — wait" || echo "stopped"
```

**Step 2: Start brain_api**

```bash
launchctl start com.brain.api
sleep 5
```

**Step 3: Verify it's up**

```bash
curl -s http://127.0.0.1:8787/stats -H "X-API-Key: local-dev-key" | python3 -m json.tool
```

Expected: JSON with `total_memories` matching the post-dedup count (~2,400, not 6,428).

If it fails to start, check the log:
```bash
tail -30 /Users/macm1air/Documents/AI/brain/logs/brain_api.err
```

---

## Task 7: Verify end-to-end

No code changes — just confirm everything works.

**Step 1: Check memory count**

```bash
python3 -c "
import sys; sys.path.insert(0, '/Users/macm1air/Documents/AI')
from brain.api_client import get_stats
s = get_stats()
print('Memories:', s['total_memories'])
print('Sessions:', s['total_sessions'])
"
```

Expected: `total_memories` significantly lower than 6,428. If still at 6,428, brain_api didn't restart properly.

**Step 2: Search quality check**

```bash
python3 -c "
import sys; sys.path.insert(0, '/Users/macm1air/Documents/AI')
from brain.api_client import search
results = search('karpathy autoresearch obsidian wiki', n=5)
for r in results:
    print(r['metadata']['source'], '|', r['content'][:100])
"
```

Expected: results are relevant (karpathy docs, not random session chunks).

**Step 3: Confirm ingest pipelines are idempotent**

```bash
python3 brain/tools/ingest_session_chunks.py --all --dry-run 2>&1 | grep "sessions to process"
python3 brain/bootstrap/07_ingest_claude_code.py --no-llm 2>&1 | tail -3
```

Expected: `0 sessions to process` for both.

**Step 4: Final commit if any loose files**

```bash
git status
git diff
```

Commit anything uncommitted.

---

## Summary: What Each Fix Does

| Bug | Root cause | Fix |
|-----|-----------|-----|
| 44 export files per session | `session_end.py` uses timestamp in filename | Name by `session_{session_id}.json` — overwrites |
| 44x chunk ingestion | `ingest_session_chunks.py` checkpoints by filename | Checkpoint by session_id from JSON |
| Old checkpoint mismatch | Checkpoint has filename stems, not UUIDs | `migrate_checkpoints.py` rebuilds from DB |
| 4,000 existing dupes | No dedup at save time | `dedup_db.py` SQL delete, keep MIN(rowid) per content |
| Stale vector index | DB changed without server restart | `launchctl stop/start com.brain.api` |


<!-- brain-linker -->
## Related
- [[brain-graph/conversation/User]]
- [[brain-graph/pattern/Ran command python3 braintoolsingest_session_chunks.py --all]]
- [[brain-graph/solution/Wrote Usersmacm1airDocumentsAIbraintoolsingest_session_chunk]]
- [[brain-graph/conversation/Claude Code session AI Ended 2026-04-09T045953.269990+0000 C]]
- [[brain-graph/pattern/Successfully verified that the `brain` module imports and th]]
<!-- /brain-linker -->
