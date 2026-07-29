"""Tests for brain/tools/backfill_entities.py.

Extraction itself is covered by test_entity_extractor.py. No live Ollama or
API calls — entity_extractor.extract_entities and api_client.link_entities
are monkeypatched everywhere.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from brain.tools import backfill_entities  # noqa: E402


# ---------------------------------------------------------------------------
# select_edgeless_durable
# ---------------------------------------------------------------------------

def _make_test_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE memories (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            type TEXT NOT NULL,
            project TEXT NOT NULL DEFAULT 'general',
            timestamp TEXT NOT NULL,
            superseded_by TEXT
        );
        CREATE TABLE edges (
            id TEXT PRIMARY KEY,
            src_memory_id TEXT NOT NULL,
            dst_entity_id TEXT NOT NULL,
            relation_type TEXT NOT NULL
        );
        """
    )
    conn.executemany(
        "INSERT INTO memories (id, content, type, project, timestamp, superseded_by) VALUES (?, ?, ?, ?, ?, ?)",
        [
            # Edge-less active fact — should be selected
            ("f1", "Fact one content", '"fact"', "brain", "2026-01-01T00:00:00Z", None),
            # Has an edge already — must NOT be selected
            ("f2", "Fact two content", '"fact"', "brain", "2026-01-02T00:00:00Z", None),
            # Superseded — must NOT be selected even though edge-less
            ("f3", "Fact three content", '"fact"', "brain", "2026-01-03T00:00:00Z", "f9"),
            # episode is the one non-durable type — must NOT be selected
            ("e1", "Episode content", '"episode"', "brain", "2026-01-04T00:00:00Z", None),
            # Edge-less active fact, different project
            ("f4", "Fact four content", '"fact"', "other", "2026-01-05T00:00:00Z", None),
            # Edge-less active rows for the other six durable types — all selected
            ("d-sol", "Solution content", '"solution"', "brain", "2026-01-06T00:00:00Z", None),
            ("d-dec", "Decision content", '"decision"', "brain", "2026-01-07T00:00:00Z", None),
            ("d-pat", "Pattern content", '"pattern"', "brain", "2026-01-08T00:00:00Z", None),
            ("d-ctx", "Project context content", '"project_context"', "brain", "2026-01-09T00:00:00Z", None),
            ("d-err", "Error lesson content", '"error_lesson"', "brain", "2026-01-10T00:00:00Z", None),
            ("d-con", "Conversation content", '"conversation"', "brain", "2026-01-11T00:00:00Z", None),
            # Superseded non-fact — must NOT be selected
            ("d-sup", "Superseded solution", '"solution"', "brain", "2026-01-12T00:00:00Z", "d-sol"),
            # Non-fact that already has an edge — must NOT be selected
            ("d-edg", "Linked conversation", '"conversation"', "brain", "2026-01-13T00:00:00Z", None),
        ],
    )
    conn.executemany(
        "INSERT INTO edges (id, src_memory_id, dst_entity_id, relation_type) VALUES (?, ?, ?, ?)",
        [
            ("e-1", "f2", "ent-1", "mentions"),
            ("e-2", "d-edg", "ent-1", "mentions"),
        ],
    )
    conn.commit()
    conn.close()


# Every edge-less, active, durable row in _make_test_db.
_EXPECTED_IDS = {"f1", "f4", "d-sol", "d-dec", "d-pat", "d-ctx", "d-err", "d-con"}


def test_select_edgeless_durable_includes_all_seven_types(tmp_path: Path) -> None:
    db_path = tmp_path / "test_brain.db"
    _make_test_db(db_path)

    results = backfill_entities.select_edgeless_durable(db_path)
    ids = {r["id"] for r in results}

    assert ids == _EXPECTED_IDS


def test_select_edgeless_durable_excludes_episode(tmp_path: Path) -> None:
    db_path = tmp_path / "test_brain.db"
    _make_test_db(db_path)

    ids = {r["id"] for r in backfill_entities.select_edgeless_durable(db_path)}

    assert "e1" not in ids


def test_select_edgeless_durable_excludes_superseded(tmp_path: Path) -> None:
    db_path = tmp_path / "test_brain.db"
    _make_test_db(db_path)

    ids = {r["id"] for r in backfill_entities.select_edgeless_durable(db_path)}

    assert "f3" not in ids  # superseded fact
    assert "d-sup" not in ids  # superseded non-fact


def test_select_edgeless_durable_excludes_rows_with_edges(tmp_path: Path) -> None:
    db_path = tmp_path / "test_brain.db"
    _make_test_db(db_path)

    ids = {r["id"] for r in backfill_entities.select_edgeless_durable(db_path)}

    assert "f2" not in ids  # edged fact
    assert "d-edg" not in ids  # edged non-fact


def test_select_edgeless_durable_respects_project_filter(tmp_path: Path) -> None:
    db_path = tmp_path / "test_brain.db"
    _make_test_db(db_path)

    results = backfill_entities.select_edgeless_durable(db_path, project="other")
    ids = {r["id"] for r in results}

    assert ids == {"f4"}


def test_select_edgeless_durable_respects_limit(tmp_path: Path) -> None:
    db_path = tmp_path / "test_brain.db"
    _make_test_db(db_path)

    results = backfill_entities.select_edgeless_durable(db_path, limit=1)

    assert len(results) == 1


