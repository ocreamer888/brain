# Brain Eval Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One command (`eval_suite.py`) that runs all eval modes, measures the MCP search path gap, updates the brain viewer dashboard, and auto-runs after each ingest session.

**Architecture:** New `mcp_eval.py` module tests the real API search path via `api_client.search()`. New `eval_suite.py` orchestrates all 4 modes (quick_gate, kfold, gold_vault, mcp_path) by importing existing tools as Python modules. Results write to `brain/eval/runs/` and to `brain/rust/static/eval_dashboard.json` for the new brain viewer Eval tab.

**Tech Stack:** Python 3.13, sqlite3, numpy, existing `api_client.py`, existing `ingest_quality_gate.py` / `retrieval_eval_kfold.py` / `retrieval_eval.py`, vanilla JS (no new deps)

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Create | `brain/tools/mcp_eval.py` | MCP path eval: query via `api_client.search()`, score P@1/MRR vs `gold_semantic.jsonl` |
| Create | `brain/tools/eval_suite.py` | Unified orchestrator: runs modes, aggregates `EvalReport`, writes JSON + dashboard |
| Create | `brain/tests/test_mcp_eval.py` | TDD tests for mcp_eval (4 tests) |
| Create | `brain/tests/test_eval_suite.py` | TDD tests for eval_suite (4 tests) |
| Modify | `brain/rust/static/index.html` | Add Eval tab button + panel + CSS |
| Modify | `brain/rust/static/app.js` | Add Eval tab JS (fetch dashboard JSON, render table) |
| Modify | `brain/hooks/session_end.py` | Add background eval auto-run (opt-in via `BRAIN_EVAL_AUTO=1`) |

---

## Task 1: TDD tests for mcp_eval.py

**Files:**
- Create: `brain/tests/test_mcp_eval.py`

- [ ] **Step 1: Write 4 failing tests**

```python
# brain/tests/test_mcp_eval.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from brain.api_client import BrainApiError


def _gold_file(tmp_path: Path, entries: list[dict]) -> Path:
    p = tmp_path / "gold.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    return p


def test_p1_calculation(tmp_path: Path) -> None:
    """P@1 = 0.5 when gold is first result for q1 but second for q2."""
    from brain.tools.mcp_eval import run_mcp_eval

    gold = _gold_file(tmp_path, [
        {"query": "q1", "gold_memory_id": "aaa", "k": 3},
        {"query": "q2", "gold_memory_id": "bbb", "k": 3},
    ])

    def search_fn(query: str, k: int) -> list[dict]:
        if query == "q1":
            return [{"id": "aaa"}, {"id": "xxx"}]
        return [{"id": "xxx"}, {"id": "bbb"}]

    result = run_mcp_eval(gold, search_fn=search_fn)
    assert result["status"] == "ok"
    assert result["n_queries"] == 2
    assert result["precision_at_1"] == pytest.approx(0.5)
    assert result["mrr"] == pytest.approx((1.0 + 0.5) / 2)


def test_gold_id_in_top1(tmp_path: Path) -> None:
    """P@1 = 1.0 when gold_memory_id is the first result."""
    from brain.tools.mcp_eval import run_mcp_eval

    gold = _gold_file(tmp_path, [
        {"query": "q1", "gold_memory_id": "target-id", "k": 5},
    ])

    def search_fn(query: str, k: int) -> list[dict]:
        return [{"id": "target-id"}, {"id": "other"}]

    result = run_mcp_eval(gold, search_fn=search_fn)
    assert result["status"] == "ok"
    assert result["precision_at_1"] == 1.0


def test_api_unavailable(tmp_path: Path) -> None:
    """Returns status='skipped' when BrainApiError is raised."""
    from brain.tools.mcp_eval import run_mcp_eval

    gold = _gold_file(tmp_path, [
        {"query": "q1", "gold_memory_id": "aaa", "k": 5},
    ])

    def search_fn(query: str, k: int) -> list[dict]:
        raise BrainApiError("API unavailable: Connection refused")

    result = run_mcp_eval(gold, search_fn=search_fn)
    assert result["status"] == "skipped"
    assert "not reachable" in result["reason"]


def test_gap_calculation(tmp_path: Path) -> None:
    """gap_vs_kfold_p1 = mcp_p1 - baseline."""
    from brain.tools.mcp_eval import run_mcp_eval

    gold = _gold_file(tmp_path, [
        {"query": "q1", "gold_memory_id": "aaa", "k": 3},
        {"query": "q2", "gold_memory_id": "bbb", "k": 3},
    ])

    # q1: gold at rank 1 (hit). q2: gold at rank 2 (miss for P@1).
    def search_fn(query: str, k: int) -> list[dict]:
        return [{"id": "aaa"}, {"id": "bbb"}]

    # P@1 = 0.5 (only q1 has gold at rank 1)
    result = run_mcp_eval(gold, baseline_kfold_p1=0.7, search_fn=search_fn)
    assert result["status"] == "ok"
    assert result["gap_vs_kfold_p1"] == pytest.approx(0.5 - 0.7)
```

