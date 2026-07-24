#!/usr/bin/env python3
"""Retitle AND re-embed memory chunks in place (IDs preserved).

Unlike the title-only retitle tools, this regenerates the embedding from
`title + content`, so the title enters the vector (cosine) path — the only
thing that helps cross-lingual retrieval where BM25 finds no shared tokens
(e.g. English query vs Spanish content).

Titles are generated in ENGLISH on purpose: the corpus embedder
(all-mpnet-base-v2) is English-centric, so an English topic title pulls a
Spanish chunk closer to English queries.

Safe to interrupt/resume (checkpoint). Embedding written as little-endian
float32 raw bytes — the exact format the Rust store reads.

NOTE: the live brain_api caches its vector index at boot; restart it to pick
up new embeddings. Offline eval (mcp_eval.offline_rrf_p1) reads the DB
directly and sees changes immediately.

Usage:
    python3 brain/tools/retitle_reembed.py --project sicop --types project_context,fact [--dry-run] [--batch N]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "brain"))

from brain.core.embedder import embed  # noqa: E402
from brain.core.summarizer import _chat  # noqa: E402

DEFAULT_DB = _REPO_ROOT / "brain" / "rust" / "brain.db"
EMBEDDING_DIMS = 768
MAX_CONTENT_CHARS = 1500
SLEEP_BETWEEN = 0.1


def english_title(content: str) -> str:
    prompt = (
        "Generate a concise ENGLISH title (max 12 words) describing the topic of the "
        "content below, so an English-speaking developer can find it by search. "
        "The content may be in Spanish; still answer in English. "
        "Return ONLY the title — no quotes, no trailing punctuation, no explanation.\n\n"
        f"Content:\n{content[:MAX_CONTENT_CHARS]}"
    )
    title = _chat(prompt, max_tokens=40).strip().strip("\"'")
    return title[:100]


def embed_blob(text: str) -> bytes | None:
    vec = np.asarray(embed(text), dtype="<f4")
    if vec.shape[0] != EMBEDDING_DIMS:
        return None
    return vec.tobytes()


def sync_fts(conn: sqlite3.Connection, memory_id: str) -> None:
    conn.execute(
        "DELETE FROM memories_fts WHERE rowid=(SELECT rowid FROM memories WHERE id=?)",
        (memory_id,),
    )
    conn.execute(
        "INSERT INTO memories_fts(rowid, id, content, title) "
        "SELECT rowid, id, content, title FROM memories WHERE id=?",
        (memory_id,),
    )


def load_done(path: Path) -> set[str]:
    if path.exists():
        return set(json.loads(path.read_text()).get("done", []))
    return set()


def save_done(path: Path, done: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"done": sorted(done)}, indent=2))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", required=True)
    ap.add_argument("--types", default="conversation,solution",
                    help="comma list of memory types (default: conversation,solution)")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--batch", type=int, default=0, help="process only N rows (0=all)")
    ap.add_argument("--dry-run", action="store_true", help="preview titles for first 3, no writes")
    args = ap.parse_args(argv)

    types = [t.strip() for t in args.types.split(",") if t.strip()]
    type_clause = " OR ".join(["type = ?"] * len(types))
    type_params = [f'"{t}"' for t in types]  # Rust store stores JSON-quoted types

    checkpoint = _REPO_ROOT / "brain" / "eval" / f"retitle_reembed_{args.project}.json"

    conn = sqlite3.connect(str(args.db))
    conn.execute("PRAGMA journal_mode=WAL")
    rows = conn.execute(
        f"SELECT id, content FROM memories WHERE project = ? AND ({type_clause}) ORDER BY rowid",
        [args.project, *type_params],
    ).fetchall()
    print(f"{args.project}: {len(rows)} chunks matching types={types}")

    done = load_done(checkpoint)
    pending = [(mid, c) for mid, c in rows if mid not in done]
    print(f"Already done: {len(done)}  Remaining: {len(pending)}")
    if args.batch:
        pending = pending[: args.batch]
        print(f"Limiting to {args.batch} this run.")

    if args.dry_run:
        print("\n[DRY-RUN] preview titles:")
        for mid, content in pending[:3]:
            print(f"  [{mid[:8]}] {english_title(content or '')!r}")
            print(f"           content[:120]: {(content or '')[:120]!r}")
        conn.close()
        return 0

    updated = errors = 0
    for i, (mid, content) in enumerate(pending, 1):
        try:
            title = english_title(content or "")
            blob = embed_blob(f"{title}\n\n{content or ''}")
            if blob is None:
                raise ValueError("embedding dim mismatch")
        except Exception as e:
            print(f"  [{i}/{len(pending)}] ERROR {mid[:8]}: {e}")
            errors += 1
            continue

        conn.execute("UPDATE memories SET title=?, embedding=? WHERE id=?", (title, blob, mid))
        sync_fts(conn, mid)
        done.add(mid)
        updated += 1
        if i % 10 == 0 or i == len(pending):
            conn.commit()
            save_done(checkpoint, done)
            print(f"  [{i}/{len(pending)}] committed. last title: {title!r}")
        time.sleep(SLEEP_BETWEEN)

    conn.commit()
    save_done(checkpoint, done)
    conn.close()
    print(f"\nDone. updated={updated} errors={errors} checkpoint={checkpoint}")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
