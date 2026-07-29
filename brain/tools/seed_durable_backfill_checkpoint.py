#!/usr/bin/env python3
"""One-off: seed the durable entity-backfill checkpoint from a legacy fact-only one.

The legacy checkpoint recorded facts that were already run through entity
extraction. Re-extracting them costs GPU time for a known-zero yield, so their
ids are carried into the new durable checkpoint. The other six durable types
were never checkpointed and therefore still start from zero — which is what the
"do not treat fact-only progress as complete" decision requires.

Only ids that BOTH exist in the current DB AND are typed `fact` are carried
over. `linked_total` / `facts_seen` are deliberately NOT copied: they must keep
meaning "work done by runs of this checkpoint". Provenance lives in `seeded_*`.

Idempotent — re-running adds nothing.

Usage:
    python3 brain/tools/seed_durable_backfill_checkpoint.py --source PATH [--target PATH] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

DB_PATH = _REPO_ROOT / "brain" / "rust" / "brain.db"
TARGET_PATH = _REPO_ROOT / "brain" / "bootstrap" / "checkpoint_entity_backfill_durable.json"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _load_fact_ids(db_path: Path) -> set[str]:
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    try:
        return {r[0] for r in conn.execute("SELECT id FROM memories WHERE type = '\"fact\"'")}
    finally:
        conn.close()


def seed_processed_ids(
    source_path: Path,
    target_path: Path = TARGET_PATH,
    db_path: Path = DB_PATH,
    dry_run: bool = False,
) -> dict:
    """Merge legacy fact ids into the durable checkpoint. Idempotent."""
    if not source_path.exists():
        raise FileNotFoundError(f"legacy checkpoint not found: {source_path}")

    legacy_ids = set(json.loads(source_path.read_text()).get("processed_ids", []))
    fact_ids = _load_fact_ids(db_path)
    valid = legacy_ids & fact_ids  # defensive: must exist in the DB AND be a fact

    if target_path.exists():
        target = json.loads(target_path.read_text())
    else:
        target = {"processed_ids": [], "linked_total": 0, "facts_seen": 0}

    before = set(target.get("processed_ids", []))
    merged = before | valid
    target["processed_ids"] = sorted(merged)
    target["seeded_from"] = str(source_path)
    target["seeded_count"] = len(valid)
    target["seeded_at"] = _now_iso()

    if not dry_run:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(json.dumps(target))

    return {
        "legacy_ids": len(legacy_ids),
        "valid": len(valid),
        "dropped": len(legacy_ids) - len(valid),
        "added": len(merged) - len(before),
        "total_processed": len(merged),
        "dry_run": dry_run,
    }


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--source",
        required=True,
        type=Path,
        help="Path to the legacy fact-only checkpoint JSON (operator-supplied)",
    )
    p.add_argument("--target", type=Path, default=TARGET_PATH, help="Durable checkpoint to seed")
    p.add_argument("--db", type=Path, default=DB_PATH, help="Read-only brain.db to validate against")
    p.add_argument("--dry-run", action="store_true", help="Report what would change, write nothing")
    args = p.parse_args()

    stats = seed_processed_ids(
        source_path=args.source,
        target_path=args.target,
        db_path=args.db,
        dry_run=args.dry_run,
    )
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
