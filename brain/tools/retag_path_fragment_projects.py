#!/usr/bin/env python3
"""Retag path-fragment projects onto canonical names (high-confidence only).

Two populations:
  1. Quarantined fact_type rows (superseded_by=quarantine:path_fragment_project)
     → unique infer → set project, clear quarantine, salience=0.5, keep audit tags
  2. Active non-quarantined rows still on path-fragment projects
     → unique infer → set project only

Ambiguous / no-signal rows are left untouched (stay quarantined or stay bad-tagged).

Usage:
  python3 brain/tools/retag_path_fragment_projects.py --dry-run
  python3 brain/tools/retag_path_fragment_projects.py --apply
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO))

from brain.ingest.project_infer import (  # noqa: E402
    infer_unique_project,
    is_path_fragment_project,
)

_DB_DEFAULT = _REPO / "brain" / "rust" / "brain.db"
_BACKUP_DIR = _REPO / "brain" / "bootstrap" / "junk_scrub_backups"

QUARANTINE_SENTINEL = "quarantine:path_fragment_project"
QUARANTINE_TAG = "quarantine:path_fragment_project"
RESTORED_SALIENCE = 0.5


def _connect(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db), timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")
    return conn


def _append_tag(tags: str | None, *new_tags: str) -> str:
    parts = [t.strip() for t in (tags or "").split(",") if t.strip()]
    for t in new_tags:
        if t and t not in parts:
            parts.append(t)
    return ",".join(parts)


def _strip_tag(tags: str | None, drop: str) -> str:
    parts = [t.strip() for t in (tags or "").split(",") if t.strip() and t.strip() != drop]
    return ",".join(parts)


def select_quarantined(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute(
        """
        SELECT id, project, type, tags, salience, content, superseded_by
        FROM memories
        WHERE superseded_by = ?
        """,
        (QUARANTINE_SENTINEL,),
    ))


def select_active_bad(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute(
        """
        SELECT id, project, type, tags, salience, content, superseded_by
        FROM memories
        WHERE (superseded_by IS NULL OR superseded_by = '')
        """
    ))


def plan_retags(rows: list[sqlite3.Row], *, unquarantine: bool) -> list[dict]:
    planned: list[dict] = []
    for r in rows:
        if not is_path_fragment_project(r["project"]):
            continue
        new_proj = infer_unique_project(r["content"] or "")
        if not new_proj or new_proj == r["project"]:
            continue
        planned.append({
            "id": r["id"],
            "old_project": r["project"],
            "new_project": new_proj,
            "type": r["type"],
            "unquarantine": unquarantine,
            "preview": (r["content"] or "")[:160],
        })
    return planned


def apply_retags(conn: sqlite3.Connection, planned: list[dict]) -> int:
    updated = 0
    for item in planned:
        row = conn.execute(
            "SELECT tags, superseded_by FROM memories WHERE id = ?",
            (item["id"],),
        ).fetchone()
        if row is None:
            continue
        tags = _append_tag(
            row["tags"],
            f"retagged:from_{item['old_project']}",
            f"retagged:to_{item['new_project']}",
        )
        if item["unquarantine"]:
            tags = _strip_tag(tags, QUARANTINE_TAG)
            conn.execute(
                """
                UPDATE memories
                SET project = ?,
                    tags = ?,
                    superseded_by = NULL,
                    salience = ?
                WHERE id = ?
                """,
                (item["new_project"], tags, RESTORED_SALIENCE, item["id"]),
            )
        else:
            conn.execute(
                """
                UPDATE memories
                SET project = ?,
                    tags = ?
                WHERE id = ?
                """,
                (item["new_project"], tags, item["id"]),
            )
        updated += 1
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
    q_plan = plan_retags(select_quarantined(conn), unquarantine=True)
    a_plan = plan_retags(select_active_bad(conn), unquarantine=False)
    # Avoid double-processing if somehow overlapping
    q_ids = {x["id"] for x in q_plan}
    a_plan = [x for x in a_plan if x["id"] not in q_ids]
    planned = q_plan + a_plan

    print(f"quarantined_unique_retags={len(q_plan)}")
    print(f"active_unique_retags={len(a_plan)}")
    print(f"total={len(planned)}")

    by_pair = Counter((x["old_project"], x["new_project"]) for x in planned)
    print("top remaps:")
    for (old, new), n in by_pair.most_common(25):
        print(f"  {n:4d}  {old} → {new}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = _BACKUP_DIR / f"retag_path_fragment_{ts}.json"
    backup.write_text(json.dumps({
        "count": len(planned),
        "quarantined_lifted": len(q_plan),
        "active_retagged": len(a_plan),
        "items": planned,
    }, indent=2))
    print(f"backup={backup}")

    if args.dry_run:
        print("dry-run: no writes")
        conn.close()
        return 0

    n = apply_retags(conn, planned)
    conn.close()
    print(f"updated={n}")
    print("NEXT: restart brain_api so lifted facts re-enter the vector index")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
