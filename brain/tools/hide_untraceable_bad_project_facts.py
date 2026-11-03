#!/usr/bin/env python3
"""Soft-hide the ~8,565 live memories whose `project` is a path-fragment
metadata bug (cursor/src/landingpage/frontend/.claude/etl/rust/test/""),
not a real project name.

2026-11-02 decision: these were already verified real (non-empty, non-
duplicate) in the 2026-10-21 layer-detection experiment, and un-quarantined
on that basis. But 97.9% are single-sentence `fact` rows (77.6% with content
identical to title -- zero elaboration) spread across 1,015 sessions with no
recoverable real project (recategorize_quarantine_project.py's session-
sibling method finds a project for ~0.4% of them). They are real but
untraceable to any project or surrounding context, and at 8,565 rows they
are the single largest "project" bucket in the corpus -- diluting unscoped
search (see brain/eval/last_report*.json).

This sets `superseded_by` (soft-hide, same mechanism as the original
quarantine) rather than deleting -- reversible, and consistent with the
2026-10 decision not to destroy real history over a metadata bug. Hidden
rows stay in brain.db and are excluded from search via the existing
SearchFilter::exclude_superseded (default true), live, no restart needed.

Usage:
    python3 brain/tools/hide_untraceable_bad_project_facts.py --dry-run
    python3 brain/tools/hide_untraceable_bad_project_facts.py --apply
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

HIDE_TAG = "hidden:no_traceable_project_2026-11-02"
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
    return list(
        conn.execute(
            f"""
            SELECT id, project, superseded_by
            FROM memories
            WHERE project IN ({placeholders})
              AND (superseded_by IS NULL OR superseded_by = '')
            ORDER BY timestamp
            """,
            BAD_PROJECTS,
        )
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=_DB_DEFAULT)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    conn = _connect(args.db)
    rows = select_candidates(conn)
    print(f"candidates to hide: {len(rows)}")
    by_project: dict[str, int] = {}
    for r in rows:
        by_project[r["project"]] = by_project.get(r["project"], 0) + 1
    for proj, count in sorted(by_project.items(), key=lambda kv: -kv[1]):
        print(f"  {proj!r}: {count}")

    if not rows:
        print("nothing to do")
        return 0

    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup_path = _BACKUP_DIR / f"hide_untraceable_bad_project_{stamp}.json"
    backup_path.write_text(
        json.dumps(
            [{"id": r["id"], "project": r["project"], "superseded_by": r["superseded_by"]} for r in rows],
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"backup={backup_path}")

    if args.dry_run:
        print("dry-run: no writes")
        return 0

    ids = [r["id"] for r in rows]
    with conn:
        for id_ in ids:
            conn.execute(
                "UPDATE memories SET superseded_by = ? WHERE id = ?",
                (HIDE_TAG, id_),
            )
    print(f"hid {len(ids)} rows with superseded_by={HIDE_TAG!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
