"""Brain Forge Phase C — minimal native job worker (C2).

Loads a job spec, runs canary/command/gate steps, appends JSONL events.
No LLM. Gates decide success. Detach via supervisor (background process).
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = Path(__file__).resolve().parent / "job_spec.schema.json"
RUNS_DIR = REPO_ROOT / "brain" / "eval" / "runs"
VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
CANARY = REPO_ROOT / "brain" / "harness" / "canary_sample.py"
DEFAULT_GATE = [
    str(VENV_PYTHON if VENV_PYTHON.is_file() else Path(sys.executable)),
    str(REPO_ROOT / "brain" / "harness" / "run_gates.py"),
    "--phase",
    "smoke",
    "--skip-quality-gate",
]


def _python() -> str:
    if VENV_PYTHON.is_file():
        return str(VENV_PYTHON)
    return sys.executable


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_job(spec: dict[str, Any]) -> None:
    jsonschema.validate(instance=spec, schema=load_schema())
    if spec.get("irreversible") and not spec.get("canary_required"):
        raise ValueError("irreversible jobs require canary_required=true")
    for i, step in enumerate(spec["steps"]):
        t = step["type"]
        if t == "command" and not step.get("argv"):
            raise ValueError(f"steps[{i}]: command requires argv")
        if t == "canary" and not step.get("label"):
            step["label"] = spec["job_id"]


class Transcript:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event: dict[str, Any]) -> None:
        payload = {"timestamp": utc_now(), **event}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, default=str) + "\n")
            fh.flush()


_CURRENT_CHILD: subprocess.Popen[str] | None = None


def run_argv(
    argv: list[str],
    *,
    cwd: Path,
    timeout_s: float | None,
    extra_env: dict[str, str] | None = None,
) -> tuple[int, str]:
    global _CURRENT_CHILD
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    proc = subprocess.Popen(
        argv,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    _CURRENT_CHILD = proc
    try:
        try:
            out, _ = proc.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
            return 124, out or ""
        return int(proc.returncode or 0), out or ""
    finally:
        _CURRENT_CHILD = None


def gate_argv_list(spec: dict[str, Any]) -> list[list[str]]:
    gates = spec.get("gates") or []
    if not gates:
        return [list(DEFAULT_GATE)]
    return [shlex.split(g) for g in gates]


def run_gates(
    spec: dict[str, Any],
    transcript: Transcript,
    *,
    phase_label: str,
    wall_deadline: float,
) -> int:
    retries = int((spec.get("autonomous") or {}).get("gate_retries", 1))
    last_code = 2
    for argv in gate_argv_list(spec):
        attempt = 0
        while True:
            if time.monotonic() > wall_deadline:
                transcript.emit(
                    {
                        "type": "job_end",
                        "status": "budget",
                        "reason": "max_wall_ms",
                    }
                )
                return 2
            transcript.emit(
                {
                    "type": "gate_start",
                    "phase": phase_label,
                    "attempt": attempt,
                    "argv": argv,
                }
            )
            t0 = time.perf_counter()
            remaining = max(1.0, wall_deadline - time.monotonic())
            code, out = run_argv(argv, cwd=REPO_ROOT, timeout_s=remaining)
            ms = int((time.perf_counter() - t0) * 1000)
            transcript.emit(
                {
                    "type": "gate_end",
                    "phase": phase_label,
                    "attempt": attempt,
                    "exit_code": code,
                    "duration_ms": ms,
                    "output_tail": out[-2000:] if out else "",
                }
            )
            last_code = code
            if code == 0:
                break
            if attempt >= retries:
                break
            attempt += 1
            transcript.emit(
                {
                    "type": "gate_retry",
                    "phase": phase_label,
                    "next_attempt": attempt,
                }
            )
        if last_code != 0:
            return last_code
    return last_code


def run_canary_step(
    step: dict[str, Any], transcript: Transcript, *, wall_deadline: float
) -> int:
    label = step.get("label") or "canary"
    limit = int(step.get("limit") or 100)
    out_dir = RUNS_DIR / f"canary-{label}"
    argv = [
        _python(),
        str(CANARY),
        "--label",
        label,
        "--limit",
        str(limit),
        "--out-dir",
        str(out_dir),
    ]
    if step.get("sql"):
        argv.extend(["--sql", step["sql"]])
    transcript.emit({"type": "canary_start", "label": label, "limit": limit})
    remaining = max(1.0, wall_deadline - time.monotonic())
    code, out = run_argv(argv, cwd=REPO_ROOT, timeout_s=remaining)
    transcript.emit(
        {
            "type": "canary_complete",
            "label": label,
            "exit_code": code,
            "sample_path": str(out_dir),
            "output_tail": out[-1000:] if out else "",
        }
    )
    return code


def run_command_step(
    step: dict[str, Any],
    transcript: Transcript,
    *,
    wall_deadline: float,
    extra_env: dict[str, str] | None = None,
) -> int:
    argv = list(step["argv"])
    cwd = Path(step["cwd"]) if step.get("cwd") else REPO_ROOT
    if not cwd.is_absolute():
        cwd = REPO_ROOT / cwd
    transcript.emit({"type": "command_start", "argv": argv})
    remaining = max(1.0, wall_deadline - time.monotonic())
    code, out = run_argv(
        argv, cwd=cwd, timeout_s=remaining, extra_env=extra_env
    )
    transcript.emit(
        {
            "type": "command_end",
            "argv": argv,
            "exit_code": code,
            "output_tail": out[-2000:] if out else "",
        }
    )
    return code


def run_job(
    spec: dict[str, Any],
    *,
    transcript_path: Path,
    resume: bool = False,
    job_path: Path | None = None,
) -> int:
    validate_job(spec)
    job_id = spec["job_id"]
    auto = spec.get("autonomous") or {}
    max_wall_ms = int(auto.get("max_wall_ms", 7_200_000))
    wall_deadline = time.monotonic() + (max_wall_ms / 1000.0)
    extra_env = (
        {"BRAIN_REFLECTION_DISABLED": "1"} if spec.get("irreversible") else None
    )

    transcript = Transcript(transcript_path)
    state_path = transcript_path.with_suffix(".state.json")
    start_index = 0
    if resume and state_path.is_file():
        prev = json.loads(state_path.read_text(encoding="utf-8"))
        start_index = int(prev.get("next_step") or 0)
        transcript.emit(
            {
                "type": "job_resume",
                "job_id": job_id,
                "next_step": start_index,
            }
        )

    crashed = {"flag": False}

    def _on_signal(signum, _frame):
        crashed["flag"] = True
        child = _CURRENT_CHILD
        if child is not None and child.poll() is None:
            child.terminate()
        transcript.emit(
            {"type": "job_end", "status": "crashed", "signal": int(signum)}
        )
        _write_state(
            state_path,
            {
                "job_id": job_id,
                "status": "crashed",
                "next_step": start_index,
                "transcript": str(transcript_path),
                "job_path": str(job_path) if job_path else None,
                "finished_at": utc_now(),
                "pid": os.getpid(),
            },
        )
        raise SystemExit(2)

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    _write_state(
        state_path,
        {
            "job_id": job_id,
            "status": "running",
            "started_at": utc_now(),
            "pid": os.getpid(),
            "next_step": start_index,
            "transcript": str(transcript_path),
            "job_path": str(job_path) if job_path else None,
        },
    )

    if not resume:
        transcript.emit(
            {
                "type": "job_start",
                "job_id": job_id,
                "intent": spec["intent"],
                "invariants": spec.get("invariants") or [],
                "irreversible": bool(spec.get("irreversible")),
            }
        )

    if spec.get("canary_required") and not any(
        s.get("type") == "canary" for s in spec["steps"]
    ):
        code = run_canary_step(
            {"type": "canary", "label": job_id, "limit": 100},
            transcript,
            wall_deadline=wall_deadline,
        )
        if code != 0:
            transcript.emit(
                {"type": "job_end", "status": "failed", "reason": "canary"}
            )
            _finish_state(state_path, "failed")
            return 2

    steps = list(spec["steps"])
    mid_gate_at = max(1, len(steps) // 2)
    ran_mid_gate = start_index > mid_gate_at

    for i, step in enumerate(steps):
        if i < start_index:
            continue
        if crashed["flag"]:
            return 2
        if time.monotonic() > wall_deadline:
            transcript.emit(
                {"type": "job_end", "status": "budget", "reason": "max_wall_ms"}
            )
            _finish_state(state_path, "budget")
            return 2

        t = step["type"]
        if t == "canary":
            code = run_canary_step(step, transcript, wall_deadline=wall_deadline)
        elif t == "command":
            code = run_command_step(
                step, transcript, wall_deadline=wall_deadline, extra_env=extra_env
            )
        elif t == "gate":
            code = run_gates(
                spec, transcript, phase_label=f"step-{i}", wall_deadline=wall_deadline
            )
            ran_mid_gate = True
        else:
            raise ValueError(f"unknown step type: {t}")

        if code != 0:
            transcript.emit(
                {
                    "type": "job_end",
                    "status": "failed",
                    "reason": f"step_{i}_{t}",
                    "exit_code": code,
                }
            )
            _finish_state(state_path, "failed")
            return 2 if code != 1 else 1

        start_index = i + 1
        _patch_state(state_path, next_step=start_index)

        if (
            not ran_mid_gate
            and i + 1 == mid_gate_at
            and not any(s.get("type") == "gate" for s in steps)
        ):
            code = run_gates(
                spec, transcript, phase_label="mid", wall_deadline=wall_deadline
            )
            ran_mid_gate = True
            if code != 0:
                transcript.emit(
                    {
                        "type": "job_end",
                        "status": "failed",
                        "reason": "mid_gate",
                        "exit_code": code,
                    }
                )
                _finish_state(state_path, "failed")
                return 2 if code != 1 else 1

    if spec.get("run_end_gate", True):
        code = run_gates(
            spec, transcript, phase_label="end", wall_deadline=wall_deadline
        )
        if code != 0:
            transcript.emit(
                {
                    "type": "job_end",
                    "status": "failed",
                    "reason": "end_gate",
                    "exit_code": code,
                }
            )
            _finish_state(state_path, "failed")
            return 2 if code != 1 else 1

    cert = spec.get("certificate_path") or str(
        REPO_ROOT
        / "docs"
        / "superpowers"
        / "specs"
        / "brain-forge"
        / "certificates"
        / f"{job_id}.md"
    )
    transcript.emit(
        {
            "type": "job_end",
            "status": "success",
            "certificate_path": cert,
        }
    )
    _finish_state(state_path, "success", certificate_path=cert)
    return 0


def _write_state(state_path: Path, data: dict[str, Any]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _patch_state(state_path: Path, **fields: Any) -> None:
    data = json.loads(state_path.read_text(encoding="utf-8"))
    data.update(fields)
    _write_state(state_path, data)


def _finish_state(
    state_path: Path, status: str, certificate_path: str | None = None
) -> None:
    data = json.loads(state_path.read_text(encoding="utf-8"))
    data["status"] = status
    data["finished_at"] = utc_now()
    if certificate_path:
        data["certificate_path"] = certificate_path
    state_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Brain Forge C2 job worker")
    parser.add_argument("--job", type=Path, required=True, help="Job spec JSON path")
    parser.add_argument(
        "--transcript",
        type=Path,
        default=None,
        help="JSONL transcript path (default brain/eval/runs/<job_id>.jsonl)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Continue from state.json next_step after a crash",
    )
    args = parser.parse_args(argv)

    job_path = args.job if args.job.is_absolute() else REPO_ROOT / args.job
    spec = json.loads(job_path.read_text(encoding="utf-8"))
    transcript = args.transcript
    if transcript is None:
        transcript = RUNS_DIR / f"{spec['job_id']}.jsonl"
    elif not transcript.is_absolute():
        transcript = REPO_ROOT / transcript

    try:
        return run_job(
            spec,
            transcript_path=transcript,
            resume=args.resume,
            job_path=job_path,
        )
    except (jsonschema.ValidationError, ValueError) as exc:
        print(f"job spec invalid: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    raise SystemExit(main())
