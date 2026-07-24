"""Extract atomic facts from episode text using a non-reasoning LLM.

CRITICAL: Only use non-reasoning models (gemini-2.5-flash-lite, gpt-4o-mini).
Reasoning models emit to `reasoning_content`, leaving `content` empty — silent garbage.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
import sys

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import OLLAMA_URL, OLLAMA_SUMMARIZE_MODEL
from brain.core.embedder import embed_batch

_VALID_FACT_TYPES = frozenset({"decision", "error_fix", "preference", "named_entity", "outcome"})

_PROMPT_V1 = """\
Extract up to {max_facts} atomic, self-contained facts from the session below.

Return ONLY a JSON object matching this schema exactly:
{{
  "facts": [
    {{
      "content": "One clear, specific, self-contained fact statement.",
      "salience": 0.85,
      "event_time": null,
      "entities": ["entity1", "entity2"],
      "fact_type": "decision"
    }}
  ]
}}

Rules:
- fact_type must be one of: decision, error_fix, preference, named_entity, outcome
- salience: 0.0–1.0 — how durable and important this fact is
- event_time: ISO8601 if a specific date/time is mentioned, else null
- content must be non-empty and self-contained (no dangling pronouns)
- Sort facts by salience descending; return at most {max_facts}
- If nothing worth extracting: return {{"facts": []}}
- Output ONLY the JSON object — no markdown, no explanation

Session:
{episode_text}"""


@dataclass
class FactDraft:
    content: str
    salience: float
    event_time: str | None
    entities: list[str]
    fact_type: str   # "decision"|"error_fix"|"preference"|"named_entity"|"outcome"
    derived_from: str = field(default="")  # set by extract_facts; passed through to curator


def _call_llm(prompt: str) -> str:
    """Call local Ollama (non-reasoning model) for fact extraction."""
    resp = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": OLLAMA_SUMMARIZE_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0.0},
        },
        timeout=120,
    )
    resp.raise_for_status()
    content = resp.json()["message"]["content"]
    if not content:
        raise ValueError(
            "LLM returned empty content — likely a reasoning model. "
            "Use a non-reasoning Ollama model (e.g. qwen2.5:32b)."
        )
    return content


def _parse_facts(raw_json: str, max_facts: int) -> list[FactDraft]:
    """Parse and validate LLM response. Raises ValueError on JSON failure — whole batch rejected."""
    # Strip markdown fences if the model wrapped the JSON anyway
    stripped = raw_json.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        stripped = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON parse failed — rejecting whole batch: {e}") from e

    if not isinstance(data, dict) or "facts" not in data:
        raise ValueError("LLM response missing 'facts' key — rejecting whole batch")
    if not isinstance(data["facts"], list):
        raise ValueError("'facts' must be a list — rejecting whole batch")

    results: list[FactDraft] = []
    for item in data["facts"]:
        if not isinstance(item, dict):
            continue
        content = (item.get("content") or "").strip()
        if not content:
            continue  # per spec: skip silently, don't reject batch
        salience = float(item.get("salience") or 0.5)
        salience = max(0.0, min(1.0, salience))
        fact_type = str(item.get("fact_type") or "decision")
        if fact_type not in _VALID_FACT_TYPES:
            fact_type = "decision"
        results.append(FactDraft(
            content=content,
            salience=salience,
            event_time=item.get("event_time") or None,
            entities=list(item.get("entities") or []),
            fact_type=fact_type,
        ))

    results.sort(key=lambda f: f.salience, reverse=True)
    return results[:max_facts]


def _dedup_within_batch(facts: list[FactDraft], threshold: float = 0.90) -> list[FactDraft]:
    """Pairwise cosine dedup within one extracted batch. Zero LLM calls.

    Uses in-process embedder — no HTTP round-trip.
    sim > threshold → keep higher salience, drop lower.
    """
    if len(facts) <= 1:
        return facts
    vecs = np.array(embed_batch([f.content for f in facts]), dtype=np.float32)
    sims = vecs @ vecs.T  # already L2-normalised → dot = cosine
    keep = [True] * len(facts)
    for i in range(len(facts)):
        if not keep[i]:
            continue
        for j in range(i + 1, len(facts)):
            if not keep[j]:
                continue
            if sims[i, j] > threshold:
                if facts[i].salience >= facts[j].salience:
                    keep[j] = False
                else:
                    keep[i] = False
                    break
    return [f for f, k in zip(facts, keep) if k]


def extract_facts(
    episode_text: str,
    project: str,
    session_id: str | None,
    parent_id: str,
    model: str = "google/gemini-2.5-flash-lite",
    max_facts: int = 10,
    prompt_version: str = "v1",
) -> list[FactDraft]:
    """Extract facts from one episode. Returns deduplicated list of FactDraft objects."""
    if prompt_version == "v1":
        prompt = _PROMPT_V1.format(episode_text=episode_text, max_facts=max_facts)
    else:
        raise ValueError(f"Unknown prompt_version: {prompt_version!r}")

    raw = _call_llm(prompt)
    facts = _parse_facts(raw, max_facts)
    facts = _dedup_within_batch(facts)

    derived_from = f"ollama/{OLLAMA_SUMMARIZE_MODEL}/{prompt_version}"
    for f in facts:
        f.derived_from = derived_from

    return facts
