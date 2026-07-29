#!/usr/bin/env python3
"""Re-ingest bracket-prefixed doc chunks into titled, word-bounded memories (any project).

Groups rows where ``content`` starts with ``[DOC_NAME]`` (legacy PDF / paste pipeline),
re-chunks with the same rules as Obsidian ingest, saves via API, deletes old rows.

Default ``project`` is ``ocreamer``; override with ``--project``.

Requires ``brain_api`` and optional ``BRAIN_API_KEY``. Uses ``OBSIDIAN_CHUNK_WORDS`` (default 1500).

Usage:
    python3 brain/tools/reingest_ocreamer_docs.py [--dry-run] [--project NAME]
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from brain.api_client import delete_memories, save_memory_batch  # noqa: E402
from brain.ingest.payloads import (  # noqa: E402
    format_bracketed_memory,
    memory_display_title,
    with_ingest_tag,
)
from brain.ingest.text_chunking import (  # noqa: E402
    normalize_section_title,
    refine_chunks_for_word_limit,
)

DB_PATH = _REPO_ROOT / "brain" / "rust" / "brain.db"


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


CHUNK_WORD_THRESHOLD = max(200, _int_env("OBSIDIAN_CHUNK_WORDS", 1500))


def slugify(text: str) -> str:
    s = re.sub(r"[^\w\s-]", "", text.lower().strip())
    return re.sub(r"[\s_-]+", "_", s)[:80] or "doc"


def load_doc_groups(db_path: Path, project: str) -> dict[str, list[tuple[str, str]]]:
    """Return {doc_name: [(id, body_after_prefix), ...]} for legacy chunk rows."""
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        """
        SELECT id, content FROM memories
        WHERE project = ? AND content LIKE '[%'
          AND (tags IS NULL OR tags NOT LIKE '%' || ? || '%')
        ORDER BY rowid
        """,
        (project, "brain/ingest"),
    ).fetchall()
    conn.close()

    docs: dict[str, list[tuple[str, str]]] = {}
    for mem_id, content in rows:
        bracket_end = content.find("]")
        if bracket_end == -1:
            continue
        doc_name = content[1:bracket_end]
        body = content[bracket_end + 1 :].lstrip()
        if doc_name not in docs:
            docs[doc_name] = []
        docs[doc_name].append((mem_id, body))
    return docs


def build_save_items(doc_name: str, bodies: list[tuple[str, str]], project: str) -> list[dict]:
    full_text = "\n\n".join(b for _, b in bodies)
    raw = [(doc_name, full_text)]
    refined = refine_chunks_for_word_limit(
        raw, doc_name, word_threshold=CHUNK_WORD_THRESHOLD
    )
    out: list[dict] = []
    for i, (section_title, body) in enumerate(refined):
        st = normalize_section_title(doc_name, section_title)
        content = format_bracketed_memory(doc_name, st, body)
        title = memory_display_title(doc_name, st)
        out.append(
            {
                "content": content,
                "memory_type": "project_context",
                "project": project,
                "tags": with_ingest_tag(["document", "reingest"]),
                "title": title,
                "source": "reingest_tool",
                "session_id": f"reingest_{slugify(doc_name)}_{i}",
            }
        )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print plan, do not call API")
    parser.add_argument("--project", default="ocreamer", help="Brain project name (default ocreamer)")
    args = parser.parse_args(argv)

    print(f"Loading bracket chunks from {DB_PATH} project={args.project!r}...")
    docs = load_doc_groups(DB_PATH, args.project)
    n_chunks = sum(len(v) for v in docs.values())
    print(f"Found {n_chunks} chunks across {len(docs)} documents (threshold={CHUNK_WORD_THRESHOLD}w)\n")

    created = 0
    deleted = 0
    batch_size = 32

    for doc_name, chunk_rows in sorted(docs.items(), key=lambda kv: -len(kv[1])):
        print(f"[{len(chunk_rows):3d} legacy rows] {doc_name}")

        items = build_save_items(doc_name, chunk_rows, args.project)
        print(f"  → {len(items)} new memories after chunking")

        if args.dry_run:
            created += len(items)
            deleted += len(chunk_rows)
            continue

        chunk_ids = [mid for mid, _ in chunk_rows]
        try:
            for i in range(0, len(items), batch_size):
                batch = items[i : i + batch_size]
                res = save_memory_batch(batch, default_auto_entities=False)
                failed = [r for r in res.get("results", []) if r.get("error")]
                if failed:
                    print(f"  ERROR save-batch: {failed[:3]}", file=sys.stderr)
                    raise RuntimeError("save-batch failed")
                time.sleep(0.3)
        except Exception as e:
            print(f"  SKIP: {e!r} — not deleting legacy rows", file=sys.stderr)
            continue

        created += len(items)
        n_del = delete_memories(chunk_ids)
        deleted += n_del
        print(f"  ✓ saved {len(items)} deleted={n_del} legacy ids")
        print()

    print(f"Done. Created {created} memories, removed {deleted} legacy rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
