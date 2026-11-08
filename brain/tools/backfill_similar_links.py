#!/usr/bin/env python3
"""Backfill memory_links (relation_type='similar_to') -- G7, spec §7.

spec §7.2's proposed build mechanism: query the existing index with a
memory's own embedding for its top-k nearest *other* memories, weight =
1 - cosine_distance. This script does the one-time backfill for the
existing corpus; the equivalent at save time (one extra index lookup per
save, per spec) is NOT implemented here -- that's a brain_api.rs save-path
change, deliberately out of scope for an offline backfill tool.

No LLM judgement step here (unlike backfill_layer_links.py's G8 backfill):
G7 is pure embedding math, spec §7.2 names no precision problem for it to
solve the way G8's judgement step solves the ~33% tier-precision problem.
Candidates are not filtered through brain/ingest/layer_judgment.py and
this script does not call Ollama at all.

Computed as exact brute-force cosine (not through Rust's quantized
VectorIndex, which isn't reachable from Python) directly against the
`embedding` BLOBs already in brain.db -- same approach
backfill_layer_links.py already uses for its own pairwise checks, just
batched: the full embedding matrix is loaded once, multiplied in
row-chunks against itself (not one N^2 matrix at once) to keep memory
bounded regardless of corpus size.

No project restriction (unlike backfill_layer_links.py's G8 candidates,
spec §8.5a) -- spec §7 names none for similar_to, and cross-project
"related memories" browsing is a legitimate use (e.g. a reusable pattern
shared between two projects). --project scopes the computation if wanted.

Safety: read-only unless --apply is passed. --apply creates memory_links
(already exists live as of the G8 backfill; CREATE TABLE IF NOT EXISTS is
a no-op there) and inserts rows with ON CONFLICT DO NOTHING -- purely
additive. Commits per row, not once at the end (the first G8 backfill
held one transaction open for a ~5hr run against a live database and had
to be killed and rewritten before any data was lost -- same lesson
applied here from the start, not learned the hard way twice).

Usage:
    ./.venv/bin/python3 brain/tools/backfill_similar_links.py --count-only
    ./.venv/bin/python3 brain/tools/backfill_similar_links.py                 # dry run
    ./.venv/bin/python3 brain/tools/backfill_similar_links.py --apply
    ./.venv/bin/python3 brain/tools/backfill_similar_links.py --project brain
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import uuid
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

K = 10  # neighbors per memory, matches the existing find_similar(k) default use
MIN_WEIGHT = 0.5  # same empirically-grounded floor as G8's MIN_CANDIDATE_SIM --
                  # below this, "nearest" is not meaningfully "similar"
DB_PATH = REPO_ROOT / "brain" / "rust" / "brain.db"
RELATION_TYPE = "similar_to"
CHUNK = 1000  # rows per matmul chunk, bounds memory to CHUNK * n_total * 4 bytes


def load_active_embeddings(conn: sqlite3.Connection, project: str | None):
    sql = "SELECT id, embedding FROM memories WHERE superseded_by IS NULL AND embedding IS NOT NULL"
    args: list = []
    if project:
        sql += " AND project = ?"
        args.append(project)
    ids: list[str] = []
    vecs: list[np.ndarray] = []
    for mid, emb in conn.execute(sql, args):
        v = np.frombuffer(emb, dtype="<f4")
        n = np.linalg.norm(v)
        if n > 0:
            ids.append(mid)
            vecs.append(v / n)
    if not vecs:
        return [], np.zeros((0, 0), dtype=np.float32)
    return ids, np.stack(vecs).astype(np.float32)


def top_k_neighbors(ids: list[str], matrix: np.ndarray, k: int, min_weight: float):
    """Yields (src_id, dst_id, weight) for each row's top-k neighbors above
    min_weight, excluding self. Chunked so memory stays bounded regardless
    of corpus size."""
    n = len(ids)
    for start in range(0, n, CHUNK):
        end = min(start + CHUNK, n)
        sims = matrix[start:end] @ matrix.T  # (chunk, n)
        for local_i, global_i in enumerate(range(start, end)):
            row = sims[local_i]
            row[global_i] = -1.0  # exclude self
            top_idx = np.argpartition(row, -k)[-k:]
            top_idx = top_idx[np.argsort(-row[top_idx])]
            for j in top_idx:
                w = float(row[j])
                if w < min_weight:
                    continue
                yield ids[global_i], ids[j], w


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=None)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--count-only", action="store_true")
    ap.add_argument("--k", type=int, default=K)
    args = ap.parse_args()

    mode = "ro" if not args.apply else "rwc"
    conn = sqlite3.connect(f"file:{DB_PATH}?mode={mode}", uri=True)

    t0 = time.time()
    ids, matrix = load_active_embeddings(conn, args.project)
    print(f"active embeddings loaded: {len(ids)} ({time.time()-t0:.1f}s)", flush=True)
    if not ids:
        return

    if args.count_only:
        # Just report corpus size + a timing estimate from one chunk, don't
        # compute the full pass.
        t1 = time.time()
        _ = matrix[: min(CHUNK, len(ids))] @ matrix.T
        per_chunk = time.time() - t1
        n_chunks = (len(ids) + CHUNK - 1) // CHUNK
        print(f"estimated full pass: ~{per_chunk * n_chunks:.0f}s ({n_chunks} chunks of {CHUNK})")
        return

    written = 0
    pairs_above_floor = 0
    t1 = time.time()
    audit_path = REPO_ROOT / "brain" / "eval" / "runs" / f"similar-backfill-{int(time.time())}.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("w") as audit_f:
        for src_id, dst_id, weight in top_k_neighbors(ids, matrix, args.k, MIN_WEIGHT):
            pairs_above_floor += 1
            audit_f.write(json.dumps({"src": src_id, "dst": dst_id, "weight": weight}) + "\n")
            if args.apply:
                conn.execute(
                    "INSERT INTO memory_links (id, src_memory_id, dst_memory_id, relation_type, weight, created_at) "
                    "VALUES (?, ?, ?, ?, ?, datetime('now')) "
                    "ON CONFLICT(src_memory_id, dst_memory_id, relation_type) DO NOTHING",
                    (str(uuid.uuid4()), src_id, dst_id, RELATION_TYPE, weight),
                )
                conn.commit()  # per-row, not once at the end -- see module docstring
                written += 1

    elapsed = time.time() - t1
    print(f"computed {pairs_above_floor} neighbor pairs (weight>={MIN_WEIGHT}) in {elapsed:.1f}s", flush=True)
    if args.apply:
        print(f"memory_links rows written (ON CONFLICT DO NOTHING applied): {written}")
    else:
        print(f"DRY RUN -- {pairs_above_floor} rows would be written. Pass --apply to write.")
    print(f"audit log: {audit_path}")


if __name__ == "__main__":
    main()
