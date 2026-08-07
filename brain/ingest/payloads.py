"""Shared memory payload shape for ingest scripts."""

from __future__ import annotations

import sys

TAG_BRAIN_INGEST = "brain/ingest"


def forbid_knowledge_type(memory_type: str, writer: str) -> str:
    """Corpus purity guard: session recycling, fact extraction, and PostToolUse
    flushes must never mint ``knowledge`` rows (spec 2026-08-06). Coerces to
    ``conversation`` with a warning instead of failing the background path.
    """
    if memory_type == "knowledge":
        print(
            f"[{writer}] blocked type=knowledge (reserved for deliberate corpus "
            "ingest); coerced to conversation",
            file=sys.stderr,
        )
        return "conversation"
    return memory_type


def with_ingest_tag(tags: list[str] | None) -> list[str]:
    base = list(tags or [])
    if TAG_BRAIN_INGEST not in base:
        base.append(TAG_BRAIN_INGEST)
    return base


def memory_display_title(note_stem: str, section_title: str) -> str:
    stem = note_stem.strip()
    sec = section_title.strip()
    if not sec or sec == stem:
        return stem
    return f"{stem} — {sec}"


def format_bracketed_memory(note_stem: str, section_title: str | None, body: str) -> str:
    stem = note_stem.strip()
    sec = (section_title or "").strip()
    body = body.strip()
    if sec and sec != stem:
        return f"[{stem}] {sec}\n\n{body}"
    return f"[{stem}]\n\n{body}"
