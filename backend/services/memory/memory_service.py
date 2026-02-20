from __future__ import annotations

from typing import Optional

from backend.services.memory.commit_executor import CommitPlan, CommitResult
from backend.services.memory.commit_executor import execute as _execute_commit
from backend.services.memory.memory_driver import MemoryDriver
from backend.services.memory.models import SemanticMemory, WorkingItem
from backend.services.memory import semantic_store
from backend.services.memory import working_store


class MemoryService:
    """
    Public use-case API for Core/Orchestrator.
    Internals are delegated to MemoryDriver.
    """

    def __init__(self, driver: Optional[MemoryDriver] = None) -> None:
        self._driver = driver or MemoryDriver()

    # ── Episodic (existing) ──────────────────────────────────────

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

    # ── Semantic (Phase B) ───────────────────────────────────────

    def get_semantic(self, id: str) -> Optional[SemanticMemory]:
        return semantic_store.get_by_id(id)

    def get_semantic_chain(self, id: str) -> list[SemanticMemory]:
        return semantic_store.get_chain(id)

    def search_semantic(self, thread_id: str, *, limit: int = 20) -> list[SemanticMemory]:
        return semantic_store.search_active(thread_id, limit=limit)

    # ── Working (Phase C) ──────────────────────────────────────────

    def get_working(self, id: str) -> Optional[WorkingItem]:
        return working_store.get_by_id(id)

    def list_open_working(self, thread_id: str, *, limit: int = 20) -> list[WorkingItem]:
        return working_store.list_open(thread_id, limit=limit)

    def count_open_working(self, thread_id: str) -> int:
        return working_store.count_open(thread_id)

    # ── S5 Commit (Phase B+C) ────────────────────────────────────

    def commit(
        self,
        plan: CommitPlan,
        *,
        thread_id: str,
        turn_id: Optional[str] = None,
    ) -> CommitResult:
        return _execute_commit(plan, thread_id=thread_id, turn_id=turn_id)


memory_service = MemoryService()
