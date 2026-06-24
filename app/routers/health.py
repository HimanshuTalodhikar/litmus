import structlog
from fastapi import APIRouter, status
from pydantic import BaseModel

from app.db.session import get_db_session, check_db_connection
from app.db.redis_client import check_redis_connection
from app.db.qdrant_client import check_qdrant_connection

router = APIRouter(prefix="/health", tags=["health"])
logger = structlog.get_logger()


class HealthResponse(BaseModel):
    status: str
    database: str
    redis: str
    qdrant: str


@router.get("", response_model=HealthResponse, status_code=status.HTTP_200_OK)
async def health_check():
    db_status = await check_db_connection()
    redis_status = await check_redis_connection()
    qdrant_status = check_qdrant_connection()

    all_ok = (db_status == "ok") and (redis_status == "ok") and (qdrant_status == "ok")
    overall = "ok" if all_ok else "degraded"

    logger.info("health_check", overall=overall, db=db_status, redis=redis_status, qdrant=qdrant_status)

    return HealthResponse(
        status=overall,
        database=db_status,
        redis=redis_status,
        qdrant=qdrant_status,
    )
