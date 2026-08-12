"""Curate extracted facts against the existing store.

Three-tier similarity gate per fact:
  max_sim > 0.92  → IGNORE (exact duplicate)
  0.78–0.92       → LLM tiebreaker → ADD | UPDATE | MERGE | IGNORE
  max_sim < 0.78  → ADD (clearly new)

Guards:
  Gap-1: hallucination guard — reject UPDATE/MERGE if old_id not in top-5 result set.
  Gap-2: empty facts early exit — skip the whole curation call if new_facts is empty.

Writes new facts via the brain HTTP API.
Logs curation events and marks superseded facts via direct SQLite (no HTTP endpoint exists).
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import sys

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import OLLAMA_URL, OLLAMA_SUMMARIZE_MODEL
from brain.core.embedder import embed, embed_batch
import brain.api_client as api_client
from brain.ingest.fact_extractor import FactDraft

IGNORE_THRESHOLD = 0.92
TIEBREAK_LOW = 0.78


@dataclass
class CurationResult:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    merged: list[str] = field(default_factory=list)
    ignored: int = 0
    errors: int = 0
    reason: Optional[str] = None


# ---------------------------------------------------------------------------
# SQLite helpers (direct DB access — no HTTP endpoint for these operations)
# ---------------------------------------------------------------------------

def _db_path() -> str:
    return os.environ.get("BRAIN_DB_PATH", str(Path.home() / ".brain" / "brain.db"))


def _db_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _mark_superseded(old_id: str, new_id: str) -> None:
    conn = _db_conn()
    try:
        conn.execute(
            "UPDATE memories SET superseded_by = ? WHERE id = ?",
            (new_id, old_id),
        )
        conn.commit()
    finally:
        conn.close()


def _log_curation_event(
    fact_id: str,
    decision: str,
    sim: float,
    reason: str,
    model: str,
    batch_id: str,
) -> None:
    conn = _db_conn()
    try:
        conn.execute(
            """INSERT INTO curation_events
               (id, ts, fact_id, decision, sim, reason, model, batch_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4()),
                datetime.now(timezone.utc).isoformat(),
                fact_id,
                decision,
                sim,
                reason,
                model,
                batch_id,
            ),
        )
        conn.commit()
    except Exception:
        pass  # logging is best-effort; don't fail curation over it
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# LLM tiebreaker
# ---------------------------------------------------------------------------

def _call_tiebreaker(
    existing_content: str,
    new_content: str,
    sim: float,
    model: str,
) -> dict:
    """Returns dict with keys: decision, reason, merged_content (optional)."""
    prompt = f"""\
Two facts are similar but not identical. Decide what to do with the new one.

Context:
{{
  "existing_fact": {json.dumps(existing_content)},
  "new_fact": {json.dumps(new_content)},
  "cosine_similarity": {sim:.4f}
}}

Return ONLY valid JSON:
{{
  "decision": "ADD|UPDATE|MERGE|IGNORE",
  "reason": "one sentence",
  "merged_content": "only present if decision is MERGE"
}}

- ADD: new fact adds genuinely new information not in existing
- UPDATE: new fact supersedes existing (more accurate or complete)
- MERGE: both have value; unified content is better than either alone
- IGNORE: new fact is redundant or lower quality"""

    resp = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": OLLAMA_SUMMARIZE_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0.0},
        },
        timeout=60,
    )
    resp.raise_for_status()
    raw = resp.json()["message"]["content"]
    if not raw:
        raise ValueError("LLM tiebreaker returned empty content")

    stripped = raw.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        stripped = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    result = json.loads(stripped)
    if result.get("decision") not in {"ADD", "UPDATE", "MERGE", "IGNORE"}:
        raise ValueError(f"Invalid tiebreaker decision: {result.get('decision')!r}")
    return result


# ---------------------------------------------------------------------------
# Save via HTTP API
# ---------------------------------------------------------------------------

