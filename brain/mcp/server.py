"""
Brain MCP Server — exposes brain tools to Claude and Claude Code.

Run with: python -m brain.mcp.server
Or via Claude Code MCP config.
"""
import sys
import site
import json
from pathlib import Path

# brain/mcp/ shadows the installed 'mcp' package when brain/ is in sys.path.
# Fix: put site-packages before brain/ so the installed 'mcp' is resolved first.
_brain_dir = str(Path(__file__).parent.parent)
_ai_dir = str(Path(__file__).parent.parent.parent)
_sp = next((p for p in site.getsitepackages() if 'site-packages' in p), None)

if _sp:
    # Rebuild path: site-packages first, then everything except brain/ dir
    sys.path = [_sp] + [p for p in sys.path if p not in (_brain_dir, _sp)]
    # Clear any stale brain.mcp entries so Python re-resolves from site-packages
    for _k in [k for k in list(sys.modules.keys()) if k == 'mcp' or k.startswith('mcp.')]:
        del sys.modules[_k]

from mcp.server.fastmcp import FastMCP  # now resolves to installed mcp package

# Restore: re-add AI dir for brain.core.* imports
if _ai_dir not in sys.path:
    sys.path.insert(0, _ai_dir)

from brain.api_client import (
    backend_mode,
    get_context as api_get_context,
    get_episode as api_get_episode,
    get_neighbors as api_get_neighbors,
    get_observations as api_get_observations,
    get_stats as api_get_stats,
    record_feedback as api_record_feedback,
    reflect as api_reflect,
    save_memory as api_save_memory,
    search as api_search,
    search_index as api_search_index,
    template_search as api_template_search,
    timeline as api_timeline,
    update_salience as api_update_salience,
)
import os as _os
import re as _re

# Rust API parse_memory_type allow-list (snake_case only).
_VALID_MEMORY_TYPES = frozenset(
    {
        "solution",
        "decision",
        "conversation",
        "pattern",
        "project_context",
        "error_lesson",
        "fact",
        "episode",
    }
)

# Common agent/LLM synonyms → canonical type.
_MEMORY_TYPE_ALIASES = {
    "knowledge": "fact",
    "note": "conversation",
    "memory": "conversation",
    "insight": "pattern",
    "preference": "decision",
    "lesson": "error_lesson",
    "error": "error_lesson",
    "bugfix": "solution",
    "fix": "solution",
    "context": "project_context",
    "summary": "project_context",
    "observation": "fact",
}


def _normalize_memory_type(raw: str | None, default: str = "conversation") -> str:
    """Map free-form labels to an API-accepted memory_type."""
    if not raw or not str(raw).strip():
        return default
    s = str(raw).strip()
    # CamelCase / PascalCase → snake_case, then lower.
    s = _re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    s = s.replace("-", "_").replace(" ", "_").lower()
    s = _MEMORY_TYPE_ALIASES.get(s, s)
    if s in _VALID_MEMORY_TYPES:
        return s
    return default


if _os.environ.get("BRAIN_BACKEND", "api") == "python":
    from brain.core.memory import (
        _trigger_reflection as py_reflect,
        get_context as py_get_context,
        get_stats as py_get_stats,
        save_memory as py_save_memory,
        search as py_search,
    )
else:
    py_reflect = py_get_context = py_get_stats = py_save_memory = py_search = None

# BRAIN_BACKEND=python (Chroma + local embedder) is manual QA only.
# Production golden path is BRAIN_BACKEND=api (Rust brain_api).
mcp = FastMCP("brain", instructions=(
    "You have access to a persistent brain with months of coding history. "
    "Use search_brain to recall past decisions and solutions. "
    "Use save_memory_tool to save important new knowledge. "
    "Use get_context_tool at session start to load relevant memories. "
    "Use reflect_tool periodically to consolidate memories. "
    "Use record_feedback to log when the user accepts, rejects, or corrects a retrieved memory. "
    "For large queries, use the 3-layer pattern: search_index → timeline_tool → get_observations_tool. "
    "Start with search_index to get IDs, use timeline_tool for surrounding context, then get_observations_tool "
    "for full content of only the IDs you actually need. "
    "After search_brain, if you use facts from a hit that shows a vault/... source file, read that file "
    "before citing precise figures or commitments; if the top two distances are within ~0.02, read both vault files."
))


_UNCERTAINTY_GAP = 0.05  # cosine distance gap below which top-2 results are "uncertain"
_LOW_TRUST = 0.40  # salience below which a hit is flagged "⚠ low-trust"


def _salience_of(result: dict) -> float | None:
    """Trust score from a result's metadata. None when absent or unparseable."""
    raw = (result.get("metadata") or {}).get("salience")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


