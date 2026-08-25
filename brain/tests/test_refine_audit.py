"""Phase D refine audit — constitution block + append-only log."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VENV_PY = REPO_ROOT / ".venv" / "bin" / "python"
AUDIT = REPO_ROOT / "brain" / "harness" / "refine_audit.py"


def _python() -> str:
    return str(VENV_PY) if VENV_PY.is_file() else sys.executable


def test_constitution_path_blocked():
    proc = subprocess.run(
        [
            _python(),
            str(AUDIT),
            "check-path",
            "brain/constitution/invariants.yaml",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 2
    data = json.loads(proc.stdout)
    assert data["forbidden"] is True


def test_classify_blocks_lower_threshold_summary():
    proc = subprocess.run(
        [
            _python(),
            str(AUDIT),
            "classify",
            "--target",
            "pattern",
            "--edit-summary",
            "lower threshold on quality gate to ship faster",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 2
    data = json.loads(proc.stdout)
    assert data["allowed"] is False
    assert data["classification"] == "constitution"


def test_tactic_append_and_force_blocked(tmp_path: Path):
    audit_path = tmp_path / "refine_audit.jsonl"
    ok = subprocess.run(
        [
            _python(),
            str(AUDIT),
            "append",
            "--trigger",
            "unit test tactic",
            "--target",
            "pattern",
            "--edit-summary",
            "Always run deploy parity before hook edits",
            "--brain-memory-id",
            "test-mem-id",
            "--outcome",
            "recorded",
            "--audit-path",
            str(audit_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert ok.returncode == 0, ok.stdout + ok.stderr

    blocked = subprocess.run(
        [
            _python(),
            str(AUDIT),
            "append",
            "--trigger",
            "unit test block",
            "--target",
            "constitution",
            "--edit-summary",
            "remove invariant INV-HOOK-01",
            "--force-blocked",
            "--outcome",
            "blocked",
            "--audit-path",
            str(audit_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    # force-blocked still exits 2 (not allowed) but appends
    assert blocked.returncode == 2
    lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    recs = [json.loads(x) for x in lines]
    assert recs[0]["allowed"] is True
    assert recs[1]["allowed"] is False
    assert recs[1]["classification"] == "constitution"


def test_check_staged_blocks_constitution_paths():
    proc = subprocess.run(
        [
            _python(),
            str(AUDIT),
            "check-staged",
            "--paths",
            "brain/constitution/invariants.yaml",
            "README.md",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 2
    data = json.loads(proc.stdout)
    assert any("invariants.yaml" in p for p in data["blocked"])


def test_check_staged_allows_normal_paths():
    proc = subprocess.run(
        [
            _python(),
            str(AUDIT),
            "check-staged",
            "--paths",
            "brain/harness/canary_sample.py",
            "docs/TOOLS.md",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["blocked"] == []
