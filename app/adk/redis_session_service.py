"""
ADK SessionService backed by ElastiCache Redis.
Replaces InMemorySessionService for production use.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import redis.asyncio as redis
from google.adk.sessions import Session, BaseSessionService
from google.adk.events import Event


class RedisSessionService(BaseSessionService):
    """
    ADK BaseSessionService backed by Redis.
    Creates a fresh Redis connection per-request to avoid event-loop issues.

    Key structure:
      adk:sessions:{app}:{user}:{session}  → JSON(Session)
      adk:sessions:{app}:{user}:ids         → SET of session_ids
    """

    def __init__(self, redis_url: str, ttl_seconds: int = 86400):
        self.redis_url = redis_url
        self.ttl = ttl_seconds

    async def _get_redis(self) -> redis.Redis:
        return redis.from_url(self.redis_url, decode_responses=True)

    def _skey(self, app_name: str, user_id: str, session_id: str) -> str:
        return f"adk:sessions:{app_name}:{user_id}:{session_id}"

    def _isk(self, app_name: str, user_id: str) -> str:
        return f"adk:sessions:{app_name}:{user_id}:ids"

    def _session_to_dict(self, s: Session) -> dict:
        return {
            "id": s.id,
            "app_name": s.app_name,
            "user_id": s.user_id,
            "state": s.state,
            "last_update_time": s.last_update_time,
            "events": [],
        }

    def _dict_to_session(self, d: dict) -> Session:
        return Session(
            id=d["id"],
            app_name=d["app_name"],
            user_id=d["user_id"],
            state=d.get("state", {}),
            last_update_time=d.get("last_update_time", 0.0),
        )

    async def create_session(
        self,
        *,
        app_name: str,
        user_id: str,
        state: Optional[dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> Session:
        r = await self._get_redis()
        sid = session_id or str(uuid.uuid4())
        now_ts = datetime.now(timezone.utc).timestamp()

        session = Session(
            id=sid,
            app_name=app_name,
            user_id=user_id,
            state=state or {},
            last_update_time=now_ts,
        )

        await r.setex(
            self._skey(app_name, user_id, sid),
            self.ttl,
            json.dumps(self._session_to_dict(session)),
        )
        await r.sadd(self._isk(app_name, user_id), sid)
        await r.aclose()
        return session

    async def get_session(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        config: Optional[Any] = None,
    ) -> Optional[Session]:
        r = await self._get_redis()
        try:
            data = await r.get(self._skey(app_name, user_id, session_id))
            if data is None:
                return None
            return self._dict_to_session(json.loads(data))
        finally:
            await r.aclose()

    async def list_sessions(
        self, *, app_name: str, user_id: Optional[str] = None
    ) -> Any:
        from google.adk.sessions import ListSessionsResponse

        r = await self._get_redis()
        try:
            if user_id:
                sids = await r.smembers(self._isk(app_name, user_id))
                sessions = []
                for sid in sids:
                    s = await self.get_session(app_name=app_name, user_id=user_id, session_id=sid)
                    if s:
                        sessions.append(s)
                return ListSessionsResponse(sessions=sessions)
            # List all
            pattern = f"adk:sessions:{app_name}:*"
            keys = []
            async for key in r.scan_iter(match=pattern):
                if ":ids" not in key:
                    keys.append(key)
            sessions = []
            for key in keys:
                data = await r.get(key)
                if data:
                    sessions.append(self._dict_to_session(json.loads(data)))
            return ListSessionsResponse(sessions=sessions)
        finally:
            await r.aclose()

    async def delete_session(
        self, *, app_name: str, user_id: str, session_id: str
    ) -> None:
        r = await self._get_redis()
        try:
            await r.delete(self._skey(app_name, user_id, session_id))
            await r.srem(self._isk(app_name, user_id), session_id)
        finally:
            await r.aclose()

    async def append_event(
        self, session: Session, event: Event
    ) -> Event:
        r = await self._get_redis()
        try:
            session.last_update_time = datetime.now(timezone.utc).timestamp()
            await r.setex(
                self._skey(session.app_name, session.user_id, session.id),
                self.ttl,
                json.dumps(self._session_to_dict(session)),
            )
            return event
        finally:
            await r.aclose()
