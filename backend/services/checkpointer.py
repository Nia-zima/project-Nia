"""
CheckpointerService — LangGraph conversation checkpoint management.

Extracted from memory_manager.py (Phase 5, Batch 2).
No dependency on MemoryManager or memory system.
"""
import os
import asyncio
import sqlite3
from typing import Optional
from contextlib import asynccontextmanager

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from backend.core.config import settings
from backend.core.logger import logger


class CheckpointerService:
    def __init__(self):
        self._checkpointer: Optional[AsyncSqliteSaver] = None
        self._checkpointer_conn: Optional[aiosqlite.Connection] = None
        self._checkpointer_lock = asyncio.Lock()

    async def init_checkpointer(self) -> None:
        if self._checkpointer is not None:
            return
        async with self._checkpointer_lock:
            if self._checkpointer is not None:
                return
            conn = await aiosqlite.connect(settings.CHECKPOINTER_DB_PATH)
            self._checkpointer_conn = conn
            self._checkpointer = AsyncSqliteSaver(conn)

    @asynccontextmanager
    async def get_async_checkpointer_conn(self):
        # App-scope: keep one connection open for the lifetime of the app
        if self._checkpointer is None:
            await self.init_checkpointer()
        # Guard: if the underlying aiosqlite thread has died, reconnect
        conn = self._checkpointer_conn
        if conn is not None:
            thread = getattr(conn, "_thread", None)
            if thread is not None and not thread.is_alive():
                logger.warning("[CHECKPOINTER] aiosqlite thread died — reconnecting")
                self._checkpointer = None
                self._checkpointer_conn = None
                await self.init_checkpointer()
        yield self._checkpointer

    async def close_checkpointer(self) -> None:
        if self._checkpointer_conn is None:
            return
        try:
            await self._checkpointer_conn.close()
        finally:
            self._checkpointer_conn = None
            self._checkpointer = None

    async def get_all_threads(self):
        return []

    async def delete_thread_state_history(self, thread_id: str):
        return True

    async def cleanup_old_checkpoints(self, retention_days: int | None = None) -> dict:
        """retention_days より古いチェックポイントと writes を削除し VACUUM する。"""
        if retention_days is None:
            retention_days = getattr(settings, "CHECKPOINTER_RETENTION_DAYS", 7)

        import time as _time
        cutoff_ts = _time.time() - retention_days * 86400

        db_path = settings.CHECKPOINTER_DB_PATH
        if not os.path.exists(db_path):
            return {"deleted_checkpoints": 0, "deleted_writes": 0, "freed_mb": 0.0}

        size_before = os.path.getsize(db_path)

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            all_ids = conn.execute(
                "SELECT thread_id, checkpoint_ns, checkpoint_id FROM checkpoints"
            ).fetchall()

            to_delete: list[tuple[str, str, str]] = []
            for row in all_ids:
                ts = self._uuid6_to_unix(row["checkpoint_id"])
                if ts is not None and ts < cutoff_ts:
                    to_delete.append(
                        (row["thread_id"], row["checkpoint_ns"], row["checkpoint_id"])
                    )

            deleted_cp = 0
            deleted_wr = 0
            for tid, ns, cid in to_delete:
                conn.execute(
                    "DELETE FROM checkpoints WHERE thread_id=? AND checkpoint_ns=? AND checkpoint_id=?",
                    (tid, ns, cid),
                )
                deleted_cp += 1
                rc = conn.execute(
                    "DELETE FROM writes WHERE thread_id=? AND checkpoint_ns=? AND checkpoint_id=?",
                    (tid, ns, cid),
                ).rowcount
                deleted_wr += rc

            conn.commit()
            if deleted_cp > 0:
                conn.execute("VACUUM")

            size_after = os.path.getsize(db_path)
            freed_mb = round((size_before - size_after) / (1024 * 1024), 2)

            logger.info(
                "[CHECKPOINTER_CLEANUP] deleted_cp=%d deleted_wr=%d freed=%.1fMB retention=%dd",
                deleted_cp, deleted_wr, freed_mb, retention_days,
            )
            return {
                "deleted_checkpoints": deleted_cp,
                "deleted_writes": deleted_wr,
                "freed_mb": freed_mb,
            }
        finally:
            conn.close()

    @staticmethod
    def _uuid6_to_unix(uuid_str: str) -> float | None:
        """UUID v6 の checkpoint_id から Unix timestamp を抽出する。"""
        try:
            h = uuid_str.replace("-", "")
            time_high = int(h[0:8], 16)
            time_mid = int(h[8:12], 16)
            time_low = int(h[13:16], 16)  # skip version nibble at h[12]
            ticks = (time_high << 28) | (time_mid << 12) | time_low
            return (ticks - 0x01B21DD213814000) / 1e7
        except Exception:
            return None

    async def get_checkpointer_stats(self) -> dict:
        """Diagnostics: checkpointer DB の統計を返す。"""
        db_path = settings.CHECKPOINTER_DB_PATH
        if not os.path.exists(db_path):
            return {"size_mb": 0, "threads": 0, "checkpoints": 0, "retention_days": settings.CHECKPOINTER_RETENTION_DAYS}
        size_mb = round(os.path.getsize(db_path) / (1024 * 1024), 1)
        conn = sqlite3.connect(db_path)
        try:
            cp_count = conn.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0]
            thread_count = conn.execute("SELECT COUNT(DISTINCT thread_id) FROM checkpoints").fetchone()[0]
        finally:
            conn.close()
        return {
            "size_mb": size_mb,
            "threads": thread_count,
            "checkpoints": cp_count,
            "retention_days": settings.CHECKPOINTER_RETENTION_DAYS,
        }


checkpointer_service = CheckpointerService()
