#!/usr/bin/env python3
"""Redact real OpenRouter secret keys found in memory content.

V-04 (closed 2026-08-12) stopped the entity extractor from minting
`sk-or-v1-*` entities, but never redacted the plaintext keys already
sitting in `memories.content`. Verified 2026-10-27: 6 live rows contain
5 distinct real-shaped (64 hex chars after `sk-or-v1-`) OpenRouter keys.
Rows that only *mention* the pattern (e.g. "format is sk-or-v1-...",
the V-04 fake-canary token) are left untouched.

This is a content EDIT, not a delete. The backup JSON stores the full
original row (embedding base64-encoded) before mutation, same convention
as delete_junk_stubs.py, so it can be fully reconstructed if needed.

Usage:
  python3 brain/tools/redact_leaked_openrouter_keys.py --dry-run
  python3 brain/tools/redact_leaked_openrouter_keys.py --apply
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

_REAL_KEY_RE = re.compile(r"sk-or-v1-[0-9a-f]{40,}")
_REDACTED = "sk-or-v1-[REDACTED]"

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


def row_to_dict(r: sqlite3.Row) -> dict:
    d = {k: r[k] for k in _COLUMNS if k != "embedding"}
    emb = r["embedding"]
    d["embedding_b64"] = base64.b64encode(emb).decode("ascii") if emb else None
    return d


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
    cols = ",".join(_COLUMNS)
    rows = list(conn.execute(
        f"SELECT {cols} FROM memories WHERE content LIKE '%sk-or-v1-%'"
    ))

    to_fix = []
    for r in rows:
        matches = set(_REAL_KEY_RE.findall(r["content"] or ""))
        if matches:
            to_fix.append((r, matches))

    print(f"rows scanned={len(rows)} rows_with_real_key={len(to_fix)}")
    unique_keys = set()
    for r, matches in to_fix:
        unique_keys |= matches
        print(f"  id={r['id']} project={r['project']} type={r['type']} keys={len(matches)}")
    print(f"unique real keys found={len(unique_keys)}")

    if not to_fix:
        print("nothing to redact")
        conn.close()
        return 0

    if args.dry_run:
        # Security audit 2026-11-05: this used to write the full unredacted
        # backup (real plaintext secret keys) to disk even on a dry run,
        # which is supposed to be read-only. A preview should never persist
        # anything -- the backup is only needed, and only written, right
        # before the actual mutation below.
        print("dry-run: no writes")
        conn.close()
        return 0

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = _BACKUP_DIR / f"redact_openrouter_keys_{ts}.json"
    payload = {
        "unique_key_count": len(unique_keys),
        "redacted_rows": [row_to_dict(r) for r, _ in to_fix],
    }
    backup.write_text(json.dumps(payload, indent=2))
    print(f"backup={backup}")

    for r, _ in to_fix:
        new_content = _REAL_KEY_RE.sub(_REDACTED, r["content"])
        conn.execute("UPDATE memories SET content = ? WHERE id = ?", (new_content, r["id"]))
        # memories_fts is a standalone (non external-content) FTS5 table, so it
        # holds its own copy of content and needs the same update directly.
        conn.execute("UPDATE memories_fts SET content = ? WHERE id = ?", (new_content, r["id"]))
    conn.commit()
    conn.close()
    print(f"redacted={len(to_fix)} rows, {len(unique_keys)} unique keys")
    print("NEXT: restart brain_api (launchctl kickstart -k gui/$(id -u)/com.brain.api)")
    print("      so the in-memory index drops the old plaintext content.")
    print("ALSO: rotate/revoke these keys on openrouter.ai if still active —")
    print("      this script only cleans the historical record, not the credential.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
