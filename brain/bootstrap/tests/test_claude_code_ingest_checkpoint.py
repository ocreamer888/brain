"""Test that ingest_claude_code checkpoints by session_id from JSON, not filename."""
import json
import sys
from pathlib import Path
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


def make_session_file(directory: Path, filename: str, session_id: str) -> Path:
    data = {
        "session_id": session_id,
        "project": "test",
        "cwd": "/test",
        "ended_at": "2026-01-01T00:00:00Z",
        "message_count": 2,
        "messages": [
            {"role": "user", "content": "hello world, what is rust?"},
            {"role": "assistant", "content": "Rust is a systems language focused on safety."},
        ],
    }
    p = directory / filename
    p.write_text(json.dumps(data))
    return p


def test_checkpoint_uses_session_id_not_filename(tmp_path, monkeypatch):
    """Two files, same session_id — only ONE memory should be saved."""
    sessions_dir = tmp_path / "sessions_export"
    sessions_dir.mkdir()
    cp_path = tmp_path / "checkpoint.json"

    make_session_file(sessions_dir, "session_2026-04-03_06-00-00.json", "real-uuid-abc")
    make_session_file(sessions_dir, "session_2026-04-03_07-00-00.json", "real-uuid-abc")

    saved = []
    monkeypatch.setattr(
        "brain.bootstrap.ingest_claude_code_lib.save_memory_batch",
        lambda items: saved.extend(items) or {"results": [{"index": i} for i in range(len(items))]},
    )

    from brain.bootstrap.ingest_claude_code_lib import run_with_dirs
    run_with_dirs(sessions_dir=sessions_dir, checkpoint_path=cp_path, use_llm=False)

    assert len(saved) == 1  # only one save, not two
    cp_data = json.loads(cp_path.read_text())
    assert "real-uuid-abc" in cp_data["processed_ids"]
