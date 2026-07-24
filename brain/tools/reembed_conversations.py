"""
Re-embed all conversation memories to encode their current titles.

The stored embedding may encode stale content (without the current title prepended). By
prepending the title, we anchor the embedding to the meaningful title, making semantic
search work correctly.

Target: memories WHERE type='"conversation"'

Embed text: title + "\\n\\n" + content[:1500]  (truncated to stay within model limits)

FTS5: not affected — we only update the embedding blob, not title/content.

Usage:
    python3 brain/tools/reembed_conversations.py [--dry-run] [--batch N] [--db PATH]
"""
from __future__ import annotations

import argparse
import sqlite3
import struct
import sys
from pathlib import Path

import numpy as np

DEFAULT_DB = Path(__file__).resolve().parents[1] / "rust" / "brain.db"
DEFAULT_BATCH = 64


def _embedding_to_bytes(emb: list[float]) -> bytes:
    """Pack float32 list as little-endian bytes (matches Rust embedding_to_bytes)."""
    return struct.pack(f"<{len(emb)}f", *emb)


def run_reembed(db_path: Path = DEFAULT_DB, batch_size: int = DEFAULT_BATCH, dry_run: bool = False) -> int:
    """Re-embed all conversation memories with current titles. Returns count of memories updated."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from brain.core.embedder import embed_batch

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")

    rows = conn.execute(
        "SELECT id, title, content FROM memories "
        "WHERE type='\"conversation\"' AND embedding IS NOT NULL"
    ).fetchall()

    print(f"{'[DRY RUN] ' if dry_run else ''}Found {len(rows)} conversation memories to re-embed")

    if dry_run or not rows:
        conn.close()
        return len(rows)

    updated = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        ids = [r[0] for r in batch]
        texts = [f"{r[1]}\n\n{r[2][:1500]}" for r in batch]

        embeddings = embed_batch(texts)

        for mid, emb in zip(ids, embeddings):
            emb_bytes = _embedding_to_bytes(emb)
            conn.execute("UPDATE memories SET embedding=? WHERE id=?", (emb_bytes, mid))

        conn.commit()
        updated += len(batch)
        print(f"  Re-embedded {updated}/{len(rows)} ...", end="\r")

    print(f"\nDone. Re-embedded {updated} conversation memories.")
    conn.close()
    return updated


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch", type=int, default=DEFAULT_BATCH)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    run_reembed(db_path=args.db, batch_size=args.batch, dry_run=args.dry_run)
