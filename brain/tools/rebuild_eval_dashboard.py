#!/usr/bin/env python3
"""Rebuild eval_dashboard.json from the per-run archive in brain/eval/runs/.

Recovery tool: the dashboard is runtime data (not git-tracked) and a deploy with
emptyOutDir can wipe it. Each eval run is also archived under brain/eval/runs/,
so the dashboard history can always be reconstructed from those. See
docs/deploy/README.md (incident 2026-06-08).

Usage: python3 brain/tools/rebuild_eval_dashboard.py
"""
import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS = _REPO_ROOT / "brain" / "eval" / "runs"
OUT = _REPO_ROOT / "brain" / "rust" / "static" / "eval_dashboard.json"


def row_from_run(run: dict) -> dict:
    row = {
        "run_id": run.get("run_id"),
        "pass": run.get("pass"),
        "quick_p1_avg": None,
        "non_fact_p1": None,
        "mcp_p1": None,
        "mcp_gap": None,
    }
    qg = run.get("quick_gate")
    if qg and qg.get("status") == "ok":
        by_type = qg.get("by_type", {}) or {}
        vals = list(by_type.values())
        non_fact = [v for k, v in by_type.items() if "fact" not in k]
        if vals:
            row["quick_p1_avg"] = round(sum(vals) / len(vals), 4)
        if non_fact:
            row["non_fact_p1"] = round(sum(non_fact) / len(non_fact), 4)
    mcp = run.get("mcp_path")
    if mcp and mcp.get("status") == "ok":
        row["mcp_p1"] = mcp.get("precision_at_1")
        # old runs used gap_vs_kfold_p1; new runs use gap_vs_offline_rrf
        row["mcp_gap"] = mcp.get("gap_vs_offline_rrf", mcp.get("gap_vs_kfold_p1"))
    return row


runs = []
for f in sorted(RUNS.glob("*.json")):
    try:
        runs.append(row_from_run(json.loads(f.read_text(encoding="utf-8"))))
    except Exception as e:
        print(f"skip {f.name}: {e}")

# Newest first (run_id is a sortable timestamp string)
runs.sort(key=lambda r: r.get("run_id") or "", reverse=True)
OUT.write_text(json.dumps({"runs": runs}, indent=2), encoding="utf-8")
print(f"rebuilt {OUT} with {len(runs)} rows")
print(f"newest: {runs[0]['run_id']}  oldest: {runs[-1]['run_id']}")
