"""Test that session_end deduplicates exports by session_id while preserving timestamps."""
import json
from pathlib import Path
import tempfile


def _do_export(export_dir: Path, session_id: str, message_count: int) -> Path:
    """Call the extracted find-or-create logic from session_end.py."""
    from brain.hooks.session_end import find_or_create_export_path
    export_file, _is_new = find_or_create_export_path(export_dir, session_id)
    data = {
        "session_id": session_id,
        "project": "test",
        "cwd": "/test",
        "ended_at": "2026-01-01T00:00:00Z",
        "message_count": message_count,
        "messages": [],
    }
    export_file.write_text(json.dumps(data))
    return export_file


def test_first_export_uses_timestamp_name():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        path = _do_export(p, "abc-123", 10)
        # Should contain timestamp pattern, not just session_id
        assert path.suffix == ".json"
        assert path.name.startswith("session_")
        assert "abc-123" not in path.name  # NOT named by session_id


def test_second_export_same_session_overwrites_original():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        first_path = _do_export(p, "abc-123", 10)
        first_name = first_path.name  # e.g. session_2026-04-10_10-00-00.json

        second_path = _do_export(p, "abc-123", 20)

        files = list(p.glob("session_*.json"))
        assert len(files) == 1, f"Expected 1 file, got {len(files)}: {[f.name for f in files]}"
        assert second_path.name == first_name  # same filename preserved
        data = json.loads(second_path.read_text())
        assert data["message_count"] == 20  # content updated


def test_different_sessions_create_separate_files():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        import time
        _do_export(p, "session-aaa", 5)
        time.sleep(0.01)  # ensure different timestamp
        _do_export(p, "session-bbb", 5)
        files = list(p.glob("session_*.json"))
        assert len(files) == 2
