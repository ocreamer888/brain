#!/usr/bin/env python3
"""Leave-one-out retrieval eval (precision@k, MRR) over the full memory corpus.

Complementary to retrieval_eval.py:
- retrieval_eval.py = hand-curated gold queries vs vault-file matches.
- this script = automated, every memory is its own query (title -> body).

Reads brain/rust/brain.db directly. No API needed. Embeds queries with the
same all-mpnet-base-v2 model used at ingest time.

Usage:
    python3 brain/tools/retrieval_eval_kfold.py --sample 200
    python3 brain/tools/retrieval_eval_kfold.py --full --report brain/eval/kfold_report.json

    # Fact-layer eval (after first backfill batch):
    python3 brain/tools/retrieval_eval_kfold.py --facts-only \\
        --gold-semantic brain/tests/fixtures/eval/facts_queries.jsonl \\
        --rollback-batch <BATCH_ID> --rollback-baseline 0.72
"""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

EMBEDDING_DIMS = 768
MIN_QUERY_CHARS = 12  # too-short queries are noise


def rollback_batch(db_path: Path, batch_id: str) -> int:
    """Hard-rollback all facts inserted by a backfill batch.

    Mirrors store.rs rollback_batch: deletes facts, clears superseded_by on
    any memories they superseded, and marks the batch row as rolled_back=1.
    Returns the number of facts deleted.
    """
    conn = sqlite3.connect(str(db_path), timeout=30)
    try:
        fact_ids = [
            row[0]
            for row in conn.execute(
                """SELECT DISTINCT fact_id FROM curation_events
                   WHERE batch_id = ? AND decision IN ('ADD','UPDATE','MERGE')""",
                (batch_id,),
            ).fetchall()
        ]
        if not fact_ids:
            return 0
        for fact_id in fact_ids:
            conn.execute(
                "UPDATE memories SET superseded_by = NULL WHERE superseded_by = ?",
                (fact_id,),
            )
            conn.execute("DELETE FROM memories WHERE id = ?", (fact_id,))
        conn.execute(
            "UPDATE backfill_batches SET rolled_back = 1, finished_at = ? WHERE batch_id = ?",
            (datetime.now(timezone.utc).isoformat(), batch_id),
        )
        conn.commit()
        return len(fact_ids)
    finally:
        conn.close()


def load_corpus(
    db_path: Path,
    facts_only: bool = False,
    episodes_only: bool = False,
) -> tuple[list[dict], np.ndarray]:
    """Load memories from SQLite.

    facts_only: restrict to type=fact with superseded_by IS NULL.
    episodes_only: exclude type=fact (original corpus without fact layer).
    """
    clauses = ["embedding IS NOT NULL"]
    # SQLite stores memory types with embedded JSON quotes, e.g. '"fact"'
    if facts_only:
        clauses.append('type = \'"fact"\'')
        clauses.append("superseded_by IS NULL")
    elif episodes_only:
        clauses.append('type != \'"fact"\'')

    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        f"""
        SELECT id, type, project, title, content, embedding
        FROM memories
        WHERE {' AND '.join(clauses)}
        """
    ).fetchall()
    conn.close()

    metas: list[dict] = []
    embeddings: list[np.ndarray] = []
    for mid, mtype, project, title, content, emb_blob in rows:
        emb = np.frombuffer(emb_blob, dtype="<f4")
        if emb.shape[0] != EMBEDDING_DIMS:
            continue
        metas.append({
            "id": mid,
            "type": mtype or "unknown",
            "project": project or "general",
            "title": (title or "").strip(),
            "content": content or "",
        })
        embeddings.append(emb)
    matrix = np.vstack(embeddings).astype(np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms < 1e-10] = 1.0
    matrix /= norms
    return metas, matrix


