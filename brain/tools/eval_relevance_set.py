#!/usr/bin/env python3
"""Relevance-set retrieval eval: a hit = top-1 is ANY memory in the query's
relevant_ids set (fair for corpora with topically-overlapping / near-duplicate
memories, where single-gold-ID P@1 understates quality).

Reports success@1, recall@10, and MRR (first relevant). RRF fusion of cosine +
BM25, identical to the production retrieval path. Reads a DB snapshot directly,
so it reflects in-place embedding changes without a server restart.

Usage:
    python3 brain/tools/eval_relevance_set.py --db brain/rust/brain.db --gold brain/eval/gold_sicop.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "brain"))

from brain.tools.mcp_eval import load_gold
from brain.tools.retrieval_eval_kfold import build_fts_index, bm25_ranks_for_queries, load_corpus
from brain.core.embedder import embed_batch


def evaluate(db: Path, gold_path: Path, rrf_k: int = 60) -> dict:
    gold = load_gold(gold_path)
    metas, matrix = load_corpus(db)
    id8 = [m["id"][:8] for m in metas]

    queries = [str(g["query"]) for g in gold]
    qv = np.asarray(embed_batch(queries), dtype=np.float32)
    qv /= np.linalg.norm(qv, axis=1, keepdims=True).clip(1e-10)
    sims = qv @ matrix.T
    cos_ranks = (sims.shape[1] - np.argsort(np.argsort(sims, axis=1), axis=1)).astype(np.float32)
    bm = bm25_ranks_for_queries(queries, build_fts_index(metas), matrix.shape[0]).astype(np.float32)
    rrf = 1.0 / (rrf_k + cos_ranks) + 1.0 / (rrf_k + bm)

    succ1 = rec10 = 0
    mrr = 0.0
    per_query = []
    for i, g in enumerate(gold):
        rel = set(g.get("relevant_ids") or [g["gold_memory_id"][:8]])
        order = np.argsort(-rrf[i])  # best first
        # rank (1-based) of first relevant doc
        first_rel = None
        for rank, idx in enumerate(order, 1):
            if id8[idx] in rel:
                first_rel = rank
                break
        top1_rel = first_rel == 1
        in10 = first_rel is not None and first_rel <= 10
        succ1 += int(top1_rel)
        rec10 += int(in10)
        mrr += (1.0 / first_rel) if first_rel else 0.0
        per_query.append({"q": queries[i][:50], "first_relevant_rank": first_rel})

    n = len(gold)
    return {
        "n": n,
        "success_at_1": round(succ1 / n, 4),
        "recall_at_10": round(rec10 / n, 4),
        "mrr": round(mrr / n, 4),
        "per_query": per_query,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--gold", type=Path, required=True)
    args = ap.parse_args(argv)
    res = evaluate(args.db, args.gold)
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
