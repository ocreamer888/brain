#!/usr/bin/env python3
"""Reclassify dangling `superseded_by` pointers as quarantined (G2/G7 prep).

59 live rows have `superseded_by` set to a UUID that no longer resolves to
any existing memory -- their real successor was deleted at some point by a
later cleanup pass. Every existing quarantine/cleanup tool
(hide_untraceable_bad_project_facts.py, quarantine_path_fragment_facts.py,
recategorize_generic_project_tags.py, retag_path_fragment_projects.py)
explicitly skips rows where `superseded_by` is already non-null
(`AND (superseded_by IS NULL OR superseded_by = '')`), so these 59 rows fell
through every pass -- not because they're different content (sampled: same
mechanical session-dump noise, same cursor/src/frontend/ocreamer project
pattern as the May-2026 backfill bug already quarantined elsewhere), but
because they already looked "superseded" to those scripts' WHERE clauses.

They are already excluded from search today (SearchFilter::
exclude_superseded hides any non-null superseded_by, regardless of string
content) -- this does not change what's visible. It only replaces an
ambiguous, no-longer-resolving UUID with the same quarantine-sentinel
convention the rest of the corpus already uses, so future code (G7/G8)
walking supersede chains doesn't have to guess whether a string is a real
pointer or dead weight.

Usage:
    python3 brain/tools/reclassify_dangling_superseded.py --dry-run
    python3 brain/tools/reclassify_dangling_superseded.py --apply
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

DANGLING_TAG = "quarantine:dangling_reference"


def _connect(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db), timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")
    return conn


def select_candidates(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT id, project, superseded_by
            FROM memories
            WHERE superseded_by IS NOT NULL
              AND superseded_by != ''
              AND superseded_by NOT LIKE 'quarantine:%'
              AND superseded_by NOT LIKE 'hidden:%'
              AND superseded_by NOT IN (SELECT id FROM memories)
            ORDER BY timestamp
            """
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
    print(f"candidates to reclassify: {len(rows)}")
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
    backup_path = _BACKUP_DIR / f"reclassify_dangling_superseded_{stamp}.json"
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
                (DANGLING_TAG, id_),
            )
    print(f"reclassified {len(ids)} rows with superseded_by={DANGLING_TAG!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
