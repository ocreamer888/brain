"""
Live Ollama canary — exercises the real summarization path used by hooks (summarize_session).

Default pytest runs skip this (no local Ollama). Turn on when you want automated proof
the summarizer still works against local Ollama:

    BRAIN_RUN_OLLAMA_CANARY=1 \\
      python3 -m pytest brain/tests/integration/test_ollama_summarizer_live.py -v
"""

from __future__ import annotations

import os

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.ollama]

_ON = {"1", "true", "yes", "on"}


def _canary_enabled() -> bool:
    return os.environ.get("BRAIN_RUN_OLLAMA_CANARY", "").strip().lower() in _ON


def test_summarize_session_live_ollama():
    if not _canary_enabled():
        pytest.skip("set BRAIN_RUN_OLLAMA_CANARY=1 to call local Ollama summarization")

    # Check that OLLAMA_URL is set and accessible
    ollama_url = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
    if not ollama_url:
        pytest.skip("OLLAMA_URL not set")

    from brain.core.summarizer import summarize_session

    messages = [
        {"role": "user", "content": "We chose SQLite for the local brain store with ONNX embeddings."},
        {
            "role": "assistant",
            "content": "SQLite fits single-user local indexing; ONNX keeps embeddings on-device.",
        },
    ]
    out = summarize_session(messages)
    assert isinstance(out, dict)
    assert "summary" in out and "decisions" in out and "next_steps" in out
    assert len(str(out.get("summary", "")).strip()) >= 8
    assert isinstance(out["decisions"], list)
    assert isinstance(out["next_steps"], list)
