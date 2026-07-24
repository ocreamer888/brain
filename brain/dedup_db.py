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