- [ ] **Step 2: Run to verify all 4 fail**

```bash
cd /Users/macm1air/Documents/AI
.venv/bin/python -m pytest brain/tests/test_mcp_eval.py -v 2>&1 | tail -20
```

Expected: 4 × `FAILED` with `ModuleNotFoundError: No module named 'brain.tools.mcp_eval'`

---

## Task 2: Implement mcp_eval.py

**Files:**
- Create: `brain/tools/mcp_eval.py`

- [ ] **Step 1: Write the implementation**

```python
#!/usr/bin/env python3
"""MCP path eval — queries via api_client.search() and scores against gold_semantic.jsonl.

Each gold entry: {"query": "...", "gold_memory_id": "uuid", "k": 10, "description": "..."}
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable


def load_gold(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            entries.append(json.loads(line))
    return entries


def run_mcp_eval(
    gold_path: Path,
    n: int = 10,
    baseline_kfold_p1: float | None = None,
    search_fn: Callable[[str, int], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Evaluate retrieval via the MCP/API search path.

    Returns a dict with keys: status, n_queries, precision_at_1, mrr, gap_vs_kfold_p1.
    status is 'ok', 'skipped', or 'error'.
    """
    from brain.api_client import BrainApiError

    if search_fn is None:
        from brain.api_client import search as api_search

        def search_fn(query: str, k: int) -> list[dict[str, Any]]:
            return api_search(query=query, n=k)

    try:
        gold = load_gold(gold_path)
    except (OSError, ValueError) as e:
        return {"status": "error", "reason": str(e)}

    if not gold:
        return {"status": "error", "reason": "gold file is empty"}

    hits_at_1 = 0
    mrr_sum = 0.0
    n_valid = 0

    for entry in gold:
        query = str(entry["query"])
        gold_id = str(entry["gold_memory_id"])
        k = int(entry.get("k", n))

        try:
            results = search_fn(query, k)
        except BrainApiError:
            return {"status": "skipped", "reason": "brain API not reachable"}
        except Exception as e:
            return {"status": "error", "reason": str(e)}

        n_valid += 1
        ids = [str(r.get("id", "")) for r in results]

        if ids and ids[0] == gold_id:
            hits_at_1 += 1

        for rank, rid in enumerate(ids, 1):
            if rid == gold_id:
                mrr_sum += 1.0 / rank
                break

    if n_valid == 0:
        return {"status": "skipped", "reason": "no queries completed"}

    p1 = hits_at_1 / n_valid
    mrr = mrr_sum / n_valid

    result: dict[str, Any] = {
        "status": "ok",
        "n_queries": n_valid,
        "precision_at_1": round(p1, 4),
        "mrr": round(mrr, 4),
        "gap_vs_kfold_p1": None,
    }

    if baseline_kfold_p1 is not None:
        result["gap_vs_kfold_p1"] = round(p1 - baseline_kfold_p1, 4)

    return result
```

