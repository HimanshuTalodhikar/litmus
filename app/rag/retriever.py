"""
RAG retriever — searches Qdrant for relevant document chunks.
Uses qdrant-client 1.18.0 API.
"""

import asyncio
from dataclasses import dataclass
from typing import Any
from qdrant_client.models import Distance, VectorParams, PointStruct
from app.db.qdrant_client import get_qdrant
from app.rag.embedder import embed_texts

COLLECTION = "product_docs"
VECTOR_SIZE = 384


@dataclass
class RetrievedChunk:
    content: str
    source: str
    heading: str
    score: float


def ensure_collection():
    """Create the collection if it doesn't exist."""
    client = get_qdrant()
    collections = [c.name for c in client.get_collections().collections]
    if COLLECTION not in collections:
        client.create_collection(
            collection_name=COLLECTION,
            vectors_config={VECTOR_SIZE: VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE)},
        )


def upsert_chunks(chunks: list[dict], batch_size: int = 50):
    """
    Upsert document chunks into Qdrant.
    Each chunk dict needs: id, content, source, heading, vector (384-dim list).
    """
    ensure_collection()
    client = get_qdrant()

    points = [
        PointStruct(
            id=chunk["id"],
            vector=chunk["vector"],
            payload={
                "content": chunk["content"],
                "source": chunk["source"],
                "heading": chunk["heading"],
            },
        )
        for chunk in chunks
    ]

    for i in range(0, len(points), batch_size):
        batch = points[i : i + batch_size]
        client.upsert(collection_name=COLLECTION, points=batch)


def retrieve(query: str, top_k: int = 5) -> list[RetrievedChunk]:
    """
    Embed the query, search Qdrant, return top_k relevant chunks.
    """
    query_embedding = embed_texts([query])[0]
    client = get_qdrant()

    try:
        results = client.query_points(
            collection_name=COLLECTION,
            query=query_embedding,
            limit=top_k,
            score_threshold=0.3,
            with_payload=True,
        )
    except Exception:
        return []

    chunks = []
    for r in results.points:
        chunks.append(
            RetrievedChunk(
                content=r.payload.get("content", ""),
                source=r.payload.get("source", ""),
                heading=r.payload.get("heading", ""),
                score=r.score,
            )
        )
    return chunks


def check_product_exists(query: str, top_k: int = 3, score_threshold: float = 0.55) -> tuple[bool, list[RetrievedChunk]]:
    """
    Check if a feature already exists in the product docs (not FR embeddings).
    Returns (exists, matching_chunks).
    Only matches chunks with source != 'feature_request'.
    """
    chunks = retrieve(query, top_k=top_k)
    if not chunks:
        return False, []

    # Filter out FR embeddings — dedup already handles those
    product_chunks = [c for c in chunks if c.source != "feature_request"]
    if not product_chunks:
        return False, []  # No real product docs in Qdrant yet — skip gate

    top = product_chunks[0]
    return top.score >= score_threshold, product_chunks[:2]
