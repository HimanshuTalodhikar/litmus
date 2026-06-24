import redis.asyncio as redis
from app.config import get_settings


def _get_redis_config() -> dict:
    settings = get_settings()
    return {
        "host": settings.redis_host or "localhost",
        "port": settings.redis_port or 6379,
        "password": settings.redis_password or None,
        "ssl": settings.redis_use_ssl,
        "decode_responses": True,
        "socket_connect_timeout": 5,
        "socket_timeout": 5,
    }


async def check_redis_connection() -> str:
    settings = get_settings()
    if not settings.redis_host:
        return "not_configured"
    try:
        client = redis.Redis(**_get_redis_config())
        await client.ping()
        await client.aclose()
        return "ok"
    except Exception as e:
        return f"error: {e}"