- [ ] **Step 2: Run tests and verify all 4 pass**

```bash
cd /Users/macm1air/Documents/AI
.venv/bin/python -m pytest brain/tests/test_mcp_eval.py -v
```

Expected: `4 passed`

- [ ] **Step 3: Commit**

```bash
git add brain/tools/mcp_eval.py brain/tests/test_mcp_eval.py
git commit -m "feat(eval): add mcp_eval — P@1/MRR via actual API search path"
```

---

## Task 3: TDD tests for eval_suite.py

**Files:**
- Create: `brain/tests/test_eval_suite.py`

- [ ] **Step 1: Write 4 failing tests**

```python
# brain/tests/test_eval_suite.py
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


_GOLD_SEMANTIC = Path(__file__).resolve().parents[1] / "eval" / "gold_semantic.jsonl"


def test_report_structure() -> None:
    """EvalReport.to_dict() serializes with correct keys and 'pass' (not 'passed')."""
    from brain.tools.eval_suite import EvalReport, ModeResult

    report = EvalReport(
        run_id="2026-05-23-1430",
        modes_run=["quick_gate"],
        passed=True,
        quick_gate=ModeResult(
            status="ok",
            data={"exit_code": 0, "by_type": {'"conversation"': 0.7}},
        ),
    )
    d = report.to_dict()
    assert d["run_id"] == "2026-05-23-1430"
    assert d["pass"] is True
    assert d["modes_run"] == ["quick_gate"]
    assert d["kfold"] is None
    assert d["mcp_path"] is None
    assert d["quick_gate"]["status"] == "ok"
    assert d["quick_gate"]["exit_code"] == 0


def test_mode_isolation_dashboard_still_written(tmp_path: Path) -> None:
    """A mode crash does not abort the suite or skip the dashboard write."""
    from brain.tools.eval_suite import run_suite

    dash = tmp_path / "eval_dashboard.json"
    result = run_suite(
        modes={"quick_gate"},
        db_path=tmp_path / "nonexistent.db",  # causes error inside quick_gate
        gold_semantic_path=_GOLD_SEMANTIC,
        gold_vault_path=tmp_path / "nope.jsonl",
        runs_dir=tmp_path / "runs",
        dashboard_path=dash,
    )
    assert result.quick_gate is not None
    assert result.quick_gate.status == "error"
    assert dash.exists()


def test_dashboard_append_newest_first(tmp_path: Path) -> None:
    """Calling _update_dashboard twice keeps runs newest-first."""
    from brain.tools.eval_suite import EvalReport, _update_dashboard

    dash = tmp_path / "eval_dashboard.json"
    r1 = EvalReport(run_id="2026-05-22-1000", modes_run=[], passed=True)
    r2 = EvalReport(run_id="2026-05-23-1430", modes_run=[], passed=False)

    _update_dashboard(dash, r1)
    _update_dashboard(dash, r2)

    data = json.loads(dash.read_text(encoding="utf-8"))
    assert data["runs"][0]["run_id"] == "2026-05-23-1430"
    assert len(data["runs"]) == 2


def test_pass_false_when_quick_gate_exit_code_2(tmp_path: Path) -> None:
    """run_suite sets passed=False when quick_gate returns exit_code 2 (ERROR threshold)."""
    from brain.tools.eval_suite import run_suite

    dash = tmp_path / "eval_dashboard.json"
    with patch("brain.tools.ingest_quality_gate.run_gate") as mock_gate:
        mock_gate.return_value = ({'"conversation"': 0.2}, 2)
        result = run_suite(
            modes={"quick_gate"},
            db_path=tmp_path / "fake.db",
            gold_semantic_path=_GOLD_SEMANTIC,
            gold_vault_path=tmp_path / "nope.jsonl",
            runs_dir=tmp_path / "runs",
            dashboard_path=dash,
        )

    assert result.passed is False
    assert result.quick_gate is not None
    assert result.quick_gate.status == "ok"
    assert result.quick_gate.data["exit_code"] == 2
```

