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
