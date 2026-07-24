import sys
from pathlib import Path

# Repo root (AI/), not brain/ — inserting brain/ shadows the PyPI `mcp` package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import pytest
import json
from unittest.mock import patch


SAMPLE_CONVERSATION = [
    {"role": "user", "content": "How do I fix the CORS error in my Express app?"},
    {"role": "assistant", "content": "Add cors middleware: npm install cors, then app.use(cors())"},
    {"role": "user", "content": "That fixed it, thanks!"},
]

SAMPLE_SUMMARY_RESPONSE = json.dumps({
    "summary": "Fixed CORS error in Express by adding cors middleware",
    "project": "bella",
    "topics": ["cors", "express", "middleware"],
    "decisions": ["Use cors npm package"],
    "solutions": ["CORS error: install cors package, call app.use(cors())"],
    "patterns": ["Express middleware setup pattern"],
    "type": "solution"
})


def test_summarize_conversation_returns_dict():
    import brain.core.summarizer as s
    with patch.object(s, "_openrouter_chat", return_value=SAMPLE_SUMMARY_RESPONSE):
        result = s.summarize_conversation(SAMPLE_CONVERSATION)
    assert isinstance(result, dict)
    assert "summary" in result
    assert "topics" in result
    assert "type" in result


def test_summarize_conversation_handles_json_with_surrounding_text():
    import brain.core.summarizer as s
    wrapped = "Here is the analysis:\n" + SAMPLE_SUMMARY_RESPONSE + "\nDone."
    with patch.object(s, "_openrouter_chat", return_value=wrapped):
        result = s.summarize_conversation(SAMPLE_CONVERSATION)
    assert result["type"] == "solution"


def test_summarize_exchange_returns_string():
    import brain.core.summarizer as s
    with patch.object(s, "_openrouter_chat", return_value="Saved CORS fix to brain."):
        result = s.summarize_exchange("user asked about CORS", "assistant explained cors package")
    assert isinstance(result, str)
    assert len(result) > 0


def test_reflect_memories_returns_dict():
    import brain.core.summarizer as s
    reflect_response = json.dumps({
        "consolidated": ["Fixed CORS issues using cors package in Express apps"],
        "patterns": ["Always use cors middleware in Express for CORS"],
        "to_delete_indices": []
    })
    with patch.object(s, "_openrouter_chat", return_value=reflect_response):
        result = s.reflect_memories(["memory 1", "memory 2"])
    assert "consolidated" in result
    assert "to_delete_indices" in result
