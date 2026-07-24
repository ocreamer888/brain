"""Tests for brain/tools/backfill_entities.py.

No live Ollama or API calls — _call_llm and api_client.link_entities are
monkeypatched everywhere.
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
# extract_entities
# ---------------------------------------------------------------------------

def test_extract_entities_parses_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        backfill_entities,
        "_call_llm",
        lambda *a, **kw: json.dumps({"entities": ["Next.js", "Supabase"]}),
    )
    result = backfill_entities.extract_entities("We migrated from Next.js to Supabase.")
    assert result == ["Next.js", "Supabase"]


def test_extract_entities_handles_garbage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backfill_entities, "_call_llm", lambda *a, **kw: "this is not json at all")
    result = backfill_entities.extract_entities("Some fact text")
    assert result == []


def test_extract_entities_handles_llm_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*a, **kw):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(backfill_entities, "_call_llm", _raise)
    result = backfill_entities.extract_entities("Some fact text")
    assert result == []


def test_extract_entities_strips_markdown_fence(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = '```json\n{"entities": ["Rust", "SQLite"]}\n```'
    monkeypatch.setattr(backfill_entities, "_call_llm", lambda *a, **kw: raw)
    result = backfill_entities.extract_entities("Rust talks to SQLite directly.")
    assert result == ["Rust", "SQLite"]


def test_clean_entities_drops_stoplist() -> None:
    result = backfill_entities._clean_entities(["git", "React", "commit", "Supabase"])
    assert result == ["React", "Supabase"]


def test_clean_entities_drops_short_and_punct() -> None:
    result = backfill_entities._clean_entities([".", "a", "Go", "--", "AI"])
    assert result == ["Go", "AI"]


def test_clean_entities_dedupes_case_insensitive_preserving_first() -> None:
    result = backfill_entities._clean_entities(["React", "react", "REACT"])
    assert result == ["React"]


def test_extract_entities_applies_cleaning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        backfill_entities,
        "_call_llm",
        lambda *a, **kw: json.dumps({"entities": ["git", "Next.js", "commit_message", "Next.js"]}),
    )
    result = backfill_entities.extract_entities("Some fact text")
    assert result == ["Next.js"]


def test_extract_entities_dedups_case_insensitive_and_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    names = [f"Entity{i}" for i in range(20)] + ["entity0"]  # dup of Entity0, case-insensitive
    monkeypatch.setattr(
        backfill_entities, "_call_llm", lambda *a, **kw: json.dumps({"entities": names})
    )
    result = backfill_entities.extract_entities("text")
    assert len(result) == backfill_entities.MAX_ENTITIES_PER_FACT
    assert result[0] == "Entity0"


# ---------------------------------------------------------------------------
# select_edgeless_facts
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
            # Non-fact type — must NOT be selected
            ("e1", "Episode content", '"episode"', "brain", "2026-01-04T00:00:00Z", None),
            # Edge-less active fact, different project
            ("f4", "Fact four content", '"fact"', "other", "2026-01-05T00:00:00Z", None),
        ],
    )
    conn.execute(
        "INSERT INTO edges (id, src_memory_id, dst_entity_id, relation_type) VALUES (?, ?, ?, ?)",
        ("e-1", "f2", "ent-1", "mentions"),
    )
    conn.commit()
    conn.close()


def test_select_edgeless_facts(tmp_path: Path) -> None:
    db_path = tmp_path / "test_brain.db"
    _make_test_db(db_path)

    results = backfill_entities.select_edgeless_facts(db_path)
    ids = {r["id"] for r in results}

    assert ids == {"f1", "f4"}


def test_select_edgeless_facts_respects_project_filter(tmp_path: Path) -> None:
    db_path = tmp_path / "test_brain.db"
    _make_test_db(db_path)

    results = backfill_entities.select_edgeless_facts(db_path, project="other")
    ids = {r["id"] for r in results}

    assert ids == {"f4"}


def test_select_edgeless_facts_respects_limit(tmp_path: Path) -> None:
    db_path = tmp_path / "test_brain.db"
    _make_test_db(db_path)

    results = backfill_entities.select_edgeless_facts(db_path, limit=1)

    assert len(results) == 1


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
        backfill_entities, "_call_llm", lambda *a, **kw: json.dumps({"entities": ["Rust"]})
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


def test_run_links_edgeless_facts_and_writes_checkpoint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "test_brain.db"
    _make_test_db(db_path)
    checkpoint_path = tmp_path / "checkpoint.json"

    monkeypatch.setattr(
        backfill_entities, "_call_llm", lambda *a, **kw: json.dumps({"entities": ["Rust", "SQLite"]})
    )
    calls: list[tuple[str, list[str]]] = []

    def _fake_link(mid: str, ents: list[str]) -> int:
        calls.append((mid, ents))
        return len(ents)

    monkeypatch.setattr(backfill_entities.api_client, "link_entities", _fake_link)

    result = backfill_entities.run(db_path=db_path, checkpoint_path=checkpoint_path)

    linked_ids = {mid for mid, _ in calls}
    assert linked_ids == {"f1", "f4"}
    assert result["linked_total"] == 4  # 2 facts * 2 entities each
    assert checkpoint_path.exists()
    saved = json.loads(checkpoint_path.read_text())
    assert set(saved["processed_ids"]) == {"f1", "f4"}


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
        backfill_entities, "_call_llm", lambda *a, **kw: json.dumps({"entities": ["Rust"]})
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
        backfill_entities, "_call_llm", lambda *a, **kw: json.dumps({"entities": ["Rust"]})
    )
    calls: list[str] = []

    def _fail_on_f1(mid: str, ents: list[str]) -> int:
        if mid == "f1":
            raise backfill_entities.api_client.BrainApiError("502 Bad Gateway")
        calls.append(mid)
        return len(ents)

    monkeypatch.setattr(backfill_entities.api_client, "link_entities", _fail_on_f1)

    result = backfill_entities.run(db_path=db_path, checkpoint_path=checkpoint_path)

    assert "f4" in calls
    assert result["linked_total"] == 1
    saved = json.loads(checkpoint_path.read_text())
    assert "f1" not in saved["processed_ids"]
    assert "f4" in saved["processed_ids"]
