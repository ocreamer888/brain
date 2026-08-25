"""Tests for Claude Code JSONL transcript normalization + groundedness gate."""
from __future__ import annotations

from brain.ingest.transcript import (
    claim_is_grounded,
    filter_grounded_claims,
    format_transcript,
    has_substantive_transcript,
    normalize_messages,
)


def _claude_jsonl_user(text: str) -> dict:
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": text}],
        },
    }


def _claude_jsonl_assistant(text: str) -> dict:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
        },
    }


def test_normalize_extracts_nested_claude_jsonl_text():
    raw = [
        {"type": "file-history-snapshot", "messageId": "x"},
        _claude_jsonl_user("Fix the brain rate limiter 429 flood"),
        _claude_jsonl_assistant(
            "Raised BRAIN_API_RATE_LIMIT_MAX_REQUESTS to 2000 on com.brain.api plist."
        ),
    ]
    out = normalize_messages(raw)
    assert len(out) == 2
    assert out[0]["role"] == "user"
    assert "rate limiter" in out[0]["content"]
    assert out[1]["role"] == "assistant"
    assert "BRAIN_API_RATE_LIMIT_MAX_REQUESTS" in out[1]["content"]


def test_normalize_keeps_plain_role_content_messages():
    raw = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "world"},
    ]
    out = normalize_messages(raw)
    assert out == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "world"},
    ]


def test_format_transcript_includes_real_text_not_empty_roles():
    raw = [
        _claude_jsonl_user("how do u feel with brain?"),
        _claude_jsonl_assistant("I feel good about it, with some concerns."),
    ]
    text = format_transcript(raw)
    assert "how do u feel with brain?" in text
    assert "I feel good about it" in text
    # Must not look like the empty-role poison we saw in production
    assert "user: \n" not in text


def test_empty_claude_meta_rows_are_not_substantive():
    raw = [
        {"type": "last-prompt", "leafUuid": "x", "sessionId": "s"},
        {"type": "mode", "mode": "default", "sessionId": "s"},
        {"type": "attachment", "sessionId": "s"},
        {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "Hi"}]}},
    ]
    assert has_substantive_transcript(raw) is False


def test_real_session_is_substantive():
    raw = [
        _claude_jsonl_user("Fix the brain rate limiter — Viewer /stats floods cause MCP 429s."),
        _claude_jsonl_assistant(
            "Root cause: shared localhost client_key. Raised BRAIN_API_RATE_LIMIT_MAX_REQUESTS=2000."
        ),
    ]
    assert has_substantive_transcript(raw) is True


def test_claim_grounded_when_error_appears_in_transcript():
    corpus = (
        "user: Viewer /stats floods cause MCP 429s.\n"
        "assistant: Raised BRAIN_API_RATE_LIMIT_MAX_REQUESTS to 2000 on launchd plist."
    )
    assert claim_is_grounded("MCP 429 errors from Viewer /stats floods", corpus) is True
    assert claim_is_grounded("NameError: name 'x' is not defined", corpus) is False


def test_filter_grounded_error_pairs_drops_textbook_junk():
    corpus = (
        "user: Fix rate limiter 429\n"
        "assistant: Set BRAIN_API_RATE_LIMIT_MAX_REQUESTS=2000"
    )
    pairs = [
        {
            "error": "MCP 429 from rate limiter",
            "cause": "too many stats",
            "fix": "raised limit to 2000",
            "files": [],
        },
        {
            "error": "NameError: name 'x' is not defined",
            "cause": "undeclared variable",
            "fix": "declare x = 0",
            "files": ["main.py"],
        },
    ]
    kept = filter_grounded_claims(pairs, corpus, key="error")
    assert len(kept) == 1
    assert "429" in kept[0]["error"]


def test_filter_grounded_decisions_drops_unrelated_patterns():
    corpus = "user: raise rate limit\nassistant: BRAIN_API_RATE_LIMIT_MAX_REQUESTS=2000"
    decisions = [
        {
            "decision": "Increased BRAIN_API_RATE_LIMIT_MAX_REQUESTS to 2000",
            "context": "429 floods",
        },
        {
            "decision": "Used dependency injection for database connections",
            "context": "testing",
        },
    ]
    kept = filter_grounded_claims(decisions, corpus, key="decision")
    assert len(kept) == 1
    assert "RATE_LIMIT" in kept[0]["decision"]
