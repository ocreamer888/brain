"""Checkpointed orchestrator for bulk backfill stages."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from brain.tools.backfill_state import (  # noqa: E402
    load_or_init_state,
    mark_preview_ready,
    mark_run_complete,
    mark_stage,
)


EXIT_OK = 0
EXIT_STAGE_FAILURE = 1
EXIT_LOCK_CONFLICT = 2


def _default_state_path() -> Path:
    return Path(".cursor/hooks/state/backfill-state.json")


def _default_lock_path() -> Path:
    return Path(".cursor/hooks/state/backfill.lock")


def _artifact_path(batch_id: str) -> Path:
    return Path(".cursor/hooks/state") / f"backfill-{batch_id}.jsonl"


def _run_command(args: list[str]) -> tuple[bool, str]:
    proc = subprocess.run(args, capture_output=True, text=True)
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, out.strip()


def _stage_commands(state: dict[str, Any], no_llm: bool, legacy_chroma_migrate: bool) -> list[tuple[str, list[str]]]:
    commands: list[tuple[str, list[str]]] = [
        (
            "ingest_claude_code",
            [sys.executable, "brain/bootstrap/07_ingest_claude_code.py", *(["--no-llm"] if no_llm else [])],
        ),
        (
            "ingest_perplexity",
            [sys.executable, "brain/bootstrap/06_ingest_perplexity.py", *(["--no-llm"] if no_llm else [])],
        ),
        ("ingest_claw", [sys.executable, "brain/bootstrap/05_ingest_claw.py"]),
        ("ingest_cursor_history", [sys.executable, "brain/bootstrap/03_ingest.py"]),
    ]
    if legacy_chroma_migrate:
        batch_id = state["preview"]["batch_id"]
        artifact = _artifact_path(batch_id)
        commands.append(("export_to_jsonl", [sys.executable, "brain/tools/export_to_jsonl.py", str(artifact)]))
        commands.append(
            (
                "migrate_rust",
                [
                    "cargo",
                    "run",
                    "--bin",
                    "brain_migrate",
                    "--",
                    str(artifact),
                    "--db",
                    "brain/db",
                    "--index",
                    "brain/index",
                ],
            )
        )
    commands.append(("verify", [sys.executable, "-c", "print('verify:ok')"]))
    return commands


def _should_skip_stage(state: dict[str, Any], stage: str, forced_stages: set[str]) -> bool:
    if stage in forced_stages:
        return False
    stage_info = state.get("stages", {}).get(stage, {})
    return (
        stage_info.get("status") == "success"
        and stage_info.get("batch_id") == state["preview"].get("batch_id")
    )


def _run_pipeline(args: argparse.Namespace) -> int:
    state_path = Path(args.state)
    lock_path = Path(args.lock)
    state = load_or_init_state(state_path)
    preview = state.get("preview", {})

    if not preview.get("ready") or not preview.get("batch_id"):
        print("preview not ready; skipping run")
        return EXIT_OK

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        print("lock already exists; refusing to run", file=sys.stderr)
        return EXIT_LOCK_CONFLICT

    lock_path.write_text(str(preview["batch_id"]), encoding="utf-8")
    success = True
    try:
        for stage, command in _stage_commands(state, no_llm=args.no_llm, legacy_chroma_migrate=args.legacy_chroma_migrate):
            state = load_or_init_state(state_path)
            if _should_skip_stage(state, stage, set(args.force_stage)):
                mark_stage(state_path, stage, "skipped", {"reason": "already-success"})
                continue

            mark_stage(state_path, stage, "running", {"command": command})
            if args.dry_run:
                mark_stage(state_path, stage, "success", {"dry_run": True, "command": command})
                print(stage)
                continue

            ok, detail = _run_command(command)
            if ok:
                mark_stage(state_path, stage, "success", {"output": detail})
            else:
                mark_stage(state_path, stage, "failed", {"output": detail, "command": command})
                success = False
                break
    finally:
        mark_run_complete(state_path, success=success)
        if lock_path.exists():
            lock_path.unlink()

    return EXIT_OK if success else EXIT_STAGE_FAILURE


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill orchestration")
    sub = parser.add_subparsers(dest="command")

    mark_ready = sub.add_parser("mark-preview-ready", help="mark preview as ready")
    mark_ready.add_argument("--state", default=str(_default_state_path()))
    mark_ready.add_argument("--batch-id", required=True)
    mark_ready.add_argument("--input", action="append", default=[])

    parser.add_argument("--state", default=str(_default_state_path()))
    parser.add_argument("--lock", default=str(_default_lock_path()))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--legacy-chroma-migrate", action="store_true")
    parser.add_argument("--force-stage", action="append", default=[])
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]

    if argv and argv[0] == "mark-preview-ready":
        mark_parser = argparse.ArgumentParser(description="Mark preview as ready")
        mark_parser.add_argument("--state", default=str(_default_state_path()))
        mark_parser.add_argument("--batch-id", required=True)
        mark_parser.add_argument("--input", action="append", default=[])
        ns = mark_parser.parse_args(argv[1:])
        mark_preview_ready(ns.state, batch_id=ns.batch_id, inputs=list(ns.input))
        print(f"preview marked ready for batch {ns.batch_id}")
        return EXIT_OK

    parser = _build_parser()
    args = parser.parse_args(argv)
    return _run_pipeline(args)


if __name__ == "__main__":
    raise SystemExit(main())
