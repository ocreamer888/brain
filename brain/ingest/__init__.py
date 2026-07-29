"""
Unified ingest rules for the Brain corpus (all pipelines):

- Every memory gets a **non-empty title** (for FTS, hybrid rank hints, and eval).
- Long markdown is **split by section and/or word budget** so embeddings stay sharp.
- **Content** uses a bracketed source line ``[source]`` when applicable (keyword + dense signal).

Python tools attach tag ``brain/ingest``; the Rust API also fills missing titles at save time.

Re-exports are **lazy** (PEP 562). ``fact_extractor`` / ``fact_curator`` pull numpy +
sentence-transformers + torch (~2s); eager re-export made that cost unavoidable for
*any* consumer of this package, including ``api_client``'s per-save entity extraction
running in short-lived hook processes. Attribute access below imports on first use, so
``from brain.ingest import entity_extractor`` stays at ~0.06s and lean environments
without numpy can still use the light members.
"""

from typing import TYPE_CHECKING

_LAZY_MEMBERS = {
    # payloads (light)
    "TAG_BRAIN_INGEST": "brain.ingest.payloads",
    "format_bracketed_memory": "brain.ingest.payloads",
    "memory_display_title": "brain.ingest.payloads",
    "with_ingest_tag": "brain.ingest.payloads",
    # text_chunking (light)
    "chunk_by_paragraphs": "brain.ingest.text_chunking",
    "chunk_by_sections": "brain.ingest.text_chunking",
    "normalize_section_title": "brain.ingest.text_chunking",
    "refine_chunks_for_word_limit": "brain.ingest.text_chunking",
    # fact layer (HEAVY — numpy/torch/sentence-transformers)
    "FactDraft": "brain.ingest.fact_extractor",
    "extract_facts": "brain.ingest.fact_extractor",
    "CurationResult": "brain.ingest.fact_curator",
    "curate_facts": "brain.ingest.fact_curator",
    # entity layer (light)
    "DURABLE_MEMORY_TYPES": "brain.ingest.entity_extractor",
    "extract_entities": "brain.ingest.entity_extractor",
}


def __getattr__(name: str):
    module_path = _LAZY_MEMBERS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    value = getattr(importlib.import_module(module_path), name)
    globals()[name] = value  # cache so subsequent access skips __getattr__
    return value


def __dir__() -> list[str]:
    return sorted(__all__)


if TYPE_CHECKING:  # static analysers still see the real symbols
    from brain.ingest.entity_extractor import DURABLE_MEMORY_TYPES, extract_entities
    from brain.ingest.fact_curator import CurationResult, curate_facts
    from brain.ingest.fact_extractor import FactDraft, extract_facts
    from brain.ingest.payloads import (
        TAG_BRAIN_INGEST,
        format_bracketed_memory,
        memory_display_title,
        with_ingest_tag,
    )
    from brain.ingest.text_chunking import (
        chunk_by_paragraphs,
        chunk_by_sections,
        normalize_section_title,
        refine_chunks_for_word_limit,
    )

__all__ = [
    "TAG_BRAIN_INGEST",
    "chunk_by_paragraphs",
    "chunk_by_sections",
    "format_bracketed_memory",
    "memory_display_title",
    "normalize_section_title",
    "refine_chunks_for_word_limit",
    "with_ingest_tag",
    # Fact layer
    "CurationResult",
    "FactDraft",
    "curate_facts",
    "extract_facts",
    # Entity layer
    "DURABLE_MEMORY_TYPES",
    "extract_entities",
]
