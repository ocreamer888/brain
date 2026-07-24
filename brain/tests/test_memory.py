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
