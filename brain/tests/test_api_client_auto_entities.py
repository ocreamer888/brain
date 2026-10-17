"""A3 — auto_entities parameter and the BRAIN_AUTO_ENTITIES kill switch.

No live Ollama: the extractor is mocked at ``brain.ingest.entity_extractor``,
which is the module ``api_client._extract_entities_for_save`` lazily imports from.

V-18: extraction runs after a successful, non-deduped POST /save via link_entities.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import brain.api_client as api_client


class _Capture:
    __slots__ = ("saves", "links")

    def __init__(self) -> None:
        self.saves: list[dict] = []
        self.links: list[dict] = []


@pytest.fixture
def capture(monkeypatch):
    """Capture /save and /link-entities payloads."""
    cap = _Capture()

    def fake_request(method: str, path: str, payload: dict | None = None, timeout: int = 10) -> dict:
        if method == "POST" and path == "/save":
            cap.saves.append(payload)
            return {"id": "mem-1", "deduped": False}
        if method == "POST" and path == "/link-entities":
            cap.links.append(payload)
            return {"linked": len((payload or {}).get("entities") or [])}
        raise AssertionError(f"unexpected call: {method} {path}")

    monkeypatch.setattr(api_client, "_request", fake_request)
    monkeypatch.delenv("BRAIN_AUTO_ENTITIES", raising=False)
    return cap


@pytest.fixture
def extractor(monkeypatch):
    """Stub extract_entities; return the list of (text, kwargs) it was called with."""
    import brain.ingest.entity_extractor as ee

    calls: list[tuple[str, dict]] = []

    def fake_extract(text: str, **kw) -> list[str]:
        calls.append((text, kw))
        return ["React"]

    monkeypatch.setattr(ee, "extract_entities", fake_extract)
    return calls


# --- save_memory ------------------------------------------------------------


def test_durable_type_extracts_after_save(capture, extractor):
    mem_id = api_client.save_memory(content="alpha beta", memory_type="solution")
    assert mem_id == "mem-1"
    assert extractor == [("alpha beta", {"memory_type": "solution"})]
    assert "entities" not in capture.saves[0]
    assert capture.links == [{"memory_id": "mem-1", "entities": ["React"]}]


def test_conversation_passes_memory_type_for_higher_cap(capture, extractor):
    """V-10 teeth: live save must forward memory_type (not silently default to fact cap)."""
    api_client.save_memory(content="long chat", memory_type="conversation")
    assert extractor[0][1].get("memory_type") == "conversation"


def test_auto_entities_false_skips_extraction(capture, extractor):
    api_client.save_memory(content="alpha beta", memory_type="solution", auto_entities=False)
    assert extractor == []
    assert capture.links == []


def test_episode_type_skips_extraction(capture, extractor):
    api_client.save_memory(content="alpha beta", memory_type="episode")
    assert extractor == []
    assert capture.links == []


def test_mixed_case_memory_type_still_extracts(capture, extractor):
    """V-35: 'Solution' must not silently skip the durable-type check."""
    api_client.save_memory(content="alpha beta", memory_type=" Solution ")
    assert extractor == [("alpha beta", {"memory_type": "solution"})]
    assert capture.links == [{"memory_id": "mem-1", "entities": ["React"]}]


def test_supplied_entities_are_sanitized_and_linked_after_save(capture, extractor):
    """Caller-supplied entities still go through _clean_entities (stoplist etc.)."""
    api_client.save_memory(
        content="alpha beta", memory_type="solution", entities=["Bar", "React"]
    )
    assert extractor == []
    assert "entities" not in capture.saves[0]
    assert capture.links[0]["entities"] == ["React"]


def test_supplied_secret_entities_are_stripped(capture, extractor):
    """V-04: entities=[...] must not bypass the secret filter."""
    api_client.save_memory(
        content="alpha beta",
        memory_type="solution",
        entities=["sk-or-v1", "React", "ghp/github_pat/AKIA"],
    )
    assert extractor == []
    assert capture.links[0]["entities"] == ["React"]


def test_link_entities_strips_secrets(monkeypatch):
    seen: list[dict] = []

    def fake_request(method, path, payload=None, timeout=10):
        seen.append({"method": method, "path": path, "payload": payload})
        return {"linked": len((payload or {}).get("entities") or [])}

    monkeypatch.setattr(api_client, "_request", fake_request)
    n = api_client.link_entities("mem-1", ["sk-or", "Next.js", "sk-or-v1-free"])
    assert n == 1
    assert seen[0]["payload"]["entities"] == ["Next.js"]


def test_extractor_failure_does_not_block_save(capture, monkeypatch):
    import brain.ingest.entity_extractor as ee

    def boom(text: str, **_kw) -> list[str]:
        raise RuntimeError("ollama down")

    monkeypatch.setattr(ee, "extract_entities", boom)

    mem_id = api_client.save_memory(content="alpha beta", memory_type="solution")
    assert mem_id == "mem-1"
    assert "entities" not in capture.saves[0]
    assert capture.links == []


def test_deduped_save_skips_extraction(capture, extractor, monkeypatch):
    def fake_request(method, path, payload=None, timeout=10):
        if method == "POST" and path == "/save":
            capture.saves.append(payload)
            return {"id": "mem-existing", "deduped": True}
        raise AssertionError(f"unexpected call: {method} {path}")

    monkeypatch.setattr(api_client, "_request", fake_request)
    mem_id = api_client.save_memory(content="alpha beta", memory_type="solution")
    assert mem_id == "mem-existing"
    assert extractor == []
    assert capture.links == []


def test_save_failure_skips_extraction(capture, extractor, monkeypatch):
    def fake_request(method, path, payload=None, timeout=10):
        if method == "POST" and path == "/save":
            raise api_client.BrainApiError("api down")
        raise AssertionError(f"unexpected call: {method} {path}")

    monkeypatch.setattr(api_client, "_request", fake_request)
    with pytest.raises(api_client.BrainApiError):
        api_client.save_memory(content="alpha beta", memory_type="solution")
    assert extractor == []
    assert capture.saves == []


@pytest.mark.parametrize("value", ["0", "false", "no", "off", " OFF "])
def test_env_kill_switch_disables_extraction(capture, extractor, monkeypatch, value):
    monkeypatch.setenv("BRAIN_AUTO_ENTITIES", value)
    api_client.save_memory(content="alpha beta", memory_type="solution")
    assert extractor == []
    assert capture.links == []


def test_env_kill_switch_cannot_force_extraction_on(capture, extractor, monkeypatch):
    """The switch is OFF-only: BRAIN_AUTO_ENTITIES=1 never overrides a False arg."""
    monkeypatch.setenv("BRAIN_AUTO_ENTITIES", "1")
    api_client.save_memory(content="alpha beta", memory_type="solution", auto_entities=False)
    assert extractor == []
    assert capture.links == []


# --- save_memory_with_status ------------------------------------------------


def test_with_status_durable_type_extracts_after_save(capture, extractor):
    res = api_client.save_memory_with_status(content="alpha beta", memory_type="pattern")
    assert res["status"] == "success" and res["id"] == "mem-1"
    assert res["deduped"] is False
    assert extractor == [("alpha beta", {"memory_type": "pattern"})]
    assert capture.links[0]["entities"] == ["React"]


def test_with_status_auto_entities_false_skips_extraction(capture, extractor):
    api_client.save_memory_with_status(
        content="alpha beta", memory_type="pattern", auto_entities=False
    )
    assert extractor == []
    assert capture.links == []


def test_with_status_episode_type_skips_extraction(capture, extractor):
    api_client.save_memory_with_status(content="alpha beta", memory_type="episode")
    assert extractor == []
    assert capture.links == []


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
