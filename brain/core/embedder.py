from sentence_transformers import SentenceTransformer
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import EMBEDDING_MODEL

_model = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def embed(text: str) -> list[float]:
    return get_model().encode(text, normalize_embeddings=True).tolist()


def embed_batch(texts: list[str], batch_size: int = 128) -> list[list[float]]:
    return get_model().encode(texts, batch_size=batch_size, normalize_embeddings=True).tolist()
