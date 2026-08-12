"""A4 — `save_memory_batch` carries caller-supplied entities, and NEVER extracts.

The batch path is pass-through only by design: every caller is a bulk/migration
script with no per-item resume, so the checkpointed backfill handles their
edgeless rows instead. These tests pin both halves of that contract.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from brain import api_client


@pytest.fixture
def captured(monkeypatch):
    """Capture the single _request call save_memory_batch makes."""
    calls: list[dict] = []

    def fake_request(method, path, payload=None, timeout=10):
        calls.append(
            {"method": method, "path": path, "payload": payload, "timeout": timeout}
        )
        return {"results": []}

    monkeypatch.setattr(api_client, "_request", fake_request)
    return calls


@pytest.fixture
def no_extraction(monkeypatch):
    """Make any extraction attempt from the batch path an immediate failure.

    `_maybe_extract_entities` is the only door to the extractor in this module,
    so blowing up here proves the batch path never opens it.
    """

    def boom(**kwargs):
        raise AssertionError(
            "save_memory_batch must never call _maybe_extract_entities"
        )

    monkeypatch.setattr(api_client, "_maybe_extract_entities", boom)


def _items(calls):
    assert len(calls) == 1
    call = calls[0]
    assert call["method"] == "POST"
    assert call["path"] == "/save-batch"
    assert call["timeout"] == 120
    return call["payload"]["items"]


def test_provided_entities_pass_through(captured, no_extraction):
    api_client.save_memory_batch(
        [{"content": "c", "memory_type": "solution", "entities": ["Rust", "SQLite"]}]
    )
    assert _items(captured)[0]["entities"] == ["Rust", "SQLite"]


def test_absent_entities_key_omitted(captured, no_extraction):
    api_client.save_memory_batch([{"content": "c", "memory_type": "conversation"}])
    assert "entities" not in _items(captured)[0]


def test_empty_entities_key_omitted(captured, no_extraction):
    api_client.save_memory_batch(
        [{"content": "c", "memory_type": "solution", "entities": []}]
    )
    assert "entities" not in _items(captured)[0]


def test_durable_type_without_entities_never_extracts(captured, no_extraction):
    """A durable type with no entities is exactly the case save_memory extracts on."""
    api_client.save_memory_batch(
        [{"content": "Fixed the WAL checkpoint stall", "memory_type": "solution"}]
    )
    assert "entities" not in _items(captured)[0]


def test_default_auto_entities_true_still_never_extracts(captured, no_extraction):
    """The symmetry parameter is inert — even True must not reach the extractor."""
    api_client.save_memory_batch(
        [{"content": "c", "memory_type": "solution"}], default_auto_entities=True
    )
    assert "entities" not in _items(captured)[0]


def test_default_auto_entities_false_accepted_as_kwarg(captured, no_extraction):
    """Pins the kwarg the three bulk call sites pass; a rename breaks them."""
    api_client.save_memory_batch(
        [{"content": "c", "memory_type": "project_context"}],
        default_auto_entities=False,
    )
    assert len(_items(captured)) == 1


def test_per_item_independence(captured, no_extraction):
    api_client.save_memory_batch(
        [
            {"content": "a", "memory_type": "solution", "entities": ["Tokio"]},
            {"content": "b", "memory_type": "solution"},
        ]
    )
    items = _items(captured)
    assert len(items) == 2
    assert items[0]["entities"] == ["Tokio"]
    assert "entities" not in items[1]


def test_other_fields_unaffected(captured, no_extraction):
    """Entities pass-through must not disturb the existing whitelist."""
    api_client.save_memory_batch(
        [
            {
                "content": "c",
                "memory_type": "pattern",
                "tags": ["t"],
                "project": "brain",
                "session_id": "s1",
                "source": "src",
                "file_path": "/tmp/f",
                "title": "T",
                "timestamp": "2026-07-28T00:00:00Z",
                "entities": ["E"],
            }
        ]
    )
    body = _items(captured)[0]
    assert body == {
        "content": "c",
        "memory_type": "pattern",
        "tags": ["t"],
        "project": "brain",
        "session_id": "s1",
        "source": "src",
        "file_path": "/tmp/f",
        "title": "T",
        "timestamp": "2026-07-28T00:00:00Z",
        "entities": ["E"],
    }
