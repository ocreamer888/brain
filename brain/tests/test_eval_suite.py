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
