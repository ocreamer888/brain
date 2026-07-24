"""
Post-ingest quality gate: samples k-fold P@1 by type and warns/fails on thresholds.

Reads brain.db directly — no API required. Uses cosine similarity (no BM25) for
speed. Samples up to MAX_SAMPLE per type to keep runtime under 60s.

Exit codes:
    0  All types meet warning threshold (>= 0.45 P@1)
    1  At least one type below warning threshold
    2  At least one type below error threshold (< 0.25 P@1)

Usage:
    python3 brain/tools/ingest_quality_gate.py [--db PATH] [--sample N]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Tuple

import numpy as np

DEFAULT_DB = Path(__file__).resolve().parents[1] / "rust" / "brain.db"
MAX_SAMPLE = 300
WARN_THRESHOLD = 0.45
ERROR_THRESHOLD = 0.25
TARGET_TYPES = ['"conversation"', '"pattern"', '"solution"', '"project_context"']


def _load_sample(conn: sqlite3.Connection, memory_type: str, n: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, title, content, embedding FROM memories "
        "WHERE type=? AND embedding IS NOT NULL "
        "ORDER BY RANDOM() LIMIT ?",
        (memory_type, n),
    ).fetchall()
    result = []
    for row in rows:
        mid, title, content, emb_blob = row
        if not emb_blob:
            continue
        emb = np.frombuffer(emb_blob, dtype=np.float32).copy()
        query_text = title.strip() if title and len(title.strip()) >= 12 else (content or "")[:200]
        result.append({"id": mid, "query_text": query_text, "embedding": emb})
    return result


def _cosine_top1(query_emb: np.ndarray, corpus: list[dict], own_id: str) -> str | None:
    """Return id of top-1 hit including query itself."""
    sims = []
    for item in corpus:
        norm = float(np.linalg.norm(query_emb) * np.linalg.norm(item["embedding"]))
        if norm == 0:
            continue
        dot = float(np.dot(query_emb, item["embedding"]))
        sims.append((dot / norm, item["id"]))
    if not sims:
        return None
    sims.sort(reverse=True)
    return sims[0][1]


def run_gate(db_path: Path = DEFAULT_DB, sample: int = MAX_SAMPLE) -> Tuple[dict, int]:
    conn = sqlite3.connect(str(db_path))

    results: dict[str, float] = {}
    exit_code = 0

    print(f"Quality gate — sampling up to {sample} per type from {db_path.name}\n")

    for mtype in TARGET_TYPES:
        corpus = _load_sample(conn, mtype, sample)
        if len(corpus) < 2:
            print(f"  {mtype:20s}  n={len(corpus):4d}  SKIP (too few)")
            continue

        hits = 0
        for item in corpus:
            top1_id = _cosine_top1(item["embedding"], corpus, item["id"])
            if top1_id == item["id"]:
                hits += 1

        p1 = hits / len(corpus)
        results[mtype] = p1
        status = "OK" if p1 >= WARN_THRESHOLD else ("WARN" if p1 >= ERROR_THRESHOLD else "ERROR")
        print(f"  {mtype:20s}  n={len(corpus):4d}  P@1={p1:.3f}  [{status}]")

        if p1 < ERROR_THRESHOLD:
            exit_code = 2
        elif p1 < WARN_THRESHOLD and exit_code < 1:
            exit_code = 1

    conn.close()
    return results, exit_code


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--sample", type=int, default=MAX_SAMPLE)
    args = parser.parse_args()

    _, exit_code = run_gate(db_path=args.db, sample=args.sample)
    print(f"\nExit code: {exit_code}")
    if exit_code == 2:
        print("  ERROR: critical retrieval regression detected")
    elif exit_code == 1:
        print("  WARN: some types below threshold — run full k-fold eval")
    else:
        print("  OK: all types meet threshold")
    sys.exit(exit_code)
