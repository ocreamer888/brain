from __future__ import annotations

import json
from pathlib import Path

import pytest

from brain.api_client import BrainApiError


def _gold_file(tmp_path: Path, entries: list[dict]) -> Path:
    p = tmp_path / "gold.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    return p


def test_p1_calculation(tmp_path: Path) -> None:
    """P@1 = 0.5 when gold is first result for q1 but second for q2."""
    from brain.tools.mcp_eval import run_mcp_eval

    gold = _gold_file(tmp_path, [
        {"query": "q1", "gold_memory_id": "aaa", "k": 3},
        {"query": "q2", "gold_memory_id": "bbb", "k": 3},
    ])

    def search_fn(query: str, k: int) -> list[dict]:
        if query == "q1":
            return [{"id": "aaa"}, {"id": "xxx"}]
        return [{"id": "xxx"}, {"id": "bbb"}]

    result = run_mcp_eval(gold, search_fn=search_fn, corpus_ids={"aaa", "bbb"})
    assert result["status"] == "ok"
    assert result["n_queries"] == 2
    assert result["precision_at_1"] == pytest.approx(0.5)
    assert result["mrr"] == pytest.approx((1.0 + 0.5) / 2)
    assert result["n_skipped_dangling"] == 0


def test_gold_id_in_top1(tmp_path: Path) -> None:
    """P@1 = 1.0 when gold_memory_id is the first result."""
    from brain.tools.mcp_eval import run_mcp_eval

    gold = _gold_file(tmp_path, [
        {"query": "q1", "gold_memory_id": "target-id", "k": 5},
    ])

    def search_fn(query: str, k: int) -> list[dict]:
        return [{"id": "target-id"}, {"id": "other"}]

    result = run_mcp_eval(gold, search_fn=search_fn, corpus_ids={"target-id"})
    assert result["status"] == "ok"
    assert result["precision_at_1"] == 1.0


def test_api_unavailable(tmp_path: Path) -> None:
    """Returns status='skipped' when BrainApiError is raised."""
    from brain.tools.mcp_eval import run_mcp_eval

    gold = _gold_file(tmp_path, [
        {"query": "q1", "gold_memory_id": "aaa", "k": 5},
    ])

    def search_fn(query: str, k: int) -> list[dict]:
        raise BrainApiError("API unavailable: Connection refused")

    result = run_mcp_eval(gold, search_fn=search_fn, corpus_ids={"aaa"})
    assert result["status"] == "skipped"
    assert "not reachable" in result["reason"]


def test_gap_calculation(tmp_path: Path) -> None:
    """gap_vs_offline_rrf = mcp_p1 - baseline."""
    from brain.tools.mcp_eval import run_mcp_eval

    gold = _gold_file(tmp_path, [
        {"query": "q1", "gold_memory_id": "aaa", "k": 3},
        {"query": "q2", "gold_memory_id": "bbb", "k": 3},
    ])

    # q1: gold at rank 1 (hit). q2: gold at rank 2 (miss for P@1).
    def search_fn(query: str, k: int) -> list[dict]:
        return [{"id": "aaa"}, {"id": "bbb"}]

    # P@1 = 0.5 (only q1 has gold at rank 1)
    result = run_mcp_eval(
        gold, baseline_offline_p1=0.7, search_fn=search_fn, corpus_ids={"aaa", "bbb"}
    )
    assert result["status"] == "ok"
    assert result["gap_vs_offline_rrf"] == pytest.approx(0.5 - 0.7)


def test_dangling_gold_id_is_skipped_not_scored_as_miss(tmp_path: Path) -> None:
    """A gold_memory_id absent from the corpus is skipped, not counted as a miss.

    Pre-fix, this entry would have counted toward n_valid and scored a
    guaranteed miss, deflating precision_at_1. Post-fix it is excluded
    entirely: n_queries reflects only the valid entry, and P@1 is computed
    over that entry alone.
    """
    from brain.tools.mcp_eval import run_mcp_eval

    gold = _gold_file(tmp_path, [
        {"query": "q1", "gold_memory_id": "aaa", "k": 3},
        {"query": "q2-dangling", "gold_memory_id": "dangling-id", "k": 3},
    ])

    def search_fn(query: str, k: int) -> list[dict]:
        assert query != "q2-dangling", "search_fn must not be called for a dangling gold id"
        return [{"id": "aaa"}, {"id": "xxx"}]

    result = run_mcp_eval(gold, search_fn=search_fn, corpus_ids={"aaa"})
    assert result["status"] == "ok"
    assert result["n_queries"] == 1
    assert result["precision_at_1"] == 1.0
    assert result["n_skipped_dangling"] == 1


def test_all_gold_ids_dangling_returns_skipped(tmp_path: Path) -> None:
    """If every gold entry is dangling, n_valid is 0 and eval is 'skipped', not 'ok' at P@1=0."""
    from brain.tools.mcp_eval import run_mcp_eval

    gold = _gold_file(tmp_path, [
        {"query": "q1", "gold_memory_id": "dangling-1", "k": 3},
    ])

    def search_fn(query: str, k: int) -> list[dict]:
        raise AssertionError("search_fn must not be called for a dangling gold id")

    result = run_mcp_eval(gold, search_fn=search_fn, corpus_ids={"some-other-id"})
    assert result["status"] == "skipped"
    assert result["reason"] == "no queries completed"


def test_corpus_ids_defaults_to_loading_from_db_path(tmp_path: Path) -> None:
    """When corpus_ids is not injected, it is loaded from db_path via sqlite."""
    import sqlite3

    from brain.tools.mcp_eval import run_mcp_eval

    db_path = tmp_path / "brain.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE memories (id TEXT PRIMARY KEY)")
    conn.execute("INSERT INTO memories (id) VALUES ('present-id')")
    conn.commit()
    conn.close()

    gold = _gold_file(tmp_path, [
        {"query": "q-present", "gold_memory_id": "present-id", "k": 3},
        {"query": "q-absent", "gold_memory_id": "absent-id", "k": 3},
    ])

    def search_fn(query: str, k: int) -> list[dict]:
        assert query == "q-present"
        return [{"id": "present-id"}]

    result = run_mcp_eval(gold, search_fn=search_fn, db_path=db_path)
    assert result["status"] == "ok"
    assert result["n_queries"] == 1
    assert result["n_skipped_dangling"] == 1


def test_corpus_ids_load_failure_falls_back_to_no_filtering(tmp_path: Path) -> None:
    """A missing/unreadable db_path degrades to the pre-fix behavior (no filtering), not a crash."""
    from brain.tools.mcp_eval import run_mcp_eval

    gold = _gold_file(tmp_path, [
        {"query": "q1", "gold_memory_id": "aaa", "k": 3},
    ])

    def search_fn(query: str, k: int) -> list[dict]:
        return [{"id": "aaa"}]

    result = run_mcp_eval(gold, search_fn=search_fn, db_path=tmp_path / "nonexistent.db")
    assert result["status"] == "ok"
    assert result["n_queries"] == 1
    assert result["n_skipped_dangling"] == 0
