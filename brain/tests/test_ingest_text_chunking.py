"""Shared ingest chunking rules."""

from brain.ingest.text_chunking import refine_chunks_for_word_limit


def test_refine_splits_oversized_single_section():
    # Many short paragraphs so ``chunk_by_paragraphs`` can form multiple windows.
    paras = ["w " * 500 for _ in range(6)]
    body = "\n\n".join(paras)
    out = refine_chunks_for_word_limit(
        [("root", body)],
        "root",
        word_threshold=400,
    )
    assert len(out) >= 2
