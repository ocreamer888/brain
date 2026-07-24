"""Tests for brain/tools/backfill_facts.py.

All external calls are mocked (extract_facts, curate_facts).
Tests cover: episode text builder, checkpoint I/O, single-file mode,
project filter, limit, trivial-session skip, Cursor DB builder/inference.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from brain.tools.backfill_facts import (
    _build_cursor_episode,
    _build_episode_text,
    _extract_text,
    _infer_cursor_project,
    load_checkpoint,
    process_session,
    save_checkpoint,
)
from brain.ingest.fact_extractor import FactDraft
from brain.ingest.fact_curator import CurationResult


# ---------------------------------------------------------------------------
# _extract_text
# ---------------------------------------------------------------------------

def test_extract_text_str_content() -> None:
    msg = {"message": {"content": "hello world"}}
    assert _extract_text(msg) == "hello world"


def test_extract_text_list_content() -> None:
    msg = {"message": {"content": [
        {"type": "text", "text": "part one"},
        {"type": "tool_use", "name": "Read"},
        {"type": "text", "text": "part two"},
    ]}}
    result = _extract_text(msg)
    assert "part one" in result
    assert "part two" in result


def test_extract_text_flat_content() -> None:
    """Recovered session format: content at top level, not nested under 'message'."""
    msg = {"role": "user", "content": "flat content here"}
    assert _extract_text(msg) == "flat content here"


def test_extract_text_empty() -> None:
    assert _extract_text({}) == ""
    assert _extract_text({"message": {}}) == ""


# ---------------------------------------------------------------------------
# _build_episode_text
# ---------------------------------------------------------------------------

def _msg(role: str, text: str) -> dict:
    return {"role": role, "message": {"content": text}}


def test_build_episode_text_basic() -> None:
    msgs = [
        _msg("user", "How do we configure the brain API database path and port?"),
        _msg("assistant", "The brain API runs on port 8787 by default, configurable via BRAIN_API_BIND."),
    ]
    result = _build_episode_text(msgs)
    assert "User: How do we configure" in result
    assert "Assistant: The brain API runs on port 8787" in result


def test_build_episode_text_skips_local_commands() -> None:
    msgs = [
        _msg("user", "<local-command-caveat>some system content injected here</local-command-caveat>"),
        _msg("user", "How does the fact extractor decide salience scores for each extracted fact?"),
        _msg("assistant", "Salience reflects how actionable or reusable the fact is across future sessions."),
    ]
    result = _build_episode_text(msgs)
    assert "<local-command" not in result
    assert "fact extractor" in result


def test_build_episode_text_skips_short_messages() -> None:
    msgs = [
        _msg("user", "ok"),  # too short (< 30 chars)
        _msg("assistant", "A" * 100),
    ]
    result = _build_episode_text(msgs)
    assert "User: ok" not in result
    assert "Assistant: " in result


def test_build_episode_text_skips_non_user_assistant() -> None:
    msgs = [
        {"type": "last-prompt", "message": {"content": "system content here that is long enough to pass threshold"}},
        _msg("user", "What does the brain persistent memory system store across sessions?"),
        _msg("assistant", "It stores facts, decisions, error fixes, and project context across sessions."),
    ]
    result = _build_episode_text(msgs)
    assert "system content" not in result
    assert "brain" in result


def test_build_episode_text_respects_max_chars() -> None:
    long_text = "x" * 900
    msgs = [_msg("user", long_text), _msg("assistant", long_text)] * 20
    result = _build_episode_text(msgs, max_chars=3000)
    assert len(result) <= 3200  # small buffer for prefix/newlines


# ---------------------------------------------------------------------------
# Checkpoint I/O
# ---------------------------------------------------------------------------

def test_checkpoint_roundtrip(tmp_path: Path) -> None:
    cp = tmp_path / "cp.json"
    save_checkpoint({"id-1", "id-2"}, cp)  # type: ignore[call-arg]
    loaded = load_checkpoint(cp)  # type: ignore[call-arg]
    assert loaded == {"id-1", "id-2"}


def test_checkpoint_missing_returns_empty(tmp_path: Path) -> None:
    cp = tmp_path / "nonexistent.json"
    assert load_checkpoint(cp) == set()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# process_session
# ---------------------------------------------------------------------------

def _make_session(project: str = "test", session_id: str = "sid-001") -> dict:
    return {
        "session_id": session_id,
        "project": project,
        "messages": [
            {"role": "user", "message": {"content": "How do we configure the brain API?"}},
            {"role": "assistant", "message": {
                "content": "Set BRAIN_API_AUTH_REQUIRED=0 in your environment and point BRAIN_DB_PATH to the SQLite file."
            }},
            {"role": "user", "message": {"content": "What port does it use?"}},
            {"role": "assistant", "message": {
                "content": "The brain API binds on port 8787 by default, configurable via BRAIN_API_BIND."
            }},
        ],
    }


def test_process_session_dry_run_returns_zeros(capsys) -> None:
    session = _make_session()
    a, u, m = process_session(session, "batch-1", dry_run=True)
    assert (a, u, m) == (0, 0, 0)
    captured = capsys.readouterr()
    assert "dry-run" in captured.out


def test_process_session_skips_trivial(monkeypatch: pytest.MonkeyPatch) -> None:
    session = {"session_id": "s", "project": "test", "messages": [
        {"role": "user", "message": {"content": "hi"}},
    ]}
    a, u, m = process_session(session, "batch-1")
    assert (a, u, m) == (0, 0, 0)


def test_process_session_calls_extract_and_curate(monkeypatch: pytest.MonkeyPatch) -> None:
    draft = FactDraft(
        content="Brain API uses port 8787",
        salience=0.9, event_time=None, entities=[], fact_type="decision",
    )
    monkeypatch.setattr(
        "brain.tools.backfill_facts.extract_facts",
        lambda **kw: [draft],
    )
    curate_result = CurationResult(added=["new-uuid-001"])
    monkeypatch.setattr(
        "brain.tools.backfill_facts.curate_facts",
        lambda **kw: curate_result,
    )
    a, u, m = process_session(_make_session(), "batch-x")
    assert a == 1
    assert u == 0
    assert m == 0


def test_process_session_handles_extract_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(**kw):
        raise RuntimeError("LLM timeout")
    monkeypatch.setattr("brain.tools.backfill_facts.extract_facts", _raise)
    a, u, m = process_session(_make_session(), "batch-x")
    assert (a, u, m) == (0, 0, 0)


def test_process_session_empty_facts_returns_zeros(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "brain.tools.backfill_facts.extract_facts",
        lambda **kw: [],
    )
    a, u, m = process_session(_make_session(), "batch-x")
    assert (a, u, m) == (0, 0, 0)


# ---------------------------------------------------------------------------
# _build_cursor_episode
# ---------------------------------------------------------------------------

def _bubble(btype: int, text: str, relevant_files: list[str] | None = None) -> dict:
    return {"type": btype, "text": text, "relevantFiles": relevant_files or []}


def test_build_cursor_episode_basic() -> None:
    bubbles = [
        _bubble(1, "How do I configure the brain API port?"),
        _bubble(2, "Set BRAIN_API_BIND env var to the desired address and port."),
    ]
    result = _build_cursor_episode(bubbles)
    assert "User: How do I configure" in result
    assert "Assistant: Set BRAIN_API_BIND" in result


def test_build_cursor_episode_skips_short() -> None:
    bubbles = [
        _bubble(1, "ok"),  # < 30 chars
        _bubble(2, "Sure, " + "x" * 50),
    ]
    result = _build_cursor_episode(bubbles)
    assert "User: ok" not in result
    assert "Assistant:" in result


def test_build_cursor_episode_skips_empty_text() -> None:
    bubbles = [
        _bubble(2, ""),  # assistant with no text (diff-only bubble)
        _bubble(1, "What did that change do to the layout?"),
        _bubble(2, "It wrapped the body in a flex column so the footer stays pinned."),
    ]
    result = _build_cursor_episode(bubbles)
    assert "User: What did that change" in result
    assert "Assistant: It wrapped" in result


def test_build_cursor_episode_respects_max_chars() -> None:
    bubbles = [_bubble(1, "x" * 900), _bubble(2, "y" * 900)] * 20
    result = _build_cursor_episode(bubbles, max_chars=3000)
    assert len(result) <= 3200


def test_build_cursor_episode_empty_bubbles_returns_empty() -> None:
    assert _build_cursor_episode([]) == ""


# ---------------------------------------------------------------------------
# _infer_cursor_project
# ---------------------------------------------------------------------------

def test_infer_cursor_project_from_src_path() -> None:
    bubbles = [_bubble(1, "x" * 50, relevant_files=["landingpage/src/components/Foo.tsx"])]
    assert _infer_cursor_project(bubbles) == "landingpage"


def test_infer_cursor_project_from_absolute_path() -> None:
    bubbles = [_bubble(1, "x" * 50, relevant_files=[
        "/Users/macm1air/Documents/Code/meddefi_AI/landingpage/src/components/Bar.tsx"
    ])]
    assert _infer_cursor_project(bubbles) == "landingpage"


def test_infer_cursor_project_fallback() -> None:
    bubbles = [_bubble(1, "x" * 50, relevant_files=[])]
    assert _infer_cursor_project(bubbles) == "cursor"


def test_infer_cursor_project_no_relevant_files() -> None:
    bubbles = [_bubble(2, "Some answer with no files")]
    assert _infer_cursor_project(bubbles) == "cursor"


# ---------------------------------------------------------------------------
# Phase 7: ended_at forwarded as source_event_time
# ---------------------------------------------------------------------------

def test_process_session_passes_ended_at(monkeypatch):
    """ended_at from session JSON is forwarded as source_event_time."""
    captured = {}
    def mock_curate(new_facts, project, batch_id, session_id, source_event_time=None, **kw):
        captured["source_event_time"] = source_event_time
        return CurationResult()
    def mock_extract(*a, **kw):
        return [FactDraft("fact", 0.8, None, [], "decision", "v1")]

    monkeypatch.setattr("brain.tools.backfill_facts.extract_facts", mock_extract)
    monkeypatch.setattr("brain.tools.backfill_facts.curate_facts", mock_curate)

    session = {
        "session_id": "abc",
        "project": "test",
        "ended_at": "2026-04-15T10:00:00+00:00",
        "messages": [{"role": "user", "content": "x" * 300}],
    }
    process_session(session, batch_id="b1")
    assert captured.get("source_event_time") == "2026-04-15T10:00:00+00:00"
