#!/usr/bin/env python3
"""MCP path eval — queries via api_client.search() and scores against gold_semantic.jsonl.

Each gold entry: {"query": "...", "gold_memory_id": "uuid", "k": 10, "description": "..."}
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable


def load_gold(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            entries.append(json.loads(line))
    return entries


def offline_rrf_p1(db_path: Path, gold_path: Path, rrf_k: int = 60) -> float | None:
    """Offline BM25+cosine RRF P@1 on the SAME gold queries — the honest baseline.

    This is the apples-to-apples comparator for the live MCP path: identical
    queries, identical gold targets, plain RRF fusion (no salience/recency/
    diversity reranking). Returns None if the corpus can't be loaded.
    """
    import numpy as np

    from brain.tools.retrieval_eval_kfold import (
        build_fts_index,
        bm25_ranks_for_queries,
        load_corpus,
    )
    from brain.core.embedder import embed_batch

    try:
        gold = load_gold(gold_path)
        metas, matrix = load_corpus(db_path)
    except (OSError, ValueError) as e:
        return None
    if not gold or not metas:
        return None

    id_to_idx = {m["id"]: i for i, m in enumerate(metas)}
    queries = [str(g["query"]) for g in gold]
    n_docs = matrix.shape[0]

    q_vecs = np.asarray(embed_batch(queries), dtype=np.float32)
    q_norms = np.linalg.norm(q_vecs, axis=1, keepdims=True)
    q_norms[q_norms < 1e-10] = 1.0
    q_vecs /= q_norms
    sims = q_vecs @ matrix.T
    cos_ranks = (sims.shape[1] - np.argsort(np.argsort(sims, axis=1), axis=1)).astype(np.float32)
    bm25_ranks = bm25_ranks_for_queries(queries, build_fts_index(metas), n_docs).astype(np.float32)
    rrf = 1.0 / (rrf_k + cos_ranks) + 1.0 / (rrf_k + bm25_ranks)

    hits = 0
    for q_i, g in enumerate(gold):
        mi = id_to_idx.get(str(g["gold_memory_id"]))
        if mi is None:
            continue
        if int(np.sum(rrf[q_i] > rrf[q_i][mi])) + 1 == 1:
            hits += 1
    return round(hits / len(gold), 4)


def run_mcp_eval(
    gold_path: Path,
    n: int = 10,
    baseline_offline_p1: float | None = None,
    search_fn: Callable[[str, int], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Evaluate retrieval via the MCP/API search path.

    Returns a dict with keys: status, n_queries, precision_at_1, mrr, gap_vs_offline_rrf.
    gap_vs_offline_rrf compares the live path to plain offline RRF on the SAME
    queries (positive = live path beats naive RRF). status is 'ok'|'skipped'|'error'.
    """
    from brain.api_client import BrainApiError

    if search_fn is None:
        from brain.api_client import template_search

        def search_fn(query: str, k: int) -> list[dict[str, Any]]:
            return template_search(query=query, n=k)

    try:
        gold = load_gold(gold_path)
    except (OSError, ValueError) as e:
        return {"status": "error", "reason": str(e)}

    if not gold:
        return {"status": "error", "reason": "gold file is empty"}

    hits_at_1 = 0
    mrr_sum = 0.0
    n_valid = 0

    for entry in gold:
        query = str(entry["query"])
        gold_id = str(entry["gold_memory_id"])
        k = int(entry.get("k", n))

        try:
            results = search_fn(query, k)
        except BrainApiError:
            return {"status": "skipped", "reason": "brain API not reachable"}
        except Exception as e:
            return {"status": "error", "reason": str(e)}

        n_valid += 1
        ids = [str(r.get("id", "")) for r in results]

        if ids and ids[0] == gold_id:
            hits_at_1 += 1

        for rank, rid in enumerate(ids, 1):
            if rid == gold_id:
                mrr_sum += 1.0 / rank
                break

    if n_valid == 0:
        return {"status": "skipped", "reason": "no queries completed"}

    p1 = hits_at_1 / n_valid
    mrr = mrr_sum / n_valid

    result: dict[str, Any] = {
        "status": "ok",
        "n_queries": n_valid,
        "precision_at_1": round(p1, 4),
        "mrr": round(mrr, 4),
        "gap_vs_offline_rrf": None,
    }

    if baseline_offline_p1 is not None:
        result["gap_vs_offline_rrf"] = round(p1 - baseline_offline_p1, 4)

    return result
