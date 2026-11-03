#!/usr/bin/env python3
"""Recategorize raw PostToolUse traces from solution/decision into episode.

Fixes mistyped rows from the old post_tool_use.py, which saved every plain
Write tool call as a `solution` ("Created {path}\\nContent preview: ...")
and every Agent dispatch as a `decision` ("Dispatched agent: ...") — pure
tool telemetry with no reasoning, crowding out curated knowledge in search
and context-injection (2026-10-20 audit: 1,489 + 79 rows).

This does NOT delete or truncate anything — content, title, and tags are
untouched. Only the `type` column changes, from solution/decision to
episode, which is what these always were: raw audit trail, not curated
knowledge. `Brain::search` excludes episode rows from untyped queries by
default (brain.rs SearchFilter.exclude_episodes_by_default) — the full
trace stays queryable via an explicit memory_type=episode filter or
get_episode(id), it just stops wasting context-injection tokens.

Reversible: the backup JSON records every id + original type; restore by
UPDATE memories SET type = <original> WHERE id IN (...).

Usage:
  python3 brain/tools/recategorize_episodic_traces.py --dry-run
  python3 brain/tools/recategorize_episodic_traces.py --apply
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_DB_DEFAULT = _REPO / "brain" / "rust" / "brain.db"
_BACKUP_DIR = _REPO / "brain" / "bootstrap" / "junk_scrub_backups"

RECAT_TAG = "recategorized:episode_trace"

PATTERNS = (
    ("solution", "Created /%", "write_source"),
    ("decision", "%Dispatched agent:%", "agent_dispatch"),
)


def _connect(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db), timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")
    return conn


def select_candidates(conn: sqlite3.Connection) -> dict[str, list[sqlite3.Row]]:
    out: dict[str, list[sqlite3.Row]] = {}
    for old_type, like_pattern, reason in PATTERNS:
        sql = """
            SELECT id, type, project, tags, title, content, timestamp
            FROM memories
            WHERE type = ?
              AND content LIKE ?
              AND (superseded_by IS NULL OR superseded_by = '')
            ORDER BY timestamp
        """
        rows = list(conn.execute(sql, (f'"{old_type}"', like_pattern)))
        out[reason] = rows
    return out


def append_tag(tags: str | None, tag: str) -> str:
    parts = [t.strip() for t in (tags or "").split(",") if t.strip()]
    if tag not in parts:
        parts.append(tag)
    return ",".join(parts)


def apply_recategorize(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> int:
    updated = 0
    for r in rows:
        new_tags = append_tag(r["tags"], RECAT_TAG)
        cur = conn.execute(
            """
            UPDATE memories
            SET type = '"episode"',
                tags = ?
            WHERE id = ?
              AND (superseded_by IS NULL OR superseded_by = '')
            """,
            (new_tags, r["id"]),
        )
        updated += cur.rowcount
    conn.commit()
    return updated


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, default=_DB_DEFAULT)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = p.parse_args()

    if not args.db.exists():
        print(f"error: db not found: {args.db}", file=sys.stderr)
        return 1

    conn = _connect(args.db)
    by_reason = select_candidates(conn)
    all_rows = [r for rows in by_reason.values() for r in rows]

    print(f"candidates={len(all_rows)}")
    for reason, rows in by_reason.items():
        print(f"  {reason}: {len(rows)}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = _BACKUP_DIR / f"recategorize_episodic_{ts}.json"
    payload = {
        "tag": RECAT_TAG,
        "count": len(all_rows),
        "by_reason": {k: len(v) for k, v in by_reason.items()},
        "rows": [
            {"id": r["id"], "original_type": r["type"], "project": r["project"]}
            for rows in by_reason.values()
            for r in rows
        ],
        "sample": [
            {
                "id": r["id"],
                "original_type": r["type"],
                "project": r["project"],
                "content": (r["content"] or "")[:200],
            }
            for reason, rows in by_reason.items()
            for r in rows[:10]
        ],
    }
    backup.write_text(json.dumps(payload, indent=2))
    print(f"backup={backup}")

    if args.dry_run:
        print("dry-run: no writes")
        conn.close()
        return 0

    n = apply_recategorize(conn, all_rows)
    conn.close()
    print(f"recategorized={n}")
    print("NEXT: restart brain_api (launchctl kickstart -k gui/$(id -u)/com.brain.api)")
    print("      so the Rust binary with exclude_episodes_by_default is live.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