- [ ] **Step 2: Run to verify all 4 fail**

```bash
cd /Users/macm1air/Documents/AI
.venv/bin/python -m pytest brain/tests/test_eval_suite.py -v 2>&1 | tail -20
```

Expected: 4 × `FAILED` with `ModuleNotFoundError: No module named 'brain.tools.eval_suite'`

---

## Task 4: Implement eval_suite.py

**Files:**
- Create: `brain/tools/eval_suite.py`

- [ ] **Step 1: Write the implementation**

```python
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
LAST_KFOLD_REPORT = _REPO_ROOT / "brain" / "eval" / "kfold_report.json"


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
            # "fact" is not in TARGET_TYPES, but guard anyway
            non_fact_vals = [v for k, v in by_type.items() if "fact" not in k]
            if vals:
                row["quick_p1_avg"] = round(sum(vals) / len(vals), 4)
            if non_fact_vals:
                row["non_fact_p1"] = round(sum(non_fact_vals) / len(non_fact_vals), 4)
        if self.mcp_path and self.mcp_path.status == "ok":
            row["mcp_p1"] = self.mcp_path.data.get("precision_at_1")
            row["mcp_gap"] = self.mcp_path.data.get("gap_vs_kfold_p1")
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
    # Remove any existing row with same run_id (idempotent)
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

    # Load kfold baseline for MCP gap (from last saved kfold report)
    baseline_kfold_p1: float | None = None
    if LAST_KFOLD_REPORT.exists():
        try:
            d = json.loads(LAST_KFOLD_REPORT.read_text(encoding="utf-8"))
            baseline_kfold_p1 = d.get("overall", {}).get("precision@1")
        except Exception:
            pass

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
                # Use fresh kfold result as baseline for MCP gap
                baseline_kfold_p1 = report.get("overall", {}).get("precision@1")
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
                from brain.tools.mcp_eval import run_mcp_eval

                mcp_result = run_mcp_eval(
                    gold_semantic_path,
                    baseline_kfold_p1=baseline_kfold_p1,
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
            print(f"    P@1={m.get('precision_at_1')}  MRR={m.get('mrr')}  gap={m.get('gap_vs_kfold_p1')}")


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
        # Default when called with no flags
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
```

- [ ] **Step 2: Run all 8 tests and verify they pass**

```bash
cd /Users/macm1air/Documents/AI
.venv/bin/python -m pytest brain/tests/test_mcp_eval.py brain/tests/test_eval_suite.py -v
```

Expected: `8 passed`

- [ ] **Step 3: Run the smoke test**

```bash
cd /Users/macm1air/Documents/AI
.venv/bin/python brain/tools/eval_suite.py --quick --dry-run
```

Expected: exits 0, prints `=== Brain Eval Suite: ...`, `quick_gate: skipped (dry-run)`

- [ ] **Step 4: Commit**

```bash
git add brain/tools/eval_suite.py brain/tests/test_eval_suite.py
git commit -m "feat(eval): add eval_suite — unified orchestrator with EvalReport and dashboard output"
```

---

## Task 5: Add Eval tab to brain viewer

**Files:**
- Modify: `brain/rust/static/index.html`
- Modify: `brain/rust/static/app.js`

- [ ] **Step 1: Add CSS + tab + panel to index.html**

In `index.html`, add 3 CSS rules inside the `<style>` block after the last rule:

```css
    .eval-table { width: 100%; border-collapse: collapse; font-size: 0.85rem; margin-top: 1rem; }
    .eval-table th, .eval-table td { padding: 0.4rem 0.6rem; border-bottom: 1px solid #222; text-align: left; }
    .eval-table th { color: #888; font-weight: normal; }
    .eval-pass { color: #9f9; }
    .eval-fail { color: #f99; }
    .eval-row { color: #aaa; font-size: 0.85rem; margin: 0.3rem 0; }
```

