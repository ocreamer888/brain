#!/usr/bin/env python3
"""UserPromptSubmit hook — Strategy Layer: proactive context injection.

Fires on every user message. Reads session state (errors, recent edits) and
the user's prompt to build context-aware brain searches. Injects results
into the conversation via stdout.

Strategy triggers:
  1. Pending error → search for similar past errors/solutions
  2. Project-specific context → surface relevant patterns/decisions
  3. Repeated question detection → flag with original session date
"""
import sys
import json
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def _search_brain(query: str, n: int = 5, memory_type: str | None = None, project: str | None = None) -> list[dict]:
    try:
        from brain.api_client import template_search, search
        if memory_type:
            return search(query=query, n=n, memory_type=memory_type, project=project)
        return template_search(query=query, n=n, project=project)
    except Exception:
        return []


def _format_hits(hits: list[dict], max_items: int = 3, max_chars: int = 150) -> list[str]:
    lines = []
    for h in hits[:max_items]:
        meta = h.get("metadata", {})
        mtype = meta.get("type", "?")
        project = meta.get("project", "?")
        content = h.get("content", "")[:max_chars].replace("\n", " ")
        dist = h.get("distance", 1.0)
        if isinstance(dist, (int, float)) and dist < 0.5:
            lines.append(f"  ({mtype} | {project}) {content}")
    return lines


def run_strategy(prompt: str, session_id: str, cwd: str) -> str | None:
    """Build proactive context from session state + prompt. Returns text to inject or None."""
    from brain.hooks.action_state import load_state
    from brain.hooks.session_start import detect_project

    state = load_state()
    project = detect_project(cwd) or Path(cwd).name
    sections: list[str] = []

    # --- Proactive: Pre-fetched error hints (from PostToolUse) ---
    hints = state.get("strategy_hints", [])
    if hints:
        for hint in hints:
            if hint.get("type") == "similar_error" and hint.get("hits"):
                sections.append("Brain recall — similar past error:")
                for h in hint["hits"][:2]:
                    content = h.get("content", "")[:150].replace("\n", " ")
                    mtype = h.get("type", "?")
                    sections.append(f"  ({mtype}) {content}")
        state["strategy_hints"] = []
        from brain.hooks.action_state import save_state
        save_state(state)

    # --- Context: Prompt-based search (always runs if prompt is meaningful) ---
    if len(prompt) > 20:
        hits = _search_brain(prompt, n=5, project=project)
        relevant = _format_hits(hits, max_items=3)

        if relevant:
            sections.append("Relevant brain context:")
            sections.extend(relevant)

    if not sections:
        return None

    return "\n".join(sections)


try:
    raw = sys.stdin.read().strip()
    if not raw:
        sys.exit(0)

    context = json.loads(raw)
    prompt = context.get("prompt", "")
    session_id = context.get("session_id", "")
    cwd = context.get("cwd", os.getcwd())

    if not prompt or len(prompt) < 5:
        sys.exit(0)

    result = run_strategy(prompt, session_id, cwd)
    if result:
        print(result)

except Exception as e:
    print(f"[BRAIN] UserPromptSubmit failed (non-fatal): {e}", file=sys.stderr)