@mcp.tool(description="Semantic search across all memories. Returns most relevant past decisions, solutions, patterns.")
def search_brain(
    query: str,
    n: int = 10,
    memory_type: str = "",
    project: str = "",
    graph_expand: bool = False,
    min_salience: float = 0.0,
) -> str:
    if backend_mode() == "python":
        results = py_search(query=query, n=n, memory_type=memory_type or None, project=project or None)
    elif memory_type:
        # Explicit type filter bypasses template routing
        results = api_search(
            query=query,
            n=n,
            memory_type=memory_type,
            project=project or None,
            graph_expand=graph_expand,
        )
    else:
        results = api_template_search(
            query=query, n=n, project=project or None, graph_expand=graph_expand
        )
    if not results:
        return "No relevant memories found."

    # Confidence filter: drop hits whose known salience is below the threshold.
    # Results with no salience are kept — unknown trust is not evidence of low trust.
    if min_salience > 0.0:
        filtered = [
            r for r in results
            if (_salience_of(r) is None or _salience_of(r) >= min_salience)
        ]
        if not filtered:
            return (
                f"No memories above trust threshold {min_salience:.2f} "
                f"({len(results)} result(s) suppressed)."
            )
        results = filtered

    lines = [f"Found {len(results)} relevant memories:\n"]
    for i, r in enumerate(results, 1):
        meta = r["metadata"]
        lines.append(f"[{i}] ({meta.get('type', '?')} | {meta.get('project', '?')})")
        lines.append(f"    {r['content']}")
        lines.append(f"    Tags: {meta.get('tags', '')} | Source: {meta.get('source', '?')}")
        sal = _salience_of(r)
        trust = "" if sal is None else f" | Trust: {sal:.2f}"
        if sal is not None and sal < _LOW_TRUST:
            trust += " ⚠ low-trust"
        lines.append(f"    Distance: {r.get('distance', '?')}{trust}")
        fp = meta.get("file_path")
        if fp:
            lines.append(f"    Source file: {fp}")
        lines.append("")

    # Active learning: flag uncertain retrievals so user can provide feedback.
    if len(results) >= 2:
        d1 = results[0].get("distance") or 1.0
        d2 = results[1].get("distance") or 1.0
        if isinstance(d1, (int, float)) and isinstance(d2, (int, float)):
            if abs(d2 - d1) < _UNCERTAINTY_GAP:
                id1 = results[0].get("id", "")
                id2 = results[1].get("id", "")
                lines.append(
                    f"⚠ Uncertain retrieval: top 2 results are within {abs(d2 - d1):.3f} distance. "
                    f"If you know which is more relevant, call record_feedback with "
                    f"memory_id='{id1}' event_type='accepted' or memory_id='{id2}' event_type='rejected'."
                )

    return "\n".join(lines)


@mcp.tool(description="Layer 1: search brain index, returns compact rows with IDs.")
def search_index(query: str, n: int = 10, memory_type: str = "", project: str = "") -> str:
    if backend_mode() == "python":
        return "search_index requires BRAIN_BACKEND=api (Rust brain_api)."
    rows = api_search_index(query, n, memory_type or None, project or None)
    if not rows:
        return "No relevant memories found."

    def _fmt(r: dict) -> str:
        line = f"[#{r['id']}] {r['memory_type']} | {r['project']} | {r['snippet']}"
        if r.get("parent_id"):
            line += f" → episode:{r['parent_id']}"
        return line

    return "\n".join(_fmt(r) for r in rows)


@mcp.tool(description="Layer 2: get chronological context around an observation ID.")
def timeline_tool(anchor_id: str, before: int = 3, after: int = 3) -> str:
    if backend_mode() == "python":
        return "timeline_tool requires BRAIN_BACKEND=api (Rust brain_api)."
    rows = api_timeline(anchor_id, before, after)
    if not rows:
        return "No timeline rows for that anchor."
    return "\n".join(
        f"[{r.get('timestamp', '')}] {(r.get('content') or '')[:200]}"
        for r in rows
    )


@mcp.tool(description="Layer 3: fetch full details for observation IDs.")
def get_observations_tool(ids: str) -> str:
    if backend_mode() == "python":
        return "get_observations_tool requires BRAIN_BACKEND=api (Rust brain_api)."
    id_list = [s.strip() for s in ids.split(",") if s.strip()]
    if not id_list:
        return "No IDs provided."
    rows = api_get_observations(id_list)
    if not rows:
        return "No observations for those IDs."
    return "\n\n".join(
        f"--- {r.get('id', '')} ---\n{r.get('content', '')}"
        for r in rows
    )


@mcp.tool(description="Expand a fact to its source episode. Pass a fact_id or episode_id.")
def get_episode(id: str) -> str:
    if backend_mode() == "python":
        return "get_episode requires BRAIN_BACKEND=api (Rust brain_api)."
    ep = api_get_episode(id)
    if not ep:
        return "Episode not found."
    project = ep.get("metadata", {}).get("project", "?")
    return f"[{project}] {ep['content']}"


