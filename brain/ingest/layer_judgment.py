"""Judge whether a newer memory is a temporal *layer* on an older one.

Spec: docs/architecture/cognitive-architecture-spec.md §8.5-§8.7. The
deterministic tiers there (file_path / shared specific entity / embedding
similarity) only find *candidate* pairs that might share a subject -- the
2026-10-21 experiment (docs/architecture/experiments/2026-10-21-layer-detection/)
measured that candidates alone hit ~33% precision at deciding whether a pair
is actually the same evolving subject. This module is the missing judgement
step named there as proposal (B): a curator-style LLM tiebreak, generalized
from facts-only (brain/ingest/fact_curator.py) to every durable memory type.

Four-way label, matching the hand-labelled ground truth in
docs/architecture/experiments/2026-10-21-layer-detection/exp3_labeled.json:
  LAYER     - the newer memory changes, fixes, or replaces the status of
              what the older one says about the same specific thing.
  RELATED   - same subject, different aspect; both remain independently valid.
  DUP       - the same content stored twice (a save-time dedup miss, not a
              layering question -- out of scope for depth()).
  UNRELATED - the pair only shares a generic/coincidental entity.

Only LAYER pairs contribute to a memory's stack depth (spec §8.4): L(m) is
restricted to same(m,m') AND judge(m,m') == LAYER, not every tier-matched
candidate. w(m,m') for a judged LAYER pair is the candidate's cosine
similarity itself (spec: "similarity-based weight otherwise") -- the
judgement step's job is gating membership in L(m), not re-deriving the
weight.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import OLLAMA_URL, OLLAMA_SUMMARIZE_MODEL

VALID_LABELS = {"LAYER", "RELATED", "DUP", "UNRELATED"}

# Candidate-generation floor, not a judgement-prompt parameter: the
# 2026-10-21 experiment's hand-labelled sample found 0 true LAYER pairs
# below cosine 0.50 (docs/architecture/experiments/2026-10-21-layer-detection/
# README.md, Exp 3 table, "< 0.50" band, 0/14 sampled, "Est. layers ~0" across
# an estimated 18,537 pairs in that band). Below this floor, a pair is not a
# layering candidate at all and should never reach classify_pair -- this is
# an empirically-grounded prior from real labelled data, not a judgement
# model limitation to fix with a different prompt.
MIN_CANDIDATE_SIM = 0.50

_PROMPT = """\
Two memories from the same project share a specific entity. Decide how the \
newer one relates to the older one.

{{
  "older_memory": {old},
  "newer_memory": {new},
  "cosine_similarity": {sim:.4f}
}}

Return ONLY valid JSON:
{{"label": "LAYER|RELATED|DUP|UNRELATED", "reason": "one sentence"}}

- LAYER: the newer memory reports a later state of the SAME specific thing \
as the older one, and that later state makes the older one's specific \
claim or status stale (a bug then its fix, a value that got corrected, a \
status moving from one state to the next). This includes progress reports \
on the same identified process -- the same task, run, branch, or pipeline \
-- even when the concrete sub-finding differs: if the newer report is what \
you would now tell someone who asked "what's the current status of that", \
the older status report is a LAYER below it.
- RELATED: both describe the same general subject but are genuinely \
different, independently-valid aspects of it -- not two snapshots of the \
same ongoing process at different times, and neither makes the other stale.
- DUP: the newer memory restates the older one's content with no \
meaningfully new information, even if it adds minor incremental detail.
- UNRELATED: the only connection is the shared entity name, or the two \
memories are sibling chunks of one larger ingested document (same subject \
matter, different section) rather than one superseding the other."""


@dataclass(frozen=True)
class LayerJudgment:
    label: str
    reason: str


def classify_pair(
    old_content: str,
    new_content: str,
    sim: float,
    model: str = OLLAMA_SUMMARIZE_MODEL,
    timeout: float = 60.0,
) -> LayerJudgment:
    """Classify the (old, new) pair. Raises on malformed/empty LLM output --
    callers should count that as an error, same convention as
    fact_curator.py's _call_tiebreaker, not silently default to a label."""
    prompt = _PROMPT.format(
        old=json.dumps(old_content), new=json.dumps(new_content), sim=sim
    )
    resp = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "think": False,
            "options": {"temperature": 0.0},
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    raw = resp.json()["message"]["content"]
    if not raw:
        raise ValueError("layer judgment LLM call returned empty content")

    stripped = raw.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        stripped = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    result = json.loads(stripped)
    label = result.get("label")
    if label not in VALID_LABELS:
        raise ValueError(f"invalid layer judgment label: {label!r}")
    return LayerJudgment(label=label, reason=result.get("reason", ""))
