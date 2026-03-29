from __future__ import annotations

import sqlite3
from typing import Iterable, Optional

from backend.core.db import managed_conn
from backend.core.logger import logger
from backend.services.memory.models import MemoryEvent, MemoryIndexEntry


class StorageDriver:
    """
    Raw DB IO only.
    Business rules must stay in MemoryDriver.
    """

    def _insert_event(self, conn: sqlite3.Connection, event: MemoryEvent) -> None:
        conn.execute(
            """
            INSERT INTO memory_events (
                event_id, thread_id, turn_id, message_id,
                event_type, payload_json, created_at, schema_version
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.thread_id,
                event.turn_id,
                event.message_id,
                event.event_type,
                event.payload_json,
                float(event.created_at),
                int(event.schema_version),
            ),
        )

    def _upsert_index_entry(self, conn: sqlite3.Connection, it: MemoryIndexEntry) -> None:
        conn.execute(
            """
            INSERT INTO memory_index (
                index_id, event_id, thread_id, scope, state_tag,
                tags_json, keywords_json, related_turn_id,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(index_id) DO UPDATE SET
                state_tag=excluded.state_tag,
                tags_json=excluded.tags_json,
                keywords_json=excluded.keywords_json,
                related_turn_id=excluded.related_turn_id,
                updated_at=excluded.updated_at
            """,
            (
                it.index_id,
                it.event_id,
                it.thread_id,
                it.scope,
                it.state_tag,
                it.tags_json,
                it.keywords_json,
                it.related_turn_id,
                float(it.created_at),
                float(it.updated_at),
            ),
        )

    def append_event(self, event: MemoryEvent) -> str:
        with managed_conn() as conn:
            try:
                self._insert_event(conn, event)
                return event.event_id
            except sqlite3.IntegrityError:
                logger.warning("[StorageDriver] append_event conflict event_id=%s", event.event_id)
                raise

    def append_event_and_index(self, event: MemoryEvent, index: Optional[MemoryIndexEntry] = None) -> str:
        """
        Atomic write for event + index.
        Prevents partial state if process crashes between operations.
        """
        with managed_conn() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                self._insert_event(conn, event)
                if index is not None:
                    self._upsert_index_entry(conn, index)
                conn.execute("COMMIT")
                return event.event_id
            except sqlite3.IntegrityError:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                logger.warning("[StorageDriver] append_event_and_index conflict event_id=%s", event.event_id)
                raise
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise

    def upsert_index_entries(self, items: Iterable[MemoryIndexEntry]) -> int:
        with managed_conn() as conn:
            count = 0
            try:
                conn.execute("BEGIN IMMEDIATE")
                for it in items:
                    self._upsert_index_entry(conn, it)
                    count += 1
                conn.execute("COMMIT")
                return count
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise

    def query_index(
        self,
        *,
        thread_id: str,
        scope: Optional[str] = None,
        related_turn_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        with managed_conn() as conn:
            clauses = ["thread_id = ?"]
            params: list[object] = [thread_id]
            if scope:
                clauses.append("scope = ?")
                params.append(scope)
            if related_turn_id:
                clauses.append("related_turn_id = ?")
                params.append(related_turn_id)
            params.append(int(limit))
            where_sql = " AND ".join(clauses)
            rows = conn.execute(
                f"""
                SELECT *
                FROM memory_index
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
            return [dict(r) for r in rows]

    def load_events_by_ids(self, event_ids: list[str]) -> list[dict]:
        if not event_ids:
            return []
        with managed_conn() as conn:
            placeholders = ",".join(["?"] * len(event_ids))
            rows = conn.execute(
                f"""
                SELECT *
                FROM memory_events
                WHERE event_id IN ({placeholders})
                """,
                tuple(event_ids),
            ).fetchall()
            return [dict(r) for r in rows]

    def list_events(
        self,
        *,
        thread_id: Optional[str] = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict]:
        with managed_conn() as conn:
            if thread_id:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM memory_events
                    WHERE thread_id = ?
                    ORDER BY created_at DESC, event_id DESC
                    LIMIT ? OFFSET ?
                    """,
                    (thread_id, int(limit), int(offset)),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM memory_events
                    ORDER BY created_at DESC, event_id DESC
                    LIMIT ? OFFSET ?
                    """,
                    (int(limit), int(offset)),
                ).fetchall()
            return [dict(r) for r in rows]

    def clear_index_for_thread(self, thread_id: str) -> None:
        with managed_conn() as conn:
            conn.execute("DELETE FROM memory_index WHERE thread_id = ?", (thread_id,))
