"""
Feature requests REST API — CRUD + listing.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.models.feature_request import FeatureRequest, FeatureRequestStatus
from app.db.feature_request_repo import (
    create_feature_request,
    get_feature_request,
    update_feature_request,
    get_recent_feature_requests,
)
from app.services.prioritization import score_priority
from app.services.jira_client import create_jira_ticket
import structlog

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/feature-requests", tags=["feature-requests"])


class CreateFRRequest(BaseModel):
    raw_text: str
    enriched_text: Optional[str] = None
    requester_id: Optional[str] = None
    workspace_id: str = "default"


class UpdateFRRequest(BaseModel):
    status: Optional[str] = None


@router.post("", status_code=201)
async def create_fr(req: CreateFRRequest):
    fr = FeatureRequest(raw_text=req.raw_text, enriched_text=req.enriched_text)
    created = await create_feature_request(fr)

    # Score it
    scores = await score_priority(str(created.id))

    await update_feature_request(
        str(created.id),
        priority_score=scores["final_score"],
        reach_score=scores.get("reach"),
        impact_score=scores.get("impact"),
        confidence_score=scores.get("confidence"),
        effort_estimate=str(scores.get("effort")),
    )

    return {
        "id": str(created.id),
        "fr_number": created.fr_number,
        "priority_score": scores["final_score"],
        "status": created.status.value,
    }


@router.get("/{fr_id}")
async def get_fr(fr_id: str):
    fr = await get_feature_request(fr_id)
    if not fr:
        raise HTTPException(status_code=404, detail="Feature request not found")
    return fr


@router.get("")
async def list_frs(workspace_id: str = "default", limit: int = 20):
    frs = await get_recent_feature_requests(workspace_id=workspace_id, limit=limit)
    return frs


@router.patch("/{fr_id}")
async def update_fr(fr_id: str, req: UpdateFRRequest):
    fields = {}
    if req.status:
        fields["status"] = req.status
    updated = await update_feature_request(fr_id, **fields)
    if not updated:
        raise HTTPException(status_code=404, detail="Feature request not found")
    return updated


@router.post("/{fr_id}/jira-ticket")
async def post_jira_ticket(fr_id: str):
    result = await create_jira_ticket(fr_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result
