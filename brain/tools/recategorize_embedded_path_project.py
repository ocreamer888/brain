#!/usr/bin/env python3
"""Recover the real project for episode/solution rows whose generic-bucket
`project` tag couldn't be fixed by session-sibling inference, but whose
content embeds the real project folder directly: raw tool-trace rows like
"Created /Users/Shared/Code/sicop-health/services/analytics/..." carry the
real project name ("sicop-health") right in the path, regardless of what
`project` got set to at save time.

Scope (2026-10-22): of the 9,995 rows left with a generic-bucket project
after recategorize_quarantine_project.py and recategorize_generic_project_tags.py,
1,437 are type episode/solution and contain a "/Code/<project>/" path.

Rule: take the first `/Code/<segment>/` match in content. Only apply it if
the segment is not itself a generic-bucket value (guards against paths like
"/Code/.claude/...") and is at least 2 characters. Anything that doesn't
match, or extracts a generic value, is left untouched and tagged as checked.

Nothing is deleted, no superseded_by changes. Reversible: the backup JSON
records id + original project for every row; restore via
UPDATE memories SET project = ? WHERE id = ?.

Usage:
  python3 brain/tools/recategorize_embedded_path_project.py --dry-run
  python3 brain/tools/recategorize_embedded_path_project.py --apply
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_DB_DEFAULT = _REPO / "brain" / "rust" / "brain.db"
_BACKUP_DIR = _REPO / "brain" / "bootstrap" / "junk_scrub_backups"

RECOVERED_TAG = "recategorized:embedded_path_project_recovered"
CHECKED_TAG = "recategorized:embedded_path_project_checked"

BAD_PROJECTS = (
    "cursor", "src", "landingpage", "frontend", ".claude", "etl", "rust", "test", "",
)

_PATH_RE = re.compile(r"/Code/([^/\s]+)/")


def _connect(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db), timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")
    return conn


def select_candidates(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    placeholders = ",".join("?" for _ in BAD_PROJECTS)
    return list(conn.execute(
        f"""
        SELECT id, content, project, tags
        FROM memories
        WHERE project IN ({placeholders})
          AND project != ''
          AND type IN ('"episode"', '"solution"')
          AND content LIKE '%/Code/%'
        ORDER BY timestamp
        """,
        BAD_PROJECTS,
    ))


def extract_project(content: str) -> str | None:
    m = _PATH_RE.search(content or "")
    if not m:
        return None
    candidate = m.group(1)
    if len(candidate) < 2 or candidate in BAD_PROJECTS:
        return None
    return candidate


def append_tag(tags: str | None, tag: str) -> str:
    parts = [t.strip() for t in (tags or "").split(",") if t.strip()]
    if tag not in parts:
        parts.append(tag)
    return ",".join(parts)


def apply_changes(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> tuple[int, int]:
    recovered = 0
    checked = 0
    for r in rows:
        real_project = extract_project(r["content"])
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

    by_project: dict[str, int] = {}
    unmatched = 0
    for r in rows:
        real_project = extract_project(r["content"])
        if real_project:
            by_project[real_project] = by_project.get(real_project, 0) + 1
        else:
            unmatched += 1

    print(f"candidates={len(rows)}")
    print(f"  recoverable: {sum(by_project.values())}")
    for proj, n in sorted(by_project.items(), key=lambda kv: -kv[1]):
        print(f"    {proj}: {n}")
    print(f"  unmatched (left as-is, tagged checked): {unmatched}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = _BACKUP_DIR / f"recategorize_embedded_path_project_{ts}.json"
    payload = {
        "count": len(rows),
        "rows": [
            {
                "id": r["id"],
                "original_project": r["project"],
                "recovered_project": extract_project(r["content"]),
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

    recovered_n, checked_n = apply_changes(conn, rows)
    conn.close()
    print(f"recovered={recovered_n} checked_only={checked_n}")
    print("NEXT: restart brain_api (launchctl kickstart -k gui/$(id -u)/com.brain.api)")
    print("      so the in-memory index picks up the corrected project tags.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
