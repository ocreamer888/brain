#!/usr/bin/env python3
"""Measure whether deleting high-fragility memories actually helps retrieval.

Read-only. Does NOT touch the DB. Simulates the noise-detection deletion
(fragility >= threshold) by masking those memories out of the candidate pool,
then compares hand-curated gold-set retrieval BEFORE vs AFTER the prune.

Answers three honest questions:
  1. COVERAGE: how many memories are fragile, by type (what would get deleted).
  2. EFFECTIVENESS: does pruning improve P@1 / P@10 / MRR on real paraphrase queries?
  3. SAFETY: how many gold-relevant answers are themselves fragile (wrongly deleted)?

Usage:
    .venv/bin/python brain/tools/noise_effectiveness.py
    .venv/bin/python brain/tools/noise_effectiveness.py --threshold 0.95 --sample-frag 0
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from brain.tools.noise_detect import fragility_score
from brain.tools.retrieval_eval_kfold import load_corpus

DB_PATH = _REPO_ROOT / "brain" / "rust" / "brain.db"
GOLD_FILES = [
    _REPO_ROOT / "brain" / "eval" / "gold_semantic.jsonl",
    _REPO_ROOT / "brain" / "eval" / "gold_semantic_conversations.jsonl",
    _REPO_ROOT / "brain" / "eval" / "gold_semantic_project_context.jsonl",
]


def compute_fragility_all(matrix, sigma, k, trials, seed):
    rng = np.random.default_rng(seed)
    n = matrix.shape[0]
    frag = np.empty(n, dtype=np.float32)
    t0 = time.time()
    for i in range(n):
        frag[i] = fragility_score(i, matrix, sigma, k, trials, rng)
        if (i + 1) % 1000 == 0:
            rate = (i + 1) / (time.time() - t0)
            print(f"  fragility {i+1}/{n} ({rate:.0f}/s, ETA {(n-i-1)/rate:.0f}s)", file=sys.stderr)
    return frag


def load_gold():
    gold = []
    for gf in GOLD_FILES:
        if not gf.exists():
            continue
        for line in gf.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                gold.append(json.loads(line))
    return gold


def rank_of(sims_row, target_idx, kill_mask):
    """Rank of target among candidates, with kill_mask docs removed.

    Returns rank (1-based), or None if target itself is killed (deleted)."""
    if kill_mask is not None and kill_mask[target_idx]:
        return None  # gold answer was deleted -> miss
    target_sim = sims_row[target_idx]
    higher = sims_row > target_sim
    if kill_mask is not None:
        higher = higher & ~kill_mask
    return int(higher.sum()) + 1


def metrics(ranks, ks=(1, 5, 10)):
    present = [r for r in ranks if r is not None]
    n = len(ranks)
    out = {"n": n, "n_missed_deleted": sum(1 for r in ranks if r is None)}
    for k in ks:
        out[f"p@{k}"] = round(sum(1 for r in present if r <= k) / max(1, n), 4)
    out["mrr"] = round(sum(1.0 / r for r in present) / max(1, n), 4)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DB_PATH)
    ap.add_argument("--threshold", type=float, default=0.95)
    ap.add_argument("--sigma", type=float, default=0.05)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--trials", type=int, default=5)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args(argv)

    print(f"Loading corpus from {args.db}...", file=sys.stderr)
    metas, matrix = load_corpus(args.db)
    n = len(metas)
    print(f"  {n} memories", file=sys.stderr)

    print(f"Computing fragility for ALL {n} memories...", file=sys.stderr)
    frag = compute_fragility_all(matrix, args.sigma, args.k, args.trials, args.seed)

    # Distribution of fragility across the full corpus
    pct = {p: round(float(np.percentile(frag, p)), 4) for p in [50, 75, 90, 95, 99]}
    print(f"\nFRAGILITY DISTRIBUTION (full corpus): mean={frag.mean():.4f} max={frag.max():.4f}", file=sys.stderr)
    print(f"  p50={pct[50]} p75={pct[75]} p90={pct[90]} p95={pct[95]} p99={pct[99]}", file=sys.stderr)
    for thr in [0.6, 0.7, 0.8, 0.9, 0.95]:
        print(f"  >= {thr}: {int((frag>=thr).sum())} memories", file=sys.stderr)

    kill_mask = frag >= args.threshold
    n_fragile = int(kill_mask.sum())

    # --- Q1: COVERAGE (what gets deleted) ---
    by_type = defaultdict(lambda: [0, 0])  # type -> [total, fragile]
    for i, m in enumerate(metas):
        by_type[m["type"]][0] += 1
        if kill_mask[i]:
            by_type[m["type"]][1] += 1

    # --- Q2 + Q3: gold-set eval ---
    gold = load_gold()
    id_to_idx = {m["id"]: i for i, m in enumerate(metas)}

    from brain.core.embedder import embed_batch

    valid = [g for g in gold if g["gold_memory_id"] in id_to_idx]
    missing = len(gold) - len(valid)
    queries = [g["query"] for g in valid]
    print(f"Embedding {len(queries)} gold queries...", file=sys.stderr)
    q_vecs = np.asarray(embed_batch(queries), dtype=np.float32)
    qn = np.linalg.norm(q_vecs, axis=1, keepdims=True)
    qn[qn < 1e-10] = 1.0
    q_vecs /= qn
    sims = q_vecs @ matrix.T  # (Q, N)

    target_idxs = [id_to_idx[g["gold_memory_id"]] for g in valid]
    ranks_full = [rank_of(sims[qi], ti, None) for qi, ti in enumerate(target_idxs)]
    m_full = metrics(ranks_full)

    # --- print report ---
    print("\n" + "=" * 70)
    print("NOISE-DETECTION EFFECTIVENESS — threshold sweep")
    print("=" * 70)
    print(f"\nBASELINE gold-set retrieval (n={m_full['n']} queries, {missing} gold IDs missing from corpus)")
    print(f"  p@1={m_full['p@1']}  p@5={m_full['p@5']}  p@10={m_full['p@10']}  mrr={m_full['mrr']}")

    print(f"\n{'thresh':>7} {'deleted':>8} {'%corpus':>8} | {'p@1':>7} {'p@5':>7} {'p@10':>7} {'mrr':>7} | {'gold_killed':>11}")
    for thr in [0.6, 0.7, 0.8, 0.9, 0.95]:
        km = frag >= thr
        nd = int(km.sum())
        ranks_p = [rank_of(sims[qi], ti, km) for qi, ti in enumerate(target_idxs)]
        mp = metrics(ranks_p)
        gold_killed = mp["n_missed_deleted"]
        d1 = mp["p@1"] - m_full["p@1"]
        print(f"{thr:>7} {nd:>8} {100*nd/n:>7.1f}% | {mp['p@1']:>7.4f} {mp['p@5']:>7.4f} {mp['p@10']:>7.4f} {mp['mrr']:>7.4f} | {gold_killed:>11}")

    # Coverage by type at the production threshold
    print(f"\nCOVERAGE by type at production threshold {args.threshold}: {n_fragile}/{n} fragile")
    for t, (tot, fr) in sorted(by_type.items(), key=lambda kv: -kv[1][1]):
        if fr:
            print(f"  {t:<16} {fr}/{tot} ({100*fr/max(1,tot):.1f}%)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
