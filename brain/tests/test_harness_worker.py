"""Faux / integration tests for Brain Forge C2 worker + supervisor."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
VENV_PY = REPO_ROOT / ".venv" / "bin" / "python"
WORKER = REPO_ROOT / "brain" / "harness" / "worker.py"
SUPERVISOR = REPO_ROOT / "brain" / "harness" / "supervisor.py"
SCHEMA = REPO_ROOT / "brain" / "harness" / "job_spec.schema.json"
EXAMPLE = REPO_ROOT / "brain" / "harness" / "examples" / "job-phase-c-canary-1k.json"


def _python() -> str:
    return str(VENV_PY) if VENV_PY.is_file() else sys.executable


BACKFILL_EXAMPLE = (
    REPO_ROOT / "brain" / "harness" / "examples" / "job-entity-backfill-canary-25.json"
)


def test_example_job_matches_schema():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    spec = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    jsonschema.validate(instance=spec, schema=schema)


def test_backfill_canary_job_matches_schema():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    spec = json.loads(BACKFILL_EXAMPLE.read_text(encoding="utf-8"))
    jsonschema.validate(instance=spec, schema=schema)
    assert spec["irreversible"] is True
    assert spec["canary_required"] is True


def test_worker_rejects_irreversible_without_canary(tmp_path: Path):
    job = {
        "job_id": "bad-irreversible",
        "intent": "should fail validation",
        "irreversible": True,
        "canary_required": False,
        "steps": [{"type": "command", "argv": ["true"]}],
    }
    path = tmp_path / "job.json"
    path.write_text(json.dumps(job), encoding="utf-8")
    proc = subprocess.run(
        [_python(), str(WORKER), "--job", str(path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 2
    assert "canary_required" in (proc.stderr + proc.stdout)


def test_worker_faux_job_emits_mid_and_end_gates(tmp_path: Path):
    job_id = "faux-worker-unit"
    job = {
        "job_id": job_id,
        "intent": "unit faux job",
        "gates": [f"{_python()} -c \"raise SystemExit(0)\""],
        "steps": [
            {
                "type": "command",
                "argv": [_python(), "-c", "print('a')"],
            },
            {
                "type": "command",
                "argv": [_python(), "-c", "print('b')"],
            },
        ],
        "canary_required": False,
        "irreversible": False,
        "run_end_gate": True,
        "autonomous": {"max_wall_ms": 60000, "gate_retries": 0},
    }
    job_path = tmp_path / "job.json"
    transcript = tmp_path / f"{job_id}.jsonl"
    job_path.write_text(json.dumps(job), encoding="utf-8")
    proc = subprocess.run(
        [
            _python(),
            str(WORKER),
            "--job",
            str(job_path),
            "--transcript",
            str(transcript),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    events = [
        json.loads(line)
        for line in transcript.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    types = [e["type"] for e in events]
    assert types[0] == "job_start"
    assert "gate_start" in types and "gate_end" in types
    phases = [e.get("phase") for e in events if e["type"] == "gate_start"]
    assert "mid" in phases
    assert "end" in phases
    assert events[-1]["type"] == "job_end"
    assert events[-1]["status"] == "success"


def test_supervisor_start_status_stop_foreground_style(tmp_path: Path):
    """Background start + status; stop if still alive (short faux job usually finishes)."""
    job_id = f"sup-faux-{int(time.time())}"
    job = {
        "job_id": job_id,
        "intent": "supervisor smoke",
        "gates": [f"{_python()} -c \"raise SystemExit(0)\""],
        "steps": [
            {"type": "command", "argv": [_python(), "-c", "import time; time.sleep(0.4)"]},
            {"type": "command", "argv": [_python(), "-c", "print('done')"]},
        ],
        "canary_required": False,
        "run_end_gate": True,
        "autonomous": {"max_wall_ms": 30000, "gate_retries": 0},
    }
    # Write job under eval/runs so default transcript paths align — use tmp job file
    # but job_id controls runs dir artifacts.
    job_path = tmp_path / "job.json"
    job_path.write_text(json.dumps(job), encoding="utf-8")
    start = subprocess.run(
        [_python(), str(SUPERVISOR), "start", str(job_path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert start.returncode == 0, start.stdout + start.stderr
    status = subprocess.run(
        [_python(), str(SUPERVISOR), "status", job_id],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert status.returncode == 0
    # Wait for completion
    deadline = time.time() + 15
    state_path = REPO_ROOT / "brain" / "eval" / "runs" / f"{job_id}.state.json"
    while time.time() < deadline:
        if state_path.is_file():
            st = json.loads(state_path.read_text(encoding="utf-8"))
            if st.get("status") != "running":
                break
        time.sleep(0.1)
    assert state_path.is_file()
    st = json.loads(state_path.read_text(encoding="utf-8"))
    assert st.get("status") == "success"
    transcript = REPO_ROOT / "brain" / "eval" / "runs" / f"{job_id}.jsonl"
    assert transcript.is_file()


def test_worker_crash_then_recover(tmp_path: Path):
    job_id = f"crash-recover-{int(time.time())}"
    partial = tmp_path / "partial.txt"
    done = tmp_path / "done.txt"
    job = {
        "job_id": job_id,
        "intent": "crash drill",
        "gates": [f"{_python()} -c \"raise SystemExit(0)\""],
        "steps": [
            {
                "type": "command",
                "argv": [
                    _python(),
                    "-c",
                    f"open({str(partial)!r},'w').write('a')",
                ],
            },
            {
                "type": "command",
                "argv": [_python(), "-c", "import time; time.sleep(8)"],
            },
            {
                "type": "command",
                "argv": [
                    _python(),
                    "-c",
                    f"open({str(done)!r},'w').write('ok')",
                ],
            },
        ],
        "canary_required": False,
        "run_end_gate": True,
        "autonomous": {"max_wall_ms": 60000, "gate_retries": 0},
    }
    job_path = tmp_path / "job.json"
    job_path.write_text(json.dumps(job), encoding="utf-8")
    start = subprocess.run(
        [_python(), str(SUPERVISOR), "start", str(job_path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert start.returncode == 0, start.stdout + start.stderr
    state_path = REPO_ROOT / "brain" / "eval" / "runs" / f"{job_id}.state.json"
    deadline = time.time() + 12
    while time.time() < deadline:
        if partial.is_file() and state_path.is_file():
            st = json.loads(state_path.read_text(encoding="utf-8"))
            if int(st.get("next_step") or 0) >= 1 and st.get("status") == "running":
                break
        time.sleep(0.05)
    assert partial.is_file(), "step 0 must finish before crash"
    assert not done.is_file()
    stop = subprocess.run(
        [_python(), str(SUPERVISOR), "stop", job_id],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert stop.returncode == 0, stop.stdout + stop.stderr
    rec = subprocess.run(
        [_python(), str(SUPERVISOR), "reconcile"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert rec.returncode == 0
    st = json.loads(state_path.read_text(encoding="utf-8"))
    assert st.get("status") in {"crashed", "failed"}
    assert int(st.get("next_step") or 0) >= 1
    rec2 = subprocess.run(
        [_python(), str(SUPERVISOR), "recover", job_id],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert rec2.returncode == 0, rec2.stdout + rec2.stderr
    deadline = time.time() + 40
    while time.time() < deadline:
        st = json.loads(state_path.read_text(encoding="utf-8"))
        if st.get("status") in {"success", "failed", "budget"}:
            break
        time.sleep(0.2)
    st = json.loads(state_path.read_text(encoding="utf-8"))
    assert st.get("status") == "success", st
    assert done.is_file()


def test_daemon_once_processes_inbox(tmp_path: Path):
    jobs_root = tmp_path / "jobs"
    inbox = jobs_root / "inbox"
    done = jobs_root / "done"
    inbox.mkdir(parents=True)
    job_id = f"daemon-once-{int(time.time())}"
    job = {
        "job_id": job_id,
        "intent": "daemon once",
        "gates": [f"{_python()} -c \"raise SystemExit(0)\""],
        "steps": [{"type": "command", "argv": [_python(), "-c", "print('daemon-ok')"]}],
        "canary_required": False,
        "run_end_gate": True,
        "autonomous": {"max_wall_ms": 30000, "gate_retries": 0},
    }
    (inbox / f"{job_id}.json").write_text(json.dumps(job), encoding="utf-8")
    env = os.environ.copy()
    env["BRAIN_FORGE_JOBS_ROOT"] = str(jobs_root)
    proc = subprocess.run(
        [_python(), str(SUPERVISOR), "daemon", "--once"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (done / f"{job_id}.json").is_file()
    state_path = REPO_ROOT / "brain" / "eval" / "runs" / f"{job_id}.state.json"
    st = json.loads(state_path.read_text(encoding="utf-8"))
    assert st.get("status") == "success"
