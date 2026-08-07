"""Tests for brain/ingest/entity_extractor.py.

No live Ollama — _call_llm is monkeypatched everywhere.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from brain.ingest import entity_extractor  # noqa: E402


def _prompt_text(prompt: str) -> str:
    """The slice of a rendered prompt that carries the memory content."""
    return prompt.split("Text:\n", 1)[1]


# ---------------------------------------------------------------------------
# extract_entities
# ---------------------------------------------------------------------------

def test_extract_entities_parses_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        entity_extractor,
        "_call_llm",
        lambda *a, **kw: json.dumps({"entities": ["Next.js", "Supabase"]}),
    )
    result = entity_extractor.extract_entities("We migrated from Next.js to Supabase.")
    assert result == ["Next.js", "Supabase"]


def test_extract_entities_handles_garbage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(entity_extractor, "_call_llm", lambda *a, **kw: "this is not json at all")
    result = entity_extractor.extract_entities("Some fact text")
    assert result == []


def test_extract_entities_handles_llm_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*a, **kw):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(entity_extractor, "_call_llm", _raise)
    result = entity_extractor.extract_entities("Some fact text")
    assert result == []


def test_extract_entities_never_raises_on_unexpected_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(*a, **kw):
        raise ValueError("unexpected")

    monkeypatch.setattr(entity_extractor, "_call_llm", _raise)
    assert entity_extractor.extract_entities("Some fact text") == []


def test_extract_entities_strips_markdown_fence(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = '```json\n{"entities": ["Rust", "SQLite"]}\n```'
    monkeypatch.setattr(entity_extractor, "_call_llm", lambda *a, **kw: raw)
    result = entity_extractor.extract_entities("Rust talks to SQLite directly.")
    assert result == ["Rust", "SQLite"]


def test_extract_entities_applies_cleaning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        entity_extractor,
        "_call_llm",
        lambda *a, **kw: json.dumps({"entities": ["git", "Next.js", "commit_message", "Next.js"]}),
    )
    result = entity_extractor.extract_entities("Some fact text")
    assert result == ["Next.js"]


def test_extract_entities_dedups_case_insensitive_and_caps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    names = [f"Entity{i}" for i in range(20)] + ["entity0"]  # dup of Entity0, case-insensitive
    monkeypatch.setattr(
        entity_extractor, "_call_llm", lambda *a, **kw: json.dumps({"entities": names})
    )
    result = entity_extractor.extract_entities("text")
    assert len(result) == entity_extractor.MAX_ENTITIES_PER_FACT
    assert result[0] == "Entity0"


# ---------------------------------------------------------------------------
# Input cap
# ---------------------------------------------------------------------------

def test_extract_entities_truncates_input_before_prompting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def _capture(prompt: str, **_kw: object) -> str:
        # **_kw absorbs `timeout`; a bare (prompt) stub raises TypeError, which
        # extract_entities correctly swallows, silently emptying `seen`.
        seen.append(prompt)
        return json.dumps({"entities": []})

    monkeypatch.setattr(entity_extractor, "_call_llm", _capture)
    entity_extractor.extract_entities("x" * (entity_extractor.MAX_INPUT_CHARS + 5_000))

    assert len(_prompt_text(seen[0])) == entity_extractor.MAX_INPUT_CHARS


def test_extract_entities_does_not_truncate_at_or_under_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def _capture(prompt: str, **_kw: object) -> str:
        # **_kw absorbs `timeout`; a bare (prompt) stub raises TypeError, which
        # extract_entities correctly swallows, silently emptying `seen`.
        seen.append(prompt)
        return json.dumps({"entities": []})

    monkeypatch.setattr(entity_extractor, "_call_llm", _capture)

    exact = "y" * entity_extractor.MAX_INPUT_CHARS
    under = "z" * (entity_extractor.MAX_INPUT_CHARS - 1)
    entity_extractor.extract_entities(exact)
    entity_extractor.extract_entities(under)

    assert _prompt_text(seen[0]) == exact
    assert _prompt_text(seen[1]) == under


# ---------------------------------------------------------------------------
# _parse_entities
# ---------------------------------------------------------------------------

def test_parse_entities_rejects_non_dict_json() -> None:
    assert entity_extractor._parse_entities('["Rust", "SQLite"]') == []


def test_parse_entities_missing_entities_key() -> None:
    assert entity_extractor._parse_entities('{"things": ["Rust"]}') == []


def test_parse_entities_non_list_entities() -> None:
    assert entity_extractor._parse_entities('{"entities": "Rust"}') == []


# ---------------------------------------------------------------------------
# _clean_entities
# ---------------------------------------------------------------------------

def test_clean_entities_drops_stoplist() -> None:
    result = entity_extractor._clean_entities(["git", "React", "commit", "Supabase"])
    assert result == ["React", "Supabase"]


def test_clean_entities_drops_short_and_punct() -> None:
    result = entity_extractor._clean_entities([".", "a", "Go", "--", "AI"])
    assert result == ["Go", "AI"]


def test_clean_entities_dedupes_case_insensitive_preserving_first() -> None:
    result = entity_extractor._clean_entities(["React", "react", "REACT"])
    assert result == ["React"]


# ---------------------------------------------------------------------------
# DURABLE_MEMORY_TYPES
# ---------------------------------------------------------------------------

def test_durable_memory_types_contains_expected_eight() -> None:
    assert entity_extractor.DURABLE_MEMORY_TYPES == frozenset({
        "fact", "solution", "decision", "pattern",
        "project_context", "error_lesson", "conversation",
        "knowledge",
    })
    # Bare strings, not the JSON-encoded form the DB stores.
    assert "episode" not in entity_extractor.DURABLE_MEMORY_TYPES
    assert '"fact"' not in entity_extractor.DURABLE_MEMORY_TYPES


# --- Regressions found by adversarial verification (D-1..D-4) -----------------

def test_live_timeout_is_short_and_bounded():
    """D-1: the 120s batch timeout must not reach the interactive hook path.

    PostToolUse/Stop hooks have no `timeout` in settings.json, so they die at the
    harness default. A killed process never reaches post_tool_use's `except`
    branch, so the memory is never spooled -- it is silently lost.
    """
    connect, read = entity_extractor.LIVE_TIMEOUT
    assert connect + read <= 20, "live budget must stay well under any hook timeout"
    assert entity_extractor.BACKFILL_TIMEOUT[1] == 120.0, "batch keeps the long budget"


def test_call_llm_defaults_to_live_timeout(monkeypatch):
    seen = {}

    def fake_post(url, **kw):
        seen["timeout"] = kw.get("timeout")
        raise RuntimeError("stop here")

    monkeypatch.setattr(entity_extractor.requests, "post", fake_post)
    entity_extractor.extract_entities("x")
    assert seen["timeout"] == entity_extractor.LIVE_TIMEOUT
    assert isinstance(seen["timeout"], tuple), "tuple bounds connect AND read separately"


@pytest.mark.parametrize("bad", [None, 3, {"a": 1}, [1, 2], b"bytes", object()])
def test_extract_entities_never_raises_on_non_str_input(monkeypatch, bad):
    """D-2: the slice was outside the try, so a non-str caller broke the contract."""
    monkeypatch.setattr(entity_extractor, "_call_llm", lambda *a, **k: '{"entities":["X"]}')
    assert isinstance(entity_extractor.extract_entities(bad), list)


@pytest.mark.parametrize("payload", [None, b"bytes", ["list", "parts"], 42, {"k": "v"}])
def test_extract_entities_never_raises_on_non_str_llm_response(monkeypatch, payload):
    """D-3: an OpenAI-compatible gateway returns `content` as a list of parts."""
    monkeypatch.setattr(entity_extractor, "_call_llm", lambda *a, **k: payload)
    assert entity_extractor.extract_entities("some text") == []


def test_non_string_entities_are_dropped_not_stringified(monkeypatch):
    """D-4: {"entities":[{"name":"React"}]} must not yield "{'name': 'React'}"."""
    monkeypatch.setattr(
        entity_extractor, "_call_llm",
        lambda *a, **k: '{"entities":[{"name":"React"},["x"],null,3.14,"Postgres"]}',
    )
    assert entity_extractor.extract_entities("t") == ["Postgres"]
