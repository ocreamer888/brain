import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from unittest.mock import patch, MagicMock, mock_open


def _run_save_session_summary(messages, project, session_id, ended_at):
    """Extract and call just the summary-saving logic we'll add."""
    # Logic now lives in the shared core module (reused by Claude hook + Hermes provider).
    from brain.core.session_ingest import save_session_summary
    save_session_summary(messages=messages, project=project, session_id=session_id, ended_at=ended_at)


def test_save_session_summary_calls_save_memory():
    """save_session_summary must call save_memory with correct type and tag."""
    fake_summary = {"summary": "Worked on brain.", "decisions": ["Use project_context"], "next_steps": []}

    with patch("brain.core.session_ingest.summarize_session", return_value=fake_summary) as mock_sum, \
         patch("brain.core.session_ingest.save_memory_fn") as mock_save:

        _run_save_session_summary(
            messages=[{"role": "user", "content": "hi"}],
            project="AI",
            session_id="abc-123",
            ended_at="2026-04-11T10:00:00+00:00",
        )

        mock_save.assert_called_once()
        call_kwargs = mock_save.call_args[1]
        assert call_kwargs["memory_type"] == "project_context"
        assert "session_summary" in call_kwargs["tags"]
        assert "2026-04-11" in call_kwargs["title"]
        assert "AI" in call_kwargs["title"]


def test_save_session_summary_skips_trivial_sessions():
    """Sessions with no decisions/next_steps and a 'no actionable' summary must not be saved."""
    trivial = {
        "summary": "No actionable content or decisions were recorded in the session.",
        "decisions": [],
        "next_steps": [],
    }

    with patch("brain.core.session_ingest.summarize_session", return_value=trivial), \
         patch("brain.core.session_ingest.save_memory_fn") as mock_save:

        _run_save_session_summary(
            messages=[{"role": "user", "content": "hi"}],
            project="AI",
            session_id="abc-999",
            ended_at="2026-04-20T10:00:00+00:00",
        )

        mock_save.assert_not_called()


def test_save_session_summary_saves_when_only_next_steps_present():
    """A session with only next_steps (no decisions) still has signal and must save."""
    summary = {
        "summary": "Explored retrieval quality in the brain pipeline.",
        "decisions": [],
        "next_steps": ["Add reranker to search path"],
    }

    with patch("brain.core.session_ingest.summarize_session", return_value=summary), \
         patch("brain.core.session_ingest.save_memory_fn") as mock_save:

        _run_save_session_summary(
            messages=[{"role": "user", "content": "hi"}],
            project="AI",
            session_id="abc-777",
            ended_at="2026-04-20T10:00:00+00:00",
        )

        mock_save.assert_called_once()
