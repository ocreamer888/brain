"""Tests for Perplexity thread extraction helpers."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from brain.bootstrap.perplexity_extractors import extract_thread_record, summarize_thread_text


def _sample_thread(tmp_path, title="What is RAG?", n_messages=2):
    data = {
        "id": "abc123",
        "title": title,
        "created_at": 1710000000,
        "messages": [
            {"role": "user", "content": "What is RAG in LLMs?"},
            {"role": "assistant", "content": "RAG stands for Retrieval Augmented Generation. It lets LLMs retrieve external documents.", "sources": [{"title": "RAG paper", "url": "https://example.com"}]},
        ] * (n_messages // 2),
    }
    f = tmp_path / "abc123.json"
    f.write_text(json.dumps(data))
    return f


def test_extract_thread_record_basic(tmp_path):
    f = _sample_thread(tmp_path)
    result = extract_thread_record(f)
    assert result["metadata"]["source"] == "perplexity"
    assert result["metadata"]["project"] == "perplexity"
    assert result["metadata"]["thread_id"] == "abc123"
    assert "What is RAG?" in result["text"] or "RAG" in result["text"]
    assert result["file_path"] == "threads/abc123.json"


def test_extract_thread_record_missing_fields(tmp_path):
    f = tmp_path / "minimal.json"
    f.write_text('{"id": "x1", "messages": []}')
    result = extract_thread_record(f)
    assert result["metadata"]["thread_id"] == "x1"
    assert result["file_path"] == "threads/x1.json"


def test_summarize_thread_text_basic():
    messages = [
        {"role": "user", "content": "What is ChromaDB?"},
        {"role": "assistant", "content": "ChromaDB is an open-source vector database.", "sources": []},
    ]
    text = summarize_thread_text("ChromaDB intro", messages)
    assert "ChromaDB" in text
    assert len(text) > 20