def _save_fact(
    draft: FactDraft,
    project: str,
    parent_id: str | None,
    session_id: str | None,
    source_event_time: str | None = None,
) -> str:
    tags = ["brain/ingest", f"fact_type:{draft.fact_type}"]
    effective_event_time = draft.event_time or source_event_time
    return api_client.save_memory(
        content=draft.content,
        memory_type="fact",
        tags=tags,
        project=project,
        session_id=session_id,
        title=draft.content[:120],
        parent_id=parent_id,
        event_time=effective_event_time,
        salience=draft.salience,
        derived_from=draft.derived_from or None,
        entities=draft.entities or None,
        auto_entities=False,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def curate_facts(
    new_facts: list[FactDraft],
    project: str,
    batch_id: str,
    parent_id: str | None = None,
    session_id: str | None = None,
    tiebreaker_model: str = OLLAMA_SUMMARIZE_MODEL,
    source_event_time: str | None = None,
) -> CurationResult:
    # Gap-2: empty facts early exit (Mem0 b3d340f pattern)
    if not new_facts:
        return CurationResult(reason="no_facts_extracted")

    result = CurationResult()
    for draft in new_facts:
        try:
            _curate_one(
                draft=draft,
                project=project,
                batch_id=batch_id,
                parent_id=parent_id,
                session_id=session_id,
                tiebreaker_model=tiebreaker_model,
                result=result,
                source_event_time=source_event_time,
            )
        except Exception:
            result.errors += 1
    return result


# ---------------------------------------------------------------------------
# Per-fact logic
# ---------------------------------------------------------------------------

def _curate_one(
    draft: FactDraft,
    project: str,
    batch_id: str,
    parent_id: str | None,
    session_id: str | None,
    tiebreaker_model: str,
    result: CurationResult,
    source_event_time: str | None = None,
) -> None:
    # Search top-5 existing facts (same project, type=fact)
    raw_existing = api_client.search(
        query=draft.content,
        n=5,
        memory_type="fact",
        project=project,
    )
    # Filter out already-superseded facts
    existing = [e for e in raw_existing if not e.get("metadata", {}).get("superseded_by")]

    # Gap-1: build valid_ids set for hallucination guard
    valid_ids = {e.get("id") for e in existing}

    if not existing:
        new_id = _save_fact(draft, project, parent_id, session_id, source_event_time)
        _log_curation_event(new_id, "ADD", 0.0, "no existing facts", "", batch_id)
        result.added.append(new_id)
        return

    # Embed new fact + all existing in one batch call (in-process, no HTTP)
    all_texts = [draft.content] + [e.get("content", "") for e in existing]
    all_vecs = np.array(embed_batch(all_texts), dtype=np.float32)
    new_vec = all_vecs[0]
    existing_vecs = all_vecs[1:]

    sims = (existing_vecs @ new_vec).tolist()
    best_idx = int(np.argmax(sims))
    max_sim = float(sims[best_idx])
    best = existing[best_idx]

    if max_sim > IGNORE_THRESHOLD:
        _log_curation_event(
            best.get("id", ""), "IGNORE", max_sim, "above ignore threshold", "", batch_id
        )
        result.ignored += 1
        return

    if max_sim < TIEBREAK_LOW:
        new_id = _save_fact(draft, project, parent_id, session_id, source_event_time)
        _log_curation_event(new_id, "ADD", max_sim, "below tiebreak threshold", "", batch_id)
        result.added.append(new_id)
        return

    # Tiebreaker zone: call LLM
    llm = _call_tiebreaker(
        existing_content=best.get("content", ""),
        new_content=draft.content,
        sim=max_sim,
        model=tiebreaker_model,
    )
    decision = llm["decision"]
    reason = llm.get("reason", "")
    old_id = best.get("id", "")

    if decision == "ADD":
        new_id = _save_fact(draft, project, parent_id, session_id, source_event_time)
        _log_curation_event(new_id, "ADD", max_sim, reason, tiebreaker_model, batch_id)
        result.added.append(new_id)

    elif decision == "UPDATE":
        # Gap-1: hallucination guard — reject if old_id not in the top-5 result set
        if old_id not in valid_ids:
            _log_curation_event(
                old_id, "IGNORE", max_sim, "hallucinated_id", tiebreaker_model, batch_id
            )
            result.ignored += 1
            return
        new_id = _save_fact(draft, project, parent_id, session_id, source_event_time)
        _mark_superseded(old_id, new_id)
        _log_curation_event(new_id, "UPDATE", max_sim, reason, tiebreaker_model, batch_id)
        result.updated.append(new_id)

    elif decision == "MERGE":
        # Gap-1: hallucination guard
        if old_id not in valid_ids:
            _log_curation_event(
                old_id, "IGNORE", max_sim, "hallucinated_id", tiebreaker_model, batch_id
            )
            result.ignored += 1
            return
        merged_content = llm.get("merged_content") or draft.content
        merged = FactDraft(
            content=merged_content,
            salience=max(draft.salience, float(best.get("metadata", {}).get("salience") or 0.5)),
            event_time=draft.event_time,
            entities=draft.entities,
            fact_type=draft.fact_type,
            derived_from=draft.derived_from,
        )
        new_id = _save_fact(merged, project, parent_id, session_id, source_event_time)
        _mark_superseded(old_id, new_id)
        _log_curation_event(new_id, "MERGE", max_sim, reason, tiebreaker_model, batch_id)
        result.merged.append(new_id)

    else:  # IGNORE
        _log_curation_event(old_id, "IGNORE", max_sim, reason, tiebreaker_model, batch_id)
        result.ignored += 1
