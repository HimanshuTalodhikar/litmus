import json
import logging
import redis as redis_sync
import redis.asyncio as redis
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_redis_client = None
_redis_async_client = None


def publish_event_sync(queue_name: str, payload: dict) -> int:
    """Synchronous publish — safe to call from FastAPI route handlers."""
    client = redis_sync.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password,
        ssl=settings.redis_use_ssl,
        decode_responses=True,
        socket_timeout=10,
        socket_connect_timeout=5,
    )
    try:
        message = json.dumps(payload)
        result = client.rpush(f"queue:{queue_name}", message)
        logger.info("event_published_sync", queue=queue_name, payload_size=len(message))
        return result
    finally:
        client.close()


async def get_redis_client():
    global _redis_async_client
    if _redis_async_client is None:
        _redis_async_client = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password,
            ssl=settings.redis_use_ssl,
            decode_responses=True,
            socket_timeout=10,
            socket_connect_timeout=5,
        )
    return _redis_async_client


async def _recreate_client():
    global _redis_async_client
    if _redis_async_client is not None:
        try:
            await _redis_async_client.aclose()
        except Exception:
            pass
    _redis_async_client = None


async def publish_event(queue_name: str, payload: dict) -> int:
    """Async publish — for use in async contexts."""
    client = await get_redis_client()
    message = json.dumps(payload)
    result = await client.rpush(f"queue:{queue_name}", message)
    logger.info("event_published", queue=queue_name, payload_size=len(message))
    return result


async def pop_event(queue_name: str, timeout: int = 5) -> dict | None:
    """Blocking pop from a Redis queue (BLPOP)."""
    client = await get_redis_client()
    try:
        result = await client.blpop(f"queue:{queue_name}", timeout=timeout)
        if result:
            _, message = result
            return json.loads(message)
        return None
    except RedisTimeoutError:
        # Connection timed out during blpop — recreate client to avoid
        # stuck connection state, then return None (normal empty result)
        await _recreate_client()
        return None

