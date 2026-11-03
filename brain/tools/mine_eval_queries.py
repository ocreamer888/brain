#!/usr/bin/env python3
"""Mine real brain-search queries + accepted results out of Claude Code transcripts.

Ground truth for retrieval_eval.py should come from real usage, not invented
queries (see 2026-10-27 eval reset: the kfold self-match eval is circular).
This walks every ~/.claude/projects/*/*.jsonl transcript, finds
mcp__brain__search_index / search_brain / get_context_tool calls, and treats
any observation ID the agent later pulled full text for via
get_observations_tool (within the same turn or the next couple of turns) as
an accepted/relevant result for that query. That "did the agent promote this
hit to full-read" signal is a real usage-based relevance judgment, not a
guess.

Output is a JSONL of *candidates* for human/CTO spot-check -- not written
directly into brain/eval/gold.jsonl.

Usage:
    python3 brain/tools/mine_eval_queries.py --out brain/eval/gold_mined_candidates.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

PROJECTS_DIR = Path.home() / ".claude" / "projects"
SEARCH_TOOLS = {
    "mcp__brain__search_index": "query",
    "mcp__brain__search_brain": "query",
    "mcp__brain__get_context_tool": "topic",
}
OBSERVE_TOOL = "mcp__brain__get_observations_tool"
ANCHOR_TOOL = "mcp__brain__timeline_tool"
ACCEPT_WINDOW = 15
ID_RE = re.compile(r"#?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")
MIN_QUERY_CHARS = 12


def iter_transcript_messages(path: Path) -> list[dict[str, Any]]:
    out = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return out


def extract_tool_uses(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten to a linear list of {kind, tool_use_id, name, input/content, idx}."""
    events = []
    for idx, obj in enumerate(messages):
        msg = obj.get("message") or {}
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "tool_use":
                events.append(
                    {
                        "kind": "tool_use",
                        "idx": idx,
                        "id": c.get("id"),
                        "name": c.get("name"),
                        "input": c.get("input") or {},
                    }
                )
            elif c.get("type") == "tool_result":
                events.append(
                    {
                        "kind": "tool_result",
                        "idx": idx,
                        "tool_use_id": c.get("tool_use_id"),
                        "content": c.get("content"),
                    }
                )
    return events


def result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(parts)
    return ""


def mine_file(path: Path, project_hint: str) -> list[dict[str, Any]]:
    messages = iter_transcript_messages(path)
    events = extract_tool_uses(messages)

    # tool_use_id -> result text
    results_by_id: dict[str, str] = {}
    for ev in events:
        if ev["kind"] == "tool_result" and ev.get("tool_use_id"):
            results_by_id[ev["tool_use_id"]] = result_text(ev["content"])

    search_calls = [
        ev
        for ev in events
        if ev["kind"] == "tool_use" and ev["name"] in SEARCH_TOOLS
    ]
    observe_calls = [
        ev for ev in events if ev["kind"] == "tool_use" and ev["name"] == OBSERVE_TOOL
    ]
    anchor_calls = [
        ev for ev in events if ev["kind"] == "tool_use" and ev["name"] == ANCHOR_TOOL
    ]

    candidates = []
    for sc in search_calls:
        field = SEARCH_TOOLS[sc["name"]]
        query = sc["input"].get(field)
        if not isinstance(query, str) or len(query.strip()) < MIN_QUERY_CHARS:
            continue
        res_text = results_by_id.get(sc["id"], "")
        returned_ids = list(dict.fromkeys(ID_RE.findall(res_text)))
        if not returned_ids:
            continue

        # accepted = any id returned by this search that the agent then
        # promoted to full-read (get_observations_tool) or anchored a
        # timeline on (timeline_tool), within the next ACCEPT_WINDOW events.
        accepted: list[str] = []
        for oc in observe_calls:
            if not (sc["idx"] < oc["idx"] <= sc["idx"] + ACCEPT_WINDOW):
                continue
            ids_field = oc["input"].get("ids", "")
            requested_ids = [s.strip() for s in str(ids_field).split(",")]
            for rid in requested_ids:
                if rid in returned_ids and rid not in accepted:
                    accepted.append(rid)
        for ac in anchor_calls:
            if not (sc["idx"] < ac["idx"] <= sc["idx"] + ACCEPT_WINDOW):
                continue
            anchor_id = str(ac["input"].get("anchor_id", "")).strip()
            if anchor_id in returned_ids and anchor_id not in accepted:
                accepted.append(anchor_id)

        if not accepted:
            continue

        cand = {
            "query": query.strip(),
            "gold_ids": accepted,
            "k": 10,
            "description": f"mined from transcript ({project_hint}, {path.name})",
            "source_tool": sc["name"],
        }
        brain_project = sc["input"].get("project")
        if isinstance(brain_project, str) and brain_project.strip():
            cand["project"] = brain_project.strip()
        mem_type = sc["input"].get("memory_type")
        if isinstance(mem_type, str) and mem_type.strip():
            cand["memory_type"] = mem_type.strip()
        candidates.append(cand)
    return candidates


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="brain/eval/gold_mined_candidates.jsonl")
    ap.add_argument("--project-filter", default=None, help="substring filter on projects dir name")
    args = ap.parse_args()

    all_candidates = []
    seen_queries: set[str] = set()
    for proj_dir in sorted(PROJECTS_DIR.glob("*")):
        if not proj_dir.is_dir():
            continue
        if args.project_filter and args.project_filter not in proj_dir.name:
            continue
        for jsonl_file in sorted(proj_dir.glob("*.jsonl")):
            for cand in mine_file(jsonl_file, proj_dir.name):
                key = cand["query"].lower()
                if key in seen_queries:
                    continue
                seen_queries.add(key)
                all_candidates.append(cand)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for cand in all_candidates:
            fh.write(json.dumps(cand, ensure_ascii=False) + "\n")

    print(f"Mined {len(all_candidates)} candidate queries -> {out_path}")


if __name__ == "__main__":
    main()
