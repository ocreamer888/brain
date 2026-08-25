"""Tests for Phase B teeth + canary helpers."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VENV_PY = REPO_ROOT / ".venv" / "bin" / "python"
TEETH = REPO_ROOT / "brain" / "harness" / "teeth_check.py"
CANARY = REPO_ROOT / "brain" / "harness" / "canary_sample.py"

from brain.harness.teeth_probes import PROBES


def _python() -> str:
    return str(VENV_PY) if VENV_PY.is_file() else sys.executable


@pytest.mark.parametrize("inv_id", sorted(PROBES))
def test_teeth_auto_probe_registered(inv_id: str, tmp_path: Path):
    from brain.harness.teeth_probes import probe_path

    target = probe_path(PROBES[inv_id])
    original = target.read_text(encoding="utf-8")
    out = tmp_path / f"teeth-{inv_id}.json"
    try:
        proc = subprocess.run(
            [
                _python(),
                str(TEETH),
                "--invariant",
                inv_id,
                "--auto-probe",
                "--emit-json",
                str(out),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        evidence = json.loads(out.read_text(encoding="utf-8"))
        assert evidence["passed"] is True
        steps = {s["step"]: s["ok"] for s in evidence["steps"]}
        assert steps["baseline"] is True
        assert steps["broken_must_fail"] is True
        assert steps["restored"] is True
    finally:
        assert target.read_text(encoding="utf-8") == original


def test_canary_sample_writes_artifacts(tmp_path: Path):
    out_dir = tmp_path / "canary"
    proc = subprocess.run(
        [
            _python(),
            str(CANARY),
            "--label",
            "phase-b-test",
            "--limit",
            "5",
            "--out-dir",
            str(out_dir),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode in (0, 1), proc.stdout + proc.stderr
    assert (out_dir / "sample.jsonl").is_file()
    assert (out_dir / "summary.md").is_file()
    assert (out_dir / "meta.json").is_file()
    meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["label"] == "phase-b-test"
