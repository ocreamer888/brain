import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from unittest.mock import patch

from brain.core.summarizer import summarize_session


def test_summarize_session_returns_required_keys():
    """summarize_session must return dict with summary, decisions, next_steps."""
    fake_json = '{"summary": "Worked on brain fixes.", "decisions": ["Use project_context type"], "next_steps": ["Ship it"]}'

    with patch("brain.core.summarizer._openrouter_chat", return_value=fake_json):
        messages = [
            {"role": "user", "content": "fix the session start"},
            {"role": "assistant", "content": "done"},
        ]
        result = summarize_session(messages)

    assert "summary" in result
    assert "decisions" in result
    assert "next_steps" in result
    assert isinstance(result["decisions"], list)
    assert isinstance(result["next_steps"], list)


def test_summarize_session_handles_empty_messages():
    """summarize_session must not crash on empty message list."""
    fake_json = '{"summary": "No activity.", "decisions": [], "next_steps": []}'

    with patch("brain.core.summarizer._openrouter_chat", return_value=fake_json):
        result = summarize_session([])

    assert result["summary"] == "No activity."
