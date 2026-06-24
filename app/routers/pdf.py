"""
PDF download API — generates and serves a PDF for a feature request.
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from app.db.feature_request_repo import get_feature_request
from app.services.pdf_generator import generate_fr_pdf
import structlog

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/feature-requests", tags=["pdf"])


@router.get("/{fr_id}/pdf")
async def download_fr_pdf(fr_id: str):
    """Generate and download a PDF for a feature request."""
    fr = await get_feature_request(fr_id)
    if not fr:
        raise HTTPException(status_code=404, detail="Feature request not found")

    try:
        pdf_bytes = generate_fr_pdf(fr)
        filename = f"FR-{fr.fr_number}-feature-request.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(len(pdf_bytes)),
            },
        )
    except RuntimeError as e:
        if "weasyprint" in str(e):
            raise HTTPException(
                status_code=500,
                detail="PDF generation unavailable — weasyprint not installed"
            )
        raise
    except Exception as e:
        logger.exception("pdf_generation_error", fr_id=fr_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")
