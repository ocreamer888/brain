"""Cursor adapter maps Cursor hook JSON onto Brain Claude-style payloads."""
import json

from brain.hooks.cursor_adapter import (
    SKIP_EVENTS,
    claude_post_tool,
    claude_prompt,
    claude_session_end,
    event_name,
    handle,
    resolve_cwd,
    resolve_session_id,
)


def test_session_start_event():
    ctx = {
        "hook_event_name": "sessionStart",
        "session_id": "sess-1",
        "workspace_roots": ["/Users/Shared/Code/magic-portfolio"],
        "is_background_agent": False,
        "composer_mode": "agent",
    }
    assert event_name(ctx) == "sessionStart"
    assert resolve_cwd(ctx) == "/Users/Shared/Code/magic-portfolio"
    assert resolve_session_id(ctx) == "sess-1"


def test_prompt_maps_cwd_and_text():
    ctx = {
        "hook_event_name": "beforeSubmitPrompt",
        "conversation_id": "conv-9",
        "prompt": "are hooks working?",
        "workspace_roots": ["/tmp/proj"],
    }
    payload = claude_prompt(ctx)
    assert payload["prompt"] == "are hooks working?"
    assert payload["session_id"] == "conv-9"
    assert payload["cwd"] == "/tmp/proj"


def test_shell_post_tool_maps_to_bash():
    ctx = {
        "hook_event_name": "postToolUse",
        "tool_name": "Shell",
        "tool_input": {"command": "npm test"},
        "tool_output": "{\"exitCode\":0}",
        "cwd": "/repo",
        "conversation_id": "c1",
    }
    payload = claude_post_tool(ctx)
    assert payload["tool_name"] == "Bash"
    assert payload["tool_input"]["command"] == "npm test"
    assert "exitCode" in payload["tool_response"]


def test_after_file_edit_maps_to_edit():
    ctx = {
        "hook_event_name": "afterFileEdit",
        "file_path": "/repo/src/app.ts",
        "edits": [{"old_string": "a", "new_string": "b"}],
        "workspace_roots": ["/repo"],
    }
    payload = claude_post_tool(ctx, tool_name="Edit")
    assert payload["tool_name"] == "Edit"
    assert payload["tool_input"]["file_path"] == "/repo/src/app.ts"
    assert payload["tool_input"]["old_string"] == "a"
    assert payload["tool_input"]["new_string"] == "b"


def test_write_normalizes_path_and_contents():
    ctx = {
        "tool_name": "Write",
        "tool_input": {"path": "/repo/README.md", "contents": "# hi"},
    }
    payload = claude_post_tool(ctx)
    assert payload["tool_name"] == "Write"
    assert payload["tool_input"]["file_path"] == "/repo/README.md"
    assert payload["tool_input"]["content"] == "# hi"


def test_session_end_payload():
    ctx = {
        "hook_event_name": "sessionEnd",
        "session_id": "s2",
        "transcript_path": "/tmp/t.jsonl",
        "workspace_roots": ["/repo"],
        "reason": "completed",
    }
    payload = claude_session_end(ctx)
    assert payload["session_id"] == "s2"
    assert payload["transcript_path"] == "/tmp/t.jsonl"
    assert payload["cwd"] == "/repo"
    assert payload["hook_event_name"] == "Stop"


def test_skip_events_return_empty(monkeypatch):
    for event in ("stop", "afterShellExecution", "preToolUse", "afterAgentThought"):
        out = handle({"hook_event_name": event, "session_id": "x"})
        assert out == {}


def test_unknown_json_event_empty():
    assert handle({}) == {}


def test_before_submit_continue_without_running_network(monkeypatch):
    captured = {}

    def fake_run(script, payload, cwd):
        captured["script"] = script
        captured["payload"] = payload
        return "Relevant brain context:\n  (fact) hello"

    monkeypatch.setattr("brain.hooks.cursor_adapter.run_brain_hook", fake_run)
    monkeypatch.setattr("brain.hooks.cursor_adapter._stash_inject", lambda *a, **k: None)
    out = handle({
        "hook_event_name": "beforeSubmitPrompt",
        "prompt": "what did we decide about hooks?",
        "conversation_id": "c",
        "workspace_roots": ["/repo"],
    })
    assert out == {"continue": True}
    assert captured["script"] == "user_prompt_submit.py"
    assert "hooks" in captured["payload"]["prompt"]
