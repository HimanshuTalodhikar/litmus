"""
Implementation plan generation — triggers Claude Opus to generate plan + phases.
"""
import os
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pathlib import Path
from typing import Optional

from app.db.feature_request_repo import get_feature_request, update_feature_request
from app.models.feature_request import ImplStatus
from app.services.plan_generator import generate_implementation_plan
from app.workers.queue_publisher import publish_event_sync
import structlog

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/feature-requests", tags=["implementation"])


class PlanResponse(BaseModel):
    fr_id: str
    fr_number: int
    impl_status: str
    plan_path: Optional[str] = None
    phase_count: Optional[int] = None
    phase_paths: list[str] = []
    error: Optional[str] = None


@router.post("/{fr_id}/generate-plan", response_model=PlanResponse)
async def generate_plan(fr_id: str):
    """
    Trigger plan generation. Runs asynchronously via Redis queue.
    Poll GET /{fr_id}/plan for status.
    """
    fr = await get_feature_request(fr_id)
    if not fr:
        raise HTTPException(status_code=404, detail="Feature request not found")

    if fr.impl_status == ImplStatus.GENERATING:
        raise HTTPException(status_code=409, detail="Plan is already being generated")

    # Push to Redis queue for the worker to process
    publish_event_sync("plan_generation", {
        "fr_id": fr_id,
        "fr_number": fr.fr_number,
        "raw_text": fr.raw_text,
        "enriched_text": fr.enriched_text,
        "priority_score": fr.priority_score,
    })

    # Mark generating immediately
    await update_feature_request(fr_id, impl_status=ImplStatus.GENERATING)

    return PlanResponse(
        fr_id=fr_id,
        fr_number=fr.fr_number,
        impl_status=ImplStatus.GENERATING.value,
    )


@router.get("/{fr_id}/plan", response_model=PlanResponse)
async def get_plan(fr_id: str):
    """Get plan generation status and paths."""
    fr = await get_feature_request(fr_id)
    if not fr:
        raise HTTPException(status_code=404, detail="Feature request not found")

    # Build downloadable paths (relative filenames, not container paths)
    phase_paths = []
    if fr.impl_plan_path:
        plan_path = Path(fr.impl_plan_path)
        if plan_path.exists():
            # Return relative filenames for download API
            phase_paths = [f"FR-{fr.fr_number}-phase-{i}.md" for i in range(1, 99)]
            phase_paths = [p for p in phase_paths if (plan_path.parent.parent / "phases" / p).exists()]

    return PlanResponse(
        fr_id=fr_id,
        fr_number=fr.fr_number,
        impl_status=fr.impl_status.value,
        plan_path=str(Path(fr.impl_plan_path).name) if fr.impl_plan_path else None,
        phase_count=len(phase_paths),
        phase_paths=phase_paths,
        error=fr.impl_error,
    )


# Serve impl/ and phases/ as static download directories
_impl_router = APIRouter(prefix="/impl", tags=["download"])
_phases_router = APIRouter(prefix="/phases", tags=["download"])

# Resolve download dirs relative to app root
_DOWNLOAD_ROOT = Path(__file__).resolve().parent.parent.parent


@_impl_router.get("/{filename}")
async def download_impl(filename: str):
    path = _DOWNLOAD_ROOT / "impl" / filename
    if not path.exists() or ".." in filename:
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path, media_type="text/markdown",
                       filename=filename)


@_phases_router.get("/{filename}")
async def download_phase(filename: str):
    path = _DOWNLOAD_ROOT / "phases" / filename
    if not path.exists() or ".." in filename:
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path, media_type="text/markdown",
                       filename=filename)
