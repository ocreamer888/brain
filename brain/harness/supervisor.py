"""Brain Forge C2 supervisor — start / status / attach / stop workers."""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = REPO_ROOT / "brain" / "eval" / "runs"
VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
WORKER = Path(__file__).resolve().parent / "worker.py"


def _python() -> str:
    if VENV_PYTHON.is_file():
        return str(VENV_PYTHON)
    return sys.executable


def paths_for(job_id: str) -> dict[str, Path]:
    return {
        "transcript": RUNS_DIR / f"{job_id}.jsonl",
        "state": RUNS_DIR / f"{job_id}.state.json",
        "pid": RUNS_DIR / f"{job_id}.pid",
        "log": RUNS_DIR / f"{job_id}.supervisor.log",
    }


def load_job_id(job_path: Path) -> str:
    data = json.loads(job_path.read_text(encoding="utf-8"))
    return str(data["job_id"])


def cmd_start(job: Path, *, foreground: bool, resume: bool = False) -> int:
    job_path = job if job.is_absolute() else REPO_ROOT / job
    job_id = load_job_id(job_path)
    p = paths_for(job_id)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)

    if p["pid"].is_file():
        old = int(p["pid"].read_text().strip() or "0")
        if old and _pid_alive(old):
            print(f"job {job_id} already running pid={old}", file=sys.stderr)
            return 1

    argv = [
        _python(),
        str(WORKER),
        "--job",
        str(job_path),
        "--transcript",
        str(p["transcript"]),
    ]
    if resume:
        argv.append("--resume")
    spec_copy = RUNS_DIR / f"{job_id}.job.json"
    if job_path.resolve() != spec_copy.resolve():
        spec_copy.write_text(job_path.read_text(encoding="utf-8"), encoding="utf-8")
        argv[3] = str(spec_copy)
    if foreground:
        # Write pid of current process tree leaf via Popen wait
        proc = subprocess.Popen(argv, cwd=REPO_ROOT)
        p["pid"].write_text(str(proc.pid) + "\n", encoding="utf-8")
        code = proc.wait()
        return code

    log_fh = p["log"].open("a", encoding="utf-8")
    proc = subprocess.Popen(
        argv,
        cwd=REPO_ROOT,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    p["pid"].write_text(str(proc.pid) + "\n", encoding="utf-8")
    # Patch state with pid when worker creates it (brief wait)
    for _ in range(50):
        if p["state"].is_file():
            state = json.loads(p["state"].read_text(encoding="utf-8"))
            state["pid"] = proc.pid
            p["state"].write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
            break
        time.sleep(0.05)
    print(f"started job_id={job_id} pid={proc.pid} transcript={p['transcript']}")
    print(f"attach: .venv/bin/python brain/harness/supervisor.py attach {job_id}")
    return 0


def cmd_reconcile() -> int:
    """Mark running jobs with dead pids as crashed."""
    marked = []
    for state_path in RUNS_DIR.glob("*.state.json"):
        data = json.loads(state_path.read_text(encoding="utf-8"))
        if data.get("status") != "running":
            continue
        pid = data.get("pid")
        if pid and _pid_alive(int(pid)):
            continue
        data["status"] = "crashed"
        data["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        data["reconcile"] = "pid_dead"
        state_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        marked.append(data.get("job_id") or state_path.stem)
    print(json.dumps({"crashed": marked}))
    return 0


def cmd_recover(job_id: str) -> int:
    p = paths_for(job_id)
    if not p["state"].is_file():
        print(f"no state for {job_id}", file=sys.stderr)
        return 1
    state = json.loads(p["state"].read_text(encoding="utf-8"))
    job_path = state.get("job_path")
    if not job_path:
        print("state missing job_path; cannot recover", file=sys.stderr)
        return 1
    cmd_reconcile()
    return cmd_start(Path(job_path), foreground=False, resume=True)


JOBS_ROOT = Path(
    os.environ.get("BRAIN_FORGE_JOBS_ROOT", REPO_ROOT / "brain" / "eval" / "jobs")
)


def cmd_daemon(*, poll_s: float, once: bool) -> int:
    inbox = JOBS_ROOT / "inbox"
    running = JOBS_ROOT / "running"
    done = JOBS_ROOT / "done"
    failed = JOBS_ROOT / "failed"
    for d in (inbox, running, done, failed):
        d.mkdir(parents=True, exist_ok=True)
    pid_path = JOBS_ROOT / "daemon.pid"
    pid_path.write_text(str(os.getpid()) + "\n", encoding="utf-8")
    print(f"forge daemon pid={os.getpid()} inbox={inbox}")
    while True:
        cmd_reconcile()
        for job_file in sorted(inbox.glob("*.json")):
            dest = running / job_file.name
            job_file.replace(dest)
            code = cmd_start(dest, foreground=True, resume=False)
            final = done if code == 0 else failed
            dest.replace(final / dest.name)
        if once:
            break
        time.sleep(poll_s)
    return 0


def cmd_status(job_id: str) -> int:
    p = paths_for(job_id)
    pid = None
    if p["pid"].is_file():
        pid = int(p["pid"].read_text().strip() or "0")
    alive = bool(pid and _pid_alive(pid))
    state: dict[str, Any] = {}
    if p["state"].is_file():
        state = json.loads(p["state"].read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "job_id": job_id,
                "pid": pid,
                "alive": alive,
                "state": state,
                "transcript": str(p["transcript"]) if p["transcript"].is_file() else None,
            },
            indent=2,
        )
    )
    return 0


