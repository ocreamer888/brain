"""Tests for brain/ingest/fact_extractor.py.

Uses golden fixtures from brain/tests/fixtures/extractor/.
No live LLM calls — _call_llm is monkeypatched everywhere.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from brain.ingest.fact_extractor import (
    FactDraft,
    _dedup_within_batch,
    _parse_facts,
    extract_facts,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "extractor"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / f"{name}.json").read_text())


# ---------------------------------------------------------------------------
# _parse_facts — fixture-driven shape tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fixture_name", [
    "error_fix", "decision", "outcome", "named_entity", "preference", "multi_topic",
])
def test_parse_facts_fixture_shape(fixture_name: str) -> None:
    fixture = load_fixture(fixture_name)
    raw = json.dumps({"facts": fixture["facts"]})
    facts = _parse_facts(raw, max_facts=10)
    assert len(facts) > 0, f"{fixture_name}: expected at least one fact"
    for f in facts:
        assert f.content, f"{fixture_name}: empty content in fact"
        assert 0.0 <= f.salience <= 1.0, f"{fixture_name}: salience out of range"
        assert f.fact_type in {
            "decision", "error_fix", "preference", "named_entity", "outcome"
        }, f"{fixture_name}: invalid fact_type {f.fact_type!r}"


def test_parse_facts_error_fix_has_error_fix_type() -> None:
    fixture = load_fixture("error_fix")
    raw = json.dumps({"facts": fixture["facts"]})
    facts = _parse_facts(raw, max_facts=10)
    assert any(f.fact_type == "error_fix" for f in facts)


def test_parse_facts_named_entity_all_named_entity() -> None:
    fixture = load_fixture("named_entity")
    raw = json.dumps({"facts": fixture["facts"]})
    facts = _parse_facts(raw, max_facts=10)
    assert all(f.fact_type == "named_entity" for f in facts)


def test_parse_facts_outcome_has_outcome_type() -> None:
    fixture = load_fixture("outcome")
    raw = json.dumps({"facts": fixture["facts"]})
    facts = _parse_facts(raw, max_facts=10)
    assert any(f.fact_type == "outcome" for f in facts)


def test_parse_facts_multi_topic_has_multiple_types() -> None:
    fixture = load_fixture("multi_topic")
    raw = json.dumps({"facts": fixture["facts"]})
    facts = _parse_facts(raw, max_facts=10)
    types = {f.fact_type for f in facts}
    assert len(types) > 1, "multi_topic fixture must produce more than one fact_type"


def test_parse_facts_sorted_by_salience_desc() -> None:
    fixture = load_fixture("multi_topic")
    raw = json.dumps({"facts": fixture["facts"]})
    facts = _parse_facts(raw, max_facts=10)
    saliences = [f.salience for f in facts]
    assert saliences == sorted(saliences, reverse=True)


# ---------------------------------------------------------------------------
# _parse_facts — edge cases
# ---------------------------------------------------------------------------

def test_parse_facts_empty_facts_list() -> None:
    facts = _parse_facts('{"facts": []}', 10)
    assert facts == []


def test_parse_facts_invalid_json_raises() -> None:
    with pytest.raises(ValueError, match="JSON parse failed"):
        _parse_facts("not json at all", 10)


def test_parse_facts_missing_facts_key_raises() -> None:
    with pytest.raises(ValueError, match="missing 'facts'"):
        _parse_facts('{"result": []}', 10)


def test_parse_facts_skips_empty_content() -> None:
    raw = json.dumps({"facts": [
        {"content": "", "salience": 0.9, "event_time": None, "entities": [], "fact_type": "decision"},
        {"content": "Valid fact", "salience": 0.8, "event_time": None, "entities": [], "fact_type": "decision"},
    ]})
    facts = _parse_facts(raw, max_facts=10)
    assert len(facts) == 1
    assert facts[0].content == "Valid fact"


def test_parse_facts_caps_at_max_facts() -> None:
    facts_data = [
        {
            "content": f"Fact number {i}",
            "salience": round((15 - i) / 15, 2),
            "event_time": None,
            "entities": [],
            "fact_type": "decision",
        }
        for i in range(15)
    ]
    facts = _parse_facts(json.dumps({"facts": facts_data}), max_facts=5)
    assert len(facts) == 5


def test_parse_facts_clamps_salience() -> None:
    raw = json.dumps({"facts": [
        {"content": "Over", "salience": 2.5, "event_time": None, "entities": [], "fact_type": "decision"},
        {"content": "Under", "salience": -0.3, "event_time": None, "entities": [], "fact_type": "decision"},
    ]})
    facts = _parse_facts(raw, max_facts=10)
    assert all(0.0 <= f.salience <= 1.0 for f in facts)


def test_parse_facts_invalid_fact_type_defaults_to_decision() -> None:
    raw = json.dumps({"facts": [
        {"content": "A fact", "salience": 0.7, "event_time": None, "entities": [], "fact_type": "BOGUS"},
    ]})
    facts = _parse_facts(raw, max_facts=10)
    assert facts[0].fact_type == "decision"


def test_parse_facts_strips_markdown_fence() -> None:
    raw = '```json\n{"facts": [{"content": "Clean", "salience": 0.8, "event_time": null, "entities": [], "fact_type": "decision"}]}\n```'
    facts = _parse_facts(raw, max_facts=10)
    assert len(facts) == 1
    assert facts[0].content == "Clean"


# ---------------------------------------------------------------------------
# _dedup_within_batch
# ---------------------------------------------------------------------------

def test_dedup_drops_near_duplicate_keeps_higher_salience() -> None:
    f_high = FactDraft(
        content="The brain API binds on port 8787 by default",
        salience=0.9, event_time=None, entities=[], fact_type="decision",
    )
    f_low = FactDraft(
        content="Brain API runs on port 8787",
        salience=0.6, event_time=None, entities=[], fact_type="decision",
    )
    result = _dedup_within_batch([f_high, f_low], threshold=0.90)
    assert len(result) == 1
    assert result[0].salience == 0.9


def test_dedup_keeps_clearly_distinct_facts() -> None:
    f1 = FactDraft(
        content="Use SQLite FTS5 over Postgres for hybrid search",
        salience=0.9, event_time=None, entities=[], fact_type="decision",
    )
    f2 = FactDraft(
        content="Deploy to Railway instead of AWS to avoid operational overhead",
        salience=0.8, event_time=None, entities=[], fact_type="decision",
    )
    result = _dedup_within_batch([f1, f2], threshold=0.90)
    assert len(result) == 2


def test_dedup_single_fact_unchanged() -> None:
    f = FactDraft(content="Lone fact", salience=0.8, event_time=None, entities=[], fact_type="decision")
    assert _dedup_within_batch([f]) == [f]


def test_dedup_empty_list() -> None:
    assert _dedup_within_batch([]) == []


def test_dedup_multi_topic_all_survive() -> None:
    """The 5 multi_topic fixture facts must all survive dedup — they are about distinct topics."""
    fixture = load_fixture("multi_topic")
    raw = json.dumps({"facts": fixture["facts"]})
    facts = _parse_facts(raw, max_facts=10)
    deduped = _dedup_within_batch(facts, threshold=0.90)
    assert len(deduped) == len(facts), (
        f"multi_topic facts collapsed: {len(facts)} → {len(deduped)}. "
        "Distinct facts must survive dedup."
    )


# ---------------------------------------------------------------------------
# extract_facts — end-to-end with mocked LLM
# ---------------------------------------------------------------------------

def test_extract_facts_sets_derived_from(monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = load_fixture("decision")
    mock_response = json.dumps({"facts": fixture["facts"]})
    monkeypatch.setattr("brain.ingest.fact_extractor._call_llm", lambda *a, **kw: mock_response)

    facts = extract_facts(
        episode_text=fixture["episode_text"],
        project="test",
        session_id=None,
        parent_id="parent-uuid",
    )
    assert len(facts) > 0
    for f in facts:
        assert f.derived_from, "derived_from must be set"
        assert f.derived_from.startswith("ollama/"), f"unexpected derived_from: {f.derived_from}"


def test_extract_facts_returns_empty_on_empty_llm_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "brain.ingest.fact_extractor._call_llm",
        lambda *a, **kw: json.dumps({"facts": []}),
    )
    facts = extract_facts("Some text", project="test", session_id=None, parent_id="p")
    assert facts == []


def test_extract_facts_raises_on_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "brain.ingest.fact_extractor._call_llm",
        lambda *a, **kw: "this is not json",
    )
    with pytest.raises(ValueError, match="JSON parse failed"):
        extract_facts("Some text", project="test", session_id=None, parent_id="p")
