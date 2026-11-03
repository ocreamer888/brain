#!/usr/bin/env python3
"""Fix the generic-bucket `project` mistagging bug beyond the rows the May
backfill already flagged with `quarantine:path_fragment_project`.

Scope check (2026-10-22): after recategorize_quarantine_project.py fixed the
8,200 quarantined rows, 2,962 LIVE rows still carry a generic-bucket project
value ("cursor", "src", "frontend", "landingpage", ".claude", "etl", "rust",
"test") and were never quarantined at all. This includes the older side of
135 supersede pairs that looked like false "cross-project" layers purely
because one side kept the generic tag while the other got the real project
name — fixing those removes the false cross-project signal at the source.

Same rule as recategorize_quarantine_project.py: never invent a project. A
row is only corrected when its session_id has exactly one distinct real
(non-generic) project among OTHER live rows in that session. Rows with no
such unambiguous sibling are left untouched (not hidden, not guessed) but
tagged as checked so a future pass can tell "reviewed, unresolved" apart
from "never looked at."

This does not touch superseded_by. Nothing is deleted. Reversible: the
backup JSON records id + original project for every row; restore via
UPDATE memories SET project = ? WHERE id = ?.

Usage:
  python3 brain/tools/recategorize_generic_project_tags.py --dry-run
  python3 brain/tools/recategorize_generic_project_tags.py --apply
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

RECOVERED_TAG = "recategorized:generic_project_recovered"
CHECKED_TAG = "recategorized:generic_project_checked"
ALREADY_HANDLED_TAG_PREFIX = "recategorized:quarantine_project"

BAD_PROJECTS = (
    "cursor", "src", "landingpage", "frontend", ".claude", "etl", "rust", "test", "",
)


def _connect(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db), timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")
    return conn


def select_candidates(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    placeholders = ",".join("?" for _ in BAD_PROJECTS)
    return list(conn.execute(
        f"""
        SELECT id, project, tags, session_id, superseded_by
        FROM memories
        WHERE project IN ({placeholders})
          AND project != ''
          AND tags NOT LIKE '%{ALREADY_HANDLED_TAG_PREFIX}%'
        ORDER BY timestamp
        """,
        BAD_PROJECTS,
    ))


def resolve_real_projects(conn: sqlite3.Connection, session_ids: set[str]) -> dict[str, str]:
    if not session_ids:
        return {}
    placeholders = ",".join("?" for _ in BAD_PROJECTS)
    sid_placeholders = ",".join("?" for _ in session_ids)
    rows = conn.execute(
        f"""
        SELECT session_id, project
        FROM memories
        WHERE session_id != ''
          AND session_id IN ({sid_placeholders})
          AND project NOT IN ({placeholders})
          AND (superseded_by IS NULL OR superseded_by = '')
        GROUP BY session_id, project
        """,
        (*session_ids, *BAD_PROJECTS),
    )
    by_session: dict[str, set[str]] = {}
    for r in rows:
        by_session.setdefault(r["session_id"], set()).add(r["project"])
    return {sid: next(iter(projects)) for sid, projects in by_session.items() if len(projects) == 1}


def append_tag(tags: str | None, tag: str) -> str:
    parts = [t.strip() for t in (tags or "").split(",") if t.strip()]
    if tag not in parts:
        parts.append(tag)
    return ",".join(parts)


def apply_changes(conn: sqlite3.Connection, rows: list[sqlite3.Row], real_project_by_session: dict[str, str]) -> tuple[int, int]:
    recovered = 0
    checked = 0
    for r in rows:
        real_project = real_project_by_session.get(r["session_id"]) if r["session_id"] else None
        if real_project:
            new_tags = append_tag(r["tags"], RECOVERED_TAG)
            conn.execute(
                "UPDATE memories SET project = ?, tags = ? WHERE id = ?",
                (real_project, new_tags, r["id"]),
            )
            recovered += 1
        else:
            new_tags = append_tag(r["tags"], CHECKED_TAG)
            conn.execute(
                "UPDATE memories SET tags = ? WHERE id = ?",
                (new_tags, r["id"]),
            )
            checked += 1
    conn.commit()
    return recovered, checked


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
    rows = select_candidates(conn)
    session_ids = {r["session_id"] for r in rows if r["session_id"]}
    real_project_by_session = resolve_real_projects(conn, session_ids)

    recoverable = sum(1 for r in rows if r["session_id"] and r["session_id"] in real_project_by_session)
    checked_only = len(rows) - recoverable

    print(f"candidates={len(rows)}")
    print(f"  recoverable (unambiguous session sibling): {recoverable}")
    print(f"  checked_only (left as-is, tagged reviewed): {checked_only}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = _BACKUP_DIR / f"recategorize_generic_project_tags_{ts}.json"
    payload = {
        "bad_projects": BAD_PROJECTS,
        "count": len(rows),
        "recoverable": recoverable,
        "checked_only": checked_only,
        "rows": [
            {
                "id": r["id"],
                "original_project": r["project"],
                "session_id": r["session_id"],
                "superseded_by": r["superseded_by"],
                "recovered_project": real_project_by_session.get(r["session_id"]) if r["session_id"] else None,
            }
            for r in rows
        ],
    }
    backup.write_text(json.dumps(payload, indent=2))
    print(f"backup={backup}")

    if args.dry_run:
        print("dry-run: no writes")
        conn.close()
        return 0

    recovered_n, checked_n = apply_changes(conn, rows, real_project_by_session)
    conn.close()
    print(f"recovered={recovered_n} checked_only={checked_n}")
    print("NEXT: restart brain_api (launchctl kickstart -k gui/$(id -u)/com.brain.api)")
    print("      so the in-memory index picks up the corrected project tags.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