def cmd_attach(job_id: str, *, follow: bool) -> int:
    p = paths_for(job_id)
    if not p["transcript"].is_file():
        print(f"no transcript yet: {p['transcript']}", file=sys.stderr)
        return 1
    if not follow:
        print(p["transcript"].read_text(encoding="utf-8"), end="")
        return 0
    # Simple tail -f
    with p["transcript"].open("r", encoding="utf-8") as fh:
        fh.seek(0, os.SEEK_END)
        print(f"— attaching {job_id} (Ctrl-C to detach; job keeps running) —")
        try:
            while True:
                line = fh.readline()
                if line:
                    print(line, end="")
                else:
                    time.sleep(0.3)
                    st = cmd_status_quiet(job_id)
                    if st and st.get("state", {}).get("status") not in (
                        None,
                        "running",
                    ):
                        # drain remainder
                        rest = fh.read()
                        if rest:
                            print(rest, end="")
                        print(f"— job finished status={st['state'].get('status')} —")
                        break
        except KeyboardInterrupt:
            print("\n— detached —")
    return 0


def cmd_status_quiet(job_id: str) -> dict[str, Any] | None:
    p = paths_for(job_id)
    if not p["state"].is_file():
        return None
    pid = None
    if p["pid"].is_file():
        pid = int(p["pid"].read_text().strip() or "0")
    return {
        "pid": pid,
        "alive": bool(pid and _pid_alive(pid)),
        "state": json.loads(p["state"].read_text(encoding="utf-8")),
    }


def cmd_stop(job_id: str) -> int:
    p = paths_for(job_id)
    if not p["pid"].is_file():
        print(f"no pid file for {job_id}", file=sys.stderr)
        return 1
    pid = int(p["pid"].read_text().strip() or "0")
    if not pid or not _pid_alive(pid):
        print(f"job {job_id} not running")
        return 0
    try:
        os.killpg(pid, signal.SIGTERM)
    except OSError:
        os.kill(pid, signal.SIGTERM)
    for _ in range(40):
        if not _pid_alive(pid):
            break
        time.sleep(0.1)
    if _pid_alive(pid):
        try:
            os.killpg(pid, signal.SIGKILL)
        except OSError:
            os.kill(pid, signal.SIGKILL)
    print(f"stopped job_id={job_id} pid={pid}")
    return 0


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Brain Forge C2 supervisor")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_start = sub.add_parser("start", help="Start job (background by default)")
    p_start.add_argument("job", type=Path, help="Job spec JSON")
    p_start.add_argument(
        "--foreground", action="store_true", help="Run worker in foreground"
    )
    p_start.add_argument("--resume", action="store_true", help="Resume crashed job")

    p_status = sub.add_parser("status", help="Show job status JSON")
    p_status.add_argument("job_id")

    p_attach = sub.add_parser("attach", help="Print or follow JSONL transcript")
    p_attach.add_argument("job_id")
    p_attach.add_argument(
        "--no-follow", action="store_true", help="Dump transcript and exit"
    )

    p_stop = sub.add_parser("stop", help="SIGTERM worker")
    p_stop.add_argument("job_id")

    sub.add_parser("reconcile", help="Mark dead running jobs as crashed")
    p_rec = sub.add_parser("recover", help="Resume a crashed job from next_step")
    p_rec.add_argument("job_id")
    p_daemon = sub.add_parser("daemon", help="Always-on inbox poller (launchd)")
    p_daemon.add_argument("--poll", type=float, default=5.0)
    p_daemon.add_argument("--once", action="store_true", help="Process inbox once and exit")

    args = parser.parse_args(argv)
    if args.cmd == "start":
        return cmd_start(args.job, foreground=args.foreground, resume=args.resume)
    if args.cmd == "status":
        return cmd_status(args.job_id)
    if args.cmd == "attach":
        return cmd_attach(args.job_id, follow=not args.no_follow)
    if args.cmd == "stop":
        return cmd_stop(args.job_id)
    if args.cmd == "reconcile":
        return cmd_reconcile()
    if args.cmd == "recover":
        return cmd_recover(args.job_id)
    if args.cmd == "daemon":
        return cmd_daemon(poll_s=args.poll, once=args.once)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
