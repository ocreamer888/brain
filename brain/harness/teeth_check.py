"""Prove an invariant has teeth: baseline pass → break fails → restore passes.

Never uses git stash. Registered --auto-probe edits are always restored in finally.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from brain.harness.teeth_probes import PROBES, probe_path  # noqa: E402
DEFAULT_INVARIANTS = REPO_ROOT / "brain" / "constitution" / "invariants.yaml"
VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"


def _python() -> str:
    if VENV_PYTHON.is_file():
        return str(VENV_PYTHON)
    return sys.executable


def load_invariant(registry: Path, inv_id: str) -> dict[str, Any]:
    data = yaml.safe_load(registry.read_text(encoding="utf-8"))
    for inv in data.get("invariants") or []:
        if inv.get("id") == inv_id and not inv.get("superseded_by"):
            return inv
    raise SystemExit(f"Unknown or superseded invariant: {inv_id}")


def run_pytest(paths: list[str], *, expect_fail: bool) -> tuple[bool, int, str]:
    if not paths:
        raise SystemExit("Invariant has no tests")
    proc = subprocess.run(
        [_python(), "-m", "pytest", "-q", "--tb=line", *paths],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    ok = (proc.returncode != 0) if expect_fail else (proc.returncode == 0)
    return ok, proc.returncode, out


def apply_probe(text: str, old: str, new: str) -> str:
    if old not in text:
        raise SystemExit(f"Probe old string not found in file (already broken?)")
    if text.count(old) != 1:
        raise SystemExit(f"Probe old string not unique ({text.count(old)} hits)")
    return text.replace(old, new, 1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Brain Forge teeth check")
    parser.add_argument("--invariant", default=None, help="e.g. INV-HOOK-01")
    parser.add_argument(
        "--invariants",
        type=Path,
        default=DEFAULT_INVARIANTS,
        help="Path to invariants.yaml",
    )
    parser.add_argument(
        "--expect-fail",
        action="store_true",
        help="Current tree should fail invariant tests (manual break step)",
    )
    parser.add_argument(
        "--auto-probe",
        action="store_true",
        help="Apply registered probe, expect fail, restore, expect pass",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run --auto-probe for every registered invariant (ignores --invariant)",
    )
    parser.add_argument(
        "--emit-json",
        type=Path,
        default=None,
        help="Write evidence JSON (default under brain/eval/runs/)",
    )
    args = parser.parse_args(argv)

    if args.all:
        failed = []
        for inv_id in sorted(PROBES):
            extra: list[str] = ["--invariant", inv_id, "--auto-probe"]
            if args.emit_json:
                dest = args.emit_json
                if dest.suffix == ".json":
                    dest = dest.with_name(f"{dest.stem}-{inv_id}{dest.suffix}")
                extra.extend(["--emit-json", str(dest)])
            code = main(extra)
            if code != 0:
                failed.append(inv_id)
        if failed:
            print(f"teeth --all failed: {failed}", file=sys.stderr)
            return 2
        print(f"teeth --all passed n={len(PROBES)}")
        return 0

    if not args.invariant:
        print("--invariant required unless --all", file=sys.stderr)
        return 2

    inv_path = args.invariants
    if not inv_path.is_absolute():
        inv_path = (REPO_ROOT / inv_path).resolve()
    inv = load_invariant(inv_path, args.invariant)
    tests = list(inv.get("tests") or [])
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    evidence: dict[str, Any] = {
        "invariant_id": args.invariant,
        "statement": inv.get("statement"),
        "tests": tests,
        "timestamp": ts,
        "auto_probe": bool(args.auto_probe),
        "steps": [],
    }

    def record(step: str, ok: bool, code: int, note: str = "") -> None:
        evidence["steps"].append(
            {"step": step, "ok": ok, "pytest_exit": code, "note": note}
        )

    if args.auto_probe:
        probe = PROBES.get(args.invariant)
        if probe is None:
            print(
                f"No auto-probe for {args.invariant}. "
                f"Registered: {sorted(PROBES)}",
                file=sys.stderr,
            )
            return 2
        target = probe_path(probe)
        original = target.read_text(encoding="utf-8")
        try:
            ok, code, out = run_pytest(tests, expect_fail=False)
            record("baseline", ok, code)
            if not ok:
                print(out[-3000:])
                evidence["passed"] = False
                _write(args.emit_json, evidence, args.invariant, ts)
                return 2

            broken = apply_probe(original, probe.old, probe.new)
            target.write_text(broken, encoding="utf-8")
            ok, code, out = run_pytest(tests, expect_fail=True)
            record("broken_must_fail", ok, code, probe.rationale)
            if not ok:
                print("EXPECTED FAIL but tests passed — probe too weak or wrong tests")
                print(out[-2000:])
                evidence["passed"] = False
                return 2

            target.write_text(original, encoding="utf-8")
            ok, code, out = run_pytest(tests, expect_fail=False)
            record("restored", ok, code)
            if not ok:
                print(out[-3000:])
                evidence["passed"] = False
                return 2

            evidence["passed"] = True
            evidence["probe"] = {
                "file": probe.relative_file,
                "rationale": probe.rationale,
            }
        finally:
            # Always restore even if mid-step failed
            if target.read_text(encoding="utf-8") != original:
                target.write_text(original, encoding="utf-8")
                evidence.setdefault("notes", []).append("restored_in_finally")
    else:
        ok, code, out = run_pytest(tests, expect_fail=args.expect_fail)
        step = "expect_fail" if args.expect_fail else "baseline"
        record(step, ok, code)
        if not ok:
            print(out[-3000:])
        evidence["passed"] = ok

    path = _write(args.emit_json, evidence, args.invariant, ts)
    print(
        f"teeth {args.invariant} passed={evidence['passed']} evidence={path}"
    )
    return 0 if evidence["passed"] else 2


def _write(
    emit: Path | None, evidence: dict[str, Any], inv_id: str, ts: str
) -> Path:
    if emit is None:
        out = REPO_ROOT / "brain" / "eval" / "runs" / f"teeth-{inv_id}-{ts}.json"
    else:
        out = emit if emit.is_absolute() else REPO_ROOT / emit
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    # Allow `python brain/harness/teeth_check.py` from repo root
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    raise SystemExit(main())
