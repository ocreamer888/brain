#!/usr/bin/env python3
"""BVH-style near-duplicate detector for brain memories (Tier 1 Item 3).

Pattern: PPF Bounding Volume Hierarchy collision detection.
  - Broad phase: chunked matmul sweeps the embedding space in O(n log n)-style blocks.
  - Narrow phase: cosine > threshold flags actual near-duplicate pairs.
  - Union-find: groups pairs into clusters.
  - Resolution: keep highest-salience memory per cluster, flag rest for deletion.

Differs from dedup_db.py (which does exact content match via SQL GROUP BY).
This catches near-duplicates with rephrased titles/content that embed to the same region.

Defaults:
  --threshold 0.97  (near-duplicate; cosine > 0.99 = probable exact copy)
  --chunk 1000      (block size for broad phase matmul)
  --dry-run         (report only; use --delete to actually remove)

Usage:
    python3 brain/tools/bvh_dedup.py --dry-run
    python3 brain/tools/bvh_dedup.py --threshold 0.99 --dry-run
    python3 brain/tools/bvh_dedup.py --delete --threshold 0.97
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from brain.tools.retrieval_eval_kfold import load_corpus

DB_PATH = _REPO_ROOT / "brain" / "rust" / "brain.db"
REPORT_DIR = _REPO_ROOT / "brain" / "eval"


# --- Union-Find -----------------------------------------------------------

class UnionFind:
    def __init__(self, n: int) -> None:
        self._parent = list(range(n))
        self._rank = [0] * n

    def find(self, x: int) -> int:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        a, b = self.find(a), self.find(b)
        if a == b:
            return
        if self._rank[a] < self._rank[b]:
            a, b = b, a
        self._parent[b] = a
        if self._rank[a] == self._rank[b]:
            self._rank[a] += 1

    def clusters(self) -> dict[int, list[int]]:
        groups: dict[int, list[int]] = {}
        for i in range(len(self._parent)):
            root = self.find(i)
            groups.setdefault(root, []).append(i)
        return {k: v for k, v in groups.items() if len(v) > 1}


# --- BVH broad phase + narrow phase --------------------------------------

def find_near_duplicate_pairs(
    matrix: np.ndarray,
    threshold: float,
    chunk: int,
) -> list[tuple[int, int, float]]:
    """Return list of (i, j, sim) pairs where sim > threshold and i < j.

    Broad phase: upper-triangle chunked matmul.
    Narrow phase: threshold filter.
    """
    n = matrix.shape[0]
    pairs: list[tuple[int, int, float]] = []

    t0 = time.time()
    for start in range(0, n, chunk):
        end = min(start + chunk, n)
        block = matrix[start:end]  # (C, 768)

        # Only compare against memories with higher index (upper triangle)
        tail = matrix[start:]  # (N-start, 768)
        sims = block @ tail.T  # (C, N-start)

        # Zero out self-pairs and lower triangle for this block
        c_size = end - start
        for c in range(c_size):
            sims[c, : c + 1] = 0.0  # exclude pairs (start+c, start+j) where j <= c

        rows, cols = np.where(sims > threshold)
        for r, col in zip(rows.tolist(), cols.tolist()):
            global_i = start + r
            global_j = start + col  # col is offset from start
            if global_i != global_j:
                pairs.append((global_i, global_j, float(sims[r, col])))

        if (start // chunk + 1) % 5 == 0 or end == n:
            elapsed = time.time() - t0
            pct = end / n * 100
            print(f"  broad phase: {end}/{n} ({pct:.0f}%) — {len(pairs)} pairs so far — {elapsed:.1f}s",
                  file=sys.stderr)

    return pairs


def load_salience(db_path: Path, ids: list[str]) -> dict[str, float]:
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        f"SELECT id, salience FROM memories WHERE id IN ({','.join('?'*len(ids))})",
        ids,
    ).fetchall()
    conn.close()
    return {mid: (sal or 0.5) for mid, sal in rows}


def load_content_prefixes(db_path: Path, ids: list[str], prefix_len: int = 300) -> dict[str, str]:
    """Narrow phase: load content prefixes for exact-copy confirmation."""
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        f"SELECT id, content FROM memories WHERE id IN ({','.join('?'*len(ids))})",
        ids,
    ).fetchall()
    conn.close()
    return {mid: (content or "")[:prefix_len] for mid, content in rows}


def run(
    db_path: Path,
    threshold: float,
    chunk: int,
    delete: bool,
    narrow_prefix: int = 300,
) -> dict:
    print(f"Loading corpus...", file=sys.stderr)
    metas, matrix = load_corpus(db_path)
    n = len(metas)
    print(f"  {n} memories, {matrix.shape[1]} dims", file=sys.stderr)

    print(f"\nBroad phase sweep (threshold={threshold}, chunk={chunk})...", file=sys.stderr)
    t0 = time.time()
    pairs = find_near_duplicate_pairs(matrix, threshold, chunk)
    elapsed = time.time() - t0
    print(f"  Found {len(pairs)} pairs in {elapsed:.1f}s", file=sys.stderr)

    if not pairs:
        return {"threshold": threshold, "n_pairs": 0, "n_clusters": 0, "clusters": []}

    # Narrow phase: content-prefix check — discard pairs where content differs.
    # Catches false positives like structurally-similar but distinct sessions.
    print(f"Narrow phase: loading content prefixes ({narrow_prefix} chars)...", file=sys.stderr)
    all_pair_ids = list({metas[idx]["id"] for pair in pairs for idx in (pair[0], pair[1])})
    prefixes = load_content_prefixes(db_path, all_pair_ids, narrow_prefix)
    pairs = [
        (i, j, sim)
        for i, j, sim in pairs
        if prefixes.get(metas[i]["id"], "") == prefixes.get(metas[j]["id"], "")
    ]
    print(f"  After narrow phase: {len(pairs)} confirmed exact-copy pairs", file=sys.stderr)

    if not pairs:
        return {"threshold": threshold, "n_pairs": 0, "n_clusters": 0, "clusters": [],
                "note": "all broad-phase pairs rejected by narrow-phase content check"}

    # Union-find clustering
    uf = UnionFind(n)
    for i, j, _ in pairs:
        uf.union(i, j)
    raw_clusters = uf.clusters()

    # Load salience for all cluster members
    all_cluster_ids = [metas[idx]["id"] for cluster in raw_clusters.values() for idx in cluster]
    salience_map = load_salience(db_path, all_cluster_ids)

    # Build cluster report: keep highest-salience, flag rest
    clusters_out: list[dict] = []
    ids_to_delete: list[str] = []

    for root, indices in sorted(raw_clusters.items(), key=lambda kv: -len(kv[1])):
        members = [
            {
                "idx": idx,
                "id": metas[idx]["id"],
                "type": metas[idx]["type"],
                "project": metas[idx]["project"],
                "title": metas[idx]["title"][:80],
                "salience": salience_map.get(metas[idx]["id"], 0.5),
            }
            for idx in indices
        ]
        # Keep highest salience; ties → keep first (lowest idx = earliest ingest)
        members.sort(key=lambda m: (-m["salience"], m["idx"]))
        keep = members[0]
        dupes = members[1:]

        clusters_out.append({
            "size": len(members),
            "keep": keep,
            "delete": dupes,
        })
        ids_to_delete.extend(m["id"] for m in dupes)

    n_clusters = len(clusters_out)
    n_to_delete = len(ids_to_delete)
    print(f"\nClusters: {n_clusters}  |  Memories to remove: {n_to_delete}", file=sys.stderr)

    if delete and ids_to_delete:
        from brain.api_client import delete_memories
        BATCH = 200
        total_deleted = 0
        for i in range(0, len(ids_to_delete), BATCH):
            batch = ids_to_delete[i : i + BATCH]
            total_deleted += delete_memories(batch)
            print(f"  deleted batch {i//BATCH+1}: {len(batch)}", file=sys.stderr)
        print(f"  Total deleted: {total_deleted}", file=sys.stderr)

    return {
        "threshold": threshold,
        "n_total": n,
        "n_pairs": len(pairs),
        "n_clusters": n_clusters,
        "n_to_delete": n_to_delete,
        "deleted": delete,
        "clusters": clusters_out[:50],  # top 50 by size in report
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--threshold", type=float, default=0.97,
                        help="Cosine similarity threshold (default: 0.97)")
    parser.add_argument("--chunk", type=int, default=1000,
                        help="Block size for broad phase matmul (default: 1000)")
    parser.add_argument("--delete", action="store_true",
                        help="Actually delete flagged duplicates via brain API")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report only, no deletion (default behavior)")
    parser.add_argument(
        "--report", type=Path,
        default=REPORT_DIR / f"bvh_dedup_{__import__('datetime').date.today().strftime('%Y_%m_%d')}.json",
    )
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"DB not found: {args.db}", file=sys.stderr)
        return 2

    report = run(
        db_path=args.db,
        threshold=args.threshold,
        chunk=args.chunk,
        delete=args.delete and not args.dry_run,
    )

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"\n=== BVH Dedup Report (threshold={args.threshold}) ===")
    print(f"Total memories: {report['n_total']}")
    print(f"Near-duplicate pairs: {report['n_pairs']}")
    print(f"Clusters: {report['n_clusters']}")
    print(f"Removable duplicates: {report['n_to_delete']}")
    print(f"Deleted: {report['deleted']}")

    if report["clusters"]:
        print(f"\n=== Top 10 clusters ===")
        for cl in report["clusters"][:10]:
            keep = cl["keep"]
            print(f"  [{cl['size']}x] keep: ({keep['type']}/{keep['project']}) {keep['title']}")
            for d in cl["delete"][:2]:
                print(f"         dup:  ({d['type']}/{d['project']}) {d['title']}")

    print(f"\nWrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
