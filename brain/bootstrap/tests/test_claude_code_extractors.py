"""Tests for Claude Code session extraction helpers."""
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from brain.bootstrap.claude_code_extractors import (
    extract_session_record,
    validate_session_json,
)


def test_extract_session_record_basic(tmp_path):
    """Test basic session record extraction with real JSONL format."""
    session_file = tmp_path / "session_2026-04-02_14-30-45.json"
    session_file.write_text(json.dumps({
        "session_id": "abc-123",
        "project": "AI",
        "cwd": "/Users/macm1air/Documents/AI",
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "message_count": 2,
        "messages": [
            {
                "type": "user",
                "message": {"role": "user", "content": "Add error handling"},
                "uuid": "u1",
            },
            {
                "type": "assistant",
                "message": {"role": "assistant", "content": "I'll add try-catch blocks..."},
                "uuid": "u2",
            },
        ],
    }))

    record = extract_session_record(session_file)
    assert record["session_id"] == "abc-123"
    assert record["project"] == "AI"
    assert "Add error handling" in record["text"]
    assert record["metadata"]["source"] == "claude_code_session"
    assert record["metadata"]["type"] == "conversation"


def test_validate_session_json_valid(tmp_path):
    """Test validation of valid session JSON."""
    session_file = tmp_path / "valid.json"
    session_file.write_text(json.dumps({
        "session_id": "uuid",
        "project": "test",
        "cwd": "/path",
        "ended_at": "2026-04-02T11:00:00Z",
        "messages": [],
    }))

    is_valid, error = validate_session_json(session_file)
    assert is_valid is True
    assert error is None


def test_validate_session_json_missing_field(tmp_path):
    """Test validation rejects missing required fields."""
    session_file = tmp_path / "invalid.json"
    session_file.write_text(json.dumps({
        "session_id": "uuid",
        # Missing "project", "cwd", etc.
    }))

    is_valid, error = validate_session_json(session_file)
    assert is_valid is False
    assert error is not None


def test_full_ingest_pipeline(tmp_path, monkeypatch):
    """Integration test: export → extract → ingest."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

    from brain.bootstrap.claude_code_extractors import SESSIONS_EXPORT_DIR

    # Create a fake session export
    export_dir = tmp_path / "sessions_export"
    export_dir.mkdir()
    monkeypatch.setattr("brain.bootstrap.claude_code_extractors.SESSIONS_EXPORT_DIR", export_dir)

    session_file = export_dir / "session_test.json"
    session_data = {
        "session_id": "integration-test-123",
        "project": "test_project",
        "cwd": "/test/path",
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "message_count": 2,
        "messages": [
            {"type": "user", "message": {"role": "user", "content": "Fix the bug in parser"}, "uuid": "u1"},
            {"type": "assistant", "message": {"role": "assistant", "content": "I found the issue in tokenizer.py"}, "uuid": "u2"},
        ],
    }
    session_file.write_text(json.dumps(session_data))

    # Extract record
    record = extract_session_record(session_file)
    assert record["session_id"] == "integration-test-123"
    assert "Fix the bug" in record["text"]
    assert record["metadata"]["source"] == "claude_code_session"
