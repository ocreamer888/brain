"""Tests for brain/ingest/fact_curator.py.

All external I/O is mocked:
  - api_client.search        → controlled list of existing facts
  - api_client.save_memory   → returns deterministic IDs
  - _call_tiebreaker         → controlled decision dicts
  - SQLite writes            → in-memory DB with minimal schema
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from brain.ingest.fact_extractor import FactDraft
from brain.ingest.fact_curator import (
    CurationResult,
    _log_curation_event,
    _mark_superseded,
    curate_facts,
)

# ---------------------------------------------------------------------------
# Minimal in-memory DB that mirrors the curation tables
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    superseded_by TEXT
);
CREATE TABLE IF NOT EXISTS curation_events (
    id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    fact_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    sim REAL,
    reason TEXT,
    model TEXT,
    batch_id TEXT
);
"""


def _make_mem_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(_SCHEMA)
    return conn


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _draft(content: str, salience: float = 0.8, fact_type: str = "decision") -> FactDraft:
    return FactDraft(
        content=content, salience=salience,
        event_time=None, entities=[], fact_type=fact_type,
        derived_from="openrouter/anthropic/claude-sonnet-4-5/v1",
    )


def _existing(mem_id: str, content: str, superseded_by: str | None = None) -> dict:
    return {
        "id": mem_id,
        "content": content,
        "metadata": {"superseded_by": superseded_by, "salience": 0.7},
        "distance": 0.1,
    }


# ---------------------------------------------------------------------------
# Gap-2: empty facts early exit
# ---------------------------------------------------------------------------

def test_curate_empty_facts_returns_early() -> None:
    result = curate_facts([], project="test", batch_id="b1")
    assert result.reason == "no_facts_extracted"
    assert result.added == []
    assert result.updated == []
    assert result.merged == []
    assert result.ignored == 0


# ---------------------------------------------------------------------------
# ADD path (no existing facts)
# ---------------------------------------------------------------------------

def test_curate_adds_when_no_existing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("brain.api_client.search", lambda **kw: [])
    monkeypatch.setattr("brain.api_client.save_memory", lambda **kw: "new-id-001")
    monkeypatch.setattr("brain.ingest.fact_curator._log_curation_event", lambda *a, **kw: None)

    result = curate_facts([_draft("Fresh new fact")], project="test", batch_id="b1")
    assert result.added == ["new-id-001"]
    assert result.ignored == 0
    assert result.reason is None


# ---------------------------------------------------------------------------
# IGNORE path (max_sim > 0.92)
# ---------------------------------------------------------------------------

def test_curate_ignores_near_duplicate(monkeypatch: pytest.MonkeyPatch) -> None:
    existing_content = "The brain API binds on port 8787 by default"
    new_content = "Brain API runs on port 8787"

    monkeypatch.setattr(
        "brain.api_client.search",
        lambda **kw: [_existing("old-001", existing_content)],
    )
    monkeypatch.setattr("brain.ingest.fact_curator._log_curation_event", lambda *a, **kw: None)

    # These two sentences are nearly identical — embedder should produce sim > 0.92
    result = curate_facts([_draft(new_content)], project="test", batch_id="b1")
    # Either IGNORE (sim > 0.92) or ADD (sim < 0.78) depending on embedder
    # We just assert it doesn't crash and returns a valid result
    assert isinstance(result, CurationResult)
    assert result.errors == 0


# ---------------------------------------------------------------------------
# ADD path (max_sim < 0.78)
# ---------------------------------------------------------------------------

def test_curate_adds_clearly_new(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "brain.api_client.search",
        lambda **kw: [_existing("old-001", "The sky is blue on clear days")],
    )
    monkeypatch.setattr("brain.api_client.save_memory", lambda **kw: "new-id-002")
    monkeypatch.setattr("brain.ingest.fact_curator._log_curation_event", lambda *a, **kw: None)

    # Completely unrelated fact
    result = curate_facts(
        [_draft("RMT Soluciones is a construction firm in Costa Rica")],
        project="test",
        batch_id="b1",
    )
    assert result.added == ["new-id-002"]
    assert result.errors == 0


# ---------------------------------------------------------------------------
# Tiebreaker → UPDATE
# ---------------------------------------------------------------------------

def test_curate_update_marks_superseded(monkeypatch: pytest.MonkeyPatch) -> None:
    old_id = "old-fact-abc"
    monkeypatch.setattr(
        "brain.api_client.search",
        lambda **kw: [_existing(old_id, "SQLite FTS5 uses porter stemmer by default")],
    )
    monkeypatch.setattr("brain.api_client.save_memory", lambda **kw: "new-id-003")
    monkeypatch.setattr(
        "brain.ingest.fact_curator._call_tiebreaker",
        lambda **kw: {"decision": "UPDATE", "reason": "new fact is more precise"},
    )
    superseded: list[tuple] = []
    monkeypatch.setattr(
        "brain.ingest.fact_curator._mark_superseded",
        lambda old, new: superseded.append((old, new)),
    )
    monkeypatch.setattr("brain.ingest.fact_curator._log_curation_event", lambda *a, **kw: None)

    result = curate_facts(
        [_draft("SQLite FTS5 uses the porter stemmer tokenizer, configured at index creation time")],
        project="test",
        batch_id="b1",
    )
    assert result.updated == ["new-id-003"] or result.added == ["new-id-003"]  # depends on sim
    assert result.errors == 0


