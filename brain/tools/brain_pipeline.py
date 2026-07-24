#!/usr/bin/env python3
"""Brain pipeline runner — executes named flows as ordered, logged steps.

Flows
─────
  health   — quick API liveness check
  daily    — spool replay → ingest → maintain → reflect → digest → dashboard
  weekly   — daily + knowledge graph + feedback export + backfill catch-up
  graph    — knowledge graph export only
  backfill — full backfill orchestration (heavy)
  step:<n> — run a single step by name

Usage (from repo root AI/):
    python3 brain/tools/brain_pipeline.py daily
    python3 brain/tools/brain_pipeline.py weekly
    python3 brain/tools/brain_pipeline.py health
    python3 brain/tools/brain_pipeline.py graph
    python3 brain/tools/brain_pipeline.py step:reflect
"""
from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]
LOG_PATH = ROOT / "brain/logs/pipeline.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT))


# ── logging ──────────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"{ts}  {msg}"
    print(line)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


# ── step primitives ───────────────────────────────────────────────────────────

@dataclass
class Step:
    name: str
    fn: Callable[[], str | None]   # returns optional short note, raises on failure
    critical: bool = True          # if True, pipeline aborts on failure


@dataclass
class StepResult:
    name: str
    ok: bool
    note: str = ""
    elapsed: float = 0.0


