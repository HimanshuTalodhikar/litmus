"""
Doc ingestion API — chunk + embed + upsert to Qdrant.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.rag.chunker import chunk_markdown, Chunk
from app.rag.embedder import embed_texts
from app.rag.retriever import upsert_chunks
from app.db.qdrant_client import get_qdrant
import structlog

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/docs", tags=["docs"])


class IngestRequest(BaseModel):
    text: str
    source: str  # e.g. "product-name" or filename


@router.post("/ingest")
async def ingest_docs(req: IngestRequest):
    """Chunk text and ingest into Qdrant for RAG."""
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="text cannot be empty")

    try:
        chunks: list[Chunk] = chunk_markdown(req.text, source=req.source)
        if not chunks:
            raise HTTPException(status_code=400, detail="no chunks generated from text")

        # Embed all chunks
        texts = [c.content for c in chunks]
        embeddings = embed_texts(texts)

        # Build upsert dicts
        from app.rag.retriever import COLLECTION, VECTOR_SIZE
        import uuid
        points = []
        for i, chunk in enumerate(chunks):
            points.append({
                "id": str(uuid.uuid4()),
                "vector": embeddings[i],
                "content": chunk.content,
                "source": req.source,
                "heading": chunk.heading,
            })

        # upsert_chunks needs "heading" and "source" keys
        upsert_chunks([
            {
                "id": p["id"],
                "vector": p["vector"],
                "content": p["content"],
                "source": p["source"],
                "heading": p["heading"],
            }
            for p in points
        ])

        logger.info("docs_ingested", source=req.source, chunks=len(points))
        return {"chunks_ingested": len(points), "source": req.source}

    except Exception as e:
        logger.exception("ingest_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_doc_stats():
    """Return chunk count and unique sources from Qdrant."""
    try:
        client = get_qdrant()
        from app.rag.retriever import COLLECTION
        info = client.get_collection(collection_name=COLLECTION)
        count = info.points_count

        # Sample a few to get sources
        sample = client.scroll(
            collection_name=COLLECTION,
            limit=200,
            with_payload=True,
        )
        sources = set()
        for p in sample[0]:
            src = p.payload.get("source", "")
            if src and src != "feature_request":
                sources.add(src)

        return {"total_chunks": count, "sources": sorted(sources)}
    except Exception as e:
        logger.warning("doc_stats_error", error=str(e))
        return {"total_chunks": 0, "sources": []}