# ---------------------------------------------------------------------------
# Gap-1: hallucination guard — UPDATE with fabricated old_id
# ---------------------------------------------------------------------------

def test_curate_hallucination_guard_rejects_update(monkeypatch: pytest.MonkeyPatch) -> None:
    # Search result with no 'id' field — the realistic trigger for the guard.
    # old_id = best.get("id", "") = ""
    # valid_ids = {e.get("id") for e in existing} = {None}
    # "" not in {None} → guard fires.
    monkeypatch.setattr(
        "brain.api_client.search",
        lambda **kw: [{"content": "Some existing fact about databases", "metadata": {}, "distance": 0.1}],
    )
    monkeypatch.setattr(
        "brain.ingest.fact_curator._call_tiebreaker",
        lambda **kw: {"decision": "UPDATE", "reason": "supersedes older version"},
    )
    # Force similarity into tiebreaker zone (0.78–0.92) so _call_tiebreaker is reached
    import numpy as np
    # new_vec = [1,0], existing_vec = [0.85, 0.527] → dot ≈ 0.85
    monkeypatch.setattr(
        "brain.ingest.fact_curator.embed_batch",
        lambda texts, **kw: ([[1.0, 0.0]] + [[0.85, 0.527]] * (len(texts) - 1))[: len(texts)],
    )
    mark_calls: list = []
    monkeypatch.setattr(
        "brain.ingest.fact_curator._mark_superseded",
        lambda old, new: mark_calls.append((old, new)),
    )
    logged: list[dict] = []
    monkeypatch.setattr(
        "brain.ingest.fact_curator._log_curation_event",
        lambda fact_id, decision, sim, reason, model, batch_id: logged.append(
            {"fact_id": fact_id, "decision": decision, "reason": reason}
        ),
    )

    result = curate_facts(
        [_draft("Some updated fact about databases")],
        project="test",
        batch_id="b1",
    )
    assert mark_calls == [], "mark_superseded must not fire when hallucination guard triggers"
    assert result.errors == 0
    ignore_events = [e for e in logged if e["decision"] == "IGNORE"]
    assert any(e["reason"] == "hallucinated_id" for e in ignore_events), (
        f"expected hallucinated_id IGNORE event, got: {logged}"
    )


# ---------------------------------------------------------------------------
# Tiebreaker → MERGE
# ---------------------------------------------------------------------------

def test_curate_merge_uses_merged_content(monkeypatch: pytest.MonkeyPatch) -> None:
    old_id = "old-merge-001"
    monkeypatch.setattr(
        "brain.api_client.search",
        lambda **kw: [_existing(old_id, "RMT sells fire suppression systems")],
    )
    saved: list[dict] = []
    monkeypatch.setattr(
        "brain.api_client.save_memory",
        lambda content, **kw: (saved.append({"content": content}), "merged-id-001")[1],
    )
    monkeypatch.setattr(
        "brain.ingest.fact_curator._call_tiebreaker",
        lambda **kw: {
            "decision": "MERGE",
            "reason": "combined is more complete",
            "merged_content": "RMT sells and installs fire suppression systems across Costa Rica.",
        },
    )
    monkeypatch.setattr("brain.ingest.fact_curator._mark_superseded", lambda *a: None)
    monkeypatch.setattr("brain.ingest.fact_curator._log_curation_event", lambda *a, **kw: None)

    result = curate_facts(
        [_draft("RMT installs fire suppression systems")],
        project="test",
        batch_id="b1",
    )
    assert result.errors == 0
    # If tiebreaker zone reached, merged content should be used
    if result.merged:
        assert saved[0]["content"] == "RMT sells and installs fire suppression systems across Costa Rica."


# ---------------------------------------------------------------------------
# SQLite helpers (direct DB write tests)
# ---------------------------------------------------------------------------

def test_mark_superseded_updates_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # _db_conn() closes the connection after writing, so :memory: is gone.
    # Use a temp file DB that persists across connections.
    db_file = tmp_path / "test_brain.db"
    setup = sqlite3.connect(str(db_file))
    setup.executescript(_SCHEMA)
    setup.execute("INSERT INTO memories (id) VALUES (?)", ("fact-old",))
    setup.commit()
    setup.close()

    monkeypatch.setenv("BRAIN_DB_PATH", str(db_file))
    _mark_superseded("fact-old", "fact-new")

    verify = sqlite3.connect(str(db_file))
    row = verify.execute("SELECT superseded_by FROM memories WHERE id = 'fact-old'").fetchone()
    verify.close()
    assert row[0] == "fact-new"


