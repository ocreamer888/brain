#!/usr/bin/env python3
"""
Append new feedback_events to a markdown digest (Obsidian-style daily inbox).

Hooks + API record events in real time; this job runs on a schedule (e.g. daily) to
surface what landed since the last run—same rhythm as reviewing an inbox, without
manual export.

Checkpoint: `.cursor/hooks/state/feedback-digest-state.json` (last ts + id).

Examples (from repo root `AI/`):

  python3 brain/tools/feedback_digest.py
  python3 brain/tools/feedback_digest.py --dry-run

  # macOS daily at 07:00 — see docs/PHASE7.md (launchd)
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_db_path() -> Path:
    home = Path(os.environ.get("HOME", "."))
    return Path(os.environ.get("BRAIN_DB_PATH", home / ".brain" / "brain.db"))


def default_state_path() -> Path:
    custom = os.environ.get("FEEDBACK_DIGEST_STATE", "").strip()
    if custom:
        return Path(custom)
    return repo_root() / ".cursor" / "hooks" / "state" / "feedback-digest-state.json"


def default_out_dir() -> Path:
    custom = os.environ.get("FEEDBACK_DIGEST_OUT_DIR", "").strip()
    if custom:
        return Path(custom)
    return repo_root() / "docs" / "feedback-digests"


def load_state(path: Path) -> tuple[str, str]:
    if not path.is_file():
        return "", ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return "", ""
    if not isinstance(data, dict):
        return "", ""
    last_ts = str(data.get("last_ts") or "")
    last_id = str(data.get("last_id") or "")
    return last_ts, last_id


def save_state(path: Path, last_ts: str, last_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "last_ts": last_ts,
        "last_id": last_id,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def row_line(row: sqlite3.Row, truncate_query: int) -> str:
    parts: list[str] = [
        f"`{row['event_type']}`",
        f"src={row['source']}",
    ]
    if row["memory_id"]:
        mid = row["memory_id"]
        if len(mid) > 12:
            mid = mid[:8] + "…"
        parts.append(f"id={mid}")
    if row["project"]:
        parts.append(f"proj={row['project']}")
    q = row["query"] or ""
    if q:
        if len(q) > truncate_query:
            q = q[: truncate_query - 1] + "…"
        parts.append(f"q=`{q}`")
    pl = row["payload"] or "{}"
    if pl and pl != "{}":
        if len(pl) > 80:
            pl = pl[:79] + "…"
        parts.append(f"payload={pl}")
    return "- " + " | ".join(parts)


def has_feedback_table(conn: sqlite3.Connection) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='feedback_events' LIMIT 1"
    )
    return cur.fetchone() is not None


def main() -> int:
    ap = argparse.ArgumentParser(description="Incremental feedback → markdown digest.")
    ap.add_argument("--db", type=Path, default=None, help="SQLite path (default: BRAIN_DB_PATH)")
    ap.add_argument("--state", type=Path, default=None, help="Checkpoint JSON path")
    ap.add_argument("--out-dir", type=Path, default=None, help="Digest output directory")
    ap.add_argument(
        "--bootstrap-hours",
        type=float,
        default=24.0,
        metavar="H",
        help="If no checkpoint exists, only include events from the last H hours (default: 24)",
    )
    ap.add_argument(
        "--truncate-query",
        type=int,
        default=120,
        metavar="N",
        help="Max chars for query snippet in markdown (default: 120)",
    )
    ap.add_argument("--dry-run", action="store_true", help="Print actions; do not write files")
    args = ap.parse_args()

    db_path = args.db or default_db_path()
    state_path = args.state or default_state_path()
    out_dir = args.out_dir or default_out_dir()

    if not db_path.is_file():
        print(f"error: database not found: {db_path}", file=sys.stderr)
        return 1

    last_ts, last_id = load_state(state_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows: list[sqlite3.Row] = []
    try:
        if not has_feedback_table(conn):
            print("feedback_digest: feedback_events table not found; skipping", file=sys.stderr)
            if not last_ts and not args.dry_run:
                save_state(state_path, datetime.now(timezone.utc).isoformat(), "")
            return 0

        if not last_ts:
            # First run: bounded window so we do not dump entire history.
            from datetime import timedelta

            cutoff = datetime.now(timezone.utc) - timedelta(hours=args.bootstrap_hours)
            since = cutoff.isoformat()
            cur = conn.execute(
                "SELECT id, ts, event_type, memory_id, query, session_id, project, source, payload "
                "FROM feedback_events WHERE ts >= ? ORDER BY ts ASC, id ASC",
                (since,),
            )
            rows = list(cur)
        else:
            cur = conn.execute(
                "SELECT id, ts, event_type, memory_id, query, session_id, project, source, payload "
                "FROM feedback_events WHERE (ts > ?) OR (ts = ? AND id > ?) "
                "ORDER BY ts ASC, id ASC",
                (last_ts, last_ts, last_id),
            )
            rows = list(cur)
    finally:
        conn.close()

    if not rows:
        print("feedback_digest: no new events", file=sys.stderr)
        if not last_ts and not args.dry_run:
            # First run with nothing in the bootstrap window — anchor checkpoint so we
            # switch to incremental mode (avoid re-scanning the same 24h forever).
            save_state(state_path, datetime.now(timezone.utc).isoformat(), "")
        return 0

    now = datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    stamp = now.strftime("%H:%M UTC")

    lines = [f"## {stamp}", ""]
    for row in rows:
        lines.append(row_line(row, args.truncate_query))
    lines.append("")

    digest_path = out_dir / f"{day}.md"
    header = f"# Feedback digest — {day}\n\n"

    if args.dry_run:
        print(f"Would append {len(rows)} line(s) to {digest_path}")
        print("\n".join(lines))
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    if digest_path.is_file():
        digest_path.write_text(digest_path.read_text(encoding="utf-8") + "\n".join(lines), encoding="utf-8")
    else:
        digest_path.write_text(header + "\n".join(lines), encoding="utf-8")

    last = rows[-1]
    save_state(state_path, str(last["ts"]), str(last["id"]))

    print(f"feedback_digest: wrote {len(rows)} event(s) → {digest_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
