#!/usr/bin/env python3
"""Backfill entities/edges for existing durable memories that have zero edges.

Selects edge-less active durable memories from brain/rust/brain.db (read-only),
extracts entities via a cheap Ollama prompt, and links them onto the memory via
the POST /link-entities endpoint (golden-path writes only — never direct SQLite).

Resumable via a checkpoint file; safe to re-run.

Usage:
    python3 brain/tools/backfill_entities.py [--limit N] [--project PROJ] [--dry-run] [--reset-checkpoint]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "brain"))

import api_client  # noqa: E402
from brain.ingest import entity_extractor  # noqa: E402

DB_PATH = _REPO_ROOT / "brain" / "rust" / "brain.db"
CHECKPOINT_PATH = _REPO_ROOT / "brain" / "bootstrap" / "checkpoint_entity_backfill_durable.json"

PROGRESS_EVERY = 25

# JSON-encoded types as stored in the DB (literal quotes). Deliberately NOT
# entity_extractor.DURABLE_MEMORY_TYPES, which holds bare strings for
# memory_type comparison — feeding those into SQL silently matches nothing.
_DURABLE_TYPES = (
    '"fact"', '"solution"', '"decision"', '"pattern"',
    '"project_context"', '"error_lesson"', '"conversation"',
    '"knowledge"',
)


# ---------------------------------------------------------------------------
# Selection (read-only SQLite)
# ---------------------------------------------------------------------------

def select_edgeless_durable(
    db_path: Path,
    limit: int | None = None,
    project: str | None = None,
) -> list[dict]:
    """Active durable memories (not superseded) with zero outgoing edges, newest first."""
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        placeholders = ",".join("?" for _ in _DURABLE_TYPES)
        query = (
            "SELECT id, content, project, timestamp FROM memories "
            f"WHERE type IN ({placeholders}) "
            "AND (superseded_by IS NULL OR superseded_by = '') "
            "AND id NOT IN (SELECT DISTINCT src_memory_id FROM edges)"
        )
        params: list = list(_DURABLE_TYPES)
        if project:
            query += " AND project = ?"
            params.append(project)
        query += " ORDER BY timestamp DESC"
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Checkpoint I/O
# ---------------------------------------------------------------------------

def load_checkpoint(path: Path = CHECKPOINT_PATH) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {"processed_ids": [], "linked_total": 0, "facts_seen": 0}


def save_checkpoint(state: dict, path: Path = CHECKPOINT_PATH) -> None:
    path.write_text(json.dumps(state))


# ---------------------------------------------------------------------------
# Main run
# ---------------------------------------------------------------------------

def run(
    limit: int | None = None,
    project: str | None = None,
    dry_run: bool = False,
    reset_checkpoint: bool = False,
    db_path: Path = DB_PATH,
    checkpoint_path: Path = CHECKPOINT_PATH,
) -> dict:
    if reset_checkpoint and checkpoint_path.exists():
        checkpoint_path.unlink()

    checkpoint = load_checkpoint(checkpoint_path)
    processed_ids: set[str] = set(checkpoint["processed_ids"])
    linked_total = checkpoint["linked_total"]
    facts_seen = checkpoint["facts_seen"]

    memories = select_edgeless_durable(db_path, limit=limit, project=project)
    total = len(memories)
    start = time.time()

    print(
        f"[backfill/entities] {total} edge-less durable memories selected (dry_run={dry_run})",
        file=sys.stderr,
    )

    for i, memory in enumerate(memories, start=1):
        memory_id = memory["id"]
        if memory_id in processed_ids:
            continue

        # Batch context: no hook timeout to race, so keep the original long read
        # budget rather than the short interactive default.
        entities = entity_extractor.extract_entities(
            memory["content"] or "", timeout=entity_extractor.BACKFILL_TIMEOUT
        )

        if dry_run:
            print(f"  [dry-run] {memory_id[:12]} entities={entities}")
        else:
            if entities:
                try:
                    linked = api_client.link_entities(memory_id, entities)
                except (api_client.BrainApiError, Exception) as e:
                    print(
                        f"[backfill/entities] warning: link_entities failed for {memory_id}: {e}",
                        file=sys.stderr,
                    )
                    continue
                linked_total += linked
            facts_seen += 1
            processed_ids.add(memory_id)

            if facts_seen % PROGRESS_EVERY == 0:
                save_checkpoint(
                    {
                        "processed_ids": sorted(processed_ids),
                        "linked_total": linked_total,
                        "facts_seen": facts_seen,
                    },
                    checkpoint_path,
                )
                elapsed = time.time() - start
                print(
                    f"[backfill/entities] {i}/{total}, linked_total={linked_total}, elapsed={elapsed:.1f}s",
                    file=sys.stderr,
                )

    if not dry_run:
        save_checkpoint(
            {
                "processed_ids": sorted(processed_ids),
                "linked_total": linked_total,
                "facts_seen": facts_seen,
            },
            checkpoint_path,
        )

    print(f"[backfill/entities] done — facts_seen={facts_seen} linked_total={linked_total}")
    return {"facts_seen": facts_seen, "linked_total": linked_total}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--limit", type=int, help="Cap number of memories to process")
    p.add_argument("--project", help="Filter by project name")
    p.add_argument("--dry-run", action="store_true", help="Print planned entities, do not POST or write checkpoint")
    p.add_argument("--reset-checkpoint", action="store_true", help="Discard existing checkpoint before running")
    args = p.parse_args()

    run(
        limit=args.limit,
        project=args.project,
        dry_run=args.dry_run,
        reset_checkpoint=args.reset_checkpoint,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