Add the tab button after the `<button class="tab" data-tab="facts">Facts</button>` line:

```html
    <button class="tab" data-tab="eval">Eval</button>
```

Add the panel div after the closing `</div>` of the facts panel:

```html
  <div id="eval" class="panel">
    <div id="eval-content"><div class="status">Loading…</div></div>
  </div>
```

- [ ] **Step 2: Add Eval tab JS to app.js**

Append to the end of `brain/rust/static/app.js`:

```javascript
// --- Eval tab ---
const evalContent = document.getElementById("eval-content");

async function loadEvalDashboard() {
  try {
    const r = await fetch("/eval_dashboard.json");
    if (!r.ok) {
      evalContent.innerHTML = '<div class="status">No eval history yet. Run: python3 brain/tools/eval_suite.py</div>';
      return;
    }
    const data = await r.json();
    renderEvalDashboard(data.runs || []);
  } catch (e) {
    evalContent.innerHTML = `<div class="status">Failed to load dashboard: ${escapeHtml(e.message)}</div>`;
  }
}

function renderEvalDashboard(runs) {
  if (!runs.length) {
    evalContent.innerHTML = '<div class="status">No runs yet.</div>';
    return;
  }

  const passLabel = (p) =>
    p ? '<span class="eval-pass">PASS</span>' : '<span class="eval-fail">FAIL</span>';

  const pct = (v) => (v != null ? `${(v * 100).toFixed(1)}%` : "—");

  const gap = (v) => {
    if (v == null) return "—";
    const cls = v <= -0.05 ? "eval-fail" : "eval-pass";
    const sign = v >= 0 ? "+" : "";
    return `<span class="${cls}">${sign}${(v * 100).toFixed(1)}pp</span>`;
  };

  const latest = runs[0];
  let html = `<h3 style="margin-top:1rem">Latest: ${latest.run_id} — ${passLabel(latest.pass)}</h3>`;
  html += `<div class="eval-row">`;
  html += `non-fact P@1: <strong>${pct(latest.non_fact_p1)}</strong> &nbsp; `;
  html += `MCP P@1: <strong>${pct(latest.mcp_p1)}</strong> &nbsp; `;
  html += `MCP gap: ${gap(latest.mcp_gap)}`;
  html += `</div>`;

  html += `<table class="eval-table"><thead><tr>
    <th>Run ID</th><th>Pass</th><th>P@1 avg</th><th>non-fact P@1</th><th>MCP P@1</th><th>MCP gap</th>
  </tr></thead><tbody>`;

  for (const r of runs) {
    html += `<tr>
      <td>${r.run_id}</td>
      <td>${passLabel(r.pass)}</td>
      <td>${pct(r.quick_p1_avg)}</td>
      <td>${pct(r.non_fact_p1)}</td>
      <td>${pct(r.mcp_p1)}</td>
      <td>${gap(r.mcp_gap)}</td>
    </tr>`;
  }
  html += "</tbody></table>";
  evalContent.innerHTML = html;
}

document.querySelector('[data-tab="eval"]').addEventListener("click", () => {
  loadEvalDashboard();
});
```

- [ ] **Step 3: Commit**

```bash
git add brain/rust/static/index.html brain/rust/static/app.js
git commit -m "feat(viewer): add Eval tab — renders eval_dashboard.json trend table"
```

---

## Task 6: Wire stop hook for auto eval

**Files:**
- Modify: `brain/hooks/session_end.py`

- [ ] **Step 1: Add eval auto-run block**

In `brain/hooks/session_end.py`, add the following block immediately after the reflection scheduling block (after the `except Exception as e: print(f"[BRAIN] Reflection schedule failed...")` line, before `# Save session summary`):

