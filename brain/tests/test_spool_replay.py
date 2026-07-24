from __future__ import annotations

import importlib
from pathlib import Path


def test_enqueue_and_metrics(tmp_path, monkeypatch):
    spool = importlib.import_module("brain.hooks.spool")
    monkeypatch.setattr(spool, "SPOOL_DIR", tmp_path)
    monkeypatch.setattr(spool, "SPOOL_FILE", tmp_path / "memory_spool.jsonl")
    monkeypatch.setattr(spool, "DLQ_FILE", tmp_path / "memory_spool_dlq.jsonl")

    key = spool.enqueue_memory({"content": "x", "memory_type": "conversation"}, "boom")
    assert len(key) == 64
    m = spool.metrics()
    assert m["queue_size"] == 1


def test_replay_success_clears_queue(tmp_path, monkeypatch):
    spool = importlib.import_module("brain.hooks.spool")
    monkeypatch.setattr(spool, "SPOOL_DIR", tmp_path)
    monkeypatch.setattr(spool, "SPOOL_FILE", tmp_path / "memory_spool.jsonl")
    monkeypatch.setattr(spool, "DLQ_FILE", tmp_path / "memory_spool_dlq.jsonl")

    spool.enqueue_memory({"content": "x", "memory_type": "conversation"}, "boom")

    import brain.api_client as api_client

    monkeypatch.setattr(
        api_client,
        "save_memory_with_status",
        lambda **kwargs: {"status": "success", "id": "1", "payload": kwargs},
    )

    stats = spool.replay_once()
    assert stats.replayed == 1
    assert spool.metrics()["queue_size"] == 0


def test_replay_moves_to_dlq_after_max_attempts(tmp_path, monkeypatch):
    spool = importlib.import_module("brain.hooks.spool")
    monkeypatch.setattr(spool, "SPOOL_DIR", tmp_path)
    monkeypatch.setattr(spool, "SPOOL_FILE", tmp_path / "memory_spool.jsonl")
    monkeypatch.setattr(spool, "DLQ_FILE", tmp_path / "memory_spool_dlq.jsonl")
    monkeypatch.setattr(spool, "MAX_ATTEMPTS", 2)

    spool.enqueue_memory({"content": "x", "memory_type": "conversation"}, "boom")

    import brain.api_client as api_client

    def fail(**kwargs):
        raise RuntimeError("api down")

    monkeypatch.setattr(api_client, "save_memory_with_status", fail)

    first = spool.replay_once()
    assert first.replayed == 0
    assert first.remaining == 1
    assert first.moved_to_dlq == 0

    second = spool.replay_once()
    assert second.replayed == 0
    assert second.remaining == 0
    assert second.moved_to_dlq == 1