def _run_script(*cmd: str, timeout: int = 300) -> str:
    """Run a Python script as subprocess, return stdout. Raises on non-zero exit."""
    result = subprocess.run(
        [sys.executable, *cmd],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(ROOT),
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip().splitlines()
        raise RuntimeError("\n".join(err[-5:]))  # last 5 lines of output
    return (result.stdout or "").strip()


# ── step implementations ──────────────────────────────────────────────────────

def step_health() -> str:
    import os, urllib.request, urllib.error
    url = os.environ.get("BRAIN_API_URL", "http://127.0.0.1:8787") + "/health"
    key = os.environ.get("BRAIN_API_KEY", "")
    req = urllib.request.Request(url, headers={"x-api-key": key} if key else {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.read().decode()[:60].strip()
    except Exception as e:
        raise RuntimeError(f"API not reachable: {e}") from e


def step_spool_replay() -> str:
    out = _run_script("brain/tools/replay_spool.py")
    # grab the summary line if present
    for line in reversed(out.splitlines()):
        if line.strip():
            return line.strip()[:80]
    return "done"


def step_ingest_sessions() -> str:
    out = _run_script("brain/bootstrap/07_ingest_claude_code.py", "--no-llm", timeout=600)
    for line in reversed(out.splitlines()):
        if line.strip():
            return line.strip()[:80]
    return "done"


def step_spool_maintenance() -> str:
    out = _run_script("brain/tools/spool_maintenance.py")
    for line in reversed(out.splitlines()):
        if line.strip():
            return line.strip()[:80]
    return "done"


def step_reflect() -> str:
    import json, os, urllib.request
    url = os.environ.get("BRAIN_API_URL", "http://127.0.0.1:8787") + "/reflect"
    key = os.environ.get("BRAIN_API_KEY", "")
    req = urllib.request.Request(
        url, data=b"{}",
        headers={"content-type": "application/json", "x-api-key": key},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        result = json.loads(r.read())
    consolidated = result.get("consolidated", 0)
    deleted = result.get("deleted", 0)
    return f"consolidated={consolidated} deleted={deleted}"


def step_digest() -> str:
    out = _run_script("brain/tools/feedback_digest.py")
    for line in reversed(out.splitlines()):
        if line.strip():
            return line.strip()[:80]
    return "done"


def step_dashboard() -> str:
    out = _run_script("brain/tools/export_metrics_obsidian.py")
    return out.strip()[:80] or "done"


def step_graph() -> str:
    out = _run_script("brain/tools/export_knowledge_graph.py", timeout=900)
    for line in reversed(out.splitlines()):
        if line.strip():
            return line.strip()[:80]
    return "done"


def step_feedback_export() -> str:
    import os
    from pathlib import Path
    out_dir = ROOT / "docs/feedback-digests"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"feedback-export-{datetime.now().strftime('%Y-%m-%d')}.jsonl"
    result = subprocess.run(
        [sys.executable, "brain/tools/export_feedback.py", "--since-days", "7"],
        capture_output=True, text=True, timeout=60, cwd=str(ROOT),
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[-200:])
    out_file.write_text(result.stdout, encoding="utf-8")
    lines = result.stdout.count("\n")
    return f"{lines} events → {out_file.name}"


def step_backfill() -> str:
    out = _run_script("brain/tools/backfill_orchestrator.py", "--no-llm", "--skip-migrate", timeout=900)
    for line in reversed(out.splitlines()):
        if line.strip():
            return line.strip()[:80]
    return "done"


def step_backfill_embeddings() -> str:
    import os
    import subprocess

    binary = (
        Path(__file__).resolve().parents[2]
        / "brain/rust/target/release/brain_backfill_embeddings"
    )
    result = subprocess.run(
        [str(binary)],
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ},
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[-200:])
    for line in reversed((result.stderr or result.stdout).splitlines()):
        if line.strip():
            return line.strip()[:80]
    return "done"


def step_ingest_chunks() -> str:
    out = _run_script("brain/tools/ingest_session_chunks.py", "--all", timeout=600)
    for line in reversed(out.splitlines()):
        if line.strip():
            return line.strip()[:80]
    return "done"


# ── flow definitions ──────────────────────────────────────────────────────────

ALL_STEPS: dict[str, Step] = {
    "health":            Step("health",            step_health,            critical=True),
    "spool_replay":      Step("spool_replay",      step_spool_replay,      critical=False),
    "ingest_sessions":   Step("ingest_sessions",   step_ingest_sessions,   critical=False),
    "spool_maintenance": Step("spool_maintenance", step_spool_maintenance, critical=False),
    "reflect":           Step("reflect",           step_reflect,           critical=False),
    "digest":            Step("digest",            step_digest,            critical=False),
    "dashboard":         Step("dashboard",         step_dashboard,         critical=False),
    "graph":             Step("graph",             step_graph,             critical=False),
    "feedback_export":   Step("feedback_export",   step_feedback_export,   critical=False),
    "backfill":               Step("backfill",               step_backfill,               critical=False),
    "backfill_embeddings":    Step("backfill_embeddings",    step_backfill_embeddings,    critical=False),
    "ingest_chunks":          Step("ingest_chunks",          step_ingest_chunks,          critical=False),
}

FLOWS: dict[str, list[str]] = {
    "health": [
        "health",
    ],
    "daily": [
        "health",
        "spool_replay",
        "ingest_sessions",
        "ingest_chunks",
        "backfill_embeddings",
        "spool_maintenance",
        "reflect",
        "digest",
        "dashboard",
    ],
    "weekly": [
        "health",
        "spool_replay",
        "ingest_sessions",
        "ingest_chunks",
        "backfill_embeddings",
        "spool_maintenance",
        "reflect",
        "digest",
        "dashboard",
        "graph",
        "feedback_export",
        "backfill",
    ],
    "graph": [
        "health",
        "graph",
    ],
    "backfill": [
        "health",
        "backfill",
    ],
}


# ── runner ────────────────────────────────────────────────────────────────────

def run_pipeline(flow_name: str, steps: list[Step]) -> int:
    _log(f"[pipeline] {flow_name} — {len(steps)} step(s)")
    results: list[StepResult] = []
    t_total = time.monotonic()

    for i, step in enumerate(steps, 1):
        prefix = f"[{i}/{len(steps)}] {step.name}"
        dots = "." * max(1, 22 - len(step.name))
        t0 = time.monotonic()
        try:
            note = step.fn() or ""
            elapsed = time.monotonic() - t0
            suffix = f"ok    {elapsed:.1f}s" + (f"  ({note})" if note else "")
            _log(f"{prefix} {dots} {suffix}")
            results.append(StepResult(step.name, ok=True, note=note, elapsed=elapsed))
        except Exception as exc:
            elapsed = time.monotonic() - t0
            msg = str(exc).splitlines()[0][:120]
            _log(f"{prefix} {dots} FAILED {elapsed:.1f}s  {msg}")
            results.append(StepResult(step.name, ok=False, note=msg, elapsed=elapsed))
            if step.critical:
                _log(f"[pipeline] aborted — {step.name} is critical")
                return 1

    total_elapsed = time.monotonic() - t_total
    ok_count = sum(1 for r in results if r.ok)
    fail_count = len(results) - ok_count
    status = "done" if fail_count == 0 else f"done with {fail_count} failure(s)"
    _log(f"[pipeline] {flow_name} {status} — {ok_count}/{len(steps)} ok ({total_elapsed:.1f}s)")
    return 0 if fail_count == 0 else 1


# ── entrypoint ────────────────────────────────────────────────────────────────

def main() -> int:
    if len(sys.argv) < 2:
        flows = ", ".join(FLOWS)
        print(f"Usage: brain_pipeline.py <flow|step:<name>>\nFlows: {flows}")
        return 1

    arg = sys.argv[1].strip()

    if arg.startswith("step:"):
        step_name = arg[5:]
        step = ALL_STEPS.get(step_name)
        if not step:
            print(f"Unknown step '{step_name}'. Available: {', '.join(ALL_STEPS)}")
            return 1
        return run_pipeline(f"step:{step_name}", [step])

    step_names = FLOWS.get(arg)
    if step_names is None:
        print(f"Unknown flow '{arg}'. Available: {', '.join(FLOWS)}")
        return 1

    steps = [ALL_STEPS[n] for n in step_names]
    return run_pipeline(arg, steps)


if __name__ == "__main__":
    raise SystemExit(main())
