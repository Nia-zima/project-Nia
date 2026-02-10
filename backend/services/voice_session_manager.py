from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class VoiceSessionManager:
    """
    In-memory voice session registry for WS-based voice mode.
    Step 1 scope: session lifecycle + connection tracking only.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sessions: dict[str, dict[str, Any]] = {}
        self._client_to_session: dict[str, str] = {}

    async def start_session(self, *, thread_id: str, client_id: str) -> dict[str, Any]:
        async with self._lock:
            prev_session_id = self._client_to_session.get(client_id)
            if prev_session_id and prev_session_id in self._sessions:
                prev = self._sessions[prev_session_id]
                prev["status"] = "replaced"
                prev["ended_at"] = _utc_now_iso()
                prev["updated_at"] = prev["ended_at"]

            session_id = uuid4().hex
            now = _utc_now_iso()
            session = {
                "session_id": session_id,
                "thread_id": thread_id,
                "client_id": client_id,
                "status": "created",
                "created_at": now,
                "updated_at": now,
                "ended_at": None,
                "last_seen_at": now,
                "connection_count": 0,
            }
            self._sessions[session_id] = session
            self._client_to_session[client_id] = session_id
            return dict(session)

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        async with self._lock:
            session = self._sessions.get(session_id)
            return dict(session) if session else None

    async def stop_session(self, session_id: str, reason: str = "stopped") -> dict[str, Any] | None:
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            now = _utc_now_iso()
            session["status"] = reason or "stopped"
            session["ended_at"] = now
            session["updated_at"] = now
            session["connection_count"] = 0
            client_id = str(session.get("client_id") or "")
            if client_id and self._client_to_session.get(client_id) == session_id:
                self._client_to_session.pop(client_id, None)
            return dict(session)

    async def touch(self, session_id: str) -> dict[str, Any] | None:
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            now = _utc_now_iso()
            session["last_seen_at"] = now
            session["updated_at"] = now
            return dict(session)

    async def attach_connection(self, session_id: str) -> dict[str, Any] | None:
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            session["connection_count"] = int(session.get("connection_count") or 0) + 1
            session["status"] = "connected"
            now = _utc_now_iso()
            session["last_seen_at"] = now
            session["updated_at"] = now
            return dict(session)

    async def detach_connection(self, session_id: str) -> dict[str, Any] | None:
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            current = int(session.get("connection_count") or 0)
            session["connection_count"] = max(0, current - 1)
            if session["connection_count"] == 0 and not session.get("ended_at"):
                session["status"] = "idle"
            now = _utc_now_iso()
            session["last_seen_at"] = now
            session["updated_at"] = now
            return dict(session)


voice_session_manager = VoiceSessionManager()

