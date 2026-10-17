#!/usr/bin/env python3
"""Quarantine path-fragment-project facts (soft-delete via superseded_by).

Marks fact_type-tagged memories whose project is a Cursor path fragment
(cursor/src/frontend/landingpage/.claude/…) with:

  superseded_by = 'quarantine:path_fragment_project'
  tags          += quarantine:path_fragment_project
  salience      = 0.1

Search excludes superseded by default; after brain_api restart the vector
index also omits them (get_embeddings_for_index skips superseded).

Reversible: clear superseded_by / tag and restart.

Usage:
  python3 brain/tools/quarantine_path_fragment_facts.py --dry-run
  python3 brain/tools/quarantine_path_fragment_facts.py --apply
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

QUARANTINE_SENTINEL = "quarantine:path_fragment_project"
QUARANTINE_TAG = "quarantine:path_fragment_project"
QUARANTINE_SALIENCE = 0.1

# Path fragments from Cursor vscdb backfill (_infer_cursor_project) + mis-detects.
BAD_PROJECTS = (
    "cursor",
    "src",
    "frontend",
    "landingpage",
    ".claude",
    "rust",
    "test",
    "etl",
    "app",
    "lib",
    "components",
    "pages",
    "utils",
    "hooks",
)


def _connect(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db), timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")
    return conn


def select_candidates(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    placeholders = ",".join("?" * len(BAD_PROJECTS))
    sql = f"""
        SELECT id, type, project, tags, salience, superseded_by, title, content, timestamp
        FROM memories
        WHERE tags LIKE '%fact_type:%'
          AND project IN ({placeholders})
          AND (superseded_by IS NULL OR superseded_by = '')
        ORDER BY project, timestamp
    """
    return list(conn.execute(sql, BAD_PROJECTS))


def append_tag(tags: str | None, tag: str) -> str:
    parts = [t.strip() for t in (tags or "").split(",") if t.strip()]
    if tag not in parts:
        parts.append(tag)
    return ",".join(parts)


def apply_quarantine(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> int:
    updated = 0
    for r in rows:
        new_tags = append_tag(r["tags"], QUARANTINE_TAG)
        cur = conn.execute(
            """
            UPDATE memories
            SET superseded_by = ?,
                tags = ?,
                salience = ?
            WHERE id = ?
              AND (superseded_by IS NULL OR superseded_by = '')
            """,
            (QUARANTINE_SENTINEL, new_tags, QUARANTINE_SALIENCE, r["id"]),
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
    rows = select_candidates(conn)
    by_proj: dict[str, int] = {}
    for r in rows:
        by_proj[r["project"]] = by_proj.get(r["project"], 0) + 1

    print(f"candidates={len(rows)}")
    for proj, n in sorted(by_proj.items(), key=lambda x: -x[1]):
        print(f"  {proj}: {n}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = _BACKUP_DIR / f"quarantine_path_fragment_{ts}.json"
    payload = {
        "sentinel": QUARANTINE_SENTINEL,
        "count": len(rows),
        "by_project": by_proj,
        "ids": [r["id"] for r in rows],
        "sample": [
            {
                "id": r["id"],
                "project": r["project"],
                "tags": r["tags"],
                "content": (r["content"] or "")[:200],
            }
            for r in rows[:20]
        ],
    }
    backup.write_text(json.dumps(payload, indent=2))
    print(f"backup={backup}")

    if args.dry_run:
        print("dry-run: no writes")
        conn.close()
        return 0

    n = apply_quarantine(conn, rows)
    conn.close()
    print(f"quarantined={n}")
    print("NEXT: rebuild brain_api index (launchctl kickstart -k gui/$(id -u)/com.brain.api)")
    print("      so quarantined rows drop out of the in-memory vector index.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
