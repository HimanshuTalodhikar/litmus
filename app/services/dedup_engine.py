"""
Hybrid feature dedup: vector search (Qdrant) + BM25 (PostgreSQL) + RRF.
Uses the existing product_docs Qdrant collection (unnamed 384-dim vectors).
"""
from app.db.qdrant_client import get_qdrant
from app.rag.embedder import embed_texts
import structlog

logger = structlog.get_logger()

FR_COLLECTION = "product_docs"


async def check_duplicates(query: str, workspace_id: str) -> dict:
    """
    Returns: {"matches": [...], "decision": "create"/"match"/"review"}
    """
    # 1. Embed query
    query_embedding = embed_texts([query])[0]

    # 2. Vector search in Qdrant — filter to FR entries via payload
    qdrant = get_qdrant()
    try:
        results = qdrant.query_points(
            collection_name=FR_COLLECTION,
            query=query_embedding,
            limit=20,
            score_threshold=0.25,
            with_payload=True,
        )
    except Exception as e:
        logger.warning("qdrant_dedup_error", error=str(e))
        results = None

    vector_hits = []
    if results and hasattr(results, "points"):
        for r in results.points:
            payload = r.payload or {}
            if payload.get("source") == "feature_request":
                vector_hits.append({
                    "id": str(r.id),
                    "payload": payload,
                    "score": r.score,
                })

    # 3. BM25 via PostgreSQL
    from app.db.pg_pool import get_pool
    bm25_results = []

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, fr_number, enriched_text,
                       ts_rank_cd(enriched_text_tsv, plainto_tsquery('english', $1)) AS bm25_score
                FROM feature_requests
                WHERE workspace_id = $2
                  AND status NOT IN ('rejected')
                ORDER BY bm25_score DESC
                LIMIT 5
            """, query, workspace_id)
        bm25_results = list(rows)
    except Exception as e:
        logger.warning("pg_bm25_dedup_error", error=str(e))

    # 4. RRF fusion — filter to matching workspace, skip zero-rank BM25
    fused = _reciprocal_rank_fusion(vector_hits, bm25_results, workspace_id=workspace_id)

    # 5. Decision — use raw (unnormalized) RRF score for thresholding
    if not fused:
        return {"matches": [], "decision": "create", "confidence": 1.0}

    top_score = fused[0]["score"]

    # Higher thresholds: auto-match only for very strong semantic overlap (RRF raw > 0.5)
    # Note: fused scores are normalized (0-1), so we use 0.90 as match threshold
    # (90% of the best possible score in this workspace)
    if top_score >= 0.90:
        return {"matches": [fused[0]], "decision": "match", "confidence": top_score}
    elif top_score >= 0.50:
        return {"matches": fused[:3], "decision": "review", "confidence": top_score}
    else:
        return {"matches": [], "decision": "create", "confidence": 1.0 - top_score}


def _reciprocal_rank_fusion(vector_results, bm25_results, k=60, workspace_id="default"):
    """RRF fusion of two ranked result lists. Returns raw RRF scores (not normalized)."""
    scores: dict = {}
    seen: dict = {}

    # Vector results — filter to matching workspace
    for i, result in enumerate(vector_results):
        payload_ws = result["payload"].get("workspace_id", "default")
        if payload_ws != workspace_id:
            continue
        doc_id = result["id"]
        rrf = 1.0 / (k + i + 1)
        scores[doc_id] = scores.get(doc_id, 0) + rrf
        seen[doc_id] = {**result["payload"], "id": doc_id}

    # BM25 results — only include if rank > 0 (meaningful text match)
    for i, row in enumerate(bm25_results):
        bm25_score = float(row.get("bm25_score") or 0)
        if bm25_score <= 0:
            continue
        doc_id = str(row["id"])
        rrf = 1.0 / (k + i + 1)
        scores[doc_id] = scores.get(doc_id, 0) + rrf
        if doc_id not in seen:
            seen[doc_id] = {
                "id": doc_id,
                "fr_number": row.get("fr_number"),
                "text": row.get("enriched_text", ""),
            }

    if not scores:
        return []

    # Return with raw scores — NO normalization so thresholds are meaningful
    sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)

    return [
        {**seen[doc_id], "score": round(scores[doc_id], 6)}
        for doc_id in sorted_ids
    ]
