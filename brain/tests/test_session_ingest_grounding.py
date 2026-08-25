"""Tests: session_ingest normalizes Claude JSONL and drops ungrounded LLM extracts."""
from __future__ import annotations

from unittest.mock import patch

from brain.core.session_ingest import save_session_extracted


def _claude_user(text: str) -> dict:
    return {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }


def _claude_assistant(text: str) -> dict:
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }


def test_save_session_extracted_skips_non_substantive_claude_meta():
    """Empty-role Claude meta rows must not trigger LLM recycling."""
    messages = [
        {"type": "last-prompt", "sessionId": "s"},
        {"type": "mode", "mode": "default", "sessionId": "s"},
        _claude_user("Hi"),
    ]
    with patch("brain.core.session_ingest.summarize_session") as mock_sum, \
         patch("brain.core.summarizer.extract_error_fix_pairs") as mock_err, \
         patch("brain.core.summarizer.extract_decisions") as mock_dec, \
         patch("brain.core.session_ingest.save_memory_fn") as mock_save:
        save_session_extracted(
            messages=messages,
            project="brain",
            session_id="s1",
            ended_at="2026-08-06T22:00:00+00:00",
        )
        mock_err.assert_not_called()
        mock_dec.assert_not_called()
        mock_sum.assert_not_called()
        mock_save.assert_not_called()


def test_save_session_extracted_drops_ungrounded_error_and_decision():
    messages = [
        _claude_user("Fix the brain rate limiter 429 flood from Viewer /stats."),
        _claude_assistant(
            "Raised BRAIN_API_RATE_LIMIT_MAX_REQUESTS to 2000 on com.brain.api plist."
        ),
    ]
    hallucinated_pairs = [
        {
            "error": "NameError: name 'x' is not defined",
            "cause": "undeclared",
            "fix": "declare x",
            "files": ["main.py"],
        },
        {
            "error": "MCP 429 flood from Viewer /stats",
            "cause": "shared rate bucket",
            "fix": "raised BRAIN_API_RATE_LIMIT_MAX_REQUESTS to 2000",
            "files": [],
        },
    ]
    hallucinated_decisions = [
        {
            "decision": "Used dependency injection for database connections",
            "context": "testing",
        },
        {
            "decision": "Raised BRAIN_API_RATE_LIMIT_MAX_REQUESTS to 2000",
            "context": "stop MCP 429 floods",
        },
    ]
    real_summary = {
        "summary": "Fixed brain rate limiter 429 floods by raising BRAIN_API_RATE_LIMIT_MAX_REQUESTS to 2000.",
        "decisions": ["Raised BRAIN_API_RATE_LIMIT_MAX_REQUESTS to 2000"],
        "next_steps": [],
    }

    with patch("brain.hooks.corpus_barrier.should_save", return_value=True), \
         patch("brain.core.summarizer.extract_error_fix_pairs", return_value=hallucinated_pairs), \
         patch("brain.core.summarizer.extract_decisions", return_value=hallucinated_decisions), \
         patch("brain.core.session_ingest.summarize_session", return_value=real_summary), \
         patch("brain.core.session_ingest.save_memory_fn") as mock_save:
        save_session_extracted(
            messages=messages,
            project="brain",
            session_id="s2",
            ended_at="2026-08-06T22:00:00+00:00",
        )

    saved_types = [c.kwargs["memory_type"] for c in mock_save.call_args_list]
    saved_contents = [c.kwargs["content"] for c in mock_save.call_args_list]

    assert "error_lesson" in saved_types
    assert "pattern" in saved_types
    assert "project_context" in saved_types
    assert not any("NameError" in c for c in saved_contents)
    assert not any("dependency injection" in c for c in saved_contents)
    assert any("429" in c or "RATE_LIMIT" in c for c in saved_contents)


def test_save_session_summary_rejects_ungrounded_summary():
    messages = [
        _claude_user("Fix the brain rate limiter 429 flood."),
        _claude_assistant("Raised BRAIN_API_RATE_LIMIT_MAX_REQUESTS to 2000."),
    ]
    invented = {
        "summary": (
            "The session focused on implementing a custom JSON serialization system "
            "for the application's data models with a JsonSerializable protocol."
        ),
        "decisions": [],
        "next_steps": [],
    }
    with patch("brain.core.session_ingest.summarize_session", return_value=invented), \
         patch("brain.core.session_ingest.save_memory_fn") as mock_save:
        from brain.core.session_ingest import save_session_summary

        save_session_summary(
            messages=messages,
            project="brain",
            session_id="s3",
            ended_at="2026-08-06T22:00:00+00:00",
        )
        mock_save.assert_not_called()
