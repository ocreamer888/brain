from __future__ import annotations

from brain.tools.backfill_state import (
    load_or_init_state,
    mark_preview_ready,
    mark_run_complete,
    mark_stage,
)


def test_new_state_defaults(tmp_path):
    state = load_or_init_state(tmp_path / "state.json")
    assert state["version"] == 1
    assert state["preview"]["ready"] is False
    assert state["run"]["status"] == "idle"


def test_state_transitions(tmp_path):
    state_path = tmp_path / "state.json"
    mark_preview_ready(state_path, "batch-1", ["in/a", "in/b"])
    state = load_or_init_state(state_path)
    assert state["preview"]["ready"] is True
    assert state["preview"]["batch_id"] == "batch-1"
    assert state["preview"]["inputs"] == ["in/a", "in/b"]

    mark_stage(state_path, "ingest_claude_code", "success", {"rows": 3})
    state = load_or_init_state(state_path)
    assert state["stages"]["ingest_claude_code"]["status"] == "success"
    assert state["stages"]["ingest_claude_code"]["batch_id"] == "batch-1"

    mark_run_complete(state_path, success=True)
    state = load_or_init_state(state_path)
    assert state["run"]["status"] == "success"
