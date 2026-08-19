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
import re
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

# Default / fact-calibrated cap. Kept as the public name (amendment A5).
MAX_ENTITIES_PER_FACT = 12

# V-10: longer durable types saturate at 12; raise caps without changing fact.
MAX_ENTITIES_BY_TYPE: dict[str, int] = {
    "fact": 12,
    "error_lesson": 12,
    "pattern": 16,
    "solution": 16,
    "decision": 16,
    "knowledge": 16,
    "project_context": 20,
    "conversation": 24,
}

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
    "localhost",
    # V-07 hubs measured live (generic single words with hub-scale degree)
    "solver", "sphere", "rod", "spin", "sheet", "transfer", "wall", "wind",
    "scene", "constants", "import",
})

# Credential material must never become graph nodes (V-04).
# search() (not ^-only) so bare `sk-or-v1`, slash-joined meta names, and
# embedded keys are dropped — not only canonical `sk-or-v1-<hex>` prefixes.
_SECRET_SHAPE_RE = re.compile(
    r"(?ix)(?:"
    r"sk-or-v1"                      # OpenRouter (bare, -*, -hex, -free)
    r"|sk-or(?![a-z0-9])"            # bare sk-or (not sk-order)
    r"|sk-(?:ant|proj|live)-"        # Anthropic / OpenAI-ish
    r"|ghp[_/]"                      # GitHub PAT classic or slash-meta
    r"|github_pat[_/]"               # fine-grained or slash-meta
    r"|AKIA(?:[0-9A-Z]{8,}|(?![a-z]))"  # AWS key or bare AKIA token
    r"|xox[baprs]-"                  # Slack tokens
    r")"
)

# Tailwind-ish utility prefixes. Keep real package/model names like p-queue,
# font-awesome, text-embedding-ada — only drop digit utilities or known suffixes.
_TW_PREFIX_RE = re.compile(
    r"(?i)^(?:bg|text|p|m|px|py|mx|my|mt|mb|ml|mr|pt|pb|pl|pr|w|h|"
    r"min-h|max-w|max-h|gap|flex|items|justify|overflow|rounded|shadow|"
    r"whitespace|font|border|leading|tracking)-"
)
_TW_UTILITY_SUFFIX = frozenset({
    "sm", "md", "lg", "xl", "2xl", "3xl", "4xl", "5xl", "6xl", "7xl", "8xl", "9xl",
    "full", "auto", "none", "solid", "center", "start", "end", "between", "around",
    "evenly", "baseline", "stretch", "wrap", "nowrap", "hidden", "visible", "scroll",
    "clip", "ellipsis", "tight", "normal", "bold", "medium", "semibold", "black",
    "white", "transparent", "current", "inherit", "collapse", "separate", "shrink",
    "grow", "order", "screen", "fit", "min", "max", "fill", "stroke", "px", "py",
})


def _looks_like_secret(name: str) -> bool:
    return bool(_SECRET_SHAPE_RE.search(name))


# Machine-local path / host shapes that must not become graph nodes. Targeted,
# NOT a blanket "has a slash" rule: repo-relative paths (brain/api_client.py)
# stay valid entities — _salience_key even prefers them. We drop only per-machine
# junk the 2026-08-14 backfill dry-run surfaced: absolute/home filesystem paths,
# URLs, mDNS *.local hostnames, and IP[:port].
_ABS_PATH_RE = re.compile(
    r"(?i)^(?:~|/(?:users|home|private|tmp|var|etc|opt|usr|mnt|root)(?:/|$)|[a-z]:\\)"
)
_URL_RE = re.compile(r"(?i)^[a-z][a-z0-9+.-]*://")
_DOTLOCAL_HOST_RE = re.compile(r"(?i)^[a-z0-9][a-z0-9.-]*\.local$")
_IP_OPT_PORT_RE = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?$")
# host:port with no scheme — localhost:8787, Mac-Studio.local:8787,
# api.example.com:443. Requires a dotted host (or literal localhost) so a bare
# single word:port cannot false-positive a legit token.
_HOST_PORT_RE = re.compile(r"(?i)^(?:localhost|[a-z0-9][a-z0-9.-]*\.[a-z0-9-]+):\d{2,5}$")


