from __future__ import annotations

import subprocess
import sys
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "brain" / "tools" / "backfill_orchestrator.py"


def run_orchestrator(args: list[str], cwd: Path):
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def write_state(path: Path, preview_ready: bool, batch_id: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "version": 1,
        "preview": {"ready": preview_ready, "batch_id": batch_id, "inputs": []},
        "run": {"status": "idle", "started_at": None, "ended_at": None, "last_error": None},
        "stages": {},
    }
    path.write_text(json.dumps(state), encoding="utf-8")


def test_orchestrator_refuses_when_lock_exists(tmp_path):
    state = tmp_path / "state.json"
    write_state(state, preview_ready=True, batch_id="b1")
    lock = tmp_path / "backfill.lock"
    lock.write_text("busy", encoding="utf-8")
    rc, _out, err = run_orchestrator(
        ["--state", str(state), "--lock", str(lock), "--dry-run"],
        cwd=tmp_path,
    )
    assert rc == 2
    assert "lock already exists" in err.lower()


def test_no_run_when_preview_not_ready(tmp_path):
    state = tmp_path / "state.json"
    write_state(state, preview_ready=False)
    rc, out, _err = run_orchestrator(["--state", str(state)], cwd=REPO_ROOT)
    assert rc == 0
    assert "preview not ready" in out.lower()


def test_mark_preview_ready_updates_state(tmp_path):
    state = tmp_path / "state.json"
    rc, _out, _err = run_orchestrator(
        [
            "mark-preview-ready",
            "--state",
            str(state),
            "--batch-id",
            "batch-42",
            "--input",
            "a.json",
            "--input",
            "b.json",
        ],
        cwd=REPO_ROOT,
    )
    assert rc == 0
    data = json.loads(state.read_text(encoding="utf-8"))
    assert data["preview"]["ready"] is True
    assert data["preview"]["batch_id"] == "batch-42"
    assert data["preview"]["inputs"] == ["a.json", "b.json"]