```python
    # Eval quick check — opt-in via BRAIN_EVAL_AUTO=1
    eval_flag = os.environ.get("BRAIN_EVAL_AUTO", "0").strip().lower()
    if eval_flag in ("1", "true", "yes", "on"):
        repo_root = Path(__file__).resolve().parents[2]
        eval_script = repo_root / "brain" / "tools" / "eval_suite.py"
        eval_log = Path(__file__).resolve().parent / "eval_auto.log"
        try:
            with open(eval_log, "a", encoding="utf-8") as logf:
                subprocess.Popen(
                    [sys.executable, str(eval_script), "--quick", "--mcp", "--quiet"],
                    cwd=str(repo_root),
                    stdin=subprocess.DEVNULL,
                    stdout=logf,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            print("[BRAIN] Eval quick check scheduled in background.", file=sys.stderr)
        except Exception as e:
            print(f"[BRAIN] Eval auto-run schedule failed (non-fatal): {e}", file=sys.stderr)
```

- [ ] **Step 2: Verify session_end.py syntax**

```bash
cd /Users/macm1air/Documents/AI
.venv/bin/python -c "import brain.hooks.session_end" 2>&1
```

Expected: no output (clean import)

- [ ] **Step 3: Commit**

```bash
git add brain/hooks/session_end.py
git commit -m "feat(hooks): add BRAIN_EVAL_AUTO=1 — runs eval_suite --quick --mcp in background after session"
```

---

## Task 7: Integration smoke test + final verification

- [ ] **Step 1: Run the full test suite for eval**

```bash
cd /Users/macm1air/Documents/AI
.venv/bin/python -m pytest brain/tests/test_mcp_eval.py brain/tests/test_eval_suite.py brain/tests/test_retrieval_eval_smoke.py -v
```

Expected: all tests pass (8 new + existing smoke tests)

- [ ] **Step 2: Run eval_suite --quick --dry-run (smoke test)**

```bash
cd /Users/macm1air/Documents/AI
.venv/bin/python brain/tools/eval_suite.py --quick --dry-run
```

Expected output:
```
=== Brain Eval Suite: 2026-05-23-HHMM ===
Pass: True
  quick_gate: skipped (dry-run)
```
And `brain/eval/runs/2026-05-23-HHMM.json` exists.

- [ ] **Step 3: Verify help text**

```bash
cd /Users/macm1air/Documents/AI
.venv/bin/python brain/tools/eval_suite.py --help
```

Expected: shows `--quick`, `--kfold`, `--vault`, `--mcp`, `--all`, `--quiet`, `--dry-run` flags.

- [ ] **Step 4: Confirm eval_dashboard.json was created**

```bash
ls -la /Users/macm1air/Documents/AI/brain/rust/static/eval_dashboard.json && \
python3 -c "import json; d=json.load(open('brain/rust/static/eval_dashboard.json')); print(d['runs'][0])"
```

Expected: prints the dashboard row from the dry-run.

- [ ] **Step 5: Final commit (if any files staged)**

```bash
git status
# If clean: done. If stray changes: git add + commit.
```

---

## Enabling Auto Eval After Sessions

To activate post-session eval, add `BRAIN_EVAL_AUTO=1` to `~/.zshrc`:

```bash
echo 'export BRAIN_EVAL_AUTO=1' >> ~/.zshrc
```

Then reload: `source ~/.zshrc`

The next time a session ends, `eval_suite.py --quick --mcp --quiet` runs in the background. Results appear in the brain viewer Eval tab.

---

## Success Criteria Checklist

- [ ] `python3 brain/tools/eval_suite.py --all` produces one combined JSON report
- [ ] Brain viewer Eval tab shows P@1 trend table
- [ ] MCP gap column is visible and populated after first real run
- [ ] `BRAIN_EVAL_AUTO=1` triggers eval in background at session end
- [ ] All 8 new tests pass
- [ ] No regressions in existing eval smoke tests
