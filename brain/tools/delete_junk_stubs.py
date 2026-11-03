#!/usr/bin/env python3
"""Hard-delete confirmed-junk rows: content-free Claude Code session stubs
("Claude Code session: ... Ended: ...") and `verification_probe` test rows
left over from the verification harness.

Verification (2026-10-21, docs/architecture/experiments/2026-10-21-layer-detection/):
54 session stubs and 3 verification_probe rows found live, sampled and
confirmed to carry no real content (e.g. "[user] hi", "[user] hello",
"VERIFICATION PROBE: ..."). Unlike the quarantine rows (see
recategorize_quarantine_project.py), these are genuinely empty of value.

Any stub whose content reports a message count >= --review-threshold
(default 20) is held out as NEEDS REVIEW instead of being deleted
automatically, since a long session might contain real content under a
generic-looking summary line. Print these for the owner to check by hand.

This is a real DELETE, unlike the other tools here. The backup JSON stores
every column (embedding base64-encoded) for every deleted row so it can be
fully reconstructed with an INSERT if needed.

Usage:
  python3 brain/tools/delete_junk_stubs.py --dry-run
  python3 brain/tools/delete_junk_stubs.py --apply
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_DB_DEFAULT = _REPO / "brain" / "rust" / "brain.db"
_BACKUP_DIR = _REPO / "brain" / "bootstrap" / "junk_scrub_backups"

_MESSAGE_COUNT_RE = re.compile(r"Total messages:\s*(\d+)")

_COLUMNS = (
    "id", "content", "type", "project", "tags", "timestamp", "source",
    "session_id", "importance", "file_path", "thread_id", "title",
    "embedding", "parent_id", "event_time", "salience", "superseded_by",
    "derived_from", "extracted_by",
)


def _connect(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db), timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")
    return conn


def select_candidates(conn: sqlite3.Connection) -> dict[str, list[sqlite3.Row]]:
    cols = ",".join(_COLUMNS)
    session_stubs = list(conn.execute(
        f"""
        SELECT {cols} FROM memories
        WHERE content LIKE '%Claude Code session:%Ended:%'
          AND (superseded_by IS NULL OR superseded_by = '')
        """
    ))
    probes = list(conn.execute(
        f"""
        SELECT {cols} FROM memories
        WHERE (tags LIKE '%verification_probe%' OR content LIKE '%VERIFICATION PROBE%')
          AND (superseded_by IS NULL OR superseded_by = '')
        """
    ))
    return {"session_stub": session_stubs, "verification_probe": probes}


def split_review(rows: list[sqlite3.Row], threshold: int) -> tuple[list[sqlite3.Row], list[sqlite3.Row]]:
    to_delete, needs_review = [], []
    for r in rows:
        m = _MESSAGE_COUNT_RE.search(r["content"] or "")
        if m and int(m.group(1)) >= threshold:
            needs_review.append(r)
        else:
            to_delete.append(r)
    return to_delete, needs_review


def row_to_dict(r: sqlite3.Row) -> dict:
    d = {k: r[k] for k in _COLUMNS if k != "embedding"}
    emb = r["embedding"]
    d["embedding_b64"] = base64.b64encode(emb).decode("ascii") if emb else None
    return d


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, default=_DB_DEFAULT)
    p.add_argument("--review-threshold", type=int, default=20,
                    help="session stubs reporting >= this many messages are held for manual review, not deleted")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = p.parse_args()

    if not args.db.exists():
        print(f"error: db not found: {args.db}", file=sys.stderr)
        return 1

    conn = _connect(args.db)
    by_reason = select_candidates(conn)

    to_delete: list[sqlite3.Row] = []
    needs_review: list[sqlite3.Row] = []
    for reason, rows in by_reason.items():
        d, r = split_review(rows, args.review_threshold)
        to_delete.extend(d)
        needs_review.extend(r)

    print(f"candidates={sum(len(v) for v in by_reason.values())}")
    for reason, rows in by_reason.items():
        print(f"  {reason}: {len(rows)}")
    print(f"to_delete={len(to_delete)} needs_review={len(needs_review)}")
    for r in needs_review:
        m = _MESSAGE_COUNT_RE.search(r["content"] or "")
        print(f"  NEEDS REVIEW id={r['id']} project={r['project']} messages={m.group(1) if m else '?'}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = _BACKUP_DIR / f"delete_junk_stubs_{ts}.json"
    payload = {
        "review_threshold": args.review_threshold,
        "deleted_count": len(to_delete),
        "needs_review_count": len(needs_review),
        "deleted_rows": [row_to_dict(r) for r in to_delete],
        "needs_review_rows": [row_to_dict(r) for r in needs_review],
    }
    backup.write_text(json.dumps(payload, indent=2))
    print(f"backup={backup}")

    if args.dry_run:
        print("dry-run: no writes")
        conn.close()
        return 0

    ids = [r["id"] for r in to_delete]
    conn.executemany("DELETE FROM memories WHERE id = ?", [(i,) for i in ids])
    conn.commit()
    conn.close()
    print(f"deleted={len(ids)}")
    print("NEXT: restart brain_api (launchctl kickstart -k gui/$(id -u)/com.brain.api)")
    print("      so the in-memory index drops the deleted rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
