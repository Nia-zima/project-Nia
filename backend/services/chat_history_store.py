# backend/services/chat_history_store.py
import asyncio
import json
import sqlite3
from typing import List, Dict
from pathlib import Path

from backend.core.logger import logger
from backend.core.db import get_conn  # Centralized DB Access

class ChatHistoryStore:
    """
    Store for chat messages.
    Refactored in Phase 3 to use Centralized DB (nia.sqlite3).
    """
    # init_db is handled by backend.core.db.init_schema()

    async def init_db(self) -> None:
        # Phase 3: No-op because core.db handles schema
        pass

    def _insert_sync(self, thread_id: str, turn_id: int, role: str, content_json: str, attachments_json: str) -> None:
        conn = get_conn()
        try:
            conn.execute(
                "INSERT INTO messages (thread_id, turn_id, role, content_json, attachments_json) VALUES (?, ?, ?, ?, ?)",
                (thread_id, turn_id, role, content_json, attachments_json),
            )
            # get_conn implies autocommit (isolation_level=None), safety checks:
            pass
        except Exception as e:
            logger.error(f"[ChatHistory] Insert failed: {e}")
            raise
        finally:
            conn.close()

    async def append_message(
        self,
        thread_id: str,
        turn_id: int,
        role: str,
        content: dict,
        attachments: list | None = None,
    ) -> None:
        try:
            content_json = json.dumps(content, ensure_ascii=False)
            attachments_json = json.dumps(attachments or [], ensure_ascii=False)
            await asyncio.to_thread(self._insert_sync, thread_id, turn_id, role, content_json, attachments_json)
        except Exception:
            logger.exception("[chat_history] append_message failed")

    def _read_sync(self, thread_id: str, limit: int) -> list[dict]:
        conn = get_conn()
        try:
            rows = conn.execute(
                "SELECT ts, turn_id, role, content_json, attachments_json "
                "FROM messages WHERE thread_id=? ORDER BY turn_id DESC LIMIT ?",
                (thread_id, limit),
            ).fetchall()
        finally:
            conn.close()

        out = []
        for ts, turn_id, role, content_json, attachments_json in reversed(rows):
            out.append({
                "ts": ts,
                "turn_id": turn_id,
                "role": role,
                "content": json.loads(content_json),
                "attachments": json.loads(attachments_json),
            })
        return out

    async def get_history(self, thread_id: str, limit: int = 200) -> list[dict]:
        return await asyncio.to_thread(self._read_sync, thread_id, limit)

    def _get_max_turn_sync(self, thread_id: str) -> int:
        conn = get_conn()
        try:
            cur = conn.execute("SELECT MAX(turn_id) FROM messages WHERE thread_id=?", (thread_id,))
            val = cur.fetchone()[0]
            return val if val is not None else 0
        finally:
            conn.close()

    async def get_next_turn_id(self, thread_id: str) -> int:
        current_max = await asyncio.to_thread(self._get_max_turn_sync, thread_id)
        return current_max + 1


chat_history_store = ChatHistoryStore()

