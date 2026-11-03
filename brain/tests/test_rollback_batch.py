"""Tests for retrieval_eval_kfold.rollback_batch.

2026-11-03: rollback_batch used to delete facts via raw SQLite, which never
touches brain_api's in-process vector index (rebuilt from SQLite only at
startup -- see brain.rs delete_memories, which evicts from both the store
AND the live index). A raw-SQL delete left a running API still serving the
"rolled back" facts until a restart. Fixed to delete through the live
POST /delete API instead; superseded_by clearing stays raw SQL since
Brain::search reads it live per-query (no restart needed for that part).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from brain.tools.retrieval_eval_kfold import rollback_batch


def _make_test_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE memories (
            id TEXT PRIMARY KEY,
            superseded_by TEXT
        );
        CREATE TABLE curation_events (
            id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL,
            fact_id TEXT NOT NULL,
            decision TEXT NOT NULL
        );
        CREATE TABLE backfill_batches (
            batch_id TEXT PRIMARY KEY,
            rolled_back INTEGER NOT NULL DEFAULT 0,
            finished_at TEXT
        );
        """
    )
    conn.executemany(
        "INSERT INTO memories (id, superseded_by) VALUES (?, ?)",
        [
            ("old-1", "new-1"),  # hidden by a fact this batch will roll back
            ("old-2", "new-2"),
            ("unrelated", None),
        ],
    )
    conn.executemany(
        "INSERT INTO curation_events (id, batch_id, fact_id, decision) VALUES (?, ?, ?, ?)",
        [
            ("ce-1", "b1", "new-1", "ADD"),
            ("ce-2", "b1", "new-2", "UPDATE"),
            ("ce-3", "b1", "ignored-1", "IGNORE"),  # IGNORE must not be rolled back
            ("ce-4", "b2", "new-3", "ADD"),  # different batch, must be untouched
        ],
    )
    conn.execute("INSERT INTO backfill_batches (batch_id) VALUES ('b1')")
    conn.commit()
    conn.close()


def test_rollback_batch_deletes_via_live_api_not_raw_sql(tmp_path: Path) -> None:
    db_path = tmp_path / "test_brain.db"
    _make_test_db(db_path)

    with patch("brain.api_client.delete_memories", return_value=2) as mock_delete:
        deleted = rollback_batch(db_path, "b1")

    assert deleted == 2
    mock_delete.assert_called_once()
    (called_ids,), _ = mock_delete.call_args
    assert set(called_ids) == {"new-1", "new-2"}


def test_rollback_batch_clears_superseded_by_live_via_sql(tmp_path: Path) -> None:
    """superseded_by clearing stays raw SQL -- it's read live per-query, no restart needed."""
    db_path = tmp_path / "test_brain.db"
    _make_test_db(db_path)

    with patch("brain.api_client.delete_memories", return_value=2):
        rollback_batch(db_path, "b1")

    conn = sqlite3.connect(str(db_path))
    rows = dict(conn.execute("SELECT id, superseded_by FROM memories").fetchall())
    conn.close()
    assert rows["old-1"] is None
    assert rows["old-2"] is None
    assert rows["unrelated"] is None  # was already None, unaffected


def test_rollback_batch_only_rolls_back_add_update_merge(tmp_path: Path) -> None:
    db_path = tmp_path / "test_brain.db"
    _make_test_db(db_path)

    with patch("brain.api_client.delete_memories", return_value=2) as mock_delete:
        rollback_batch(db_path, "b1")

    (called_ids,), _ = mock_delete.call_args
    assert "ignored-1" not in called_ids  # IGNORE decisions never created a fact to delete


def test_rollback_batch_scoped_to_its_own_batch_id(tmp_path: Path) -> None:
    db_path = tmp_path / "test_brain.db"
    _make_test_db(db_path)

    with patch("brain.api_client.delete_memories", return_value=2) as mock_delete:
        rollback_batch(db_path, "b1")

    (called_ids,), _ = mock_delete.call_args
    assert "new-3" not in called_ids  # belongs to batch b2


def test_rollback_batch_marks_batch_row_rolled_back(tmp_path: Path) -> None:
    db_path = tmp_path / "test_brain.db"
    _make_test_db(db_path)

    with patch("brain.api_client.delete_memories", return_value=2):
        rollback_batch(db_path, "b1")

    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT rolled_back, finished_at FROM backfill_batches WHERE batch_id='b1'"
    ).fetchone()
    conn.close()
    assert row[0] == 1
    assert row[1] is not None


def test_rollback_batch_no_matching_facts_returns_zero_and_skips_api(tmp_path: Path) -> None:
    db_path = tmp_path / "test_brain.db"
    _make_test_db(db_path)

    with patch("brain.api_client.delete_memories") as mock_delete:
        deleted = rollback_batch(db_path, "no-such-batch")

    assert deleted == 0
    mock_delete.assert_not_called()


def test_rollback_batch_raises_and_leaves_batch_not_rolled_back_on_api_failure(tmp_path: Path) -> None:
    """2026-11-03: a failed live delete must not look like a successful rollback.
    superseded_by is already cleared (committed), but rolled_back stays 0 as the
    retry signal -- calling rollback_batch again must pick up where this left off."""
    from brain.api_client import BrainApiError

    db_path = tmp_path / "test_brain.db"
    _make_test_db(db_path)

    with patch("brain.api_client.delete_memories", side_effect=BrainApiError("brain_api down")):
        with pytest.raises(BrainApiError):
            rollback_batch(db_path, "b1")

    conn = sqlite3.connect(str(db_path))
    superseded = dict(conn.execute("SELECT id, superseded_by FROM memories").fetchall())
    rolled_back = conn.execute(
        "SELECT rolled_back FROM backfill_batches WHERE batch_id='b1'"
    ).fetchone()[0]
    conn.close()
    assert superseded["old-1"] is None  # cleared despite the later failure
    assert superseded["old-2"] is None
    assert rolled_back == 0  # NOT marked done -- the failure must be visible, not hidden


def test_rollback_batch_retry_after_partial_failure_succeeds(tmp_path: Path) -> None:
    """A second call with the same batch_id, once the API is back, must finish
    the job -- fact_ids are re-read fresh and the superseded_by clear is a no-op
    the second time, not a problem."""
    from brain.api_client import BrainApiError

    db_path = tmp_path / "test_brain.db"
    _make_test_db(db_path)

    with patch("brain.api_client.delete_memories", side_effect=BrainApiError("down")):
        with pytest.raises(BrainApiError):
            rollback_batch(db_path, "b1")

    with patch("brain.api_client.delete_memories", return_value=2) as mock_delete:
        deleted = rollback_batch(db_path, "b1")

    assert deleted == 2
    (called_ids,), _ = mock_delete.call_args
    assert set(called_ids) == {"new-1", "new-2"}

    conn = sqlite3.connect(str(db_path))
    rolled_back = conn.execute(
        "SELECT rolled_back FROM backfill_batches WHERE batch_id='b1'"
    ).fetchone()[0]
    conn.close()
    assert rolled_back == 1
