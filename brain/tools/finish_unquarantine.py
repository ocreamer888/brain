#!/usr/bin/env python3
"""Finish the 2026-10-22 un-quarantine of path-fragment facts.

quarantine_path_fragment_facts.py (2026-08-07) did three things per row:
superseded_by=sentinel, +tag quarantine:path_fragment_project, salience=0.1.
recategorize_quarantine_project.py (2026-10-22) reversed only the first, so
8,200 real facts stayed visible but carried a 0.1 salience — a 0.85x rank
penalty in live search — plus a stale quarantine tag.

This restores each row's pre-quarantine salience from a DB snapshot taken
before 2026-08-07 and strips the tag. Rows missing from the snapshot are
left untouched. Backup JSON records current values for exact reversal.

Usage:
  python3 brain/tools/finish_unquarantine.py --snapshot PATH --dry-run
  python3 brain/tools/finish_unquarantine.py --snapshot PATH --apply
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
_TAG = "quarantine:path_fragment_project"


def strip_tag(tags: str) -> str:
    return ",".join(t for t in (tags or "").split(",") if t.strip() and t.strip() != _TAG)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, default=_DB_DEFAULT)
    p.add_argument("--snapshot", type=Path, required=True, help="pre-2026-08-07 brain.db snapshot (opened read-only)")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = p.parse_args()

    conn = sqlite3.connect(str(args.db), timeout=60)
    conn.execute("PRAGMA busy_timeout=60000")
    rows = conn.execute(
        "SELECT id, salience, tags FROM memories WHERE tags LIKE ? AND superseded_by IS NULL",
        (f"%{_TAG}%",),
    ).fetchall()

    snap = sqlite3.connect(f"file:{args.snapshot}?mode=ro", uri=True)
    original: dict[str, float] = {}
    ids = [r[0] for r in rows]
    for i in range(0, len(ids), 900):
        chunk = ids[i:i + 900]
        original.update(snap.execute(
            f"SELECT id, salience FROM memories WHERE id IN ({','.join('?' * len(chunk))})", chunk
        ))
    snap.close()

    plan = [(rid, sal, tags, original.get(rid)) for rid, sal, tags in rows]
    restorable = [x for x in plan if x[3] is not None]
    print(f"tagged live rows={len(rows)} restorable_from_snapshot={len(restorable)} "
          f"tag_only={len(plan) - len(restorable)}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = _BACKUP_DIR / f"finish_unquarantine_{ts}.json"
    backup.write_text(json.dumps(
        {"snapshot": str(args.snapshot),
         "rows": [{"id": rid, "salience": sal, "tags": tags} for rid, sal, tags, _ in plan]},
        indent=2,
    ))
    print(f"backup={backup}")

    if args.dry_run:
        print("dry-run: no writes")
        return 0

    for rid, sal, tags, orig in plan:
        conn.execute(
            "UPDATE memories SET salience = ?, tags = ? WHERE id = ?",
            (orig if orig is not None else sal, strip_tag(tags), rid),
        )
    conn.commit()
    conn.close()
    print(f"updated={len(plan)}")
    print("NEXT: restart brain_api (launchctl kickstart -k gui/$(id -u)/com.brain.api)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
