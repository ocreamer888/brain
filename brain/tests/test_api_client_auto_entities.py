"""A3 — auto_entities parameter and the BRAIN_AUTO_ENTITIES kill switch.

No live Ollama: the extractor is mocked at ``brain.ingest.entity_extractor``,
which is the module ``api_client._maybe_extract_entities`` lazily imports from.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import brain.api_client as api_client


@pytest.fixture
def saved(monkeypatch):
    """Capture /save payloads; return the list of payloads sent."""
    payloads: list[dict] = []

    def fake_request(method: str, path: str, payload: dict | None = None, timeout: int = 10) -> dict:
        assert method == "POST" and path == "/save", f"unexpected call: {method} {path}"
        payloads.append(payload)
        return {"id": "mem-1"}

    monkeypatch.setattr(api_client, "_request", fake_request)
    monkeypatch.delenv("BRAIN_AUTO_ENTITIES", raising=False)
    return payloads


@pytest.fixture
def extractor(monkeypatch):
    """Stub extract_entities; return the list of texts it was called with."""
    import brain.ingest.entity_extractor as ee

    calls: list[str] = []

    def fake_extract(text: str) -> list[str]:
        calls.append(text)
        return ["Foo"]

    monkeypatch.setattr(ee, "extract_entities", fake_extract)
    return calls


# --- save_memory ------------------------------------------------------------


def test_durable_type_defaults_extracts_once(saved, extractor):
    mem_id = api_client.save_memory(content="alpha beta", memory_type="solution")
    assert mem_id == "mem-1"
    assert extractor == ["alpha beta"]
    assert saved[0]["entities"] == ["Foo"]


def test_auto_entities_false_skips_extraction(saved, extractor):
    api_client.save_memory(content="alpha beta", memory_type="solution", auto_entities=False)
    assert extractor == []
    assert "entities" not in saved[0]


def test_episode_type_skips_extraction(saved, extractor):
    api_client.save_memory(content="alpha beta", memory_type="episode")
    assert extractor == []
    assert "entities" not in saved[0]


def test_supplied_entities_are_kept_verbatim(saved, extractor):
    api_client.save_memory(content="alpha beta", memory_type="solution", entities=["Bar"])
    assert extractor == []
    assert saved[0]["entities"] == ["Bar"]


def test_extractor_failure_does_not_block_save(saved, monkeypatch):
    import brain.ingest.entity_extractor as ee

    def boom(text: str) -> list[str]:
        raise RuntimeError("ollama down")

    monkeypatch.setattr(ee, "extract_entities", boom)

    mem_id = api_client.save_memory(content="alpha beta", memory_type="solution")
    assert mem_id == "mem-1"
    assert "entities" not in saved[0]


@pytest.mark.parametrize("value", ["0", "false", "no", "off", " OFF "])
def test_env_kill_switch_disables_extraction(saved, extractor, monkeypatch, value):
    monkeypatch.setenv("BRAIN_AUTO_ENTITIES", value)
    api_client.save_memory(content="alpha beta", memory_type="solution")
    assert extractor == []
    assert "entities" not in saved[0]


def test_env_kill_switch_cannot_force_extraction_on(saved, extractor, monkeypatch):
    """The switch is OFF-only: BRAIN_AUTO_ENTITIES=1 never overrides a False arg."""
    monkeypatch.setenv("BRAIN_AUTO_ENTITIES", "1")
    api_client.save_memory(content="alpha beta", memory_type="solution", auto_entities=False)
    assert extractor == []
    assert "entities" not in saved[0]


# --- save_memory_with_status ------------------------------------------------


def test_with_status_durable_type_defaults_extracts_once(saved, extractor):
    res = api_client.save_memory_with_status(content="alpha beta", memory_type="pattern")
    assert res["status"] == "success" and res["id"] == "mem-1"
    assert extractor == ["alpha beta"]
    assert saved[0]["entities"] == ["Foo"]


def test_with_status_auto_entities_false_skips_extraction(saved, extractor):
    api_client.save_memory_with_status(
        content="alpha beta", memory_type="pattern", auto_entities=False
    )
    assert extractor == []
    assert "entities" not in saved[0]


def test_with_status_episode_type_skips_extraction(saved, extractor):
    api_client.save_memory_with_status(content="alpha beta", memory_type="episode")
    assert extractor == []
    assert "entities" not in saved[0]


# --- D6: api_client stays stdlib-only at import time -------------------------


def test_api_client_imports_no_third_party():
    """D6 — a fresh `import brain.api_client` must not pull `requests`.

    Runs in a subprocess: the in-process sys.modules is already polluted by
    other tests importing the extractor.
    """
    repo_root = Path(__file__).resolve().parents[2]
    code = "import brain.api_client, sys; print('requests' in sys.modules)"
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stdout.strip() == "False", out.stdout + out.stderr
