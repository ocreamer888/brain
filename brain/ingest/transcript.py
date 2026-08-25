"""Claude Code / plain transcript normalization and groundedness checks.

Claude Code JSONL nests text under ``message.content`` (list of text parts).
Feeding raw JSONL rows into summarizer prompts produces empty ``user:\\nassistant:``
lines; local models then invent textbook fillers. Normalize before any LLM call,
and reject claims that are not grounded in the transcript corpus.
"""
from __future__ import annotations

import re
from typing import Any

_ROLE_TYPES = frozenset({"user", "assistant"})
_MIN_SUBSTANTIVE_CHARS = 80
_MIN_TOKEN_LEN = 4
# Claim tokens that must appear in the corpus (fraction of claim tokens).
_GROUND_TOKEN_RATIO = 0.45
# Or a contiguous substring this long must appear (case-insensitive).
_GROUND_SUBSTRING_LEN = 18

_STOP = frozenset(
    """
    a an the and or but if then else when with from into onto over under for to
    of in on at by as is was were be been being this that these those it its
    they them their we our you your he she his her not no yes do did does done
    have has had will would could should may might must can just also only
    about into after before than so such very more most some any all each
    error cause fix files context decision rejected alternatives used
    """.split()
)

_TOKEN_RE = re.compile(r"[a-z0-9_./:-]{4,}", re.IGNORECASE)


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" or "text" in block:
                text = block.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        return "\n".join(parts).strip()
    return ""


def _extract_role_and_text(row: dict) -> tuple[str, str] | None:
    """Return (role, text) for a user/assistant row, else None."""
    if not isinstance(row, dict):
        return None

    # Plain {role, content} shape (Hermes / already-normalized)
    role = row.get("role")
    if isinstance(role, str) and role in _ROLE_TYPES and "content" in row:
        text = _content_to_text(row.get("content"))
        if text:
            return role, text

    # Claude Code JSONL: {type: user|assistant, message: {role, content}}
    row_type = row.get("type")
    if row_type in _ROLE_TYPES:
        message = row.get("message")
        if isinstance(message, dict):
            msg_role = message.get("role") or row_type
            if msg_role in _ROLE_TYPES:
                text = _content_to_text(message.get("content"))
                if text:
                    return str(msg_role), text
        # Rare flat Claude row with top-level content
        text = _content_to_text(row.get("content"))
        if text:
            return str(row_type), text

    return None


def normalize_messages(messages: list) -> list[dict]:
    """Collapse Claude JSONL / plain rows into ``{role, content}`` only."""
    out: list[dict] = []
    for row in messages or []:
        extracted = _extract_role_and_text(row)
        if extracted is None:
            continue
        role, text = extracted
        out.append({"role": role, "content": text})
    return out


def format_transcript(
    messages: list,
    *,
    max_msgs: int = 40,
    max_chars: int = 600,
) -> str:
    """Format messages for LLM prompts. Always normalizes first."""
    normalized = normalize_messages(messages)
    if not normalized:
        return "(empty session)"
    parts: list[str] = []
    for m in normalized[:max_msgs]:
        content = str(m.get("content", ""))[:max_chars]
        parts.append(f"{m.get('role', 'unknown')}: {content}")
    return "\n".join(parts) if parts else "(empty session)"


def transcript_corpus(messages: list) -> str:
    """Lowercased corpus used for groundedness checks."""
    return format_transcript(messages, max_msgs=200, max_chars=4000).lower()


def has_substantive_transcript(messages: list, *, min_chars: int = _MIN_SUBSTANTIVE_CHARS) -> bool:
    """True when normalized user+assistant text is long enough to summarize."""
    normalized = normalize_messages(messages)
    total = sum(len(m["content"]) for m in normalized)
    return total >= min_chars


def _claim_tokens(claim: str) -> list[str]:
    tokens = []
    for tok in _TOKEN_RE.findall(claim.lower()):
        if tok in _STOP:
            continue
        if tok.isdigit():
            continue
        tokens.append(tok)
    return tokens


def claim_is_grounded(claim: str, corpus: str) -> bool:
    """Return True if claim is supported by transcript corpus text."""
    claim = (claim or "").strip()
    if not claim or not corpus or corpus.strip() == "(empty session)":
        return False

    corpus_l = corpus.lower()
    claim_l = claim.lower()

    # Contiguous substring gate (error messages, identifiers, paths)
    for size in (_GROUND_SUBSTRING_LEN, 12):
        if len(claim_l) >= size:
            # Slide a few windows from the start (errors often lead with the key phrase)
            windows = {claim_l[:size]}
            if len(claim_l) > size + 8:
                windows.add(claim_l[8 : 8 + size])
            mid = max(0, len(claim_l) // 2 - size // 2)
            windows.add(claim_l[mid : mid + size])
            if any(w in corpus_l for w in windows if len(w) >= 12):
                return True

    tokens = _claim_tokens(claim)
    if not tokens:
        return False
    hits = sum(1 for t in tokens if t in corpus_l)
    return (hits / len(tokens)) >= _GROUND_TOKEN_RATIO


def filter_grounded_claims(
    items: list[dict],
    corpus: str,
    *,
    key: str,
) -> list[dict]:
    """Keep only dict items whose ``key`` field is grounded in corpus."""
    kept: list[dict] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        claim = str(item.get(key, "") or "")
        if claim_is_grounded(claim, corpus):
            kept.append(item)
    return kept


def summary_is_grounded(summary_text: str, corpus: str) -> bool:
    """Session summaries may paraphrase; require token overlap, not full substring."""
    summary_text = (summary_text or "").strip()
    if not summary_text or not corpus or corpus.strip() == "(empty session)":
        return False
    tokens = _claim_tokens(summary_text)
    if len(tokens) < 3:
        return False
    corpus_l = corpus.lower()
    hits = sum(1 for t in tokens if t in corpus_l)
    # Slightly looser than claim_is_grounded — summaries paraphrase
    return (hits / len(tokens)) >= 0.30
