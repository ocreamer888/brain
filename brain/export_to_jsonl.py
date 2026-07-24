"""Export all ChromaDB memories to JSONL for Phase 6 Rust migration.

Usage:
    python brain/tools/export_to_jsonl.py [output.jsonl]

Each output line is a JSON object:
    {"id": "...", "content": "...", "metadata": {...}, "embedding": [...]}

The metadata keys match the Python brain schema:
    type, project, tags, timestamp, source, session_id, importance
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import chromadb
from brain.config import DB_PATH, MEMORIES_COLLECTION


def main() -> None:
    output_path = sys.argv[1] if len(sys.argv) > 1 else "memories_export.jsonl"

    client = chromadb.PersistentClient(path=str(DB_PATH))
    col = client.get_or_create_collection(MEMORIES_COLLECTION)

    total = col.count()
    print(f"[export] {total} memories in ChromaDB", file=sys.stderr)

    if total == 0:
        print("[export] nothing to export", file=sys.stderr)
        return

    # Fetch everything at once — 1 535 × 768 floats ≈ 4.7 MB, no problem.
    result = col.get(
        limit=total,
        include=["documents", "metadatas", "embeddings"],
    )

    ids: list = result["ids"]
    documents: list = result["documents"]
    metadatas: list = result["metadatas"]
    embeddings: list = result["embeddings"]

    written = 0
    skipped = 0

    with open(output_path, "w", encoding="utf-8") as f:
        for id_, doc, meta, emb in zip(ids, documents, metadatas, embeddings):
            if doc is None:
                skipped += 1
                continue

            record = {
                    "id": id_,
                    "content": doc,
                    "metadata": meta,
                    "embedding": emb.tolist() if hasattr(emb, "tolist") else emb,
                }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            written += 1

            if written % 200 == 0:
                print(f"[export] {written}/{total} written…", file=sys.stderr)

    print(
        f"[export] done — {written} records written to {output_path}"
        + (f" ({skipped} skipped)" if skipped else ""),
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
