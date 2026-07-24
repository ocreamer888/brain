#!/usr/bin/env python3
"""Evaluate brain retrieval against a JSONL gold set (recall@k, MRR)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from brain.api_client import BrainApiError, search as api_search

# Tags are comma-separated; paths may contain spaces (e.g. ``02 Areas``).
TAG_VAULT_RE = re.compile(r"vault/[^,|]+\.md")


def normalize_path(p: str) -> str:
    return p.strip().replace("\\", "/")


def extract_path_from_hit(hit: dict[str, Any]) -> str | None:
    meta = hit.get("metadata") or {}
    fp = meta.get("file_path")
    if isinstance(fp, str) and fp.startswith("vault/"):
        return normalize_path(fp)
    tags = meta.get("tags") or ""
    if isinstance(tags, str):
        m = TAG_VAULT_RE.search(tags)
        if m:
            return normalize_path(m.group(0))
    return None


def load_gold(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"{path}:{line_no}: invalid JSON: {e}") from e
        if "query" not in obj or "gold_files" not in obj:
            raise ValueError(f"{path}:{line_no}: missing query or gold_files")
        rows.append(obj)
    return rows


def score_one(
    case: dict[str, Any],
    k: int,
    search_fn: Callable[[str, int], list[dict[str, Any]]],
) -> dict[str, Any]:
    q = str(case["query"])
    gold = [normalize_path(x) for x in case["gold_files"]]
    line_k = int(case.get("k", k))
    results = search_fn(q, line_k)
    paths = [extract_path_from_hit(h) for h in results]
    first_rank = 0
    for i, p in enumerate(paths, 1):
        if p and p in gold:
            first_rank = i
            break
    recall = 1 if first_rank else 0
    mrr = (1.0 / first_rank) if first_rank else 0.0
    return {
        "query": q,
        "k": line_k,
        "gold_files": gold,
        "recall_at_k": recall,
        "first_correct_rank": first_rank,
        "mrr": round(mrr, 4),
    }


def run_eval(
    gold_path: Path,
    k: int,
    search_fn: Callable[[str, int], list[dict[str, Any]]],
) -> dict[str, Any]:
    cases = load_gold(gold_path)
    per_query = [score_one(c, k, search_fn) for c in cases]
    n = len(per_query) or 1
    mean_recall = sum(r["recall_at_k"] for r in per_query) / n
    mean_mrr = sum(r["mrr"] for r in per_query) / n
    return {
        "gold_file": str(gold_path),
        "n_queries": len(per_query),
        "mean_recall": round(mean_recall, 4),
        "mean_mrr": round(mean_mrr, 4),
        "per_query": per_query,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Retrieval eval: recall@k vs gold.jsonl")
    p.add_argument("--gold", type=Path, default=Path("brain/eval/gold.jsonl"))
    p.add_argument("--k", type=int, default=10)
    p.add_argument("--min-recall", type=float, default=None)
    p.add_argument(
        "--report",
        type=Path,
        default=Path("brain/eval/last_report.json"),
        help="Write JSON summary here",
    )
    args = p.parse_args(argv)

    gold_path = args.gold if args.gold.is_absolute() else _REPO_ROOT / args.gold
    report_path = args.report if args.report.is_absolute() else _REPO_ROOT / args.report

    def search_fn(query: str, n: int) -> list[dict[str, Any]]:
        return api_search(query=query, n=n)

    try:
        report = run_eval(gold_path, args.k, search_fn)
    except BrainApiError as e:
        print(f"API unavailable: {e}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Gold: {gold_path} ({report['n_queries']} queries)")
    print(f"mean_recall@k={report['mean_recall']}  mean_mrr={report['mean_mrr']}")
    print("per_query:")
    for row in report["per_query"]:
        print(
            f"  recall={row['recall_at_k']}  rank={row['first_correct_rank']:2d}  "
            f"mrr={row['mrr']:.4f}  q={row['query'][:60]!r}"
        )
    print(f"\nWrote {report_path}")

    if args.min_recall is not None and report["mean_recall"] < args.min_recall:
        print(
            f"FAIL: mean_recall {report['mean_recall']} < {args.min_recall}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
