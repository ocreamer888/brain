#!/usr/bin/env python3
"""Confidence-by-Corroboration scorer — v1, SHADOW MODE (Task 10).

AlphaFold pLDDT-style confidence for brain memories. Demote, never delete.

v1 computes ONE signal — local_consistency (lDDT-style neighborhood support):
  For each memory, support = mean cosine to its top-K nearest neighbors.
  High support  → well-corroborated by its local neighborhood → high confidence.
  Low support   → isolated/orphan memory                      → low confidence.

Support is binned into pLDDT-style bands by CORPUS PERCENTILE (data-driven, not
magic thresholds), each mapped to a proposed salience value:

  H (high,       >= p75) -> 0.70
  M (medium, p40..p75)   -> 0.55
  L (low,    p15..p40)   -> 0.40
  D (disordered, < p15)  -> 0.25   (still >= 0.1 API floor — never deletes)

SHADOW MODE: this tool ONLY computes and writes a report. It does NOT call
update_salience and is NOT wired into run_cleanup.py. The report's safety check
("how many already-trusted memories would get demoted?") tells us whether the
formula is sane BEFORE we ever flip writing on.

Usage:
    python3 brain/tools/confidence_score.py --sample 2000
    python3 brain/tools/confidence_score.py --full --k 10
    python3 brain/tools/confidence_score.py --report brain/eval/confidence.json
"""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
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

# Band definition: (label, lower percentile cut, proposed salience).
# Evaluated high-to-low; first match wins.
BANDS: list[tuple[str, float, float]] = [
    ("H", 75.0, 0.70),
    ("M", 40.0, 0.55),
    ("L", 15.0, 0.40),
    ("D", 0.0, 0.25),
]

# Safety check: a memory is "already trusted" if its current salience is at or
# above this, or its source is in TRUSTED_SOURCES. Demoting these is the risk.
TRUSTED_SALIENCE = 0.8
TRUSTED_SOURCES = {'"obsidian"', '"user"', '"user_feedback"'}
# A proposed value this much below current counts as a meaningful demotion.
DEMOTE_MARGIN = 0.10


def load_salience_source(db_path: Path) -> dict[str, tuple[float, str]]:
    """id -> (current_salience, source). Used for shadow diff + safety check."""
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("SELECT id, salience, source FROM memories").fetchall()
    conn.close()
    return {mid: (sal if sal is not None else 0.5, src or "") for mid, sal, src in rows}


def compute_support(
    matrix: np.ndarray,
    indices: list[int],
    k: int,
    chunk: int = 512,
) -> np.ndarray:
    """Mean cosine to top-K neighbors (excluding self) for each scored index.

    Neighbors are drawn from the FULL corpus (matrix); only `indices` are scored.
    Returns array aligned with `indices`.
    """
    n = matrix.shape[0]
    out = np.empty(len(indices), dtype=np.float32)
    idx_arr = np.asarray(indices)

    for start in range(0, len(indices), chunk):
        sel = idx_arr[start : start + chunk]
        block = matrix[sel]              # (C, d)
        sims = block @ matrix.T          # (C, N)
        # Exclude self: zero out the (row -> its own global index) entry.
        sims[np.arange(len(sel)), sel] = -np.inf
        # Top-K per row, then mean.
        topk = np.partition(sims, -k, axis=1)[:, -k:]  # (C, K)
        out[start : start + len(sel)] = topk.mean(axis=1)

    return out


def assign_bands(support: np.ndarray) -> tuple[np.ndarray, np.ndarray, dict]:
    """Map support -> (band labels, proposed salience) via corpus percentiles.

    Returns (bands, proposed, thresholds_dict).
    """
    # Percentile cut points from the scored population itself.
    cuts = {p: float(np.percentile(support, p)) for _, p, _ in BANDS if p > 0}

    bands = np.empty(support.shape[0], dtype="<U1")
    proposed = np.empty(support.shape[0], dtype=np.float32)
    for i, s in enumerate(support):
        for label, p, sal in BANDS:
            if p == 0.0 or s >= cuts[p]:
                bands[i] = label
                proposed[i] = sal
                break
    return bands, proposed, cuts


def stratified_sample(metas: list[dict], n: int, seed: int) -> list[int]:
    rng = random.Random(seed)
    by_type: dict[str, list[int]] = defaultdict(list)
    for i, m in enumerate(metas):
        by_type[m["type"]].append(i)
    total = len(metas)
    indices: list[int] = []
    for _, idxs in by_type.items():
        count = max(1, round(n * len(idxs) / total))
        indices.extend(rng.sample(idxs, k=min(count, len(idxs))))
    rng.shuffle(indices)
    return indices[:n]


