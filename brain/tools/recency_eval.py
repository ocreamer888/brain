#!/usr/bin/env python3
"""Recency eval: for each (old, new) pair about the same subject, does
production search rank the NEWER memory above the OLDER one?

This is the gold set the 2026-10-21 layer-detection experiment said was
missing before any ranking A/B (layer_w vs salience_w) could mean anything
-- see docs/architecture/experiments/2026-10-21-layer-detection/README.md,
"Exp 4 -- ranking A/B: not run, and why". Built from real data, not
invented: 16 hand-labelled true LAYER pairs plus 47 curator UPDATE pairs
confirmed to share a specific entity between old and new content. See
brain/eval/gold_recency.jsonl.

Plain recall@k (does the gold id appear in the top k) can't test this --
a query can "pass" recall@k with the stale answer ranked above the fresh
one. This measures the pairwise relationship directly.

Usage:
    python3 brain/tools/recency_eval.py --gold brain/eval/gold_recency.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from brain.api_client import BrainApiError, search as api_search


def rank_of(results: list[dict[str, Any]], target_id: str) -> int | None:
    for i, r in enumerate(results, 1):
        if str(r.get("id", "")) == target_id:
            return i
    return None


def score_one(case: dict[str, Any], n: int) -> dict[str, Any]:
    results = api_search(query=case["query"], n=n, project=case.get("project"))
    new_rank = rank_of(results, case["new_id"])
    old_rank = rank_of(results, case["old_id"])

    new_in_topk = new_rank is not None
    if new_rank is None and old_rank is None:
        # neither surfaced -- can't judge recency preference, only coverage miss
        outranks = None
    elif new_rank is not None and old_rank is None:
        outranks = True
    elif new_rank is None and old_rank is not None:
        outranks = False
    else:
        outranks = new_rank < old_rank

    return {
        "query": case["query"],
        "subject": case.get("subject"),
        "new_rank": new_rank,
        "old_rank": old_rank,
        "new_in_topk": new_in_topk,
        "new_outranks_old": outranks,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Recency eval: does search prefer the newer memory?")
    p.add_argument("--gold", type=Path, default=Path("brain/eval/gold_recency.jsonl"))
    p.add_argument("--n", type=int, default=10)
    p.add_argument("--report", type=Path, default=Path("brain/eval/last_recency_report.json"))
    args = p.parse_args(argv)

    gold_path = args.gold if args.gold.is_absolute() else _REPO_ROOT / args.gold
    report_path = args.report if args.report.is_absolute() else _REPO_ROOT / args.report

    cases = [json.loads(line) for line in gold_path.read_text().splitlines() if line.strip()]

    try:
        rows = [score_one(c, args.n) for c in cases]
    except BrainApiError as e:
        print(f"API unavailable: {e}", file=sys.stderr)
        return 2

    n = len(rows) or 1
    new_in_topk = sum(1 for r in rows if r["new_in_topk"])
    judged = [r for r in rows if r["new_outranks_old"] is not None]
    outranks = sum(1 for r in judged if r["new_outranks_old"])
    neither_found = sum(1 for r in rows if r["new_rank"] is None and r["old_rank"] is None)

    summary = {
        "gold_file": str(gold_path),
        "n_pairs": len(rows),
        "new_in_topk_rate": round(new_in_topk / n, 4),
        "new_outranks_old_rate": round(outranks / len(judged), 4) if judged else None,
        "n_judged": len(judged),
        "neither_surfaced": neither_found,
        "per_pair": rows,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Gold: {gold_path} ({len(rows)} pairs), n={args.n}")
    print(f"new_in_topk_rate = {summary['new_in_topk_rate']}  (newer memory reachable at all)")
    print(
        f"new_outranks_old_rate = {summary['new_outranks_old_rate']} "
        f"over {len(judged)} judged pairs  (of those where at least one surfaced, "
        f"does the newer one rank better?)"
    )
    print(f"neither surfaced: {neither_found}")
    misses = [r for r in rows if r["new_outranks_old"] is False]
    if misses:
        print("\nstale-wins cases (old ranks better than new):")
        for r in misses:
            print(f"  subject={r['subject']!r} new_rank={r['new_rank']} old_rank={r['old_rank']}")
    print(f"\nWrote {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
