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

    result = run_mcp_eval(gold, search_fn=search_fn)
    assert result["status"] == "ok"
    assert result["n_queries"] == 2
    assert result["precision_at_1"] == pytest.approx(0.5)
    assert result["mrr"] == pytest.approx((1.0 + 0.5) / 2)


def test_gold_id_in_top1(tmp_path: Path) -> None:
    """P@1 = 1.0 when gold_memory_id is the first result."""
    from brain.tools.mcp_eval import run_mcp_eval

    gold = _gold_file(tmp_path, [
        {"query": "q1", "gold_memory_id": "target-id", "k": 5},
    ])

    def search_fn(query: str, k: int) -> list[dict]:
        return [{"id": "target-id"}, {"id": "other"}]

    result = run_mcp_eval(gold, search_fn=search_fn)
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

    result = run_mcp_eval(gold, search_fn=search_fn)
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
    result = run_mcp_eval(gold, baseline_offline_p1=0.7, search_fn=search_fn)
    assert result["status"] == "ok"
    assert result["gap_vs_offline_rrf"] == pytest.approx(0.5 - 0.7)
