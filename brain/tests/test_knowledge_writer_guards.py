# brain/tests/test_knowledge_writer_guards.py
"""Corpus purity: forbidden writers must never mint type=knowledge rows
(spec docs/superpowers/specs/2026-08-06-knowledge-type-design.md)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from unittest.mock import patch

from brain.ingest.payloads import forbid_knowledge_type


def test_forbid_knowledge_type_coerces_to_conversation(capsys):
    assert forbid_knowledge_type("knowledge", "test_writer") == "conversation"
    assert "blocked type=knowledge" in capsys.readouterr().err


def test_forbid_knowledge_type_passes_other_types_through():
    for t in ("solution", "fact", "conversation", "project_context"):
        assert forbid_knowledge_type(t, "test_writer") == t


def test_session_ingest_save_fn_blocks_knowledge():
    """save_memory_fn is the chokepoint for all recycling passes and the
    session-end edit-group flush — knowledge must be coerced away."""
    from brain.core import session_ingest

    with patch.object(session_ingest, "backend_mode", return_value="api"), \
         patch("brain.api_client.save_memory", return_value="mem-1") as save:
        session_ingest.save_memory_fn(
            content="sneaky corpus impersonation",
            memory_type="knowledge",
            tags=["t"],
            project="p",
        )
    assert save.call_args.kwargs["memory_type"] == "conversation"


def test_session_ingest_save_fn_passes_normal_types():
    from brain.core import session_ingest

    with patch.object(session_ingest, "backend_mode", return_value="api"), \
         patch("brain.api_client.save_memory", return_value="mem-2") as save:
        session_ingest.save_memory_fn(
            content="session summary body",
            memory_type="project_context",
            tags=["t"],
            project="p",
        )
    assert save.call_args.kwargs["memory_type"] == "project_context"


def test_fact_curator_save_is_locked_to_fact_type():
    """_save_fact is the curator's only save helper; its type contract is
    load-bearing — a drift to knowledge would corrupt the corpus boundary."""
    from brain.ingest import fact_curator
    from brain.ingest.fact_extractor import FactDraft

    draft = FactDraft(
        content="the api retries three times",
        salience=0.6,
        event_time=None,
        entities=[],
        fact_type="outcome",
    )
    with patch.object(fact_curator.api_client, "save_memory", return_value="f-1") as save:
        fact_curator._save_fact(draft, project="p", parent_id=None, session_id=None)
    assert save.call_args.kwargs["memory_type"] == "fact"
