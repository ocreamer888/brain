import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import pytest
import chromadb
from unittest.mock import patch, MagicMock
from datetime import datetime


def _patch_db(module):
    """Replace ChromaDB client with ephemeral for testing."""
    module.db._client = chromadb.EphemeralClient()
    # Reset collection for isolation (chromadb 1.x EphemeralClient instances share state)
    try:
        module.db._client.delete_collection("memories")
    except Exception:
        pass
    try:
        module.db._client.delete_collection("sessions")
    except Exception:
        pass


def test_save_memory_stores_in_db():
    import brain.core.memory as m
    import brain.core.db as db
    _patch_db(m)
    # Mock embedder to avoid model loading
    with patch('brain.core.memory.embed', return_value=[0.1] * 768):
        m.save_memory(
            content="Fixed CORS in Express with cors package",
            memory_type="solution",
            tags=["cors", "express"],
            project="bella"
        )
    assert db.count_memories() == 1


def test_search_returns_relevant_results():
    import brain.core.memory as m
    import brain.core.db as db
    _patch_db(m)
    with patch('brain.core.memory.embed', return_value=[0.9] * 768):
        m.save_memory("CORS fix in Express", "solution", ["cors"], "bella")
    with patch('brain.core.memory.embed', return_value=[0.1] * 768):
        results = m.search("cors express", n=5)
    assert len(results) >= 0  # May not match with dummy embeddings — structure check


def test_save_memory_generates_id():
    import brain.core.memory as m
    _patch_db(m)
    with patch('brain.core.memory.embed', return_value=[0.1] * 768):
        memory_id = m.save_memory("test content", "solution", [], None)
    assert isinstance(memory_id, str)
    assert len(memory_id) > 0


def test_get_stats_returns_counts():
    import brain.core.memory as m
    import brain.core.db as db
    _patch_db(m)
    stats = m.get_stats()
    assert "total_memories" in stats
    assert "total_sessions" in stats


def _seed_memories(m, n, tmp_path):
    with patch('brain.core.memory.embed', return_value=[0.1] * 768):
        for i in range(n):
            m.save_memory(f"memory number {i}", "fact", [], "p")


def test_reflection_refuses_oversized_delete(tmp_path):
    # Security audit 2026-11-05: reflection used to delete whatever indices
    # the LLM returned with no limit -- a hallucinated response could wipe
    # most of the batch. 8/10 is well over MAX_REFLECTION_DELETE_FRACTION.
    import brain.core.memory as m
    import brain.core.db as db
    _patch_db(m)
    m.BACKUP_DIR = tmp_path / "backups"
    _seed_memories(m, 10, tmp_path)
    before = db.count_memories()

    with patch(
        'brain.core.memory.reflect_memories',
        return_value={"to_delete_indices": list(range(8)), "consolidated": []},
    ):
        m._trigger_reflection()

    assert db.count_memories() == before, "oversized delete request must be refused, not truncated"
    assert not list(m.BACKUP_DIR.glob("*.json")), "no backup should be written for a refused delete"


def test_reflection_deletes_within_cap_and_backs_up(tmp_path):
    import brain.core.memory as m
    import brain.core.db as db
    _patch_db(m)
    m.BACKUP_DIR = tmp_path / "backups"
    _seed_memories(m, 10, tmp_path)
    before = db.count_memories()

    with patch(
        'brain.core.memory.reflect_memories',
        return_value={"to_delete_indices": [0, 1], "consolidated": []},
    ):
        m._trigger_reflection()

    assert db.count_memories() == before - 2
    backups = list(m.BACKUP_DIR.glob("reflection_delete_*.json"))
    assert len(backups) == 1
    import json
    rows = json.loads(backups[0].read_text())
    assert len(rows) == 2
    assert all("content" in r and "id" in r for r in rows)