def test_durable_types_are_json_quoted(tmp_path: Path) -> None:
    """SQL tuple must stay JSON-quoted and separate from the extractor's bare set."""
    assert all(t.startswith('"') and t.endswith('"') for t in backfill_entities._DURABLE_TYPES)
    assert {t.strip('"') for t in backfill_entities._DURABLE_TYPES} == set(
        backfill_entities.entity_extractor.DURABLE_MEMORY_TYPES
    )


# ---------------------------------------------------------------------------
# run() — end-to-end wiring with mocked LLM + API client
# ---------------------------------------------------------------------------

def test_run_dry_run_does_not_write_checkpoint_or_call_api(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "test_brain.db"
    _make_test_db(db_path)
    checkpoint_path = tmp_path / "checkpoint.json"

    monkeypatch.setattr(
        backfill_entities.entity_extractor, "extract_entities", lambda *a, **kw: ["Rust"]
    )
    calls: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        backfill_entities.api_client,
        "link_entities",
        lambda mid, ents: calls.append((mid, ents)) or len(ents),
    )

    backfill_entities.run(dry_run=True, db_path=db_path, checkpoint_path=checkpoint_path)

    assert calls == []
    assert not checkpoint_path.exists()


def test_run_links_edgeless_durable_and_writes_checkpoint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "test_brain.db"
    _make_test_db(db_path)
    checkpoint_path = tmp_path / "checkpoint.json"

    monkeypatch.setattr(
        backfill_entities.entity_extractor, "extract_entities", lambda *a, **kw: ["Rust", "SQLite"]
    )
    calls: list[tuple[str, list[str]]] = []

    def _fake_link(mid: str, ents: list[str]) -> int:
        calls.append((mid, ents))
        return len(ents)

    monkeypatch.setattr(backfill_entities.api_client, "link_entities", _fake_link)

    result = backfill_entities.run(db_path=db_path, checkpoint_path=checkpoint_path)

    linked_ids = {mid for mid, _ in calls}
    assert linked_ids == _EXPECTED_IDS
    assert result["linked_total"] == 2 * len(_EXPECTED_IDS)
    assert checkpoint_path.exists()
    saved = json.loads(checkpoint_path.read_text())
    assert set(saved["processed_ids"]) == _EXPECTED_IDS


def test_run_marks_processed_on_empty_extract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An empty extraction is progress: no link call, but the id must be checkpointed."""
    db_path = tmp_path / "test_brain.db"
    _make_test_db(db_path)
    checkpoint_path = tmp_path / "checkpoint.json"

    monkeypatch.setattr(
        backfill_entities.entity_extractor, "extract_entities", lambda *a, **kw: []
    )
    calls: list[str] = []
    monkeypatch.setattr(
        backfill_entities.api_client,
        "link_entities",
        lambda mid, ents: calls.append(mid) or len(ents),
    )

    result = backfill_entities.run(db_path=db_path, checkpoint_path=checkpoint_path)

    assert calls == []
    assert result["linked_total"] == 0
    assert result["facts_seen"] == len(_EXPECTED_IDS)
    saved = json.loads(checkpoint_path.read_text())
    assert set(saved["processed_ids"]) == _EXPECTED_IDS


def test_run_skips_already_processed_ids_on_resume(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "test_brain.db"
    _make_test_db(db_path)
    checkpoint_path = tmp_path / "checkpoint.json"
    checkpoint_path.write_text(
        json.dumps({"processed_ids": ["f1"], "linked_total": 2, "facts_seen": 1})
    )

    monkeypatch.setattr(
        backfill_entities.entity_extractor, "extract_entities", lambda *a, **kw: ["Rust"]
    )
    calls: list[str] = []
    monkeypatch.setattr(
        backfill_entities.api_client,
        "link_entities",
        lambda mid, ents: calls.append(mid) or len(ents),
    )

    backfill_entities.run(db_path=db_path, checkpoint_path=checkpoint_path)

    assert "f1" not in calls
    assert "f4" in calls


def test_api_failure_skips_and_does_not_checkpoint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "test_brain.db"
    _make_test_db(db_path)
    checkpoint_path = tmp_path / "checkpoint.json"

    monkeypatch.setattr(
        backfill_entities.entity_extractor, "extract_entities", lambda *a, **kw: ["Rust"]
    )
    calls: list[str] = []

    def _fail_on_f1(mid: str, ents: list[str]) -> int:
        if mid == "f1":
            raise backfill_entities.api_client.BrainApiError("502 Bad Gateway")
        calls.append(mid)
        return len(ents)

    monkeypatch.setattr(backfill_entities.api_client, "link_entities", _fail_on_f1)

    result = backfill_entities.run(db_path=db_path, checkpoint_path=checkpoint_path)

    assert "f1" not in calls
    assert set(calls) == _EXPECTED_IDS - {"f1"}
    assert result["linked_total"] == len(_EXPECTED_IDS) - 1
    saved = json.loads(checkpoint_path.read_text())
    assert "f1" not in saved["processed_ids"]
    assert set(saved["processed_ids"]) == _EXPECTED_IDS - {"f1"}