@mcp.tool(description="Get 1-hop neighbor memory IDs linked via shared entities.")
def get_neighbors_tool(memory_id: str) -> str:
    if backend_mode() == "python":
        return "get_neighbors_tool requires BRAIN_BACKEND=api (Rust brain_api)."
    ids = api_get_neighbors(memory_id)
    if not ids:
        return "No neighbors found."
    return "\n".join(ids)


@mcp.tool(
    description=(
        "Save a new memory to the brain. "
        "memory_type must be one of: solution, decision, conversation, pattern, "
        "project_context, error_lesson, fact, episode (snake_case). "
        "Unknown labels are coerced to conversation."
    )
)
def save_memory_tool(
    content: str,
    memory_type: str = "conversation",
    tags: str = "",
    project: str = "",
    source: str = "claude_code_session",
    title: str = "",
) -> str:
    from brain.ingest.payloads import with_ingest_tag

    memory_type = _normalize_memory_type(memory_type)
    tag_list = with_ingest_tag([t.strip() for t in tags.split(",") if t.strip()])
    tit = title.strip() or None
    memory_id = (
        py_save_memory(
            content=content,
            memory_type=memory_type,
            tags=tag_list,
            project=project or None,
            source=source,
            title=tit,
        )
        if backend_mode() == "python"
        else api_save_memory(
            content=content,
            memory_type=memory_type,
            tags=tag_list,
            project=project or None,
            source=source,
            title=tit,
        )
    )
    return f"Memory saved: {memory_id} (type={memory_type})"


@mcp.tool(description="Get top N most relevant memories for the current topic/project. Use at session start.")
def get_context_tool(topic: str, project: str = "", n: int = 5) -> str:
    results = (
        py_get_context(topic=topic, project=project or None, n=n)
        if backend_mode() == "python"
        else api_get_context(topic=topic, project=project or None, n=n)
    )
    if not results:
        return "No relevant context found for this topic."

    lines = [f"Top {len(results)} memories for '{topic}':\n"]
    for i, r in enumerate(results, 1):
        meta = r["metadata"]
        lines.append(f"[{i}] [{meta.get('type', '?')}] {r['content']}")
    return "\n".join(lines)


@mcp.tool(description="Consolidate and find patterns across recent memories. Runs automatically every 20 saves.")
def reflect_tool() -> str:
    try:
        if backend_mode() == "python":
            py_reflect()
            stats = py_get_stats()
        else:
            api_reflect()
            stats = api_get_stats()
        return f"Reflection complete. Brain stats: {json.dumps(stats, indent=2)}"
    except Exception as e:
        return f"Reflection failed: {e}"


@mcp.tool(description="Get brain stats: memory counts, types, session info.")
def get_stats_tool() -> str:
    stats = py_get_stats() if backend_mode() == "python" else api_get_stats()
    return json.dumps(stats, indent=2)


@mcp.tool(
    description=(
        "Record feedback on a search result or saved memory: accepted, rejected, edited, ranked, or dismissed. "
        "Use when the user confirms or corrects what the brain retrieved."
    )
)
def record_feedback(
    event_type: str,
    memory_id: str = "",
    query: str = "",
    session_id: str = "",
    project: str = "",
    payload_json: str = "",
    idempotency_key: str = "",
) -> str:
    if backend_mode() == "python":
        return "record_feedback requires BRAIN_BACKEND=api (Rust brain with feedback table)."
    extra: dict | None = None
    if payload_json.strip():
        try:
            extra = json.loads(payload_json)
        except json.JSONDecodeError as e:
            return f"Invalid payload_json: {e}"
    fid = api_record_feedback(
        event_type=event_type,
        memory_id=memory_id or None,
        query=query or None,
        session_id=session_id or None,
        project=project or None,
        source="mcp",
        payload=extra,
        idempotency_key=idempotency_key or None,
    )

    # Auto-update salience on accepted/rejected feedback.
    # Conservative nudges: +0.05 accepted, -0.10 rejected. Clamped to [0.1, 1.0].
    salience_msg = ""
    if memory_id and event_type in ("accepted", "rejected"):
        delta = 0.05 if event_type == "accepted" else -0.10
        try:
            obs = api_get_observations([memory_id])
            if obs:
                current = float(obs[0].get("metadata", {}).get("salience") or 0.5)
                new_sal = max(0.1, min(1.0, current + delta))
                updated = api_update_salience(memory_id, new_sal)
                if updated:
                    salience_msg = f" Salience updated: {current:.2f} → {new_sal:.2f}."
        except Exception:
            pass  # Never block feedback recording over salience update failure

    return f"Feedback recorded: {fid}.{salience_msg}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