def run(
    db_path: Path,
    sample: int | None,
    k: int,
    seed: int,
    full: bool,
) -> dict:
    print(f"Loading corpus from {db_path}...", file=sys.stderr)
    t0 = time.time()
    metas, matrix = load_corpus(db_path)
    sal_src = load_salience_source(db_path)
    print(f"  {len(metas)} memories loaded in {time.time()-t0:.1f}s", file=sys.stderr)

    if full:
        indices = list(range(len(metas)))
    else:
        indices = stratified_sample(metas, sample or 2000, seed)

    print(f"  Scoring {len(indices)} memories (K={k})...", file=sys.stderr)
    t0 = time.time()
    support = compute_support(matrix, indices, k)
    bands, proposed, cuts = assign_bands(support)
    print(f"  Done in {time.time()-t0:.1f}s ({len(indices)/max(1e-9,time.time()-t0):.0f}/s)",
          file=sys.stderr)

    # --- aggregate ---
    band_counts: dict[str, int] = defaultdict(int)
    by_type_band: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    demotions: list[dict] = []       # trusted memories that would lose salience
    changes: list[dict] = []         # all proposed changes (for sampling)

    for pos, idx in enumerate(indices):
        m = metas[idx]
        cur_sal, src = sal_src.get(m["id"], (0.5, ""))
        band = bands[pos]
        prop = float(proposed[pos])
        band_counts[band] += 1
        by_type_band[m["type"]][band] += 1

        delta = prop - cur_sal
        rec = {
            "id": m["id"], "type": m["type"], "project": m["project"],
            "title": m["title"][:80], "support": round(float(support[pos]), 4),
            "band": band, "current_salience": round(cur_sal, 3),
            "proposed_salience": prop, "delta": round(delta, 3),
        }
        changes.append(rec)

        trusted = cur_sal >= TRUSTED_SALIENCE or src in TRUSTED_SOURCES
        if trusted and delta <= -DEMOTE_MARGIN:
            rec_d = dict(rec)
            rec_d["source"] = src
            demotions.append(rec_d)

    demotions.sort(key=lambda r: r["delta"])  # most-demoted first
    changes.sort(key=lambda r: r["support"])  # lowest support first

    report = {
        "mode": "SHADOW (no writes)",
        "params": {"k": k, "n_scored": len(indices), "bands": BANDS},
        "support": {
            "mean": round(float(support.mean()), 4),
            "p15": round(cuts.get(15.0, 0.0), 4),
            "p40": round(cuts.get(40.0, 0.0), 4),
            "p75": round(cuts.get(75.0, 0.0), 4),
            "min": round(float(support.min()), 4),
            "max": round(float(support.max()), 4),
        },
        "band_counts": dict(band_counts),
        "by_type_band": {t: dict(b) for t, b in sorted(by_type_band.items())},
        "safety": {
            "trusted_demoted_count": len(demotions),
            "trusted_demoted_pct": round(100.0 * len(demotions) / max(1, len(indices)), 2),
            "worst_50": demotions[:50],
        },
        "lowest_support_50": changes[:50],
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--sample", type=int, default=None,
                        help="Memories to score (default 2000, stratified by type)")
    parser.add_argument("--full", action="store_true", help="Score every memory")
    parser.add_argument("--k", type=int, default=10, help="Neighbor count (default 10)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--report", type=Path,
        default=REPORT_DIR / f"confidence_{__import__('datetime').date.today().strftime('%Y_%m_%d')}.json",
    )
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"DB not found: {args.db}", file=sys.stderr)
        return 2

    report = run(db_path=args.db, sample=args.sample, k=args.k, seed=args.seed, full=args.full)

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")

    s = report["support"]
    print(f"\n=== Confidence Score Report ({report['mode']}) ===")
    print(f"Scored: {report['params']['n_scored']}  |  K={args.k}")
    print(f"Support: mean={s['mean']}  p15={s['p15']}  p40={s['p40']}  p75={s['p75']}")
    print(f"\nBands: " + "  ".join(f"{b}={report['band_counts'].get(b,0)}" for b, _, _ in BANDS))

    sf = report["safety"]
    print(f"\n=== SAFETY: trusted memories that would be DEMOTED ===")
    print(f"  {sf['trusted_demoted_count']} ({sf['trusted_demoted_pct']}% of scored)")
    for r in sf["worst_50"][:10]:
        print(f"  [{r['current_salience']}->{r['proposed_salience']} {r['delta']:+}] "
              f"({r['type']}/{r['project']}) {r['title']}")

    print(f"\nWrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
