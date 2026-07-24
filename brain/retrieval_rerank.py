"""
Heuristic re-ranking for brain search hits (Phase 1: rules only).

Phase 2 (optional): set ``BRAIN_RERANKER=cross_encoder`` to reserve a hook for
a cross-encoder / bge-reranker — not implemented in v1.
"""

from __future__ import annotations

import os
from typing import Any


def rerank_results(
    query: str,
    results: list[dict[str, Any]],
    *,
    boost_vault: bool = True,
    memory_type: str | None = None,
) -> list[dict[str, Any]]:
    """Reorder API search hits: vault paths get a small boost; optional type filter."""
    mode = os.environ.get("BRAIN_RERANKER", "none").strip().lower()
    if mode == "cross_encoder":
        # Reserved for Phase 2 — fall through to heuristics until wired.
        pass

    rows = list(results)
    if memory_type:
        rows = [
            r
            for r in rows
            if (r.get("metadata") or {}).get("type") == memory_type
        ]

    q_words = len(query.split())

    def sort_key(pair: tuple[int, dict[str, Any]]) -> tuple[float, int]:
        idx, r = pair
        meta = r.get("metadata") or {}
        dist = float(r.get("distance", 1.0))
        adjusted = dist
        fp = (meta.get("file_path") or "") or ""
        if boost_vault and fp.startswith("vault/"):
            adjusted -= 0.12
        content = (r.get("content") or "").strip()
        c_words = len(content.split())
        if q_words >= 12 and 0 < c_words < 40:
            adjusted += 0.08
        return (adjusted, idx)

    indexed = list(enumerate(rows))
    indexed.sort(key=sort_key)
    return [r for _, r in indexed]
