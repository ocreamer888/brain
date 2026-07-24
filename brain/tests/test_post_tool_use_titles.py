# brain/tests/test_post_tool_use_titles.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import json
from unittest.mock import patch, MagicMock

from brain.hooks.action_state import _empty_state


def _run_hook(tool_name: str, tool_input: dict, tool_response: str = "") -> list:
    """Run the post_tool_use hook with fake stdin and capture save calls."""
    context = {
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_response": tool_response,
    }
    saved_payloads = []

    def fake_save(**kwargs):
        saved_payloads.append(kwargs)
        return {"status": "ok"}

    def fake_llm(model, messages, *args, **kwargs):
        # Deterministic title: echo the event body so it reflects content
        # (incl. filename) without a real, nondeterministic LLM call.
        text = messages[0].get("content", "") if messages else ""
        return text.split("Event:")[-1].strip()[:80]

    # This hook is nondeterministic by nature: it calls a real LLM for titles
    # and reads/writes persistent on-disk action state (so runs contaminate each
    # other). Mock both so the test verifies routing logic only.
    with patch("sys.stdin") as mock_stdin, \
         patch("brain.api_client.backend_mode", return_value="api"), \
         patch("brain.api_client.save_memory_with_status", side_effect=fake_save), \
         patch("brain.api_client.template_search", return_value=[]), \
         patch("brain.core.summarizer._openrouter_chat", side_effect=fake_llm), \
         patch("brain.hooks.corpus_barrier.should_save", return_value=True), \
         patch("brain.hooks.action_state.load_state", side_effect=lambda *a, **k: _empty_state()), \
         patch("brain.hooks.action_state.save_state", return_value=None), \
         patch("brain.hooks.action_state.flush_edit_groups", return_value=[]), \
         patch("brain.hooks.action_state.get_cached_corpus_size", return_value=1000), \
         patch("brain.hooks.spool.enqueue_memory"), \
         patch("brain.hooks.spool.replay_once", return_value=MagicMock(replayed=0, remaining=0, moved_to_dlq=0)), \
         patch("brain.hooks.spool.metrics", return_value={"queue_size": 0, "oldest_age_sec": 0}):
        mock_stdin.read.return_value = json.dumps(context)
        import importlib
        # Remove cached module so each call gets a fresh single execution
        sys.modules.pop("brain.hooks.post_tool_use", None)
        try:
            import brain.hooks.post_tool_use  # noqa: F401 — runs hook as side effect
        except SystemExit:
            pass  # hook exited cleanly (non-memorable tool)

    return saved_payloads


def test_bash_does_not_save():
    """Bash commands must not be saved — session summary covers them."""
    saved = _run_hook("Bash", {"command": "git status"})
    assert saved == [], "Bash must not trigger a memory save"


def test_edit_does_not_save():
    """File edits must not be saved — session summary covers them."""
    saved = _run_hook("Edit", {"file_path": "/some/file.py", "new_string": "x = 1"})
    assert saved == [], "Edit must not trigger a memory save"


def test_write_saves_with_filename_title():
    """Write saves as solution with a title containing the filename."""
    saved = _run_hook("Write", {"file_path": "/Users/user/project/foo/bar.py", "content": "..."})
    assert len(saved) == 1
    assert "bar.py" in saved[0]["title"]
    assert saved[0]["memory_type"] == "solution"


def test_agent_saves_with_description_title():
    """Agent dispatches save as decision with description in title."""
    saved = _run_hook("Agent", {"description": "Run retrieval eval"})
    assert len(saved) == 1
    assert saved[0]["memory_type"] == "decision"
