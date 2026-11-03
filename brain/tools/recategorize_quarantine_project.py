#!/usr/bin/env python3
"""Un-quarantine the 8,200 rows a May backfill tagged with a path fragment
as `project` (e.g. "cursor", "src", "frontend", ".claude") instead of a real
project name, then marked `superseded_by = quarantine:path_fragment_project`.

Verification (2026-10-21, docs/architecture/experiments/2026-10-21-layer-detection/):
these rows are real content, not junk — 0 of 8,200 are empty/content-free, and
0 duplicate an already-visible row. Hiding them throws away real history over
a metadata bug, not a content problem.

There is no stored ground truth for the correct project, so this script does
NOT invent one. It only trusts a project value already present on another live
(non-quarantined) row in the *same session_id* — and only when every such
sibling agrees on one project. Two outcomes:

  - RECOVERED: exactly one real project found among siblings -> project is
    corrected to it, superseded_by cleared.
  - UNRESOLVED: no sibling, or siblings disagree -> project is left as the
    path-fragment value (a bucket, not a false specific project), only
    superseded_by is cleared so the content stops being hidden from search.

Nothing is deleted. Reversible: the backup JSON records id, original
project, original superseded_by for every row; restore via
UPDATE memories SET project = ?, superseded_by = ? WHERE id = ?.

Usage:
  python3 brain/tools/recategorize_quarantine_project.py --dry-run
  python3 brain/tools/recategorize_quarantine_project.py --apply
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

QUARANTINE_TAG = "quarantine:path_fragment_project"
RECOVERED_TAG = "recategorized:quarantine_project_recovered"
UNRESOLVED_TAG = "recategorized:quarantine_project_unresolved"

BAD_PROJECTS = (
    "cursor", "src", "landingpage", "frontend", ".claude", "etl", "rust", "test", "",
)


def _connect(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db), timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")
    return conn


def select_candidates(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute(
        """
        SELECT id, project, tags, session_id, superseded_by
        FROM memories
        WHERE superseded_by = ?
        ORDER BY timestamp
        """,
        (QUARANTINE_TAG,),
    ))


def resolve_real_projects(conn: sqlite3.Connection, session_ids: set[str]) -> dict[str, str]:
    """session_id -> real project, only where exactly one distinct real project
    exists among that session's non-quarantined, non-bad-project rows."""
    placeholders = ",".join("?" for _ in BAD_PROJECTS)
    rows = conn.execute(
        f"""
        SELECT session_id, project
        FROM memories
        WHERE session_id != ''
          AND session_id IN ({",".join("?" for _ in session_ids)})
          AND project NOT IN ({placeholders})
          AND (superseded_by IS NULL OR superseded_by = '')
        GROUP BY session_id, project
        """,
        (*session_ids, *BAD_PROJECTS),
    ) if session_ids else []
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
    unresolved = 0
    for r in rows:
        real_project = real_project_by_session.get(r["session_id"]) if r["session_id"] else None
        if real_project:
            new_tags = append_tag(r["tags"], RECOVERED_TAG)
            conn.execute(
                "UPDATE memories SET project = ?, superseded_by = NULL, tags = ? WHERE id = ? AND superseded_by = ?",
                (real_project, new_tags, r["id"], QUARANTINE_TAG),
            )
            recovered += 1
        else:
            new_tags = append_tag(r["tags"], UNRESOLVED_TAG)
            conn.execute(
                "UPDATE memories SET superseded_by = NULL, tags = ? WHERE id = ? AND superseded_by = ?",
                (new_tags, r["id"], QUARANTINE_TAG),
            )
            unresolved += 1
    conn.commit()
    return recovered, unresolved


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
    unresolved = len(rows) - recoverable

    print(f"candidates={len(rows)}")
    print(f"  recoverable (unambiguous session sibling): {recoverable}")
    print(f"  unresolved (un-hide only, project kept as-is): {unresolved}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = _BACKUP_DIR / f"recategorize_quarantine_project_{ts}.json"
    payload = {
        "quarantine_tag": QUARANTINE_TAG,
        "count": len(rows),
        "recoverable": recoverable,
        "unresolved": unresolved,
        "rows": [
            {
                "id": r["id"],
                "original_project": r["project"],
                "original_superseded_by": r["superseded_by"],
                "session_id": r["session_id"],
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

    recovered_n, unresolved_n = apply_changes(conn, rows, real_project_by_session)
    conn.close()
    print(f"recovered={recovered_n} unresolved={unresolved_n}")
    print("NEXT: restart brain_api (launchctl kickstart -k gui/$(id -u)/com.brain.api)")
    print("      so the in-memory index picks up the unhidden rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
