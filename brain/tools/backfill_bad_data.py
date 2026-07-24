"""
One-shot script: fix all bad memories in brain.db created by ingest bugs.

Fixes:
  1. Conversation UUID titles → "Session YYYY-MM-DD — {project}"
  2. Delete bash-log patterns (content LIKE 'Ran command:%')
  3. Delete generic-titled patterns (title LIKE 'Bash · %')
  4. Delete file-edit solutions (content LIKE 'Edited %' OR title LIKE 'Edit · %')
  5. Delete write-hook solutions with generic titles (title LIKE 'Write · %')

FTS5 sync: memories_fts is not a content table — sync manually.
For deletes: delete from FTS first (needs memories.rowid), then delete from memories.
For updates: update memories, then delete+reinsert in FTS.

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
        "WHERE type='\"conversation\"' AND title LIKE 'Claude Code — %'"
    ).fetchall()

    print(f"  Found {len(rows)} conversations with UUID titles")
    if dry_run:
        return

    for memory_id, timestamp, project in rows:
        date_str = timestamp[:10] if timestamp and len(timestamp) >= 10 else "unknown-date"
        new_title = f"Session {date_str} — {project}"

        conn.execute("UPDATE memories SET title=? WHERE id=?", (new_title, memory_id))
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
    ids = [
        row[0] for row in conn.execute(
            "SELECT id FROM memories WHERE type='\"pattern\"' "
            "AND (content LIKE 'Ran command:%' OR title LIKE 'Bash · %')"
        ).fetchall()
    ]

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
    ids = [
        row[0] for row in conn.execute(
            "SELECT id FROM memories WHERE type='\"solution\"' "
            "AND (content LIKE 'Edited %' OR title LIKE 'Edit · %' OR title LIKE 'Write · %')"
        ).fetchall()
    ]

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
