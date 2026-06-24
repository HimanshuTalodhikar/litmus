"""
Local embedding using sentence-transformers.
No API key needed — runs entirely on CPU.
"""

from sentence_transformers import SentenceTransformer
from typing import Optional

_model: Optional[SentenceTransformer] = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        # all-MiniLM-L6-v2: 384 dimensions, fast, good quality
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Embed a list of texts. Returns list of float vectors.
    Each vector is 384-dimensional.
    """
    model = get_model()
    embeddings = model.encode(texts, normalize_embeddings=True)
    return embeddings.tolist()


def embed_text(text: str) -> list[float]:
    """Embed a single text."""
    return embed_texts([text])[0]
