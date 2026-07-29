#!/usr/bin/env python3
"""Export brain memories as an Obsidian knowledge graph.

Each memory becomes one note with YAML frontmatter + [[wikilinks]] to its
top-N semantic neighbours (found via the brain API search).

Usage:
    python3 brain/tools/export_knowledge_graph.py [options]

Options:
    --out DIR           Output directory inside vault (default: brain-graph)
    --neighbors N       Wikilinks per note (default: 3)
    --min-importance F  Skip memories below this importance (default: 0.0)
    --types TYPE,...    Comma-separated types to include (default: all)
    --limit N           Max notes to export, 0 = all (default: 0)
    --db PATH           SQLite path (default: BRAIN_DB_PATH env or brain/rust/brain.db)
    --no-clean          Skip wiping the output directory before regenerating
"""
from __future__ import annotations

import argparse
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from brain.api_client import search  # noqa: E402
from brain.config import OBSIDIAN_VAULT  # noqa: E402

# ── helpers ──────────────────────────────────────────────────────────────────

_VAULT = OBSIDIAN_VAULT
_UNSAFE = re.compile(r'[\\/:*?"<>|#^\[\]]')


def _slug(text: str, max_len: int = 60) -> str:
    """Turn memory content into a safe filename slug."""
    first_line = text.strip().splitlines()[0] if text.strip() else "untitled"
    slug = _UNSAFE.sub("", first_line)
    slug = re.sub(r"\s+", " ", slug).strip()
    return slug[:max_len] or "untitled"


def _strip_quotes(v: str) -> str:
    """SQLite stores enum strings as JSON: '"solution"' → 'solution'."""
    return v.strip('"').strip("'")


def _unique_name(base: str, seen: set[str]) -> str:
    name = base
    counter = 2
    while name.lower() in seen:
        name = f"{base} {counter}"
        counter += 1
    seen.add(name.lower())
    return name


def _frontmatter(m: dict) -> str:
    tags_raw = m.get("tags", "") or ""
    tag_list = [t.strip() for t in tags_raw.split(",") if t.strip()]
    tags_yaml = "\n".join(f"  - {t}" for t in tag_list) if tag_list else "  []"
    return (
        "---\n"
        f"id: {m['id']}\n"
        f"type: {m['type']}\n"
        f"project: {m['project']}\n"
        f"source: {m['source']}\n"
        f"importance: {m['importance']}\n"
        f"timestamp: {m['timestamp']}\n"
        f"tags:\n{tags_yaml}\n"
        "---\n"
    )


# ── main ─────────────────────────────────────────────────────────────────────

def load_memories(db_path: str, min_importance: float, types: list[str] | None) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if types:
        placeholders = ",".join("?" * len(types))
        # Match both raw and JSON-quoted values
        quoted = [f'"{t}"' for t in types]
        all_vals = types + quoted
        placeholders2 = ",".join("?" * len(all_vals))
        rows = cur.execute(
            f"SELECT * FROM memories WHERE importance >= ? AND type IN ({placeholders2})",
            [min_importance] + all_vals,
        ).fetchall()
    else:
        rows = cur.execute(
            "SELECT * FROM memories WHERE importance >= ?",
            [min_importance],
        ).fetchall()

    conn.close()
    return [dict(r) for r in rows]


def find_neighbors(memory: dict, n: int) -> list[dict]:
    """Return top-N neighbours (excluding self) via brain API search."""
    query_text = memory["content"][:300]
    try:
        results = search(query_text, n=n + 1)  # +1 to account for self
    except Exception:
        return []
    return [r for r in results if r["id"] != memory["id"]][:n]


def write_note(memory: dict, neighbors: list[dict], id_to_name: dict[str, str], out_dir: Path) -> None:
    mem_type = _strip_quotes(memory["type"])
    note_dir = out_dir / mem_type
    note_dir.mkdir(parents=True, exist_ok=True)

    name = id_to_name[memory["id"]]
    path = note_dir / f"{name}.md"

    related_links = ""
    if neighbors:
        links = []
        for nb in neighbors:
            nb_name = id_to_name.get(nb["id"])
            nb_type = _strip_quotes(nb.get("metadata", {}).get("type", "conversation"))
            if nb_name:
                links.append(f"- [[{nb_type}/{nb_name}]]")
        if links:
            related_links = "\n## Related\n" + "\n".join(links) + "\n"

    content = (
        _frontmatter(memory)
        + "\n"
        + memory["content"].strip()
        + "\n"
        + related_links
    )
    path.write_text(content, encoding="utf-8")


def write_index(memories: list[dict], id_to_name: dict[str, str], out_dir: Path) -> None:
    from collections import defaultdict
    by_type: dict[str, list] = defaultdict(list)
    for m in memories:
        t = _strip_quotes(m["type"])
        by_type[t].append(m)

    lines = [
        "# Brain Knowledge Graph\n",
        f"> {len(memories)} memories · generated {time.strftime('%Y-%m-%d')}\n",
    ]

    for t in sorted(by_type):
        lines.append(f"\n## {t.replace('_', ' ').title()} ({len(by_type[t])})\n")
        # show top 10 by importance, rest collapsed
        sorted_mems = sorted(by_type[t], key=lambda x: x["importance"], reverse=True)
        for m in sorted_mems[:10]:
            name = id_to_name[m["id"]]
            lines.append(f"- [[{t}/{name}]]")
        if len(sorted_mems) > 10:
            lines.append(f"- *(+{len(sorted_mems) - 10} more in `{t}/`)*")

    (out_dir / "Brain Knowledge Graph.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="brain-graph")
    p.add_argument("--neighbors", type=int, default=3)
    p.add_argument("--min-importance", type=float, default=0.0)
    p.add_argument("--types", default="")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--db", default="")
    p.add_argument("--no-clean", action="store_true", help="Skip wiping output dir before regenerating")
    args = p.parse_args()

    import os
    db_path = args.db or os.environ.get("BRAIN_DB_PATH") or str(
        Path(__file__).resolve().parents[2] / "brain/rust/brain.db"
    )
    out_dir = _VAULT / args.out
    types = [t.strip() for t in args.types.split(",") if t.strip()] or None

    print(f"[graph] db         : {db_path}", file=sys.stderr)
    print(f"[graph] output     : {out_dir}", file=sys.stderr)
    print(f"[graph] neighbors  : {args.neighbors}", file=sys.stderr)
    print(f"[graph] importance : >= {args.min_importance}", file=sys.stderr)

    memories = load_memories(db_path, args.min_importance, types)
    if args.limit:
        memories = memories[: args.limit]

    print(f"[graph] loaded     : {len(memories)} memories", file=sys.stderr)

    # Build id → unique display name map (needed before writing any note)
    seen: set[str] = set()
    id_to_name: dict[str, str] = {}
    for m in memories:
        base = _slug(m["content"])
        name = _unique_name(base, seen)
        id_to_name[m["id"]] = name
        m["type"] = _strip_quotes(m["type"])
        m["source"] = _strip_quotes(m["source"])

    if not args.no_clean and out_dir.exists():
        print(f"[graph] cleaning   : {out_dir}", file=sys.stderr)
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    errors = 0
    for i, m in enumerate(memories, 1):
        neighbors = find_neighbors(m, args.neighbors)
        write_note(m, neighbors, id_to_name, out_dir)
        if i % 100 == 0:
            print(f"[graph] {i}/{len(memories)} notes written…", file=sys.stderr)

    write_index(memories, id_to_name, out_dir)

    print(
        f"[graph] done — {len(memories) - errors} notes → {out_dir}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
