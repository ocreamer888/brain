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
import os
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
            "SELECT id, content, type, project, timestamp FROM memories "
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


def select_by_ids(db_path: Path, ids: list[str]) -> list[dict]:
    """Fetch memories by explicit id (regardless of edge state), newest first.

    Used to resume a frozen --limit work set: some ids will already have edges
    from a partial run, so we must fetch by id rather than the edgeless predicate.
    """
    if not ids:
        return []
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        out: list[dict] = []
        ids = list(ids)
        for i in range(0, len(ids), 900):  # stay under SQLite variable limit
            chunk = ids[i : i + 900]
            placeholders = ",".join("?" for _ in chunk)
            rows = conn.execute(
                "SELECT id, content, type, project, timestamp FROM memories "
                f"WHERE id IN ({placeholders})",
                chunk,
            ).fetchall()
            out.extend(dict(r) for r in rows)
        out.sort(key=lambda m: m.get("timestamp") or "", reverse=True)
        return out
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
    # Atomic write: a SIGTERM during the crash-resume drill must never leave a
    # torn checkpoint that breaks load_checkpoint's json.loads on recover.
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state))
    os.replace(tmp, path)


def _checkpoint_state(
    processed_ids: set[str],
    linked_total: int,
    facts_seen: int,
    work_set: list[str] | None = None,
) -> dict:
    state = {
        "processed_ids": sorted(processed_ids),
        "linked_total": linked_total,
        "facts_seen": facts_seen,
    }
    if work_set is not None:
        state["work_set"] = work_set
    return state


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
    checkpoint_every: int = PROGRESS_EVERY,
) -> dict:
    if reset_checkpoint and checkpoint_path.exists():
        checkpoint_path.unlink()

    checkpoint = load_checkpoint(checkpoint_path)
    processed_ids: set[str] = set(checkpoint["processed_ids"])
    linked_total = checkpoint["linked_total"]
    facts_seen = checkpoint["facts_seen"]
    work_set: list[str] | None = checkpoint.get("work_set")
    flush_every = max(1, int(checkpoint_every))

    # Bounded (--limit) jobs freeze their selected id set into the checkpoint so a
    # crash+resume processes exactly those ids. Without this, resume re-queries the
    # edgeless set, which shifts as we add edges, over-running the nominal limit.
    # Unlimited full-corpus runs re-query edgeless each time (they converge to empty).
    if limit is not None and not dry_run:
        if work_set:
            memories = select_by_ids(db_path, work_set)
        else:
            memories = select_edgeless_durable(db_path, limit=limit, project=project)
            work_set = [m["id"] for m in memories]
            # Persist the frozen set immediately: a crash before the first flush
            # must still resume against the same window.
            save_checkpoint(
                _checkpoint_state(processed_ids, linked_total, facts_seen, work_set),
                checkpoint_path,
            )
    else:
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
        # DB stores JSON-encoded types ('"fact"'); extractor wants bare strings.
        raw_type = memory.get("type") or ""
        memory_type = raw_type.strip('"') or None
        entities = entity_extractor.extract_entities(
            memory["content"] or "",
            timeout=entity_extractor.BACKFILL_TIMEOUT,
            memory_type=memory_type,
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

            if facts_seen % flush_every == 0:
                save_checkpoint(
                    _checkpoint_state(
                        processed_ids, linked_total, facts_seen, work_set
                    ),
                    checkpoint_path,
                )
                elapsed = time.time() - start
                print(
                    f"[backfill/entities] {i}/{total}, linked_total={linked_total}, elapsed={elapsed:.1f}s",
                    file=sys.stderr,
                )

    if not dry_run:
        save_checkpoint(
            _checkpoint_state(processed_ids, linked_total, facts_seen, work_set),
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
    p.add_argument(
        "--checkpoint",
        type=Path,
        default=CHECKPOINT_PATH,
        help="Checkpoint JSON path (Forge jobs should use a dedicated file)",
    )
    p.add_argument(
        "--checkpoint-every",
        type=int,
        default=PROGRESS_EVERY,
        help="Flush checkpoint every N processed memories (use 1 for crash-resume drills)",
    )
    args = p.parse_args()

    run(
        limit=args.limit,
        project=args.project,
        dry_run=args.dry_run,
        reset_checkpoint=args.reset_checkpoint,
        checkpoint_path=(
            args.checkpoint
            if args.checkpoint.is_absolute()
            else _REPO_ROOT / args.checkpoint
        ),
        checkpoint_every=args.checkpoint_every,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