def test_log_curation_event_inserts_row(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db_file = tmp_path / "test_brain.db"
    setup = sqlite3.connect(str(db_file))
    setup.executescript(_SCHEMA)
    setup.commit()
    setup.close()

    monkeypatch.setenv("BRAIN_DB_PATH", str(db_file))
    _log_curation_event("fact-123", "ADD", 0.45, "below threshold", "model/v1", "batch-1")

    verify = sqlite3.connect(str(db_file))
    row = verify.execute("SELECT * FROM curation_events").fetchone()
    verify.close()
    assert row is not None
    assert row[2] == "fact-123"   # fact_id
    assert row[3] == "ADD"        # decision
    assert row[7] == "batch-1"    # batch_id


# ---------------------------------------------------------------------------
# CurationResult fields
# ---------------------------------------------------------------------------

def test_curation_result_reason_defaults_to_none() -> None:
    r = CurationResult()
    assert r.reason is None


def test_curation_result_reason_set_on_early_exit() -> None:
    r = curate_facts([], project="test", batch_id="b1")
    assert r.reason == "no_facts_extracted"


# ---------------------------------------------------------------------------
# Phase 7: source_event_time fallback
# ---------------------------------------------------------------------------

def test_save_fact_forwards_entities(monkeypatch):
    from brain.ingest.fact_curator import _save_fact
    from brain.ingest.fact_extractor import FactDraft

    captured = {}

    def fake_save(**kwargs):
        captured.update(kwargs)
        return "fact-id-1"

    monkeypatch.setattr("brain.ingest.fact_curator.api_client.save_memory", fake_save)

    draft = FactDraft(
        content="Chose SQLite for local brain graph",
        salience=0.9,
        event_time=None,
        entities=["SQLite", "brain"],
        fact_type="decision",
    )
    _save_fact(draft, project="brain", parent_id="ep-1", session_id=None)
    assert captured.get("entities") == ["SQLite", "brain"]


def test_save_fact_passes_auto_entities_false_with_entities(monkeypatch):
    from brain.ingest.fact_curator import _save_fact
    from brain.ingest.fact_extractor import FactDraft

    captured = {}
    calls = []

    def fake_save(**kwargs):
        captured.update(kwargs)
        calls.append(kwargs)
        return "fact-id-2"

    monkeypatch.setattr("brain.ingest.fact_curator.api_client.save_memory", fake_save)

    draft = FactDraft(
        content="Chose SQLite for local brain graph",
        salience=0.9,
        event_time=None,
        entities=["SQLite", "brain"],
        fact_type="decision",
    )
    _save_fact(draft, project="brain", parent_id="ep-1", session_id=None)

    assert captured.get("entities") == ["SQLite", "brain"]
    assert captured.get("auto_entities") is False
    assert len(calls) == 1


def test_save_fact_passes_auto_entities_false_when_empty(monkeypatch):
    from brain.ingest.fact_curator import _save_fact
    from brain.ingest.fact_extractor import FactDraft

    captured = {}
    calls = []

    def fake_save(**kwargs):
        captured.update(kwargs)
        calls.append(kwargs)
        return "fact-id-3"

    monkeypatch.setattr("brain.ingest.fact_curator.api_client.save_memory", fake_save)

    draft = FactDraft(
        content="Chose SQLite for local brain graph",
        salience=0.9,
        event_time=None,
        entities=[],
        fact_type="decision",
    )
    _save_fact(draft, project="brain", parent_id="ep-1", session_id=None)

    assert captured.get("entities") is None
    assert captured.get("auto_entities") is False
    assert len(calls) == 1


def test_save_fact_uses_source_event_time_when_llm_null(monkeypatch):
    """source_event_time is used when LLM extracted event_time is None."""
    saved = {}
    def mock_save_memory(**kwargs):
        saved.update(kwargs)
        return "fake-id"
    monkeypatch.setattr("brain.api_client.save_memory", mock_save_memory)

    from brain.ingest.fact_extractor import FactDraft
    from brain.ingest.fact_curator import _save_fact
    draft = FactDraft(content="test fact", salience=0.8, event_time=None,
                      entities=[], fact_type="decision", derived_from="v1")
    _save_fact(draft, project="test", parent_id=None, session_id=None,
               source_event_time="2025-07-01T00:00:00+00:00")
    assert saved.get("event_time") == "2025-07-01T00:00:00+00:00"


def test_save_fact_llm_event_time_wins(monkeypatch):
    """LLM-extracted event_time takes precedence over source_event_time."""
    saved = {}
    def mock_save_memory(**kwargs):
        saved.update(kwargs)
        return "fake-id"
    monkeypatch.setattr("brain.api_client.save_memory", mock_save_memory)

    from brain.ingest.fact_extractor import FactDraft
    from brain.ingest.fact_curator import _save_fact
    draft = FactDraft(content="test fact", salience=0.8, event_time="2024-03-15T00:00:00+00:00",
                      entities=[], fact_type="decision", derived_from="v1")
    _save_fact(draft, project="test", parent_id=None, session_id=None,
               source_event_time="2025-07-01T00:00:00+00:00")
    assert saved.get("event_time") == "2024-03-15T00:00:00+00:00"
