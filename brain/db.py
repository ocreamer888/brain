import chromadb
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DB_PATH, MEMORIES_COLLECTION, SESSIONS_COLLECTION

_client = None


def get_client():
    global _client
    if _client is None:
        DB_PATH.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(DB_PATH))
    return _client


def get_memories_collection():
    return get_client().get_or_create_collection(
        name=MEMORIES_COLLECTION,
        metadata={"hnsw:space": "cosine"}
    )


def get_sessions_collection():
    return get_client().get_or_create_collection(
        name=SESSIONS_COLLECTION,
        metadata={"hnsw:space": "cosine"}
    )


def upsert_memory(id: str, document: str, embedding: list, metadata: dict):
    get_memories_collection().upsert(
        ids=[id],
        documents=[document],
        embeddings=[embedding],
        metadatas=[metadata]
    )


def upsert_session(id: str, document: str, embedding: list, metadata: dict):
    get_sessions_collection().upsert(
        ids=[id],
        documents=[document],
        embeddings=[embedding],
        metadatas=[metadata]
    )


def query_memories(embedding: list, n_results: int = 10, where: dict = None) -> dict:
    kwargs = {"query_embeddings": [embedding], "n_results": min(n_results, count_memories() or 1)}
    if where:
        kwargs["where"] = where
    return get_memories_collection().query(**kwargs)


def delete_memories(ids: list):
    get_memories_collection().delete(ids=ids)


def get_all_memory_documents(limit: int = 100) -> list:
    col = get_memories_collection()
    result = col.get(limit=limit, include=["documents", "metadatas"])
    return list(zip(result["ids"], result["documents"], result["metadatas"]))


def count_memories() -> int:
    return get_memories_collection().count()


def count_sessions() -> int:
    return get_sessions_collection().count()
