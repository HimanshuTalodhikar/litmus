"""
Feature request repository — asyncpg directly, no ORM.
"""
import json
from uuid import UUID
from datetime import datetime
from typing import Optional

import asyncpg
from app.config import get_settings
from app.models.feature_request import FeatureRequest, FeatureRequestStatus, ImplStatus

settings = get_settings()

_pool: asyncpg.Pool | None = None


async def _get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            host=settings.db_host,
            port=settings.db_port,
            user=settings.db_user,
            password=settings.db_password,
            database=settings.db_name,
            min_size=2,
            max_size=10,
            command_timeout=10,
        )
    return _pool


async def close_pool():
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def create_feature_request(fr: FeatureRequest) -> FeatureRequest:
    """Insert a new feature request. Sets fr_number from the SERIAL."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO feature_requests (
                raw_text, enriched_text, extracted_intent, status,
                priority_score, reach_score, impact_score, confidence_score,
                effort_estimate, dedup_status, dedup_match_id, dedup_similarity_score,
                jira_issue_key, jira_issue_url,
                requester_id, slack_channel_id, slack_thread_ts, slack_message_ts,
                workspace_id, impl_status
            )
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20)
            RETURNING id, fr_number, created_at, updated_at
            """,
            fr.raw_text,
            fr.enriched_text,
            json.dumps(fr.extracted_intent) if fr.extracted_intent else None,
            fr.status.value,
            fr.priority_score,
            fr.reach_score,
            fr.impact_score,
            fr.confidence_score,
            fr.effort_estimate,
            fr.dedup_status,
            str(fr.dedup_match_id) if fr.dedup_match_id else None,
            fr.dedup_similarity_score,
            fr.jira_issue_key,
            fr.jira_issue_url,
            fr.requester_id,
            fr.slack_channel_id,
            fr.slack_thread_ts,
            fr.slack_message_ts,
            fr.workspace_id or "default",
            fr.impl_status.value,
        )
    fr.id = row["id"]
    fr.fr_number = row["fr_number"]
    fr.created_at = row["created_at"]
    fr.updated_at = row["updated_at"]
    return fr


async def get_feature_request(fr_id: str) -> Optional[FeatureRequest]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM feature_requests WHERE id = $1", UUID(fr_id)
        )
    if not row:
        return None
    return _row_to_fr(row)


async def update_feature_request(fr_id: str, **fields) -> Optional[FeatureRequest]:
    pool = await _get_pool()
    set_clauses = []
    values = []
    i = 1
    for key, val in fields.items():
        if key == "status" and isinstance(val, FeatureRequestStatus):
            val = val.value
        if key in ("extracted_intent",):
            val = json.dumps(val) if val else None
        set_clauses.append(f"{key} = ${i}")
        values.append(val)
        i += 1
    set_clauses.append(f"updated_at = ${i}")
    values.append(datetime.utcnow())
    i += 1

    query = f"""
        UPDATE feature_requests SET {', '.join(set_clauses)}
        WHERE id = ${i}
        RETURNING *
    """
    values.append(UUID(fr_id))

    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, *values)
    if not row:
        return None
    return _row_to_fr(row)


async def get_recent_feature_requests(workspace_id: str = "default", limit: int = 20):
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM feature_requests
            WHERE workspace_id = $1 AND status != 'rejected'
            ORDER BY created_at DESC LIMIT $2
            """,
            workspace_id,
            limit,
        )
    return [_row_to_fr(r) for r in rows]


async def upsert_feature_request_embedding(fr_id: str, vector: list[float]):
    """Upsert a feature request's embedding into Qdrant (product_docs collection) for dedup."""
    from app.db.qdrant_client import get_qdrant
    from qdrant_client.models import PointStruct

    client = get_qdrant()

    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT fr_number, enriched_text, workspace_id FROM feature_requests WHERE id = $1",
            UUID(fr_id),
        )

    if row:
        point = PointStruct(
            id=str(fr_id),
            vector=vector,
            payload={
                "fr_number": row["fr_number"],
                "enriched_text": row["enriched_text"] or "",
                "workspace_id": row["workspace_id"],
                "source": "feature_request",
            },
        )
        # Use product_docs collection (unnamed 384-dim vectors)
        client.upsert(collection_name="product_docs", points=[point])



def _row_to_fr(row) -> FeatureRequest:
    impl_status_val = row.get("impl_status")
    return FeatureRequest(
        id=row["id"],
        fr_number=row["fr_number"],
        raw_text=row["raw_text"],
        enriched_text=row["enriched_text"],
        extracted_intent=json.loads(row["extracted_intent"]) if row["extracted_intent"] else None,
        status=FeatureRequestStatus(row["status"]),
        priority_score=float(row["priority_score"]) if row["priority_score"] else None,
        reach_score=row["reach_score"],
        impact_score=row["impact_score"],
        confidence_score=float(row["confidence_score"]) if row["confidence_score"] else None,
        effort_estimate=row["effort_estimate"],
        dedup_status=row["dedup_status"],
        dedup_match_id=row["dedup_match_id"],
        dedup_similarity_score=float(row["dedup_similarity_score"]) if row["dedup_similarity_score"] else None,
        jira_issue_key=row["jira_issue_key"],
        jira_issue_url=row["jira_issue_url"],
        requester_id=row["requester_id"],
        slack_channel_id=row["slack_channel_id"],
        slack_thread_ts=row["slack_thread_ts"],
        slack_message_ts=row["slack_message_ts"],
        workspace_id=row["workspace_id"],
        impl_status=ImplStatus(impl_status_val) if impl_status_val else ImplStatus.NOT_STARTED,
        impl_plan_path=row.get("impl_plan_path"),
        impl_error=row.get("impl_error"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        shipped_at=row["shipped_at"],
    )
