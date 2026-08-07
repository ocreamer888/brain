"""Cheap named-entity extraction for durable-memory linking.

Shared by live save (api_client) and brain/tools/backfill_entities.py.
Never raises — callers get [] on any failure so a save is never blocked.

Dependency-light on purpose: stdlib + requests + config only. No numpy, no
sentence-transformers — api_client lazy-imports this module and lean
environments import api_client.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import OLLAMA_URL, OLLAMA_SUMMARIZE_MODEL  # noqa: E402

# Bare strings, matching the `memory_type` argument. The DB stores JSON-encoded
# types ('"fact"'); SQL callers keep their own quoted tuple. Never mix them.
DURABLE_MEMORY_TYPES = frozenset({
    "fact", "solution", "decision", "pattern",
    "project_context", "error_lesson", "conversation",
    # Authored corpus chunks get entity edges like other durable types
    # (spec 2026-08-06). `episode` remains excluded (audit body, not a node).
    "knowledge",
})

MAX_ENTITIES_PER_FACT = 12
MAX_INPUT_CHARS = 8000

# (connect, read) seconds. A scalar `timeout` in requests applies to BOTH phases
# separately, so a single number silently doubles the worst case.
#
# LIVE_TIMEOUT is short on purpose. This call runs synchronously inside the
# PostToolUse/Stop hooks, which have no `timeout` configured in settings.json
# and are therefore killed at the harness default. A killed process never
# reaches post_tool_use's `except` branch, so the memory is never spooled —
# it is silently lost. A long timeout here trades a missing entity for a
# missing memory, which is the wrong trade.
#
# The backfill has no such constraint and keeps the original 120s.
LIVE_TIMEOUT: tuple[float, float] = (
    float(os.environ.get("BRAIN_ENTITY_CONNECT_TIMEOUT", "3")),
    float(os.environ.get("BRAIN_ENTITY_READ_TIMEOUT", "10")),
)
BACKFILL_TIMEOUT: tuple[float, float] = (5.0, 120.0)

_ENTITY_STOPLIST = frozenset({
    # generic VCS / shell verbs and fragments
    "git", "add", "commit", "push", "pull", "clone", "checkout", "merge",
    "rebase", "fetch", "origin", "remote", "branch", "stage", "staging",
    "run", "use", "using", "install", "update", "delete", "remove", "create",
    # placeholder / template tokens
    "commit_message", "branch_name", "repository_url", "repo_url", "file_path",
    "path", "url", "uri", "id", "name", "value", "key", "type", "foo", "bar",
    # ultra-generic nouns that create hubs without meaning
    "code", "file", "files", "function", "component", "app", "application",
    "project", "system", "user", "data", "text", "string", "number",
})

_ENTITY_PROMPT = """Extract the named entities from the text below.
Include: technologies, libraries, tools, products, people, organizations, file paths, project names.
Exclude: generic words, common verbs, filler.

Return ONLY a JSON object: {{"entities": ["Entity1", "Entity2"]}}
If none: {{"entities": []}}

Text:
{text}"""


def _call_llm(prompt: str, timeout: tuple[float, float] | None = None) -> str:
    resp = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": OLLAMA_SUMMARIZE_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0.0},
        },
        timeout=timeout or LIVE_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"] or ""


def _clean_entities(names: list[str]) -> list[str]:
    """Drop junk/generic tokens; dedupe case-insensitively; cap at 12."""
    seen_lower: set[str] = set()
    result: list[str] = []
    for item in names:
        name = str(item).strip()
        if not name or len(name) < 2:
            continue
        if not any(c.isalnum() for c in name):
            continue
        key = name.lower()
        if key in _ENTITY_STOPLIST or key in seen_lower:
            continue
        seen_lower.add(key)
        result.append(name)
        if len(result) >= MAX_ENTITIES_PER_FACT:
            break
    return result


def _parse_entities(raw: str) -> list[str]:
    """Defensive JSON parse. Returns [] on any failure — never raises."""
    stripped = raw.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        stripped = "\n".join(lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:])

    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as e:
        print(f"[entity_extractor] warning: could not parse LLM response as JSON: {e}", file=sys.stderr)
        return []
    if not isinstance(data, dict):
        print("[entity_extractor] warning: LLM response is not a JSON object", file=sys.stderr)
        return []
    raw_entities = data.get("entities")
    if not isinstance(raw_entities, list):
        print("[entity_extractor] warning: LLM response missing 'entities' list", file=sys.stderr)
        return []

    # Only real strings become entity names. Without the isinstance guard a
    # plausible LLM shape like {"entities":[{"name":"React"}]} would be
    # stringified into an entity literally named "{'name': 'React'}".
    return _clean_entities([item for item in raw_entities if isinstance(item, str)])


def extract_entities(text: str, timeout: tuple[float, float] | None = None) -> list[str]:
    """Extract entity names from `text`. Never raises; returns [] on any failure.

    `timeout` is a (connect, read) pair. Defaults to LIVE_TIMEOUT — short,
    because on the golden path this runs synchronously inside a Claude Code
    hook process. Batch callers pass BACKFILL_TIMEOUT.

    Everything is inside the try: the slice, the call, and the parse. A caller
    passing a non-str, or an OpenAI-compatible gateway returning `content` as a
    list of parts, must not be able to break a save.
    """
    try:
        prompt = _ENTITY_PROMPT.format(text=str(text or "")[:MAX_INPUT_CHARS])
        raw = _call_llm(prompt, timeout=timeout)
        return _parse_entities(raw)
    except Exception as e:
        print(f"[entity_extractor] extraction failed: {e}", file=sys.stderr)
        return []
