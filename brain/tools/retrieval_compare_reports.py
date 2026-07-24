#!/usr/bin/env python3
"""Compare retrieval reports side-by-side (RRF vs alpha-hybrid).

Usage:
  python3 brain/tools/retrieval_compare_reports.py \
    --rrf brain/eval/kfold_rrf_post_revert.json \
    --alpha-report brain/eval/kfold_alpha_sweep.json \
    --alpha 0.7
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def get_slice(d: dict, section: str, key: str) -> dict:
    bucket = d.get(section, {}) or {}
    if key in bucket:
        return bucket[key]
    quoted = f"\"{key}\""
    if quoted in bucket:
        return bucket[quoted]
    return {}


def pick_alpha_report(alpha_blob: dict, alpha: float) -> dict:
    if alpha_blob.get("mode") == "alpha_sweep":
        key = f"{alpha:.3f}"
        try:
            return alpha_blob["results"][key]
        except KeyError as exc:
            available = ", ".join(sorted(alpha_blob.get("results", {}).keys()))
            raise SystemExit(
                f"alpha={key} not found in sweep report. available: {available}"
            ) from exc
    return alpha_blob


def row_from_slice(name: str, left: dict, right: dict) -> tuple[str, int, float, float, float, float, float, float]:
    n = right.get("n", left.get("n", 0))
    l_p1 = float(left.get("precision@1", 0.0))
    r_p1 = float(right.get("precision@1", 0.0))
    l_mrr = float(left.get("mrr", 0.0))
    r_mrr = float(right.get("mrr", 0.0))
    return (
        name,
        int(n),
        l_p1,
        r_p1,
        r_p1 - l_p1,
        l_mrr,
        r_mrr,
        r_mrr - l_mrr,
    )


def fmt_row(r: tuple[str, int, float, float, float, float, float, float]) -> str:
    name, n, l_p1, r_p1, d_p1, l_mrr, r_mrr, d_mrr = r
    return (
        f"{name:<18} {n:>5}  "
        f"{l_p1:>6.3f} {r_p1:>7.3f} {d_p1:>+7.3f}   "
        f"{l_mrr:>6.3f} {r_mrr:>7.3f} {d_mrr:>+7.3f}"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rrf", type=Path, required=True, help="RRF report JSON path")
    ap.add_argument(
        "--alpha-report",
        type=Path,
        required=True,
        help="Alpha report JSON path (single report or alpha_sweep output)",
    )
    ap.add_argument("--alpha", type=float, default=0.7, help="alpha value to compare")
    ap.add_argument(
        "--projects",
        type=str,
        default="owelign,le_chandelier,rmt,sicop",
        help="comma-separated project list",
    )
    args = ap.parse_args()

    rrf = load_json(args.rrf)
    alpha_blob = load_json(args.alpha_report)
    alpha_report = pick_alpha_report(alpha_blob, args.alpha)

    rows: list[tuple[str, int, float, float, float, float, float, float]] = []
    projects = [p.strip() for p in args.projects.split(",") if p.strip()]
    for p in projects:
        l = get_slice(rrf, "by_project", p)
        r = get_slice(alpha_report, "by_project", p)
        rows.append(row_from_slice(p, l, r))

    # project_context is a type slice
    l_pc = get_slice(rrf, "by_type", "project_context")
    r_pc = get_slice(alpha_report, "by_type", "project_context")
    rows.append(row_from_slice("project_context", l_pc, r_pc))

    # overall
    rows.append(row_from_slice("overall", rrf.get("overall", {}), alpha_report.get("overall", {})))

    print("project/type           n     RRF   alpha    ΔP@1      RRF   alpha    ΔMRR")
    print("-" * 79)
    for row in rows:
        print(fmt_row(row))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

