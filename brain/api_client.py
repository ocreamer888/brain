import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class BrainApiError(RuntimeError):
    pass


def backend_mode() -> str:
    mode = os.environ.get("BRAIN_BACKEND", "api").strip().lower()
    if mode not in {"api", "python"}:
        mode = "api"

    enforce_api = os.environ.get("BRAIN_ENFORCE_API_ONLY", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if enforce_api and mode != "api":
        print(
            "[BRAIN] BRAIN_ENFORCE_API_ONLY=1 forcing backend_mode=api (ignoring BRAIN_BACKEND=python)",
            file=sys.stderr,
        )
        return "api"
    return mode


def _base_url() -> str:
    return os.environ.get("BRAIN_API_URL", "http://127.0.0.1:8787").rstrip("/")


def _headers() -> dict[str, str]:
    headers = {"content-type": "application/json"}
    api_key = os.environ.get("BRAIN_API_KEY", "").strip()
    if api_key:
        headers["x-api-key"] = api_key
    return headers


def _request(method: str, path: str, payload: dict | None = None, timeout: int = 10) -> dict:
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url=f"{_base_url()}{path}",
        data=data,
        method=method,
        headers=_headers(),
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            msg = json.loads(body).get("error", body)
        except Exception:
            msg = body
        raise BrainApiError(f"HTTP {e.code}: {msg}") from e
    except urllib.error.URLError as e:
        raise BrainApiError(f"API unavailable: {e}") from e


def get_stats() -> dict:
    return _request("GET", "/stats")


def search(
    query: str,
    n: int = 10,
    memory_type: str | None = None,
    project: str | None = None,
    alpha: float | None = None,
    graph_expand: bool = False,
) -> list[dict]:
    payload: dict = {"query": query, "n": n, "graph_expand": graph_expand}
    if memory_type:
        payload["memory_type"] = memory_type
    if project:
        payload["project"] = project
    if alpha is not None:
        payload["alpha"] = alpha
    return _request("POST", "/search", payload).get("results", [])


def search_index(
    query: str,
    n: int = 10,
    memory_type: str | None = None,
    project: str | None = None,
    graph_expand: bool = False,
) -> list[dict]:
    payload: dict = {"query": query, "n": n, "graph_expand": graph_expand}
    if memory_type:
        payload["memory_type"] = memory_type
    if project:
        payload["project"] = project
    return _request("POST", "/v1/search_index", payload).get("results", [])


def get_observations(ids: list[str]) -> list[dict]:
    return _request("POST", "/v1/get_observations", {"ids": ids}).get("results", [])


def get_episode(id: str) -> dict | None:
    path = f"/get-episode?{urllib.parse.urlencode({'id': id})}"
    try:
        return _request("GET", path)
    except BrainApiError:
        return None


def get_entities(memory_id: str) -> list[dict]:
    return _request("GET", f"/entities?memory_id={memory_id}").get("entities", [])


def link_entities(memory_id: str, entities: list[str]) -> int:
    return _request(
        "POST", "/link-entities", {"memory_id": memory_id, "entities": entities}
    ).get("linked", 0)


def get_neighbors(memory_id: str, exclude_superseded: bool = True) -> list[str]:
    flag = "true" if exclude_superseded else "false"
    return _request(
        "GET", f"/neighbors?memory_id={memory_id}&exclude_superseded={flag}"
    ).get("ids", [])


def timeline(anchor_id: str, before: int = 3, after: int = 3) -> list[dict]:
    return _request(
        "POST",
        "/v1/timeline",
        {"anchor_id": anchor_id, "before": before, "after": after},
    ).get("results", [])


def get_context(topic: str, project: str | None = None, n: int = 5) -> list[dict]:
    return search(query=topic, n=n, project=project)


def _auto_entities_env_enabled() -> bool:
    """Global kill switch — OFF-only. Default enabled."""
    return os.environ.get("BRAIN_AUTO_ENTITIES", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _maybe_extract_entities(*, memory_type, content, entities, auto_entities):
    if entities:
        return entities
    if not auto_entities or not _auto_entities_env_enabled():
        return entities
    try:
        # D6: lazy import keeps api_client stdlib-only at import time.
        # MUST be inside the try — in an environment without `requests` this
        # raises ImportError, and an unguarded import would fail the save.
        from brain.ingest.entity_extractor import extract_entities, DURABLE_MEMORY_TYPES
        if memory_type not in DURABLE_MEMORY_TYPES:
            return entities
        return extract_entities(content) or None
    except Exception:
        return entities


def save_memory(
    content: str,
    memory_type: str = "conversation",
    tags: list[str] | None = None,
    project: str | None = None,
    session_id: str | None = None,
    source: str | None = None,
    file_path: str | None = None,
    title: str | None = None,
    timestamp: str | None = None,
    # Fact-layer fields (ignored for non-fact memory types)
    parent_id: str | None = None,
    event_time: str | None = None,
    salience: float | None = None,
    derived_from: str | None = None,
    entities: list[str] | None = None,
    auto_entities: bool = True,
) -> str:
    payload: dict = {
        "content": content,
        "memory_type": memory_type,
        "tags": tags or [],
        "project": project or "general",
    }
    if session_id is not None:
        payload["session_id"] = session_id
    if source is not None:
        payload["source"] = source
    if file_path is not None:
        payload["file_path"] = file_path
    if title is not None:
        payload["title"] = title
    if timestamp is not None:
        payload["timestamp"] = timestamp
    if parent_id is not None:
        payload["parent_id"] = parent_id
    if event_time is not None:
        payload["event_time"] = event_time
    if salience is not None:
        payload["salience"] = salience
    if derived_from is not None:
        payload["derived_from"] = derived_from
    entities = _maybe_extract_entities(
        memory_type=memory_type,
        content=content,
        entities=entities,
        auto_entities=auto_entities,
    )
    if entities:
        payload["entities"] = entities
    return _request("POST", "/save", payload).get("id", "")


def save_memory_with_status(
    *,
    content: str,
    memory_type: str = "conversation",
    tags: list[str] | None = None,
    project: str | None = None,
    session_id: str | None = None,
    source: str | None = None,
    file_path: str | None = None,
    title: str | None = None,
    timestamp: str | None = None,
    entities: list[str] | None = None,
    auto_entities: bool = True,
) -> dict[str, Any]:
    """Save memory and return explicit status payload for hooks."""
    payload: dict = {
        "content": content,
        "memory_type": memory_type,
        "tags": tags or [],
        "project": project or "general",
    }
    if session_id is not None:
        payload["session_id"] = session_id
    if source is not None:
        payload["source"] = source
    if file_path is not None:
        payload["file_path"] = file_path
    if title is not None:
        payload["title"] = title
    if timestamp is not None:
        payload["timestamp"] = timestamp
    entities = _maybe_extract_entities(
        memory_type=memory_type,
        content=content,
        entities=entities,
        auto_entities=auto_entities,
    )
    if entities:
        payload["entities"] = entities

    mem_id = _request("POST", "/save", payload).get("id", "")
    return {"status": "success", "id": mem_id, "payload": payload}


def save_memory_batch(items: list[dict], default_auto_entities: bool = False) -> dict:
    """Save many memories in one API call.

    Entity handling is **pass-through only, by design** (A4): a caller may supply
    ``entities`` per item, but this path never invokes the extractor. Every batch
    caller is a bulk/migration script with no per-item resume, so synchronous
    per-item LLM calls here would be unbounded and non-resumable — the
    checkpointed entity backfill picks these rows up instead.

    ``default_auto_entities`` exists for signature symmetry with ``save_memory``
    and is deliberately unused; it only lets bulk callers state the opt-out
    explicitly. Do not wire it to the extractor.
    """
    payload_items: list[dict] = []
    for item in items:
        body = {
            "content": item.get("content", ""),
            "memory_type": item.get("memory_type", "conversation"),
            "tags": item.get("tags", []) or [],
            "project": item.get("project", "general") or "general",
        }
        if item.get("session_id") is not None:
            body["session_id"] = item["session_id"]
        if item.get("source") is not None:
            body["source"] = item["source"]
        if item.get("file_path") is not None:
            body["file_path"] = item["file_path"]
        if item.get("title") is not None:
            body["title"] = item["title"]
        if item.get("timestamp") is not None:
            body["timestamp"] = item["timestamp"]
        if item.get("entities"):
            body["entities"] = item["entities"]
        payload_items.append(body)
    return _request("POST", "/save-batch", {"items": payload_items}, timeout=120)


def reflect() -> dict:
    return _request("POST", "/reflect")


def list_memories(
    source: str | None = None,
    memory_type: str | None = None,
    project: str | None = None,
    limit: int = 1000,
    offset: int = 0,
) -> dict:
    """GET /list — list memories for admin/maintenance. Returns {total, returned, items}."""
    params: dict[str, str] = {"limit": str(limit), "offset": str(offset)}
    if source:
        params["source"] = source
    if memory_type:
        params["memory_type"] = memory_type
    if project:
        params["project"] = project
    path = "/list?" + urllib.parse.urlencode(params)
    return _request("GET", path, timeout=60)


def delete_memories(ids: list[str]) -> int:
    """POST /delete — remove memories by ID. Returns count deleted."""
    if not ids:
        return 0
    return _request("POST", "/delete", {"ids": ids}, timeout=60).get("deleted", 0)


def update_salience(memory_id: str, salience: float) -> bool:
    """PATCH /memories/:id — update salience score (0.0–1.0). Returns True if updated."""
    salience = max(0.1, min(1.0, salience))
    result = _request("PATCH", f"/memories/{memory_id}", {"salience": salience})
    return result.get("updated", False)


# ---------------------------------------------------------------------------
# Query Template Integration (AlphaFold3 template-search pattern)
# ---------------------------------------------------------------------------

_TROUBLESHOOT_PATTERNS = [
    "why do", "why does", "why is", "why are", "why can't", "why won't",
    "why did", "why doesn't", "why don't",
    " fail", "failing", "failed",
    " broke", "broken", "breaks",
    " error", "exception",
    "i lost",
    "disappear", "not working", "won't work", "doesn't work",
    "security error", "authorization", "permission denied",
    "keeps failing", "keeps crashing",
]

_FACTUAL_PATTERNS = [
    "what is the cost", "what is the runtime", "what is the price",
    "how much does", "how many ",
    "are conversation threads", "is it visible",
]

_DECISION_PATTERNS = [
    "what did we decide", "what was decided", "why did we choose",
    "what approach", "what strategy", "what pattern",
    "how should we", "what's the best way", "which option",
    "trade-off", "tradeoff", "alternative",
]

_STATUS_PATTERNS = [
    "what happened", "what did we do", "status of",
    "what changed", "what was done", "progress on",
    "session summary", "recap of", "update on",
]

# Which memory types to boost per detected intent
_TYPE_BOOST: dict[str, list[str]] = {
    "solution": ["solution", "error_lesson"],
    "fact": ["fact"],
    "decision": ["decision", "pattern"],
    "status": ["project_context"],
}


def classify_query_intent(query: str) -> str | None:
    """Return type-boost hint ('solution', 'fact', 'decision', 'status') or None."""
    q = query.lower()
    for p in _TROUBLESHOOT_PATTERNS:
        if p in q:
            return "solution"
    for p in _DECISION_PATTERNS:
        if p in q:
            return "decision"
    for p in _STATUS_PATTERNS:
        if p in q:
            return "status"
    for p in _FACTUAL_PATTERNS:
        if p in q:
            return "fact"
    return None


def template_search(
    query: str,
    n: int = 10,
    project: str | None = None,
    graph_expand: bool = False,
) -> list[dict]:
    """Type-biased search: mixes type-filtered hits with general results.

    When query intent is detected (troubleshooting → solution+error_lesson,
    factual → fact), runs a type-filtered pass first, then fills with general
    results. Deduplicates by ID. Falls back to plain search when no intent.
    """
    intent = classify_query_intent(query)
    if intent is None:
        return search(query=query, n=n, project=project, graph_expand=graph_expand)

    boost_types = _TYPE_BOOST.get(intent, [])
    seen_ids: set[str] = set()
    merged: list[dict] = []

    per_type_n = max(n // 2, 5)
    for mtype in boost_types:
        for r in search(
            query=query,
            n=per_type_n,
            memory_type=mtype,
            project=project,
            graph_expand=graph_expand,
        ):
            rid = str(r.get("id", ""))
            if rid not in seen_ids:
                seen_ids.add(rid)
                merged.append(r)

    for r in search(query=query, n=n, project=project, graph_expand=graph_expand):
        rid = str(r.get("id", ""))
        if rid not in seen_ids:
            seen_ids.add(rid)
            merged.append(r)

    return merged[:n]


# ---------------------------------------------------------------------------

def record_feedback(
    event_type: str,
    memory_id: str | None = None,
    query: str | None = None,
    session_id: str | None = None,
    project: str | None = None,
    source: str = "mcp",
    payload: dict | None = None,
    idempotency_key: str | None = None,
) -> str:
    """POST /feedback — log explicit user/tool feedback on retrieval or memories."""
    body: dict = {"event_type": event_type, "source": source}
    if memory_id is not None:
        body["memory_id"] = memory_id
    if query is not None:
        body["query"] = query
    if session_id is not None:
        body["session_id"] = session_id
    if project is not None:
        body["project"] = project
    if payload is not None:
        body["payload"] = payload
    if idempotency_key is not None:
        body["idempotency_key"] = idempotency_key
    return _request("POST", "/feedback", body).get("id", "")
