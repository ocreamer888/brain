#!/usr/bin/env python3
"""
Export `feedback_events` from the brain SQLite database as JSONL (one JSON object per line).

Uses the same `BRAIN_DB_PATH` default as the Rust brain (`~/.brain/brain.db`).

Example — last 7 days for offline review:

  BRAIN_DB_PATH=~/.brain/brain.db python3 brain/tools/export_feedback.py --since-days 7 > feedback.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def default_db_path() -> Path:
    home = Path(os.environ.get("HOME", "."))
    return Path(os.environ.get("BRAIN_DB_PATH", home / ".brain" / "brain.db"))


def has_feedback_table(conn: sqlite3.Connection) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='feedback_events' LIMIT 1"
    )
    return cur.fetchone() is not None


def main() -> int:
    p = argparse.ArgumentParser(description="Export feedback_events to JSONL on stdout.")
    p.add_argument(
        "--db",
        type=Path,
        default=None,
        help="SQLite path (default: BRAIN_DB_PATH or ~/.brain/brain.db)",
    )
    p.add_argument(
        "--since-days",
        type=float,
        default=None,
        metavar="N",
        help="Only rows with ts >= (now UTC - N days)",
    )
    args = p.parse_args()
    db_path = args.db or default_db_path()
    if not db_path.is_file():
        print(f"error: database not found: {db_path}", file=sys.stderr)
        return 1

    since: str | None = None
    if args.since_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=args.since_days)
        since = cutoff.isoformat()

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        if not has_feedback_table(conn):
            print("export_feedback: feedback_events table not found; nothing to export", file=sys.stderr)
            return 0

        if since:
            cur = conn.execute(
                "SELECT id, ts, event_type, memory_id, query, session_id, project, source, payload, idempotency_key "
                "FROM feedback_events WHERE ts >= ? ORDER BY ts ASC",
                (since,),
            )
        else:
            cur = conn.execute(
                "SELECT id, ts, event_type, memory_id, query, session_id, project, source, payload, idempotency_key "
                "FROM feedback_events ORDER BY ts ASC"
            )
        for row in cur:
            obj = {
                "schema_version": 1,
                "id": row["id"],
                "ts": row["ts"],
                "event_type": row["event_type"],
                "memory_id": row["memory_id"],
                "query": row["query"],
                "session_id": row["session_id"],
                "project": row["project"],
                "source": row["source"],
                "payload": json.loads(row["payload"] or "{}"),
            }
            if row["idempotency_key"]:
                obj["idempotency_key"] = row["idempotency_key"]
            print(json.dumps(obj, ensure_ascii=False))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
