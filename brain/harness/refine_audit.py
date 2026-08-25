"""Brain Forge Phase D — refine audit + constitution block (no LLM).

Append-only JSONL audit. Classifies paths/targets; blocks constitution edits.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AUDIT = REPO_ROOT / "brain" / "eval" / "runs" / "refine_audit.jsonl"

# Paths refine must never modify (relative to repo root, POSIX-style)
FORBIDDEN_GLOBS = (
    "brain/constitution/",
    "brain/constitution/invariants.yaml",
    "brain/tools/ingest_quality_gate.py",
    "brain/harness/run_gates.py",
    "brain/harness/teeth_probes.py",
    "docs/superpowers/specs/brain-forge/templates/masterpiece-certificate.md",
)

FORBIDDEN_TARGETS = frozenset(
    {
        "constitution",
        "invariant",
        "invariants",
        "threshold",
        "thresholds",
        "quality_gate_threshold",
        "disable_teeth",
        "auto_approve_bulk",
    }
)

ALLOWED_TARGETS = frozenset(
    {
        "pattern",
        "tactic",
        "skill_tactics",
        "canary_checklist",
        "job_wrapper",
    }
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_repo_path(path: str | Path) -> str:
    p = Path(path)
    if not p.is_absolute():
        p = (REPO_ROOT / p).resolve()
    else:
        p = p.resolve()
    try:
        rel = p.relative_to(REPO_ROOT.resolve())
    except ValueError:
        return p.as_posix()
    return rel.as_posix()


def is_forbidden_path(path: str | Path) -> bool:
    rel = normalize_repo_path(path)
    if rel.endswith("invariants.yaml") or rel.endswith("/invariants.yaml"):
        return True
    for prefix in FORBIDDEN_GLOBS:
        if prefix.endswith("/"):
            if rel == prefix.rstrip("/") or rel.startswith(prefix):
                return True
        elif rel == prefix:
            return True
    return False


def classify_target(target: str) -> str:
    """Return 'tactic' | 'constitution' | 'unknown'."""
    t = (target or "").strip().lower().replace("-", "_")
    if t in FORBIDDEN_TARGETS or t.startswith("constitution"):
        return "constitution"
    if t in ALLOWED_TARGETS:
        return "tactic"
    # Heuristic: proposals that mention lowering thresholds
    if re.search(r"lower\s+threshold|remove\s+invariant|disable\s+teeth", t):
        return "constitution"
    return "unknown"


def classify_proposal(
    *,
    target: str | None = None,
    path: str | Path | None = None,
    edit_summary: str | None = None,
) -> dict[str, Any]:
    reasons: list[str] = []
    kind = "tactic"

    if path is not None and is_forbidden_path(path):
        kind = "constitution"
        reasons.append(f"forbidden_path:{normalize_repo_path(path)}")

    if target:
        ct = classify_target(target)
        if ct == "constitution":
            kind = "constitution"
            reasons.append(f"forbidden_target:{target}")
        elif ct == "unknown" and kind != "constitution":
            kind = "unknown"
            reasons.append(f"unknown_target:{target}")

    summary = (edit_summary or "").lower()
    for needle, label in (
        ("lower threshold", "mentions_lower_threshold"),
        ("remove invariant", "mentions_remove_invariant"),
        ("disable teeth", "mentions_disable_teeth"),
        ("skip canary", "mentions_skip_canary"),
        ("brain/constitution", "mentions_constitution_path"),
    ):
        if needle in summary:
            kind = "constitution"
            reasons.append(label)

    allowed = kind == "tactic"
    return {
        "classification": kind,
        "allowed": allowed,
        "reasons": reasons,
        "action": "allow" if allowed else "block_escalate_human",
    }


def append_audit(
    record: dict[str, Any],
    *,
    audit_path: Path | None = None,
) -> Path:
    path = audit_path or DEFAULT_AUDIT
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "refine_id": record.get("refine_id") or str(uuid.uuid4()),
        "timestamp": record.get("timestamp") or utc_now(),
        **{k: v for k, v in record.items() if k not in ("refine_id", "timestamp")},
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, default=str) + "\n")
        fh.flush()
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Brain Forge refine audit (Phase D) — no LLM"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_check = sub.add_parser("check-path", help="Exit 0 if path allowed, 2 if forbidden")
    p_check.add_argument("path")

    p_staged = sub.add_parser(
        "check-staged",
        help="Block commit if any staged path is constitution-denylist (git hook)",
    )
    p_staged.add_argument(
        "--paths",
        nargs="*",
        default=None,
        help="Explicit paths (tests). Default: git diff --cached --name-only",
    )

    p_cls = sub.add_parser("classify", help="Classify a refine proposal")
    p_cls.add_argument("--target", default=None)
    p_cls.add_argument("--path", default=None)
    p_cls.add_argument("--edit-summary", default=None)

    p_app = sub.add_parser("append", help="Append audit JSONL record")
    p_app.add_argument("--trigger", required=True)
    p_app.add_argument("--target", required=True)
    p_app.add_argument("--edit-summary", required=True)
    p_app.add_argument("--brain-memory-id", default="")
    p_app.add_argument("--outcome", default="")
    p_app.add_argument("--rollback", default="")
    p_app.add_argument(
        "--force-blocked",
        action="store_true",
        help="Record a blocked constitution attempt (still appends audit)",
    )
    p_app.add_argument("--audit-path", type=Path, default=None)

    args = parser.parse_args(argv)

    if args.cmd == "check-path":
        forbidden = is_forbidden_path(args.path)
        print(
            json.dumps(
                {
                    "path": normalize_repo_path(args.path),
                    "forbidden": forbidden,
                }
            )
        )
        return 2 if forbidden else 0

    if args.cmd == "check-staged":
        paths = list(args.paths or [])
        if not paths:
            proc = subprocess.run(
                ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode != 0:
                print(proc.stderr, file=sys.stderr)
                return 2
            paths = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
        blocked = []
        for rel in paths:
            if is_forbidden_path(rel):
                blocked.append(normalize_repo_path(rel))
        payload = {"blocked": blocked, "checked": len(paths)}
        print(json.dumps(payload))
        if blocked:
            print(
                "Forge refine denylist: constitution/gate files cannot be committed "
                "without owner override. Unstage or get a human PR.",
                file=sys.stderr,
            )
            return 2
        return 0

    if args.cmd == "classify":
        result = classify_proposal(
            target=args.target,
            path=args.path,
            edit_summary=args.edit_summary,
        )
        print(json.dumps(result, indent=2))
        return 0 if result["allowed"] else 2

    if args.cmd == "append":
        result = classify_proposal(
            target=args.target,
            edit_summary=args.edit_summary,
        )
        if not result["allowed"] and not args.force_blocked:
            print(json.dumps(result, indent=2), file=sys.stderr)
            print(
                "Refusing to append tactic audit for constitution-class proposal. "
                "Use --force-blocked to record a blocked attempt.",
                file=sys.stderr,
            )
            return 2
        status = "blocked" if not result["allowed"] else "recorded"
        path = append_audit(
            {
                "trigger": args.trigger,
                "target": args.target,
                "brain_memory_id": args.brain_memory_id or None,
                "edit_summary": args.edit_summary,
                "outcome": args.outcome or status,
                "rollback": args.rollback or None,
                "classification": result["classification"],
                "allowed": result["allowed"],
                "reasons": result["reasons"],
            },
            audit_path=args.audit_path,
        )
        print(json.dumps({"audit_path": str(path), "status": status, **result}))
        return 0 if result["allowed"] else 2

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
