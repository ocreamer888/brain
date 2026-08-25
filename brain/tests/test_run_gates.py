"""Smoke tests for Brain Forge Phase A gate runner."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
VENV_PY = REPO_ROOT / ".venv" / "bin" / "python"
RUN_GATES = REPO_ROOT / "brain" / "harness" / "run_gates.py"
INVARIANTS = REPO_ROOT / "brain" / "constitution" / "invariants.yaml"


def _python() -> str:
    return str(VENV_PY) if VENV_PY.is_file() else sys.executable


def test_invariants_registry_has_at_least_five():
    data = yaml.safe_load(INVARIANTS.read_text(encoding="utf-8"))
    active = [i for i in data["invariants"] if not i.get("superseded_by")]
    assert len(active) >= 5
    ids = {i["id"] for i in active}
    assert "INV-SESSION-01" in ids
    assert "INV-DEPLOY-01" in ids


def test_run_gates_smoke_exits_zero(tmp_path: Path):
    out = tmp_path / "gates.json"
    proc = subprocess.run(
        [
            _python(),
            str(RUN_GATES),
            "--phase",
            "smoke",
            "--skip-quality-gate",
            "--emit-json",
            str(out),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    summary = json.loads(out.read_text(encoding="utf-8"))
    assert summary["exit_code"] == 0
    assert summary["pytest"]["exit_code"] == 0
    assert len(summary["invariants"]) >= 5
