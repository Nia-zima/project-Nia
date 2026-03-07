from __future__ import annotations

from typing import Optional

from backend.services.memory.memory_driver import MemoryDriver


class MemoryService:
    """
    Public use-case API for Core/Orchestrator.
    Internals are delegated to MemoryDriver.
    """

    def __init__(self, driver: Optional[MemoryDriver] = None) -> None:
        self._driver = driver or MemoryDriver()

    # ── Episodic ──────────────────────────────────────────────────

    def append_event(
        self,
        *,
        thread_id: str,
        event_type: str,
        payload: dict,
        turn_id: Optional[str] = None,
        message_id: Optional[str] = None,
        created_at: Optional[float] = None,
        schema_version: int = 1,
    ) -> str:
        return self._driver.append_event(
            thread_id=thread_id,
            event_type=event_type,
            payload=payload,
            turn_id=turn_id,
            message_id=message_id,
            created_at=created_at,
            schema_version=schema_version,
        )

    def query_index(
        self,
        *,
        thread_id: str,
        scope: Optional[str] = None,
        related_turn_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        return self._driver.query_index(
            thread_id=thread_id,
            scope=scope,
            related_turn_id=related_turn_id,
            limit=limit,
        )

    def load_events(self, event_ids: list[str]) -> list[dict]:
        return self._driver.load_events_by_ids(event_ids)

    def rebuild_index(self, thread_id: Optional[str] = None, *, limit: int = 5000) -> int:
        return self._driver.rebuild_index(thread_id=thread_id, limit=limit)


memory_service = MemoryService()
