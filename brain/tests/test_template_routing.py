"""Query-intent classification + type-biased template_search (Task 4)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from unittest.mock import patch

from brain.api_client import classify_query_intent, template_search


# --- intent classification -------------------------------------------------

def test_classify_troubleshoot_returns_solution():
    assert classify_query_intent("why does the deploy keep failing") == "solution"
    assert classify_query_intent("I got a permission denied error") == "solution"


def test_classify_decision():
    assert classify_query_intent("what did we decide about the schema") == "decision"
    assert classify_query_intent("what's the trade-off here") == "decision"


def test_classify_status():
    assert classify_query_intent("what happened in the last session") == "status"
    assert classify_query_intent("status of the migration") == "status"


def test_classify_factual():
    assert classify_query_intent("how many memories are there") == "fact"
    assert classify_query_intent("what is the cost of the API") == "fact"


def test_classify_none_for_plain_query():
    assert classify_query_intent("brain architecture overview") is None


def test_classify_precedence_troubleshoot_beats_decision():
    # Contains both a decision phrase ('trade-off') and a troubleshoot phrase ('fail');
    # troubleshoot is checked first.
    assert classify_query_intent("trade-off when the build fails") == "solution"


# --- template_search routing ----------------------------------------------

def _fake_search_factory(by_type: dict, general: list):
    def fake_search(query=None, n=10, memory_type=None, project=None, **kw):
        if memory_type is not None:
            return list(by_type.get(memory_type, []))
        return list(general)
    return fake_search


def test_template_search_no_intent_falls_back_to_plain():
    plain = [{"id": "g1"}, {"id": "g2"}]
    with patch("brain.api_client.search") as mock:
        mock.return_value = plain
        out = template_search("brain architecture overview", n=5)
    assert out == plain
    # plain path: called once, without a memory_type filter
    assert mock.call_count == 1
    assert mock.call_args.kwargs.get("memory_type") is None


def test_template_search_boosts_types_and_dedups():
    by_type = {"solution": [{"id": "s1"}, {"id": "s2"}], "error_lesson": [{"id": "e1"}]}
    general = [{"id": "s1"}, {"id": "g1"}]  # s1 duplicates the boosted hit
    with patch("brain.api_client.search", side_effect=_fake_search_factory(by_type, general)):
        out = template_search("why does it keep failing", n=4)
    ids = [r["id"] for r in out]
    assert ids == ["s1", "s2", "e1", "g1"]  # boosted first, deduped, then general fill


def test_template_search_respects_n_cap():
    by_type = {"solution": [{"id": f"s{i}"} for i in range(8)], "error_lesson": []}
    general = [{"id": "g1"}]
    with patch("brain.api_client.search", side_effect=_fake_search_factory(by_type, general)):
        out = template_search("why is it broken", n=3)
    assert len(out) == 3
