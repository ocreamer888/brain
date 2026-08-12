"""Tests for brain/tools/seed_durable_backfill_checkpoint.py.

No live DB or checkpoint — everything runs against tmp_path fixtures.
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

from brain.tools import seed_durable_backfill_checkpoint as seed  # noqa: E402


def _make_test_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE memories (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            type TEXT NOT NULL
        );
        """
    )
    conn.executemany(
        "INSERT INTO memories (id, content, type) VALUES (?, ?, ?)",
        [
            ("f1", "fact one", '"fact"'),
            ("f2", "fact two", '"fact"'),
            ("s1", "a solution", '"solution"'),
            ("c1", "a conversation", '"conversation"'),
        ],
    )
    conn.commit()
    conn.close()


def _write_source(path: Path, ids: list[str]) -> Path:
    path.write_text(json.dumps({"processed_ids": ids, "linked_total": 999, "facts_seen": 42}))
    return path


def test_seeds_legacy_fact_ids(tmp_path: Path) -> None:
    db_path = tmp_path / "brain.db"
    _make_test_db(db_path)
    source = _write_source(tmp_path / "legacy.json", ["f1", "f2"])
    target = tmp_path / "durable.json"

    stats = seed.seed_processed_ids(source, target, db_path=db_path)

    assert stats["added"] == 2
    assert stats["total_processed"] == 2
    assert json.loads(target.read_text())["processed_ids"] == ["f1", "f2"]


def test_filters_ids_absent_from_db(tmp_path: Path) -> None:
    db_path = tmp_path / "brain.db"
    _make_test_db(db_path)
    source = _write_source(tmp_path / "legacy.json", ["f1", "gone-from-db"])
    target = tmp_path / "durable.json"

    stats = seed.seed_processed_ids(source, target, db_path=db_path)

    assert stats["dropped"] == 1
    assert json.loads(target.read_text())["processed_ids"] == ["f1"]


def test_filters_non_fact_ids(tmp_path: Path) -> None:
    db_path = tmp_path / "brain.db"
    _make_test_db(db_path)
    source = _write_source(tmp_path / "legacy.json", ["f1", "s1", "c1"])
    target = tmp_path / "durable.json"

    stats = seed.seed_processed_ids(source, target, db_path=db_path)

    assert stats["valid"] == 1
    assert json.loads(target.read_text())["processed_ids"] == ["f1"]


def test_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "brain.db"
    _make_test_db(db_path)
    source = _write_source(tmp_path / "legacy.json", ["f1", "f2"])
    target = tmp_path / "durable.json"

    seed.seed_processed_ids(source, target, db_path=db_path)
    stats = seed.seed_processed_ids(source, target, db_path=db_path)

    assert stats["added"] == 0
    assert stats["total_processed"] == 2


def test_preserves_pre_existing_target_ids(tmp_path: Path) -> None:
    db_path = tmp_path / "brain.db"
    _make_test_db(db_path)
    source = _write_source(tmp_path / "legacy.json", ["f1"])
    target = tmp_path / "durable.json"
    target.write_text(
        json.dumps({"processed_ids": ["s1"], "linked_total": 3, "facts_seen": 1})
    )

    stats = seed.seed_processed_ids(source, target, db_path=db_path)
    saved = json.loads(target.read_text())

    assert stats["added"] == 1
    assert saved["processed_ids"] == ["f1", "s1"]
    # Counters earned by runs of THIS checkpoint are untouched.
    assert saved["linked_total"] == 3
    assert saved["facts_seen"] == 1


def test_does_not_copy_legacy_counters(tmp_path: Path) -> None:
    db_path = tmp_path / "brain.db"
    _make_test_db(db_path)
    source = _write_source(tmp_path / "legacy.json", ["f1"])
    target = tmp_path / "durable.json"

    seed.seed_processed_ids(source, target, db_path=db_path)
    saved = json.loads(target.read_text())

    assert saved["linked_total"] == 0
    assert saved["facts_seen"] == 0
    assert saved["seeded_from"] == str(source)
    assert saved["seeded_count"] == 1
    assert saved["seeded_at"].endswith("Z")


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    db_path = tmp_path / "brain.db"
    _make_test_db(db_path)
    source = _write_source(tmp_path / "legacy.json", ["f1"])
    target = tmp_path / "durable.json"

    stats = seed.seed_processed_ids(source, target, db_path=db_path, dry_run=True)

    assert stats["added"] == 1
    assert not target.exists()


def test_missing_source_raises(tmp_path: Path) -> None:
    db_path = tmp_path / "brain.db"
    _make_test_db(db_path)

    with pytest.raises(FileNotFoundError):
        seed.seed_processed_ids(tmp_path / "nope.json", tmp_path / "durable.json", db_path=db_path)


def test_source_argument_is_required_with_no_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """The operator supplies the legacy path; none may be baked into committed code."""
    monkeypatch.setattr(sys, "argv", ["seed_durable_backfill_checkpoint.py"])

    with pytest.raises(SystemExit):
        seed.main()
