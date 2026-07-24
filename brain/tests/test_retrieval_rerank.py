"""retrieval_rerank heuristic ordering."""

from __future__ import annotations

from brain.tools.retrieval_rerank import rerank_results


def test_vault_boost_reorders_when_distances_tied():
    query = "some moderately long query text here for heuristics"
    results = [
        {
            "id": "1",
            "content": "word " * 50,
            "distance": 0.5,
            "metadata": {"file_path": "tmp/x.txt", "type": "solution"},
        },
        {
            "id": "2",
            "content": "word " * 50,
            "distance": 0.5,
            "metadata": {"file_path": "vault/01 Projects/Foo/a.md", "type": "solution"},
        },
    ]
    out = rerank_results(query, results)
    assert [r["id"] for r in out] == ["2", "1"]


def test_memory_type_filter_drops_non_matching():
    query = "short"
    results = [
        {"id": "a", "content": "x", "distance": 0.1, "metadata": {"type": "decision"}},
        {"id": "b", "content": "y", "distance": 0.9, "metadata": {"type": "solution"}},
    ]
    out = rerank_results(query, results, memory_type="solution")
    assert len(out) == 1 and out[0]["id"] == "b"
