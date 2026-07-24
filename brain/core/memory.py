import sys
import uuid
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))
from brain.core.embedder import embed
from brain.core.summarizer import reflect_memories
import brain.core.db as db
from config import REFLECT_EVERY_N

_save_count = 0


def save_memory(
    content: str,
    memory_type: str,
    tags: list[str],
    project: str | None,
    session_id: str | None = None,
    source: str = "claude_code_session",
    title: str | None = None,
    timestamp: str | None = None,
) -> str:
    global _save_count

    memory_id = str(uuid.uuid4())
    embedding = embed(content)
    ts = (timestamp or "").strip() or datetime.now(timezone.utc).isoformat()
    metadata = {
        "type": memory_type,
        "project": project or "general",
        "tags": ",".join(tags),
        "timestamp": ts,
        "source": source,
        "session_id": session_id or "",
        "importance": 0.5,
        "title": (title or "").strip(),
    }

    db.upsert_memory(memory_id, content, embedding, metadata)

    _save_count += 1
    if _save_count % REFLECT_EVERY_N == 0:
        _trigger_reflection()

    return memory_id


def search(query: str, n: int = 10, memory_type: str | None = None, project: str | None = None) -> list[dict]:
    embedding = embed(query)
    where = None
    if memory_type and project:
        where = {"$and": [{"type": {"$eq": memory_type}}, {"project": {"$eq": project}}]}
    elif memory_type:
        where = {"type": {"$eq": memory_type}}
    elif project:
        where = {"project": {"$eq": project}}

    results = db.query_memories(embedding, n_results=n, where=where)
    if not results["ids"][0]:
        return []

    return [
        {
            "id": results["ids"][0][i],
            "content": results["documents"][0][i],
            "metadata": results["metadatas"][0][i],
            "distance": results["distances"][0][i] if "distances" in results else None
        }
        for i in range(len(results["ids"][0]))
    ]


def get_context(topic: str, project: str | None = None, n: int = 5) -> list[dict]:
    """Get top N most relevant memories for current context."""
    return search(topic, n=n, project=project)


def get_stats() -> dict:
    return {
        "total_memories": db.count_memories(),
        "total_sessions": db.count_sessions(),
        "save_count_this_session": _save_count
    }


def _is_duplicate_content(content: str) -> bool:
    """Check if content is already present in the database."""
    try:
        # Query for similar content using vector search
        embedding = embed(content)
        results = db.query_memories(embedding, n_results=1, where={"type": {"$eq": "conversation"}})

        if results["ids"][0] and len(results["ids"][0]) > 0:
            # If we found a match with very low distance (high similarity), it's likely a duplicate
            distance = results["distances"][0][0] if results.get("distances") else 1.0
            # Consider content a duplicate if similarity is above 0.95 (very high cosine similarity)
            is_duplicate = distance < 0.05
            if is_duplicate:
                print(f"[BRAIN] Detected duplicate with distance {distance:.3f}", file=sys.stderr)
            return is_duplicate
    except Exception as e:
        # If we can't check for duplicates, don't prevent saving
        print(f"[BRAIN] Duplicate check failed: {e}", file=sys.stderr)
        pass
    return False


def save_memory(
    content: str,
    memory_type: str,
    tags: list[str],
    project: str | None,
    session_id: str | None = None,
    source: str = "claude_code_session",
    title: str | None = None,
    timestamp: str | None = None,
) -> str:
    global _save_count

    # Check for duplicates before saving - if content is already present, skip
    # We check for duplicates on all memory types that might be repetitive
    if _is_duplicate_content(content):
        print(f"[BRAIN] Skipping duplicate memory (type: {memory_type})", file=sys.stderr)
        # Return a fake ID to indicate the save was skipped
        return f"duplicate_{uuid.uuid4()}"

    memory_id = str(uuid.uuid4())
    embedding = embed(content)
    ts = (timestamp or "").strip() or datetime.now(timezone.utc).isoformat()
    metadata = {
        "type": memory_type,
        "project": project or "general",
        "tags": ",".join(tags),
        "timestamp": ts,
        "source": source,
        "session_id": session_id or "",
        "importance": 0.5,
        "title": (title or "").strip(),
    }

    db.upsert_memory(memory_id, content, embedding, metadata)

    _save_count += 1
    if _save_count % REFLECT_EVERY_N == 0:
        _trigger_reflection()

    return memory_id


def _trigger_reflection():
    """Consolidate recent memories."""
    recent = db.get_all_memory_documents(limit=50)
    if len(recent) < 5:
        return

    ids = [r[0] for r in recent]
    texts = [r[1] for r in recent]

    try:
        result = reflect_memories(texts)

        # Delete near-duplicates
        to_delete = [ids[i] for i in result.get("to_delete_indices", []) if i < len(ids)]
        if to_delete:
            db.delete_memories(to_delete)
            print(f"[BRAIN] Removed {len(to_delete)} duplicate memories during reflection", file=sys.stderr)

        # Save consolidated memories
        consolidated_count = 0
        for consolidated_text in result.get("consolidated", []):
            save_memory(consolidated_text, "pattern", ["reflected"], None, source="reflection")
            consolidated_count += 1
        if consolidated_count > 0:
            print(f"[BRAIN] Saved {consolidated_count} consolidated memories during reflection", file=sys.stderr)

    except Exception as e:
        print(f"[brain] Reflection failed (non-fatal): {e}", file=sys.stderr)
