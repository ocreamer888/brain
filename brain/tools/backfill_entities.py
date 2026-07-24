#!/usr/bin/env python3
"""Backfill entities/edges for existing facts that have zero edges.

Selects edge-less active facts from brain/rust/brain.db (read-only), extracts
entities via a cheap Ollama prompt, and links them onto the memory via the
POST /link-entities endpoint (golden-path writes only — never direct SQLite).

Resumable via a checkpoint file; safe to re-run.

Usage:
    python3 brain/tools/backfill_entities.py [--limit N] [--project PROJ] [--dry-run] [--reset-checkpoint]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import OLLAMA_URL, OLLAMA_SUMMARIZE_MODEL  # noqa: E402
import api_client  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = _REPO_ROOT / "brain" / "rust" / "brain.db"
CHECKPOINT_PATH = _REPO_ROOT / "brain" / "bootstrap" / "checkpoint_entity_backfill.json"

MAX_ENTITIES_PER_FACT = 12
PROGRESS_EVERY = 25

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


# ---------------------------------------------------------------------------
# Entity extraction (cheap Ollama call — do NOT reuse fact_extractor)
# ---------------------------------------------------------------------------

def _call_llm(prompt: str) -> str:
    resp = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": OLLAMA_SUMMARIZE_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0.0},
        },
        timeout=120,
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
        print(f"[backfill/entities] warning: could not parse LLM response as JSON: {e}", file=sys.stderr)
        return []
    if not isinstance(data, dict):
        print("[backfill/entities] warning: LLM response is not a JSON object", file=sys.stderr)
        return []
    raw_entities = data.get("entities")
    if not isinstance(raw_entities, list):
        print("[backfill/entities] warning: LLM response missing 'entities' list", file=sys.stderr)
        return []

    return _clean_entities([str(item) for item in raw_entities])


def extract_entities(text: str) -> list[str]:
    """Extract entity names from `text`. Logs and returns [] on any failure."""
    prompt = _ENTITY_PROMPT.format(text=text)
    try:
        raw = _call_llm(prompt)
    except Exception as e:
        print(f"[backfill/entities] LLM call failed: {e}", file=sys.stderr)
        return []
    return _parse_entities(raw)


# ---------------------------------------------------------------------------
# Selection (read-only SQLite)
# ---------------------------------------------------------------------------

def select_edgeless_facts(
    db_path: Path,
    limit: int | None = None,
    project: str | None = None,
) -> list[dict]:
    """Active facts (not superseded) with zero outgoing edges, newest first."""
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        query = (
            "SELECT id, content, project, timestamp FROM memories "
            "WHERE type = '\"fact\"' "
            "AND (superseded_by IS NULL OR superseded_by = '') "
            "AND id NOT IN (SELECT DISTINCT src_memory_id FROM edges)"
        )
        params: list = []
        if project:
            query += " AND project = ?"
            params.append(project)
        query += " ORDER BY timestamp DESC"
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Checkpoint I/O
# ---------------------------------------------------------------------------

def load_checkpoint(path: Path = CHECKPOINT_PATH) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {"processed_ids": [], "linked_total": 0, "facts_seen": 0}


def save_checkpoint(state: dict, path: Path = CHECKPOINT_PATH) -> None:
    path.write_text(json.dumps(state))


# ---------------------------------------------------------------------------
# Main run
# ---------------------------------------------------------------------------

def run(
    limit: int | None = None,
    project: str | None = None,
    dry_run: bool = False,
    reset_checkpoint: bool = False,
    db_path: Path = DB_PATH,
    checkpoint_path: Path = CHECKPOINT_PATH,
) -> dict:
    if reset_checkpoint and checkpoint_path.exists():
        checkpoint_path.unlink()

    checkpoint = load_checkpoint(checkpoint_path)
    processed_ids: set[str] = set(checkpoint["processed_ids"])
    linked_total = checkpoint["linked_total"]
    facts_seen = checkpoint["facts_seen"]

    facts = select_edgeless_facts(db_path, limit=limit, project=project)
    total = len(facts)
    start = time.time()

    print(f"[backfill/entities] {total} edge-less facts selected (dry_run={dry_run})", file=sys.stderr)

    for i, fact in enumerate(facts, start=1):
        fact_id = fact["id"]
        if fact_id in processed_ids:
            continue

        entities = extract_entities(fact["content"] or "")

        if dry_run:
            print(f"  [dry-run] {fact_id[:12]} entities={entities}")
        else:
            if entities:
                try:
                    linked = api_client.link_entities(fact_id, entities)
                except (api_client.BrainApiError, Exception) as e:
                    print(
                        f"[backfill/entities] warning: link_entities failed for {fact_id}: {e}",
                        file=sys.stderr,
                    )
                    continue
                linked_total += linked
            facts_seen += 1
            processed_ids.add(fact_id)

            if facts_seen % PROGRESS_EVERY == 0:
                save_checkpoint(
                    {
                        "processed_ids": sorted(processed_ids),
                        "linked_total": linked_total,
                        "facts_seen": facts_seen,
                    },
                    checkpoint_path,
                )
                elapsed = time.time() - start
                print(
                    f"[backfill/entities] {i}/{total}, linked_total={linked_total}, elapsed={elapsed:.1f}s",
                    file=sys.stderr,
                )

    if not dry_run:
        save_checkpoint(
            {
                "processed_ids": sorted(processed_ids),
                "linked_total": linked_total,
                "facts_seen": facts_seen,
            },
            checkpoint_path,
        )

    print(f"[backfill/entities] done — facts_seen={facts_seen} linked_total={linked_total}")
    return {"facts_seen": facts_seen, "linked_total": linked_total}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--limit", type=int, help="Cap number of facts to process")
    p.add_argument("--project", help="Filter by project name")
    p.add_argument("--dry-run", action="store_true", help="Print planned entities, do not POST or write checkpoint")
    p.add_argument("--reset-checkpoint", action="store_true", help="Discard existing checkpoint before running")
    args = p.parse_args()

    run(
        limit=args.limit,
        project=args.project,
        dry_run=args.dry_run,
        reset_checkpoint=args.reset_checkpoint,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
