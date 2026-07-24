"""State helpers for checkpointed bulk backfill orchestration."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _default_state() -> dict[str, Any]:
    return {
        "version": 1,
        "preview": {
            "ready": False,
            "batch_id": None,
            "inputs": [],
            "marked_at": None,
        },
        "run": {
            "status": "idle",
            "started_at": None,
            "ended_at": None,
            "last_error": None,
        },
        "stages": {},
    }


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def load_or_init_state(path: str | Path) -> dict[str, Any]:
    state_path = Path(path)
    if not state_path.exists():
        state = _default_state()
        _write_state(state_path, state)
        return state

    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("version") != 1:
        raise ValueError(f"Unsupported backfill state version: {state.get('version')}")
    return state


def mark_preview_ready(path: str | Path, batch_id: str, inputs: list[str]) -> dict[str, Any]:
    if not batch_id:
        raise ValueError("batch_id is required")

    state_path = Path(path)
    state = load_or_init_state(state_path)
    state["preview"] = {
        "ready": True,
        "batch_id": batch_id,
        "inputs": list(inputs),
        "marked_at": _now_iso(),
    }
    state["run"]["status"] = "pending"
    state["run"]["last_error"] = None
    state["run"]["started_at"] = None
    state["run"]["ended_at"] = None
    _write_state(state_path, state)
    return state


def mark_stage(
    path: str | Path, stage: str, status: str, detail: dict[str, Any] | str | None
) -> dict[str, Any]:
    if not stage:
        raise ValueError("stage is required")
    if status not in {"pending", "running", "success", "failed", "skipped"}:
        raise ValueError(f"invalid stage status: {status}")

    state_path = Path(path)
    state = load_or_init_state(state_path)
    state["stages"][stage] = {
        "status": status,
        "detail": detail,
        "updated_at": _now_iso(),
        "batch_id": state["preview"].get("batch_id"),
    }
    if status == "running" and state["run"]["started_at"] is None:
        state["run"]["started_at"] = _now_iso()
        state["run"]["status"] = "running"
    _write_state(state_path, state)
    return state


def mark_run_complete(path: str | Path, success: bool) -> dict[str, Any]:
    state_path = Path(path)
    state = load_or_init_state(state_path)
    state["run"]["status"] = "success" if success else "failed"
    state["run"]["ended_at"] = _now_iso()
    state["preview"]["ready"] = False
    _write_state(state_path, state)
    return state
