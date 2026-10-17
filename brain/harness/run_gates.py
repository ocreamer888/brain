"""Brain Forge Phase A — deterministic gate runner (no LLM).

Maps constitution invariants to pytest (+ optional parity / quality gate).
Exit codes: 0 pass, 1 warn, 2 hard fail.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INVARIANTS = REPO_ROOT / "brain" / "constitution" / "invariants.yaml"
DEFAULT_DB = REPO_ROOT / "brain" / "rust" / "brain.db"
QUALITY_GATE = REPO_ROOT / "brain" / "tools" / "ingest_quality_gate.py"
PARITY_TEST = "brain/tests/test_deploy_parity.py"
VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"


def _python() -> str:
    if VENV_PYTHON.is_file():
        return str(VENV_PYTHON)
    return sys.executable


def load_registry(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "invariants" not in data:
        raise ValueError(f"Invalid invariants registry: {path}")
    return data


def filter_invariants(
    invariants: list[dict[str, Any]], pattern: str | None
) -> list[dict[str, Any]]:
    active = [inv for inv in invariants if not inv.get("superseded_by")]
    if not pattern or pattern in ("*", "all"):
        return active
    return [inv for inv in active if fnmatch.fnmatch(inv["id"], pattern)]


def collect_test_paths(invariants: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    paths: list[str] = []
    for inv in invariants:
        for t in inv.get("tests") or []:
            if t not in seen:
                seen.add(t)
                paths.append(t)
    return paths


def needs_parity(invariants: list[dict[str, Any]]) -> bool:
    return any(inv.get("parity") for inv in invariants)


def run_cmd(
    argv: list[str], *, cwd: Path, timeout: int | None = None
) -> tuple[int, str]:
    proc = subprocess.run(
        argv,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out


def run_pytest(paths: list[str], *, cwd: Path) -> tuple[int, str, float]:
    if not paths:
        return 0, "no tests", 0.0
    t0 = time.perf_counter()
    code, out = run_cmd(
        [_python(), "-m", "pytest", "-q", "--tb=line", *paths],
        cwd=cwd,
        timeout=600,
    )
    return code, out, time.perf_counter() - t0


def run_quality_gate(*, cwd: Path, db: Path) -> tuple[int, str, float]:
    t0 = time.perf_counter()
    code, out = run_cmd(
        [_python(), str(QUALITY_GATE), "--db", str(db)],
        cwd=cwd,
        timeout=180,
    )
    return code, out, time.perf_counter() - t0


def build_summary(
    *,
    registry: dict[str, Any],
    selected: list[dict[str, Any]],
    pytest_code: int,
    pytest_paths: list[str],
    pytest_secs: float,
    parity_ran: bool,
    parity_code: int | None,
    qg_ran: bool,
    qg_code: int | None,
    qg_secs: float | None,
    phase: str,
) -> dict[str, Any]:
    inv_results = []
    for inv in selected:
        # Per-invariant pass tracks pytest aggregate for Phase A (paths shared).
        status = "pass" if pytest_code == 0 else "fail"
        if inv.get("parity") and parity_ran and parity_code not in (0, None):
            status = "fail"
        inv_results.append(
            {
                "id": inv["id"],
                "statement": inv.get("statement"),
                "status": status,
                "teeth": bool(inv.get("teeth")),
                "tests": list(inv.get("tests") or []),
            }
        )

    exit_code = 0
    if pytest_code != 0:
        exit_code = 2
    elif parity_ran and parity_code not in (0, None):
        exit_code = 2
    elif qg_ran and qg_code is not None:
        if qg_code >= 2:
            exit_code = 2
        elif qg_code == 1 and exit_code == 0:
            exit_code = 1

    return {
        "version": 1,
        "phase": phase,
        "project": registry.get("project", "brain"),
        "exit_code": exit_code,
        "pytest": {
            "exit_code": pytest_code,
            "paths": pytest_paths,
            "duration_s": round(pytest_secs, 3),
        },
        "parity": {
            "ran": parity_ran,
            "exit_code": parity_code,
        },
        "quality_gate": {
            "ran": qg_ran,
            "exit_code": qg_code,
            "duration_s": None if qg_secs is None else round(qg_secs, 3),
        },
        "invariants": inv_results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Brain Forge Phase A — run constitution gates (no LLM)."
    )
    parser.add_argument(
        "--invariants",
        type=Path,
        default=DEFAULT_INVARIANTS,
        help="Path to invariants.yaml",
    )
    parser.add_argument(
        "--phase",
        choices=("verify", "smoke", "full"),
        default="verify",
        help="verify=tests+parity+qg; smoke=tests only; full=same as verify",
    )
    parser.add_argument(
        "--filter",
        default="*",
        help="fnmatch on invariant id (e.g. INV-SESSION-*)",
    )
    parser.add_argument(
        "--skip-quality-gate",
        action="store_true",
        help="Skip ingest_quality_gate.py",
    )
    parser.add_argument(
        "--skip-parity",
        action="store_true",
        help="Skip deploy parity even if an invariant sets parity: true",
    )
    parser.add_argument(
        "--emit-json",
        type=Path,
        default=None,
        help="Write machine-readable summary JSON",
    )
    parser.add_argument(
        "--teeth-check",
        action="store_true",
        help="Reserved for Phase B automation; Phase A prints procedure only",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help="brain.db for quality gate",
    )
    args = parser.parse_args(argv)

    if args.teeth_check:
        print(
            "Teeth check is manual in Phase A. See "
            "brain/constitution/README.md — automate in Phase B.",
            file=sys.stderr,
        )

    inv_path = args.invariants
    if not inv_path.is_absolute():
        inv_path = (REPO_ROOT / inv_path).resolve()
    registry = load_registry(inv_path)
    selected = filter_invariants(list(registry["invariants"]), args.filter)
    if not selected:
        print(f"No invariants matched filter={args.filter!r}", file=sys.stderr)
        return 2

    test_paths = collect_test_paths(selected)
    # smoke: pytest only; verify/full: + parity + quality gate (unless skipped)
    run_parity = (
        args.phase in ("verify", "full")
        and not args.skip_parity
        and needs_parity(selected)
    )
    if run_parity and PARITY_TEST not in test_paths:
        test_paths = [*test_paths, PARITY_TEST]

    pytest_code, pytest_out, pytest_secs = run_pytest(test_paths, cwd=REPO_ROOT)
    if pytest_code != 0:
        print(pytest_out[-4000:] if len(pytest_out) > 4000 else pytest_out)

    parity_code: int | None = None
    if run_parity:
        # Already included in pytest_paths; report same code for summary clarity
        parity_code = pytest_code if PARITY_TEST in test_paths else 0

    qg_ran = False
    qg_code: int | None = None
    qg_secs: float | None = None
    skip_qg = args.skip_quality_gate or args.phase == "smoke"
    if not skip_qg and args.phase in ("verify", "full"):
        db = args.db if args.db.is_absolute() else (REPO_ROOT / args.db)
        if db.is_file() and QUALITY_GATE.is_file():
            qg_ran = True
            qg_code, qg_out, qg_secs = run_quality_gate(cwd=REPO_ROOT, db=db)
            if qg_code != 0:
                print(qg_out[-2000:] if len(qg_out) > 2000 else qg_out)
        else:
            print(
                f"quality gate skipped (db or script missing: {db})",
                file=sys.stderr,
            )

    summary = build_summary(
        registry=registry,
        selected=selected,
        pytest_code=pytest_code,
        pytest_paths=test_paths,
        pytest_secs=pytest_secs,
        parity_ran=run_parity,
        parity_code=parity_code,
        qg_ran=qg_ran,
        qg_code=qg_code,
        qg_secs=qg_secs,
        phase=args.phase,
    )

    if args.emit_json:
        out_path = args.emit_json
        if not out_path.is_absolute():
            out_path = REPO_ROOT / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {out_path}")

    print(
        f"gates phase={args.phase} exit={summary['exit_code']} "
        f"pytest={pytest_code} invariants={len(selected)} "
        f"duration_s={pytest_secs:.1f}"
    )
    return int(summary["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