def _looks_like_host_or_path_junk(name: str) -> bool:
    return bool(
        _ABS_PATH_RE.match(name)
        or _URL_RE.match(name)
        or _DOTLOCAL_HOST_RE.match(name)
        or _IP_OPT_PORT_RE.match(name)
        or _HOST_PORT_RE.match(name)
    )


def _looks_like_junk(name: str) -> bool:
    """Mechanical junk: versions, .classes, foo(), Tailwind utilities (V-07)."""
    n = name.strip()
    if not n:
        return True
    if _looks_like_host_or_path_junk(n):
        return True
    if re.fullmatch(r"\^?\d+(?:\.\d+)*", n):
        return True
    if n.startswith(".") and re.fullmatch(r"\.[\w.-]+", n):
        return True
    if re.fullmatch(r"[A-Za-z_][\w]*\(\)", n):
        return True
    if _TW_PREFIX_RE.match(n):
        if re.search(r"\d", n):
            return True
        # Known utility suffixes only — not every short p-/text-/font- name.
        suffix = n.rsplit("-", 1)[-1].lower()
        return suffix in _TW_UTILITY_SUFFIX
    return False


def _cap_for_type(memory_type: str | None) -> int:
    if memory_type and memory_type in MAX_ENTITIES_BY_TYPE:
        return MAX_ENTITIES_BY_TYPE[memory_type]
    return MAX_ENTITIES_PER_FACT


def _salience_key(name: str) -> tuple:
    """Prefer proper nouns / paths / multi-word over bare lowercase tokens (V-10)."""
    has_upper = any(c.isupper() for c in name)
    has_pathish = any(c in name for c in "./")
    multi = (" " in name) or ("/" in name)
    return (has_upper, has_pathish or multi, len(name))


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


def _clean_entities(
    names: list[str],
    memory_type: str | None = None,
) -> list[str]:
    """Drop junk/generic/secret-shaped tokens; dedupe; rank; cap by type."""
    seen_lower: set[str] = set()
    kept: list[str] = []
    for item in names:
        name = str(item).strip()
        if not name or len(name) < 2:
            continue
        if not any(c.isalnum() for c in name):
            continue
        if _looks_like_secret(name) or _looks_like_junk(name):
            continue
        key = name.lower()
        if key in _ENTITY_STOPLIST or key in seen_lower:
            continue
        seen_lower.add(key)
        kept.append(name)

    kept.sort(key=_salience_key, reverse=True)
    return kept[: _cap_for_type(memory_type)]


def _parse_entities(raw: str, memory_type: str | None = None) -> list[str]:
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
    return _clean_entities(
        [item for item in raw_entities if isinstance(item, str)],
        memory_type=memory_type,
    )


def extract_entities(
    text: str,
    timeout: tuple[float, float] | None = None,
    memory_type: str | None = None,
) -> list[str]:
    """Extract entity names from `text`. Never raises; returns [] on any failure.

    `timeout` is a (connect, read) pair. Defaults to LIVE_TIMEOUT — short,
    because on the golden path this runs synchronously inside a Claude Code
    hook process. Batch callers pass BACKFILL_TIMEOUT.

    `memory_type` selects the per-type entity cap (V-10). Unknown/None → 12.

    Everything is inside the try: the slice, the call, and the parse. A caller
    passing a non-str, or an OpenAI-compatible gateway returning `content` as a
    list of parts, must not be able to break a save.
    """
    try:
        prompt = _ENTITY_PROMPT.format(text=str(text or "")[:MAX_INPUT_CHARS])
        raw = _call_llm(prompt, timeout=timeout)
        return _parse_entities(raw, memory_type=memory_type)
    except Exception as e:
        print(f"[entity_extractor] extraction failed: {e}", file=sys.stderr)
        return []
