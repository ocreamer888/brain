"""
Unified ingest rules for the Brain corpus (all pipelines):

- Every memory gets a **non-empty title** (for FTS, hybrid rank hints, and eval).
- Long markdown is **split by section and/or word budget** so embeddings stay sharp.
- **Content** uses a bracketed source line ``[source]`` when applicable (keyword + dense signal).

Python tools attach tag ``brain/ingest``; the Rust API also fills missing titles at save time.
"""

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
from brain.ingest.fact_extractor import FactDraft, extract_facts
from brain.ingest.fact_curator import CurationResult, curate_facts

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
]
