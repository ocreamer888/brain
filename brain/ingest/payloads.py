"""Shared memory payload shape for ingest scripts."""

from __future__ import annotations

TAG_BRAIN_INGEST = "brain/ingest"


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
