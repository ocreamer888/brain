import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest
import chromadb
from unittest.mock import patch, MagicMock


def make_in_memory_client():
    return chromadb.EphemeralClient()


def test_get_memories_collection_creates_if_not_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAIN_DB_PATH", str(tmp_path / "db"))
    import importlib
    import brain.core.db as db_module
    db_module._client = None
    with patch.object(db_module, 'DB_PATH', tmp_path / "db"):
        col = db_module.get_memories_collection()
        assert col.name == "memories"


def test_upsert_and_query_memory(tmp_path, monkeypatch):
    import brain.core.db as db_module
    db_module._client = chromadb.EphemeralClient()
    col = db_module.get_memories_collection()

    db_module.upsert_memory(
        id="test-1",
        document="Solved CORS issue with Express proxy",
        embedding=[0.1] * 768,
        metadata={"type": "solution", "project": "bella", "tags": "cors,express"}
    )

    results = db_module.query_memories(embedding=[0.1] * 768, n_results=1)
    assert results["ids"][0][0] == "test-1"
    assert "CORS" in results["documents"][0][0]


def test_count_memories(tmp_path):
    import brain.core.db as db_module
    db_module._client = chromadb.EphemeralClient()
    # chromadb 1.x EphemeralClient instances share state — reset collection for isolation
    try:
        db_module._client.delete_collection("memories")
    except Exception:
        pass
    assert db_module.count_memories() == 0
    db_module.upsert_memory("id-1", "test doc", [0.1] * 768, {"type": "solution"})
    assert db_module.count_memories() == 1
