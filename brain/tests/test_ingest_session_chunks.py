import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from brain.tools.ingest_session_chunks import chunk_session


def make_session(pairs):
    messages = []
    for user_text, asst_text in pairs:
        messages.append({"type": "user", "message": {"role": "user", "content": user_text}})
        messages.append(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": asst_text}],
                },
            }
        )
    return {"session_id": "test-session", "project": "test", "messages": messages}


def test_chunk_session_pairs_user_assistant():
    session = make_session(
        [("hello how are you today?", "I am doing well, thank you for asking!")]
    )
    chunks = chunk_session(session)
    assert len(chunks) == 1
    assert "User:" in chunks[0]["content"]
    assert "Assistant:" in chunks[0]["content"]
    assert chunks[0]["session_id"] == "test-session"


def test_chunk_session_skips_short_exchanges():
    session = make_session([("hi", "ok")])  # too short
    chunks = chunk_session(session)
    assert len(chunks) == 0


def test_chunk_session_filters_non_user_assistant():
    session = {
        "session_id": "s1",
        "project": "p",
        "messages": [
            {"type": "system", "message": {"content": "system msg"}},
            {"type": "file-history-snapshot", "snapshot": {}},
            {
                "type": "user",
                "message": {"role": "user", "content": "what is rust?"},
            },
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": "Rust is a systems programming language focused on safety and performance.",
                        }
                    ],
                },
            },
        ],
    }
    chunks = chunk_session(session)
    assert len(chunks) == 1


def test_chunk_session_multiple_pairs():
    session = make_session(
        [
            ("what is rust exactly?", "Rust is a systems programming language focused on safety."),
            ("what is python exactly?", "Python is a high-level scripting language used widely."),
        ]
    )
    chunks = chunk_session(session)
    assert len(chunks) == 2


def test_load_checkpoint_reads_session_ids():
    """Checkpoint stores session_ids, not filenames."""
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
        json.dump({"session_ids": ["uuid-1", "uuid-2"]}, f)
        cp_path = Path(f.name)
    from brain.tools.ingest_session_chunks import load_checkpoint
    result = load_checkpoint(cp_path)
    assert "uuid-1" in result
    assert "uuid-2" in result


def test_main_skips_already_processed_session_id(tmp_path, monkeypatch):
    """Two files with same session_id: only first is processed."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    cp_path = tmp_path / "checkpoint.json"

    session_data = {
        "session_id": "dup-session-uuid",
        "project": "test",
        "cwd": "/test",
        "ended_at": "2026-01-01T00:00:00Z",
        "message_count": 2,
        "messages": [
            {"type": "user", "message": {"role": "user", "content": "what is rust exactly?"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Rust is a systems programming language focused on safety and performance."}]}},
        ],
    }
    # Two files, same session_id
    (sessions_dir / "session_2026-04-03_06-39.json").write_text(json.dumps(session_data))
    (sessions_dir / "session_2026-04-03_07-11.json").write_text(json.dumps(session_data))

    saved = []
    monkeypatch.setattr(
        "brain.tools.ingest_session_chunks.save_memory_batch",
        lambda chunks, **kwargs: saved.extend(chunks),
    )
    monkeypatch.setattr("brain.tools.ingest_session_chunks.SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr("brain.tools.ingest_session_chunks.CHECKPOINT", cp_path)

    import sys
    monkeypatch.setattr(sys, "argv", ["ingest_session_chunks.py", "--all"])
    from brain.tools.ingest_session_chunks import main
    main()

    # Session has 1 exchange → 1 chunk. Should only be saved ONCE even with 2 files.
    assert len(saved) == 1
