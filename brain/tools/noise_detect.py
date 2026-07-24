#!/usr/bin/env python3
"""Perturbation-based memory fragility detector (Noise Detection, Tier 1 Item 2).

Algorithm (Implicit Geometric Learning):
  For each sampled memory:
    1. Get its top-K neighbors in original embedding space.
    2. Apply M Gaussian noise perturbations, re-normalize.
    3. For each perturbed embedding, get its top-K neighbors.
    4. Compute Jaccard overlap between original neighbors and perturbed neighbors.
    5. fragility = 1 - mean_jaccard

Low Jaccard (high fragility) means neighbors are unstable under small perturbations —
the memory sits in an ambiguous region of the embedding space, likely from:
  - Duplicate or near-identical title/content
  - Empty or very short content
  - Mismatched title vs. body semantics

Usage:
    python3 brain/tools/noise_detect.py
    python3 brain/tools/noise_detect.py --sample 3000 --sigma 0.05 --k 10 --trials 5
    python3 brain/tools/noise_detect.py --full --threshold 0.4 --report brain/eval/noise_detect.json
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from brain.tools.retrieval_eval_kfold import load_corpus

DB_PATH = _REPO_ROOT / "brain" / "rust" / "brain.db"
REPORT_DIR = _REPO_ROOT / "brain" / "eval"


def fragility_score(
    idx: int,
    matrix: np.ndarray,
    sigma: float,
    k: int,
    trials: int,
    rng: np.random.Generator,
) -> float:
    """Compute fragility for memory at index idx.

    Returns value in [0, 1]. Higher = more fragile.
    """
    n = matrix.shape[0]
    orig = matrix[idx]  # (768,) unit vector

    # Original top-K neighbors (excluding self)
    sims_orig = matrix @ orig  # (N,)
    sims_orig[idx] = -999.0
    orig_topk = set(np.argpartition(sims_orig, -k)[-k:].tolist())

    # Perturbation trials: batch all at once for this memory
    noise = rng.standard_normal((trials, orig.shape[0])).astype(np.float32) * sigma
    perturbed = orig[None, :] + noise  # (trials, 768)
    norms = np.linalg.norm(perturbed, axis=1, keepdims=True)
    norms[norms < 1e-10] = 1.0
    perturbed /= norms  # normalized (trials, 768)

    # Sims for all perturbed queries at once: (trials, N)
    sims_pert = perturbed @ matrix.T
    sims_pert[:, idx] = -999.0

    jaccard_vals: list[float] = []
    for t in range(trials):
        pert_topk = set(np.argpartition(sims_pert[t], -k)[-k:].tolist())
        intersection = len(orig_topk & pert_topk)
        union = len(orig_topk | pert_topk)
        jaccard_vals.append(intersection / union if union > 0 else 0.0)

    return float(1.0 - np.mean(jaccard_vals))


def stratified_sample(metas: list[dict], n: int, seed: int) -> list[int]:
    rng = random.Random(seed)
    by_type: dict[str, list[int]] = defaultdict(list)
    for i, m in enumerate(metas):
        by_type[m["type"]].append(i)
    total = len(metas)
    indices: list[int] = []
    for t, idxs in by_type.items():
        count = max(1, round(n * len(idxs) / total))
        indices.extend(rng.sample(idxs, k=min(count, len(idxs))))
    rng.shuffle(indices)
    return indices[:n]


def run(
    db_path: Path,
    sample: int | None,
    sigma: float,
    k: int,
    trials: int,
    seed: int,
    threshold: float,
    full: bool,
) -> dict:
    print(f"Loading corpus from {db_path}...", file=sys.stderr)
    t0 = time.time()
    metas, matrix = load_corpus(db_path)
    print(f"  {len(metas)} memories loaded in {time.time()-t0:.1f}s", file=sys.stderr)

    if full:
        indices = list(range(len(metas)))
    elif sample is not None:
        indices = stratified_sample(metas, sample, seed)
    else:
        indices = stratified_sample(metas, 2000, seed)

    print(f"  Scoring {len(indices)} memories (sigma={sigma}, K={k}, trials={trials})...", file=sys.stderr)
    rng = np.random.default_rng(seed)

    t0 = time.time()
    scores: list[tuple[float, dict]] = []
    for i, idx in enumerate(indices):
        fs = fragility_score(idx, matrix, sigma, k, trials, rng)
        scores.append((fs, metas[idx]))
        if (i + 1) % 500 == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed
            eta = (len(indices) - i - 1) / rate
            print(f"  {i+1}/{len(indices)} ({rate:.0f}/s, ETA {eta:.0f}s)", file=sys.stderr)

    elapsed = time.time() - t0
    print(f"  Done in {elapsed:.1f}s ({len(indices)/elapsed:.0f}/s)", file=sys.stderr)

    scores.sort(key=lambda x: x[0], reverse=True)

    fragile = [(fs, m) for fs, m in scores if fs >= threshold]
    stable = [(fs, m) for fs, m in scores if fs < threshold]

    by_type: dict[str, list[float]] = defaultdict(list)
    by_project: dict[str, list[float]] = defaultdict(list)
    for fs, m in scores:
        by_type[m["type"]].append(fs)
        by_project[m["project"]].append(fs)

    def type_stats(vals: list[float]) -> dict:
        a = np.array(vals)
        return {
            "n": len(vals),
            "mean_fragility": round(float(a.mean()), 4),
            "p50": round(float(np.percentile(a, 50)), 4),
            "p90": round(float(np.percentile(a, 90)), 4),
            "n_fragile": int((a >= threshold).sum()),
        }

    all_frag = np.array([fs for fs, _ in scores])

    report = {
        "params": {"sigma": sigma, "k": k, "trials": trials, "threshold": threshold, "n_scored": len(scores)},
        "overall": {
            "mean_fragility": round(float(all_frag.mean()), 4),
            "p50": round(float(np.percentile(all_frag, 50)), 4),
            "p90": round(float(np.percentile(all_frag, 90)), 4),
            "n_fragile": len(fragile),
            "fragile_pct": round(100.0 * len(fragile) / max(1, len(scores)), 1),
        },
        "by_type": {t: type_stats(v) for t, v in sorted(by_type.items())},
        "by_project": {
            p: type_stats(v)
            for p, v in sorted(by_project.items(), key=lambda kv: -len(kv[1]))[:15]
        },
        "worst_100": [
            {"fragility": round(fs, 4), "id": m["id"], "type": m["type"],
             "project": m["project"], "title": m["title"][:80]}
            for fs, m in scores[:100]
        ],
    }

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--sample", type=int, default=None,
                        help="Number of memories to sample (default: 2000, stratified by type)")
    parser.add_argument("--full", action="store_true", help="Score every memory in the corpus")
    parser.add_argument("--sigma", type=float, default=0.05, help="Noise std dev (default: 0.05)")
    parser.add_argument("--k", type=int, default=10, help="Neighbor count (default: 10)")
    parser.add_argument("--trials", type=int, default=5, help="Perturbation trials per memory (default: 5)")
    parser.add_argument("--threshold", type=float, default=0.4,
                        help="Fragility threshold — memories above this are flagged (default: 0.4)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--report", type=Path,
        default=REPORT_DIR / f"noise_detect_{__import__('datetime').date.today().strftime('%Y_%m_%d')}.json",
    )
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"DB not found: {args.db}", file=sys.stderr)
        return 2

    report = run(
        db_path=args.db,
        sample=args.sample,
        sigma=args.sigma,
        k=args.k,
        trials=args.trials,
        seed=args.seed,
        threshold=args.threshold,
        full=args.full,
    )

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")

    o = report["overall"]
    print(f"\n=== Noise Detection Report ===")
    print(f"Scored: {report['params']['n_scored']}  |  threshold: {args.threshold}")
    print(f"Mean fragility: {o['mean_fragility']}  p50: {o['p50']}  p90: {o['p90']}")
    print(f"Fragile (>= {args.threshold}): {o['n_fragile']} ({o['fragile_pct']}%)")

    print(f"\n=== By type ===")
    print(f"  {'type':<22}  {'n':>5}  {'mean':>6}  {'p90':>6}  {'n_fragile':>9}")
    for t, s in report["by_type"].items():
        print(f"  {t:<22}  {s['n']:>5}  {s['mean_fragility']:>6.3f}  {s['p90']:>6.3f}  {s['n_fragile']:>9}")

    print(f"\n=== Worst 10 ===")
    for entry in report["worst_100"][:10]:
        print(f"  [{entry['fragility']:.3f}] ({entry['type']}/{entry['project']}) {entry['title']}")

    print(f"\nWrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