def apply_mean_centering(matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Subtract corpus mean and re-normalize (T1). Returns (centered_matrix, mean_vec)."""
    mean_vec = matrix.mean(axis=0)
    centered = matrix - mean_vec
    norms = np.linalg.norm(centered, axis=1, keepdims=True)
    norms[norms < 1e-10] = 1.0
    centered /= norms
    return centered, mean_vec


def query_text_for(meta: dict) -> str | None:
    """Form a realistic query from a memory: prefer title, else first sentence."""
    title = meta["title"]
    if title and len(title) >= MIN_QUERY_CHARS:
        return title
    body = meta["content"].strip()
    if not body:
        return None
    # First sentence-ish: split on newline or period, cap at 200 chars
    first = body.split("\n", 1)[0].split(". ", 1)[0]
    first = first.strip()[:200]
    if len(first) < MIN_QUERY_CHARS:
        return None
    return first


def stratified_sample(
    metas: list[dict],
    fraction: float,
    seed: int,
    full: bool,
) -> list[int]:
    rng = random.Random(seed)
    by_type: dict[str, list[int]] = defaultdict(list)
    for i, m in enumerate(metas):
        by_type[m["type"]].append(i)
    indices: list[int] = []
    for _, idxs in by_type.items():
        if full:
            indices.extend(idxs)
            continue
        n = max(1, int(round(len(idxs) * fraction)))
        sample = rng.sample(idxs, k=min(n, len(idxs)))
        indices.extend(sample)
    rng.shuffle(indices)
    return indices


_FTS_SPECIAL = str.maketrans({c: " " for c in '"\'()[]{}^*?!~'})


def build_fts_index(metas: list[dict]) -> "sqlite3.Connection":
    """In-memory FTS5 index over title + content for BM25 hybrid scoring."""
    import sqlite3 as _sqlite3
    conn = _sqlite3.connect(":memory:")
    conn.execute(
        "CREATE VIRTUAL TABLE fts USING fts5(row_id UNINDEXED, text, tokenize='porter ascii')"
    )
    conn.executemany(
        "INSERT INTO fts(row_id, text) VALUES (?, ?)",
        (
            (i, f"{m['title']} {m['content']}"[:4096])
            for i, m in enumerate(metas)
        ),
    )
    conn.commit()
    return conn


def bm25_ranks_for_queries(
    queries: list[str],
    fts_conn: "sqlite3.Connection",
    n_docs: int,
    top_n: int = 200,
) -> "np.ndarray":
    """Return (Q, N) int32 rank matrix. Non-matching docs get rank n_docs+1."""
    out = np.full((len(queries), n_docs), n_docs + 1, dtype=np.int32)
    for q_i, raw_q in enumerate(queries):
        q = raw_q.translate(_FTS_SPECIAL).strip()
        if not q:
            continue
        try:
            rows = fts_conn.execute(
                "SELECT row_id FROM fts WHERE fts MATCH ? ORDER BY bm25(fts) LIMIT ?",
                (q, top_n),
            ).fetchall()
        except Exception:
            continue
        for rank, (row_id,) in enumerate(rows, 1):
            out[q_i, row_id] = rank
    return out


def evaluate(
    metas: list[dict],
    matrix: np.ndarray,
    held_out_idxs: list[int],
    embed_fn,
    ks: list[int],
    fts_conn=None,
    rrf_k: int = 60,
    fusion: str = "cosine",
    alpha: float = 0.7,
    scoped_project: bool = False,
) -> dict:
    queries: list[str] = []
    valid_idxs: list[int] = []
    for i in held_out_idxs:
        q = query_text_for(metas[i])
        if q is None:
            continue
        queries.append(q)
        valid_idxs.append(i)

    if not queries:
        return {"error": "no valid queries"}

    print(f"Embedding {len(queries)} queries...", file=sys.stderr)
    t0 = time.time()
    q_vecs = np.asarray(embed_fn(queries), dtype=np.float32)
    # mpnet via sentence-transformers normalize_embeddings=True already L2-normalizes
    q_norms = np.linalg.norm(q_vecs, axis=1, keepdims=True)
    q_norms[q_norms < 1e-10] = 1.0
    q_vecs /= q_norms
    print(f"  embed: {time.time() - t0:.1f}s", file=sys.stderr)

    print("Scoring...", file=sys.stderr)
    t0 = time.time()
    # Cosine similarity between every query and every memory: (Q, N)
    sims = q_vecs @ matrix.T
    print(f"  matmul: {time.time() - t0:.1f}s  shape={sims.shape}", file=sys.stderr)

    n_docs = matrix.shape[0]

    # Cosine rank matrix (Q, N): rank of each doc for each query
    # rank = number of docs with strictly higher sim + 1
    cos_ranks = (sims.shape[1] - np.argsort(np.argsort(sims, axis=1), axis=1)).astype(np.float32)

    bm25_ranks = None
    if fts_conn is not None:
        print(f"BM25 ranking {len(queries)} queries (top-200 each)...", file=sys.stderr)
        t0 = time.time()
        bm25_ranks = bm25_ranks_for_queries(queries, fts_conn, n_docs).astype(np.float32)
        print(f"  bm25: {time.time() - t0:.1f}s", file=sys.stderr)

    score_matrix = None
    if fusion == "rrf":
        if bm25_ranks is None:
            return {"error": "rrf fusion requires fts index"}
        # RRF fusion: higher score = better rank
        score_matrix = 1.0 / (rrf_k + cos_ranks) + 1.0 / (rrf_k + bm25_ranks)
    elif fusion == "alpha":
        if bm25_ranks is None:
            return {"error": "alpha fusion requires fts index"}
        # cosine in [-1, 1] -> [0, 1]
        cos_norm = (sims + 1.0) / 2.0
        # rank 1 = 1.0, non-match = 0.0
        bm25_norm = np.where(
            bm25_ranks <= n_docs,
            1.0 - ((bm25_ranks - 1.0) / np.maximum(1.0, n_docs - 1.0)),
            0.0,
        ).astype(np.float32)
        score_matrix = alpha * cos_norm + (1.0 - alpha) * bm25_norm

    # Optional project-scoping: only same-project memories compete with the held-out.
    # Diagnostic ceiling test for cross-project leakage. Skips queries where the
    # held-out is the only memory in its project (no candidates -> undefined rank).
    project_arr = None
    if scoped_project:
        project_arr = np.array([m["project"] for m in metas])

    # Rank of the held-out memory.
    # (self vs self is never strictly greater than itself, so self is excluded automatically.)
    per_query: list[dict] = []
    n_skipped_lonely = 0
    for q_i, mem_i in enumerate(valid_idxs):
        if scoped_project:
            same_proj = project_arr == metas[mem_i]["project"]
            # candidates = same-project docs minus self
            if int(same_proj.sum()) <= 1:
                n_skipped_lonely += 1
                continue

        if score_matrix is not None:
            row = score_matrix[q_i]
            true_score = row[mem_i]
            if scoped_project:
                rank = int(np.sum((row > true_score) & same_proj)) + 1
            else:
                rank = int(np.sum(row > true_score)) + 1
        else:
            row = sims[q_i]
            true_sim = row[mem_i]
            if scoped_project:
                rank = int(np.sum((row > true_sim) & same_proj)) + 1
            else:
                rank = int(np.sum(row > true_sim)) + 1
        per_query.append({
            "memory_id": metas[mem_i]["id"],
            "type": metas[mem_i]["type"],
            "project": metas[mem_i]["project"],
            "rank": rank,
        })

    out = aggregate(per_query, ks)
    if scoped_project:
        out["scoped_project"] = True
        out["n_skipped_lonely_project"] = n_skipped_lonely
    return out


def aggregate(per_query: list[dict], ks: list[int]) -> dict:
    n = len(per_query)
    if n == 0:
        return {"n": 0}

    def precision_at(k: int, rows: list[dict]) -> float:
        return sum(1 for r in rows if r["rank"] <= k) / max(1, len(rows))

    def mrr(rows: list[dict]) -> float:
        return sum(1.0 / r["rank"] for r in rows) / max(1, len(rows))

    overall = {
        "n": n,
        "mrr": round(mrr(per_query), 4),
        **{f"precision@{k}": round(precision_at(k, per_query), 4) for k in ks},
        "median_rank": int(np.median([r["rank"] for r in per_query])),
    }

    by_type: dict[str, list[dict]] = defaultdict(list)
    by_project: dict[str, list[dict]] = defaultdict(list)
    for r in per_query:
        by_type[r["type"]].append(r)
        by_project[r["project"]].append(r)

    def slice_metrics(rows: list[dict]) -> dict:
        return {
            "n": len(rows),
            "mrr": round(mrr(rows), 4),
            **{f"precision@{k}": round(precision_at(k, rows), 4) for k in ks},
        }

    return {
        "overall": overall,
        "by_type": {t: slice_metrics(rows) for t, rows in sorted(by_type.items())},
        "by_project": {
            p: slice_metrics(rows)
            for p, rows in sorted(by_project.items(), key=lambda kv: -len(kv[1]))[:15]
        },
    }


def evaluate_semantic_gold(
    gold: list[dict],
    metas: list[dict],
    matrix: np.ndarray,
    embed_fn,
    ks: list[int],
    fts_conn=None,
    alphas: list[float] | None = None,
    rrf_k: int = 60,
    corpus_mean: np.ndarray | None = None,
) -> dict:
    """Alpha comparison on hand-curated paraphrase queries.

    Each gold entry has:  query, gold_memory_id, k (optional), description (optional).
    For each alpha value, reports P@k and MRR. Designed to show whether higher/lower
    alpha (cosine vs BM25 weight) performs better on semantic paraphrase queries.
    """
    if alphas is None:
        alphas = [0.0, 0.3, 0.5, 0.7, 0.9, 1.0]

    # Build id → matrix index lookup
    id_to_idx: dict[str, int] = {m["id"]: i for i, m in enumerate(metas)}

    # Filter to gold entries whose target ID exists in the corpus
    valid: list[dict] = []
    missing: list[str] = []
    for entry in gold:
        mid = entry["gold_memory_id"]
        if mid in id_to_idx:
            valid.append(entry)
        else:
            missing.append(mid)
    if missing:
        print(f"  [gold-semantic] {len(missing)} gold IDs not in corpus (skipped)", file=sys.stderr)
    if not valid:
        return {"error": "no valid gold entries found in corpus"}

    queries = [e["query"] for e in valid]
    print(f"Embedding {len(queries)} gold-semantic queries...", file=sys.stderr)
    t0 = time.time()
    q_vecs = np.asarray(embed_fn(queries), dtype=np.float32)
    q_norms = np.linalg.norm(q_vecs, axis=1, keepdims=True)
    q_norms[q_norms < 1e-10] = 1.0
    q_vecs /= q_norms
    if corpus_mean is not None:
        q_vecs = q_vecs - corpus_mean
        q_norms2 = np.linalg.norm(q_vecs, axis=1, keepdims=True)
        q_norms2[q_norms2 < 1e-10] = 1.0
        q_vecs /= q_norms2
    print(f"  embed: {time.time() - t0:.1f}s", file=sys.stderr)

    # Cosine sims (Q, N)
    sims = q_vecs @ matrix.T

    n_docs = matrix.shape[0]
    cos_ranks = (sims.shape[1] - np.argsort(np.argsort(sims, axis=1), axis=1)).astype(np.float32)

    bm25_ranks_mat = None
    if fts_conn is not None:
        print(f"BM25 ranking {len(queries)} gold queries...", file=sys.stderr)
        t0 = time.time()
        bm25_ranks_mat = bm25_ranks_for_queries(queries, fts_conn, n_docs).astype(np.float32)
        print(f"  bm25: {time.time() - t0:.1f}s", file=sys.stderr)

    def score_matrix_for_alpha(a: float) -> np.ndarray | None:
        if bm25_ranks_mat is None:
            return None
        cos_norm = (sims + 1.0) / 2.0
        bm25_norm = np.where(
            bm25_ranks_mat <= n_docs,
            1.0 - ((bm25_ranks_mat - 1.0) / np.maximum(1.0, n_docs - 1.0)),
            0.0,
        ).astype(np.float32)
        return (a * cos_norm + (1.0 - a) * bm25_norm).astype(np.float32)

    def rank_for(q_i: int, target_idx: int, sm) -> int:
        if sm is not None:
            return int(np.sum(sm[q_i] > sm[q_i, target_idx])) + 1
        return int(np.sum(sims[q_i] > sims[q_i, target_idx])) + 1

    def precision_at(k: int, ranks: list[int]) -> float:
        return sum(1 for r in ranks if r <= k) / max(1, len(ranks))

    def mrr(ranks: list[int]) -> float:
        return sum(1.0 / r for r in ranks) / max(1, len(ranks))

    alpha_results: dict[str, dict] = {}
    for a in alphas:
        sm = score_matrix_for_alpha(a)
        ranks = [rank_for(q_i, id_to_idx[e["gold_memory_id"]], sm) for q_i, e in enumerate(valid)]
        alpha_results[f"{a:.2f}"] = {
            "alpha": a,
            "n": len(ranks),
            "mrr": round(mrr(ranks), 4),
            **{f"precision@{k}": round(precision_at(k, ranks), 4) for k in ks},
            "median_rank": int(np.median(ranks)),
            "per_query": [
                {
                    "query": e["query"],
                    "gold_memory_id": e["gold_memory_id"],
                    "description": e.get("description", ""),
                    "rank": r,
                }
                for e, r in zip(valid, ranks)
            ],
        }

    best_a = max(alpha_results, key=lambda k: alpha_results[k]["precision@1"])
    return {
        "mode": "gold_semantic",
        "n_queries": len(valid),
        "n_missing": len(missing),
        "best_alpha": float(alpha_results[best_a]["alpha"]),
        "best_precision@1": alpha_results[best_a]["precision@1"],
        "results": alpha_results,
    }


def print_semantic_report(report: dict, ks: list[int]) -> None:
    print(f"\n=== Gold-Semantic Alpha Comparison (n={report['n_queries']}) ===")
    header = f"  {'alpha':>6}  " + "  ".join(f"P@{k:<2}".rjust(6) for k in ks) + "  MRR  med_rank"
    print(header)
    for key, res in report["results"].items():
        ps = "  ".join(f"{res[f'precision@{k}']:.3f}".rjust(6) for k in ks)
        marker = " ← best" if res["alpha"] == report["best_alpha"] else ""
        print(f"  {key:>6}  {ps}  {res['mrr']:.3f}  {res['median_rank']:>4}{marker}")


def print_report(report: dict, ks: list[int]) -> None:
    o = report["overall"]
    print(f"\n=== Overall (n={o['n']}) ===")
    cols = "  ".join(f"P@{k}={o[f'precision@{k}']}" for k in ks)
    print(f"{cols}  MRR={o['mrr']}  median_rank={o['median_rank']}")

    print("\n=== By type ===")
    print(f"  {'type':<20} {'n':>5}  " + "  ".join(f"P@{k:<2}".rjust(6) for k in ks) + "  MRR")
    for t, m in report["by_type"].items():
        ps = "  ".join(f"{m[f'precision@{k}']:.3f}".rjust(6) for k in ks)
        print(f"  {t:<20} {m['n']:>5}  {ps}  {m['mrr']:.3f}")

    print("\n=== By project (top 15) ===")
    print(f"  {'project':<28} {'n':>5}  " + "  ".join(f"P@{k:<2}".rjust(6) for k in ks) + "  MRR")
    for p, m in report["by_project"].items():
        ps = "  ".join(f"{m[f'precision@{k}']:.3f}".rjust(6) for k in ks)
        print(f"  {p:<28} {m['n']:>5}  {ps}  {m['mrr']:.3f}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=_REPO_ROOT / "brain" / "rust" / "brain.db",
        help="SQLite path (default: brain/rust/brain.db)",
    )
    parser.add_argument("--fraction", type=float, default=0.10, help="Stratified hold-out fraction per type (default 0.10)")
    parser.add_argument("--full", action="store_true", help="Use every memory as a query (overrides --fraction)")
    parser.add_argument("--sample", type=int, default=None, help="Cap total queries (random subset of stratified pick)")
    parser.add_argument("--ks", type=str, default="1,5,10", help="Comma-separated k values")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--rrf", action="store_true", help="Hybrid BM25+cosine RRF (k=60)")
    parser.add_argument(
        "--scoped-project",
        action="store_true",
        help="Diagnostic: only same-project memories compete (ceiling test for cross-project leakage)",
    )
    parser.add_argument(
        "--alpha",
        type=float,
        default=0.7,
        help="Alpha for weighted hybrid fusion: alpha*cos + (1-alpha)*bm25_norm",
    )
    parser.add_argument(
        "--alpha-sweep",
        type=str,
        default=None,
        help="Comma-separated alpha values to sweep (implies fusion=alpha), e.g. 0.3,0.5,0.7,0.9",
    )
    parser.add_argument(
        "--gold-semantic",
        type=Path,
        default=None,
        metavar="GOLD_JSONL",
        help="Run alpha comparison on paraphrase gold set instead of leave-one-out",
    )
    parser.add_argument(
        "--mean-center",
        action="store_true",
        help="Apply T1 mean-centering to corpus embeddings (matches production brain.rs behavior)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=_REPO_ROOT / "brain" / "eval" / "kfold_report.json",
    )
    # Fact-layer corpus filters
    parser.add_argument(
        "--facts-only",
        action="store_true",
        help="Restrict corpus to type=fact with superseded_by IS NULL. "
             "Use with --gold-semantic to avoid self-consistency artifacts.",
    )
    parser.add_argument(
        "--episodes-only",
        action="store_true",
        help="Restrict corpus to non-fact memories (original corpus without fact layer).",
    )
    # Rollback gate
    parser.add_argument(
        "--rollback-batch",
        type=str,
        default=None,
        metavar="BATCH_ID",
        help="After eval, if P@1 drops more than 0.05 from --rollback-baseline, "
             "hard-rollback this batch (deletes facts, clears superseded_by, marks batch rolled_back=1).",
    )
    parser.add_argument(
        "--rollback-baseline",
        type=float,
        default=None,
        metavar="P1_BEFORE",
        help="P@1 baseline to compare against for the rollback gate.",
    )
    args = parser.parse_args(argv)

    if args.facts_only and args.episodes_only:
        print("--facts-only and --episodes-only are mutually exclusive", file=sys.stderr)
        return 2

    ks = [int(x) for x in args.ks.split(",") if x.strip()]

    if not args.db.exists():
        print(f"DB not found: {args.db}", file=sys.stderr)
        return 2

    print(f"Loading corpus from {args.db}...", file=sys.stderr)
    if args.facts_only:
        print("  corpus filter: type=fact AND superseded_by IS NULL", file=sys.stderr)
        if not args.gold_semantic:
            print(
                "  [warn] --facts-only without --gold-semantic uses leave-one-out queries, "
                "which inflate P@1 (self-consistency artifact). "
                "Use --gold-semantic brain/tests/fixtures/eval/facts_queries.jsonl for real eval.",
                file=sys.stderr,
            )
    elif args.episodes_only:
        print("  corpus filter: type != fact (episodes only)", file=sys.stderr)

    metas, matrix = load_corpus(args.db, facts_only=args.facts_only, episodes_only=args.episodes_only)
    print(f"  loaded {len(metas)} memories, {matrix.shape[1]} dims", file=sys.stderr)

    corpus_mean: np.ndarray | None = None
    if args.mean_center:
        matrix, corpus_mean = apply_mean_centering(matrix)
        print("  applied T1 mean-centering", file=sys.stderr)

    held_out = stratified_sample(metas, args.fraction, args.seed, args.full)
    if args.sample is not None and args.sample < len(held_out):
        rng = random.Random(args.seed)
        held_out = rng.sample(held_out, args.sample)
    print(f"  held-out: {len(held_out)} ({'full' if args.full else f'{args.fraction:.0%} stratified'})", file=sys.stderr)

    # Lazy import — model load is slow, only after corpus check passes
    from brain.core.embedder import embed_batch

    fts_conn = None
    if args.rrf or args.alpha_sweep or args.gold_semantic:
        print("Building in-memory FTS5 index...", file=sys.stderr)
        t0 = time.time()
        fts_conn = build_fts_index(metas)
        print(f"  fts build: {time.time() - t0:.1f}s", file=sys.stderr)

    if args.gold_semantic:
        gold_path = args.gold_semantic if args.gold_semantic.is_absolute() else _REPO_ROOT / args.gold_semantic
        gold: list[dict] = []
        for line in gold_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                gold.append(json.loads(line))
        alphas = (
            [float(x) for x in args.alpha_sweep.split(",") if x.strip()]
            if args.alpha_sweep
            else [0.0, 0.3, 0.5, 0.7, 0.9, 1.0]
        )
        report = evaluate_semantic_gold(
            gold, metas, matrix, embed_batch, ks,
            fts_conn=fts_conn, alphas=alphas, rrf_k=60,
            corpus_mean=corpus_mean,
        )
        if "error" in report:
            print(f"FAIL: {report['error']}", file=sys.stderr)
            return 2
        report_path = args.report if args.report.is_absolute() else _REPO_ROOT / args.report
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print_semantic_report(report, ks)
        print(f"\nWrote {report_path}")
        return 0

    if args.alpha_sweep:
        alphas = [float(x) for x in args.alpha_sweep.split(",") if x.strip()]
        sweep: dict[str, dict] = {}
        best_alpha = None
        best_p1 = -1.0
        for a in alphas:
            rep = evaluate(
                metas,
                matrix,
                held_out,
                embed_batch,
                ks,
                fts_conn=fts_conn,
                fusion="alpha",
                alpha=a,
                scoped_project=args.scoped_project,
            )
            sweep[f"{a:.3f}"] = rep
            p1 = rep["overall"]["precision@1"]
            if p1 > best_p1:
                best_p1 = p1
                best_alpha = a
        report = {
            "mode": "alpha_sweep",
            "best_alpha": best_alpha,
            "best_precision@1": best_p1,
            "results": sweep,
        }
        print("\n=== Alpha Sweep (overall) ===")
        for k, rep in sweep.items():
            o = rep["overall"]
            print(f"alpha={k}  P@1={o['precision@1']}  P@3={o.get('precision@3','-')}  MRR={o['mrr']}")
        print(f"best_alpha={best_alpha}  best_P@1={best_p1}")
    else:
        fusion = "rrf" if args.rrf else "cosine"
        report = evaluate(
            metas,
            matrix,
            held_out,
            embed_batch,
            ks,
            fts_conn=fts_conn,
            fusion=fusion,
            alpha=args.alpha,
            scoped_project=args.scoped_project,
        )
    if "error" in report:
        print(f"FAIL: {report['error']}", file=sys.stderr)
        return 2

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if args.alpha_sweep:
        pass
    else:
        print_report(report, ks)
    print(f"\nWrote {args.report}")

    # Rollback gate — only runs when both --rollback-batch and --rollback-baseline are set
    if args.rollback_batch and args.rollback_baseline is not None:
        p1_after = report.get("overall", {}).get("precision@1", 0.0)
        n_queries = report.get("overall", {}).get("n", 0)
        threshold = args.rollback_baseline - 0.05
        print(f"\n[rollback gate] batch={args.rollback_batch!r}")
        print(f"  p1_before={args.rollback_baseline:.3f}  p1_after={p1_after:.3f}  threshold={threshold:.3f}")
        # Base-case guard: skip if fewer than 5 queries — not enough signal
        if n_queries < 5:
            print(f"  SKIPPED — only {n_queries} queries in eval set (need ≥5 for a reliable rollback decision)")
        elif p1_after < threshold:
            print("  TRIGGERED — rolling back batch...")
            n_deleted = rollback_batch(args.db, args.rollback_batch)
            print(f"  ROLLED BACK: {n_deleted} facts deleted from batch {args.rollback_batch!r}")
            return 1  # non-zero exit signals rollback happened
        else:
            print("  OK — P@1 within acceptable range, batch retained")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
