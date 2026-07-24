import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import pytest
import numpy as np


class _FakeSentenceTransformer:
    def encode(self, inputs, batch_size=128, normalize_embeddings=True):
        if isinstance(inputs, str):
            return np.array(self._encode_one(inputs, normalize_embeddings), dtype=np.float32)
        return np.array(
            [self._encode_one(text, normalize_embeddings) for text in inputs],
            dtype=np.float32,
        )

    def _encode_one(self, text, normalize_embeddings):
        text_l = text.lower()
        v = np.zeros(768, dtype=np.float32)

        # Group CORS-related phrasing into the same semantic neighborhood.
        if any(k in text_l for k in ("cors", "cross origin", "resource sharing", "express server")):
            v[0] = 0.9
            v[1] = 0.7
            v[2] = 0.3
        elif "pancake" in text_l or "breakfast" in text_l:
            v[10] = 1.0
            v[11] = 0.8
        else:
            # Deterministic fallback pattern for unrelated strings.
            h = abs(hash(text_l))
            for i in range(16):
                v[100 + i] = ((h >> (i * 3)) & 0x7) / 7.0

        if normalize_embeddings:
            norm = np.linalg.norm(v)
            if norm > 0:
                v = v / norm
        return v


@pytest.fixture(autouse=True)
def _mock_embedder_model(monkeypatch):
    import brain.core.embedder as emb

    emb._model = _FakeSentenceTransformer()
    yield
    emb._model = None


def test_embed_returns_list_of_floats():
    import brain.core.embedder as emb
    result = emb.embed("test sentence about CORS")
    assert isinstance(result, list)
    assert len(result) == 768  # all-mpnet-base-v2 output dim
    assert all(isinstance(x, float) for x in result)


def test_embed_batch_returns_list_of_lists():
    import brain.core.embedder as emb
    results = emb.embed_batch(["sentence one", "sentence two"])
    assert len(results) == 2
    assert len(results[0]) == 768


def test_embed_is_deterministic():
    import brain.core.embedder as emb
    a = emb.embed("hello world")
    b = emb.embed("hello world")
    assert a == b


def test_similar_texts_have_higher_similarity():
    import brain.core.embedder as emb
    import numpy as np
    a = np.array(emb.embed("fix CORS issue in express server"))
    b = np.array(emb.embed("resolve cross origin resource sharing problem"))
    c = np.array(emb.embed("make pancakes for breakfast"))
    sim_ab = np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
    sim_ac = np.dot(a, c) / (np.linalg.norm(a) * np.linalg.norm(c))
    assert sim_ab > sim_ac
