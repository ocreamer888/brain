"""Smoke tests for retrieval_eval helpers (no live API)."""

from __future__ import annotations

from pathlib import Path

import pytest

from brain.tools.retrieval_eval import extract_path_from_hit, load_gold, run_eval


def test_extract_path_prefers_metadata_file_path():
    hit = {
        "id": "1",
        "content": "x",
        "distance": 0.1,
        "metadata": {"file_path": "vault/01 Projects/Foo/bar.md", "tags": ""},
    }
    assert extract_path_from_hit(hit) == "vault/01 Projects/Foo/bar.md"


def test_extract_path_falls_back_to_tags():
    hit = {
        "id": "1",
        "content": "x",
        "distance": 0.1,
        "metadata": {"tags": "a,vault/02 Areas/x/note.md,b"},
    }
    assert extract_path_from_hit(hit) == "vault/02 Areas/x/note.md"


def test_run_eval_with_mock_search(tmp_path):
    gold = tmp_path / "g.jsonl"
    gold.write_text(
        '{"query": "q1", "gold_files": ["vault/a.md"]}\n',
        encoding="utf-8",
    )

    def fake_search(query: str, n: int) -> list[dict]:
        return [
            {"metadata": {"file_path": "vault/other.md"}, "content": "no", "distance": 0.5},
            {"metadata": {"file_path": "vault/a.md"}, "content": "yes", "distance": 0.3},
        ]

    report = run_eval(gold, 10, fake_search)
    assert report["n_queries"] == 1
    assert report["mean_recall"] == 1.0
    assert report["per_query"][0]["first_correct_rank"] == 2
    assert report["per_query"][0]["mrr"] == pytest.approx(0.5)


def test_load_gold_repo_file():
    path = Path(__file__).resolve().parents[1] / "eval" / "gold.jsonl"
    rows = load_gold(path)
    assert len(rows) >= 1
    # gold entries match by stable memory id (gold_ids) or legacy vault path (gold_files)
    assert "query" in rows[0]
    assert "gold_ids" in rows[0] or "gold_files" in rows[0]


def test_run_eval_matches_by_gold_ids(tmp_path):
    gold = tmp_path / "g.jsonl"
    gold.write_text(
        '{"query": "q1", "gold_ids": ["mem-123", "mem-456"]}\n',
        encoding="utf-8",
    )

    def fake_search(query: str, n: int) -> list[dict]:
        return [
            {"id": "mem-999", "metadata": {}, "content": "no", "distance": 0.5},
            {"id": "mem-456", "metadata": {}, "content": "yes", "distance": 0.3},
        ]

    report = run_eval(gold, 10, fake_search)
    assert report["mean_recall"] == 1.0
    assert report["per_query"][0]["first_correct_rank"] == 2  # mem-456 at rank 2
