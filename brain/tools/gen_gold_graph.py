#!/usr/bin/env python3
"""Generate a graph-aware gold set for the `graph_expand` A/B (amendment A1).

Selects *edge-linked* active memories across the seven durable types, asks a
cheap local Ollama model for a paraphrased question each note answers, rejects
queries that share too much vocabulary with the note, and writes a JSONL gold
file that is a superset of the existing `gold_semantic.jsonl` schema (so
`mcp_eval.load_gold` still reads it).

Two hard preconditions:
  * run this AFTER the durable backfill (A6) — before it, only `fact` rows have
    edges and the non-fact strata cannot be filled;
  * `EXISTS (SELECT 1 FROM edges ...)` is a *necessary* condition for graph
    expansion to be able to reach the target at all.

SQLite access is read-only (`file:...?mode=ro`); the API owns every write.

Usage:
    python3 brain/tools/gen_gold_graph.py --out brain/eval/gold_graph_expand.jsonl --seed 42
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import OLLAMA_SUMMARIZE_MODEL, OLLAMA_URL  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = _REPO_ROOT / "brain" / "rust" / "brain.db"
DEFAULT_OUT = _REPO_ROOT / "brain" / "eval" / "gold_graph_expand.jsonl"

# Stratification from A1. Sums to 150 usable queries. `conversation` is included
# per locked decision D1; `episode` must never appear (D2 — it is an audit-body
# type with 0 rows).
DURABLE_STRATA: dict[str, int] = {
    "solution": 40,
    "fact": 30,
    "conversation": 15,
    "project_context": 20,
    "pattern": 20,
    "error_lesson": 15,
    "decision": 10,
}

EXCLUDED_TYPE = "episode"

# Calibrated, NOT arbitrary: containment overlap measured across the 17 real
# rows of gold_semantic.jsonl is mean 0.224, max 0.455 with this tokenizer
# (word tokens minus English stopwords). Rejecting > 0.45 reproduces the
# hand-written distribution. Do not "tune" this without re-measuring.
MAX_VOCAB_OVERLAP = 0.45
MIN_CONTENT_CHARS = 200

# Ollama request budget. Query generation is a single short completion.
_LLM_TIMEOUT = 120

_QUERY_PROMPT = """Write one natural question a developer would ask that this note answers. \
Use NO words from the note — paraphrase every technical term into plain description. \
Return JSON: {{"query": "..."}}

