#!/usr/bin/env python3
"""Brain eval suite — unified orchestrator for all eval modes.

Usage:
    python3 brain/tools/eval_suite.py                    # default: --quick --mcp
    python3 brain/tools/eval_suite.py --all              # all 4 modes
    python3 brain/tools/eval_suite.py --quick --mcp --quiet
    python3 brain/tools/eval_suite.py --quick --dry-run  # smoke test
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

DEFAULT_DB = _REPO_ROOT / "brain" / "rust" / "brain.db"
DEFAULT_GOLD_SEMANTIC = _REPO_ROOT / "brain" / "eval" / "gold_semantic.jsonl"
DEFAULT_GOLD_VAULT = _REPO_ROOT / "brain" / "eval" / "gold.jsonl"
DEFAULT_RUNS_DIR = _REPO_ROOT / "brain" / "eval" / "runs"
DEFAULT_DASHBOARD = _REPO_ROOT / "brain" / "rust" / "static" / "eval_dashboard.json"


@dataclass
class ModeResult:
    status: str  # "ok" | "skipped" | "error"
    reason: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalReport:
    run_id: str
    modes_run: list[str]
    passed: bool
    quick_gate: ModeResult | None = None
    kfold: ModeResult | None = None
    gold_vault: ModeResult | None = None
    mcp_path: ModeResult | None = None

    def to_dict(self) -> dict[str, Any]:
        def _mode(m: ModeResult | None) -> dict[str, Any] | None:
            if m is None:
                return None
            d: dict[str, Any] = {"status": m.status}
            if m.reason:
                d["reason"] = m.reason
            d.update(m.data)
            return d

        return {
            "run_id": self.run_id,
            "modes_run": self.modes_run,
            "pass": self.passed,
            "quick_gate": _mode(self.quick_gate),
            "kfold": _mode(self.kfold),
            "gold_vault": _mode(self.gold_vault),
            "mcp_path": _mode(self.mcp_path),
        }

    def to_dashboard_row(self) -> dict[str, Any]:
        """Compact summary row for the dashboard history JSON."""
        row: dict[str, Any] = {
            "run_id": self.run_id,
            "pass": self.passed,
            "quick_p1_avg": None,
            "non_fact_p1": None,
            "mcp_p1": None,
            "mcp_gap": None,
        }
        if self.quick_gate and self.quick_gate.status == "ok":
            by_type = self.quick_gate.data.get("by_type", {})
            vals = list(by_type.values())
            non_fact_vals = [v for k, v in by_type.items() if "fact" not in k]
            if vals:
                row["quick_p1_avg"] = round(sum(vals) / len(vals), 4)
            if non_fact_vals:
                row["non_fact_p1"] = round(sum(non_fact_vals) / len(non_fact_vals), 4)
        if self.mcp_path and self.mcp_path.status == "ok":
            row["mcp_p1"] = self.mcp_path.data.get("precision_at_1")
            row["mcp_gap"] = self.mcp_path.data.get("gap_vs_offline_rrf")
        return row


def _update_dashboard(dashboard_path: Path, report: EvalReport) -> None:
    """Prepend new run row to dashboard JSON. Atomic write."""
    dashboard_path.parent.mkdir(parents=True, exist_ok=True)

    existing_runs: list[dict] = []
    if dashboard_path.exists():
        try:
            existing_runs = json.loads(
                dashboard_path.read_text(encoding="utf-8")
            ).get("runs", [])
        except Exception:
            pass

    new_row = report.to_dashboard_row()
    existing_runs = [r for r in existing_runs if r.get("run_id") != new_row["run_id"]]
    runs = [new_row] + existing_runs

    tmp = dashboard_path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"runs": runs}, indent=2), encoding="utf-8")
    tmp.replace(dashboard_path)


def run_suite(
    modes: set[str],
    db_path: Path = DEFAULT_DB,
    gold_semantic_path: Path = DEFAULT_GOLD_SEMANTIC,
    gold_vault_path: Path = DEFAULT_GOLD_VAULT,
    runs_dir: Path = DEFAULT_RUNS_DIR,
    dashboard_path: Path = DEFAULT_DASHBOARD,
    quiet: bool = False,
    dry_run: bool = False,
) -> EvalReport:
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M")
    modes_run: list[str] = []
    passed = True

    quick_gate_result: ModeResult | None = None
    kfold_result: ModeResult | None = None
    gold_vault_result: ModeResult | None = None
    mcp_path_result: ModeResult | None = None

    # --- quick_gate ---
    if "quick_gate" in modes:
        modes_run.append("quick_gate")
        if dry_run:
            quick_gate_result = ModeResult(status="skipped", reason="dry-run")
        else:
            try:
                from brain.tools.ingest_quality_gate import run_gate
                by_type, exit_code = run_gate(db_path=db_path)
                quick_gate_result = ModeResult(
                    status="ok",
                    data={"exit_code": exit_code, "by_type": by_type},
                )
                if exit_code == 2:
                    passed = False
            except Exception as e:
                quick_gate_result = ModeResult(status="error", reason=str(e))

    # --- kfold ---
    if "kfold" in modes:
        modes_run.append("kfold")
        if dry_run:
            kfold_result = ModeResult(status="skipped", reason="dry-run")
        else:
            try:
                from brain.tools.retrieval_eval_kfold import (
                    load_corpus,
                    stratified_sample,
                    evaluate,
                )
                from brain.core.embedder import embed_batch

                metas, matrix = load_corpus(db_path)
                held_out = stratified_sample(metas, 0.10, 42, False)
                report = evaluate(metas, matrix, held_out, embed_batch, [1, 5, 10])
                kfold_result = ModeResult(status="ok", data=report)
            except Exception as e:
                kfold_result = ModeResult(status="error", reason=str(e))

    # --- gold_vault ---
    if "gold_vault" in modes:
        modes_run.append("gold_vault")
        if dry_run:
            gold_vault_result = ModeResult(status="skipped", reason="dry-run")
        else:
            try:
                from brain.tools.retrieval_eval import run_eval
                from brain.api_client import BrainApiError, search as api_search

                vault_report = run_eval(
                    gold_vault_path,
                    10,
                    lambda q, n: api_search(query=q, n=n),
                )
                gold_vault_result = ModeResult(status="ok", data=vault_report)
            except BrainApiError as e:
                gold_vault_result = ModeResult(status="skipped", reason=str(e))
            except Exception as e:
                gold_vault_result = ModeResult(status="error", reason=str(e))

    # --- mcp_path ---
    if "mcp_path" in modes:
        modes_run.append("mcp_path")
        if dry_run:
            mcp_path_result = ModeResult(status="skipped", reason="dry-run")
        else:
            try:
                from brain.tools.mcp_eval import offline_rrf_p1, run_mcp_eval

                # Honest baseline: plain offline RRF on the SAME gold queries.
                baseline_offline_p1 = offline_rrf_p1(db_path, gold_semantic_path)
                mcp_result = run_mcp_eval(
                    gold_semantic_path,
                    baseline_offline_p1=baseline_offline_p1,
                )
                mcp_path_result = ModeResult(
                    status=mcp_result["status"],
                    reason=mcp_result.get("reason"),
                    data={
                        k: v
                        for k, v in mcp_result.items()
                        if k not in ("status", "reason")
                    },
                )
            except Exception as e:
                mcp_path_result = ModeResult(status="error", reason=str(e))

    eval_report = EvalReport(
        run_id=run_id,
        modes_run=modes_run,
        passed=passed,
        quick_gate=quick_gate_result,
        kfold=kfold_result,
        gold_vault=gold_vault_result,
        mcp_path=mcp_path_result,
    )

    # Write dated run JSON
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_file = runs_dir / f"{run_id}.json"
    run_file.write_text(
        json.dumps(eval_report.to_dict(), indent=2), encoding="utf-8"
    )

    # Update dashboard
    _update_dashboard(dashboard_path, eval_report)

    if not quiet:
        _print_report(eval_report)

    return eval_report


def _print_report(report: EvalReport) -> None:
    d = report.to_dict()
    print(f"\n=== Brain Eval Suite: {report.run_id} ===")
    print(f"Pass: {report.passed}")
    for mode in report.modes_run:
        m = d.get(mode) or {}
        status = m.get("status", "not run")
        reason = f" ({m['reason']})" if m.get("reason") else ""
        print(f"  {mode}: {status}{reason}")
        if status == "ok" and mode == "quick_gate":
            for t, p1 in (m.get("by_type") or {}).items():
                print(f"    {t}: P@1={p1:.3f}")
        if status == "ok" and mode == "mcp_path":
            print(f"    P@1={m.get('precision_at_1')}  MRR={m.get('mrr')}  gap_vs_offline_rrf={m.get('gap_vs_offline_rrf')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="Run quick_gate")
    parser.add_argument("--kfold", action="store_true", help="Run kfold leave-one-out (~3 min)")
    parser.add_argument("--vault", action="store_true", help="Run gold_vault recall (requires API)")
    parser.add_argument("--mcp", action="store_true", help="Run MCP path eval (requires API)")
    parser.add_argument("--all", dest="all_modes", action="store_true", help="Run all 4 modes")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-query output")
    parser.add_argument("--dry-run", action="store_true", help="Load DB only, skip scoring")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--gold-semantic", type=Path, default=DEFAULT_GOLD_SEMANTIC)
    parser.add_argument("--gold-vault", type=Path, default=DEFAULT_GOLD_VAULT)
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    parser.add_argument("--dashboard", type=Path, default=DEFAULT_DASHBOARD)
    args = parser.parse_args(argv)

    if args.all_modes:
        modes: set[str] = {"quick_gate", "kfold", "gold_vault", "mcp_path"}
    else:
        modes = set()
        if args.quick:
            modes.add("quick_gate")
        if args.kfold:
            modes.add("kfold")
        if args.vault:
            modes.add("gold_vault")
        if args.mcp:
            modes.add("mcp_path")

    if not modes:
        modes = {"quick_gate", "mcp_path"}

    report = run_suite(
        modes=modes,
        db_path=args.db,
        gold_semantic_path=args.gold_semantic,
        gold_vault_path=args.gold_vault,
        runs_dir=args.runs_dir,
        dashboard_path=args.dashboard,
        quiet=args.quiet,
        dry_run=args.dry_run,
    )

    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
