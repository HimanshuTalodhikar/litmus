from typing import Optional
from app.config import get_settings

_qdrant_client: Optional[object] = None


def get_qdrant() -> object:
    global _qdrant_client
    if _qdrant_client is None:
        settings = get_settings()
        from qdrant_client import QdrantClient
        _qdrant_client = QdrantClient(
            url=settings.qdrant_url or "http://localhost:6333",
            api_key=settings.qdrant_api_key or "",
        )
    return _qdrant_client


def check_qdrant_connection() -> str:
    settings = get_settings()
    if not settings.qdrant_url:
        return "not_configured"
    try:
        client = get_qdrant()
        client.get_collections()
        return "ok"
    except Exception as e:
        return f"error: {e}"