Note:
{content}"""

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Function words carry no retrieval signal; including them inflates containment
# overlap uniformly and destroys the calibration above.
_STOPWORDS = frozenset("""
a an the and or but if then than that this these those is are was were be been
being am do does did doing have has had having i me my we our you your he she
it its they them their of in on at to for from by with without into over under
again further once here there when where why how all any both each few more
most other some such no nor not only own same so too very can will just should
now as what which who whom don t s
""".split())


# ---------------------------------------------------------------------------
# Query generation (self-contained cheap-Ollama call)
#
# Deliberately NOT imported from backfill_entities.py: A5 is refactoring that
# module's extractor into brain/core, and this tool must not be coupled to it.
# stdlib urllib only, so `--help` works under any interpreter.
# ---------------------------------------------------------------------------

def _call_llm(prompt: str, model: str) -> str:
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0.0},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url=f"{OLLAMA_URL}/api/chat",
        data=body,
        method="POST",
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=_LLM_TIMEOUT) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload.get("message", {}).get("content") or ""


def _parse_query(raw: str) -> str | None:
    """Defensive JSON parse. Returns None on any malformed response."""
    stripped = raw.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        stripped = "\n".join(lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:])
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    query = data.get("query")
    if not isinstance(query, str):
        return None
    query = query.strip()
    return query or None


def generate_query(content: str, model: str = OLLAMA_SUMMARIZE_MODEL) -> str | None:
    """One paraphrased question for `content`. None on any LLM/parse failure."""
    try:
        raw = _call_llm(_QUERY_PROMPT.format(content=content), model)
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        print(f"[gen_gold_graph] LLM call failed: {e}", file=sys.stderr)
        return None
    return _parse_query(raw)


# ---------------------------------------------------------------------------
# Validity filter
# ---------------------------------------------------------------------------

def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower())) - _STOPWORDS


def vocab_overlap(query: str, content: str) -> float:
    """|tokens(query) ∩ tokens(content)| / |tokens(query)| — containment overlap.

    Returns 1.0 (i.e. always rejected) for a query with no content-bearing
    tokens, since such a query cannot be a meaningful retrieval probe.
    """
    q_tokens = _tokens(query)
    if not q_tokens:
        return 1.0
    return len(q_tokens & _tokens(content)) / len(q_tokens)


# ---------------------------------------------------------------------------
# Selection (read-only SQLite)
# ---------------------------------------------------------------------------

def _ro_connect(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _sql_type(memory_type: str) -> str:
    """`memories.type` is stored JSON-quoted: bare `fact` -> SQL literal `"fact"`."""
    return json.dumps(memory_type)


def select_linked_candidates(
    db_path: Path | str,
    memory_type: str,
    limit: int,
    min_chars: int = MIN_CONTENT_CHARS,
    seed: int = 42,
) -> list[dict[str, Any]]:
    """Reproducible sample of active, edge-linked memories of `memory_type`.

    Reproducible sampling means: fetch the full candidate id list, sort it, then
    `random.Random(seed).sample`. `ORDER BY RANDOM()` is unseeded and would make
    the gold set irreproducible across runs.
    """
    if memory_type == EXCLUDED_TYPE:
        raise ValueError(f"{EXCLUDED_TYPE!r} is excluded from the durable set (D2)")
    if limit <= 0:
        return []

    conn = _ro_connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id FROM memories m "
            "WHERE m.type = ? "
            "AND (m.superseded_by IS NULL OR m.superseded_by = '') "
            "AND length(m.content) >= ? "
            "AND EXISTS (SELECT 1 FROM edges WHERE src_memory_id = m.id)",
            (_sql_type(memory_type), min_chars),
        ).fetchall()
        ids = sorted(str(r["id"]) for r in rows)
        if not ids:
            return []
        picked = random.Random(seed).sample(ids, min(limit, len(ids)))

        placeholders = ",".join("?" * len(picked))
        detail = conn.execute(
            "SELECT m.id, m.content, m.project, m.type, m.timestamp, "
            "(SELECT COUNT(*) FROM edges WHERE src_memory_id = m.id) AS n_edges "
            f"FROM memories m WHERE m.id IN ({placeholders})",
            picked,
        ).fetchall()
    finally:
        conn.close()

    by_id = {str(r["id"]): dict(r) for r in detail}
    out: list[dict[str, Any]] = []
    for mid in picked:  # preserve the seeded sample order
        row = by_id.get(mid)
        if row is None:
            continue
        row["memory_type"] = memory_type
        out.append(row)
    return out


def neighbor_degree(db_path: Path | str, memory_id: str) -> int:
    """Size of the 1-hop neighbour set: distinct other memories sharing an entity.

    Reported as a covariate — the measured distribution over 2,000 linked
    memories is mean 53.5, max 957.
    """
    conn = _ro_connect(db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(DISTINCT e2.src_memory_id) AS deg "
            "FROM edges e1 JOIN edges e2 ON e1.dst_entity_id = e2.dst_entity_id "
            "WHERE e1.src_memory_id = ? AND e2.src_memory_id <> ?",
            (memory_id, memory_id),
        ).fetchone()
    finally:
        conn.close()
    return int(row["deg"]) if row else 0


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def _validate_strata(strata: dict[str, int]) -> None:
    if EXCLUDED_TYPE in strata:
        raise ValueError(f"{EXCLUDED_TYPE!r} must never appear in the gold strata (D2)")
    unknown = set(strata) - set(DURABLE_STRATA)
    if unknown:
        raise ValueError(f"non-durable memory types in strata: {sorted(unknown)}")


def build_gold(
    db_path: Path | str,
    strata: dict[str, int],
    out_path: Path | str,
    max_overlap: float = MAX_VOCAB_OVERLAP,
    oversample: float = 1.5,
    seed: int = 42,
    dry_run: bool = False,
    model: str = OLLAMA_SUMMARIZE_MODEL,
    min_chars: int = MIN_CONTENT_CHARS,
) -> dict[str, Any]:
    """Generate one gold row per accepted query, stratified by memory type."""
    _validate_strata(strata)
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"database not found: {db_path}")

    rows: list[dict[str, Any]] = []
    stats: dict[str, Any] = {
        "by_type": {},
        "rejected_overlap": 0,
        "rejected_llm": 0,
        "shortfalls": {},
    }
    generated_at = datetime.now(timezone.utc).isoformat()

    for memory_type, want in strata.items():
        candidates = select_linked_candidates(
            db_path,
            memory_type,
            limit=int(math.ceil(want * oversample)),
            min_chars=min_chars,
            seed=seed,
        )
        accepted = 0
        for cand in candidates:
            if accepted >= want:
                break
            content = str(cand["content"])
            query = generate_query(content, model=model)
            if query is None:
                stats["rejected_llm"] += 1
                continue
            overlap = vocab_overlap(query, content)
            if overlap > max_overlap:
                stats["rejected_overlap"] += 1
                continue
            rows.append(
                {
                    "query": query,
                    "gold_memory_id": str(cand["id"]),
                    "k": 10,
                    "description": f"llm paraphrase of a {memory_type} note",
                    "memory_type": memory_type,
                    "project": str(cand.get("project") or "general"),
                    "n_edges": int(cand.get("n_edges") or 0),
                    "neighbor_degree": neighbor_degree(db_path, str(cand["id"])),
                    "source": "llm_paraphrase",
                    "generated_at": generated_at,
                    "vocab_overlap": round(overlap, 4),
                }
            )
            accepted += 1

        stats["by_type"][memory_type] = accepted
        if accepted < want:
            stats["shortfalls"][memory_type] = want - accepted
            print(
                f"[gen_gold_graph] WARNING: {memory_type} filled {accepted}/{want} "
                f"(pool exhausted; raise --oversample)",
                file=sys.stderr,
            )

    stats["n_rows"] = len(rows)
    stats["out_path"] = str(out_path)
    stats["dry_run"] = dry_run

    if not dry_run:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
            encoding="utf-8",
        )
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate the graph-aware gold set for the graph_expand A/B (A1). "
        "Run AFTER the durable backfill — non-fact types have no edges before it."
    )
    parser.add_argument("--db", default=str(DB_PATH), help="SQLite path (read-only)")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="output JSONL path")
    parser.add_argument("--seed", type=int, default=42, help="sampling seed")
    parser.add_argument(
        "--oversample",
        type=float,
        default=1.5,
        help="candidates fetched per stratum as a multiple of the target n (~30%% filter loss)",
    )
    parser.add_argument(
        "--max-overlap",
        type=float,
        default=MAX_VOCAB_OVERLAP,
        help="reject queries whose containment overlap with the note exceeds this (calibrated)",
    )
    parser.add_argument("--min-chars", type=int, default=MIN_CONTENT_CHARS)
    parser.add_argument("--model", default=OLLAMA_SUMMARIZE_MODEL)
    parser.add_argument("--dry-run", action="store_true", help="generate but do not write")
    args = parser.parse_args()

    stats = build_gold(
        db_path=args.db,
        strata=dict(DURABLE_STRATA),
        out_path=args.out,
        max_overlap=args.max_overlap,
        oversample=args.oversample,
        seed=args.seed,
        dry_run=args.dry_run,
        model=args.model,
        min_chars=args.min_chars,
    )
    print(json.dumps(stats, indent=2))
    return 0 if stats["n_rows"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
