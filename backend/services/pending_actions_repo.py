# backend/services/pending_actions_repo.py
from __future__ import annotations

import time
import sqlite3
from typing import Any, Dict, Optional, List

from backend.core.db import managed_conn
from backend.core.logger import logger


class PendingActionsRepo:
    def insert_pending_action(
        self,
        *,
        id: str,
        thread_id: str,
        message_id: str,
        action_type: str,
        payload_json: str,
        status: str,
        dedupe_key: str,
        created_at: Optional[float] = None,
        updated_at: Optional[float] = None,
        reason: Optional[str] = None,
        review_window_id: Optional[str] = None,
    ) -> str:
        created_at = float(created_at) if created_at is not None else time.time()
        updated_at = float(updated_at) if updated_at is not None else created_at
        with managed_conn() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO pending_actions (
                        id, thread_id, message_id, action_type, payload_json,
                        status, reason, review_window_id, dedupe_key,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        id,
                        thread_id,
                        message_id,
                        action_type,
                        payload_json,
                        status,
                        reason,
                        review_window_id,
                        dedupe_key,
                        created_at,
                        updated_at,
                    ),
                )
                return id
            except sqlite3.IntegrityError:
                logger.warning("[PendingActionsRepo] insert conflict dedupe_key=%s", dedupe_key)
                raise
            except Exception as e:
                logger.error("[PendingActionsRepo] insert failed: %s", e)
                raise

    def get_pending_actions(
        self,
        thread_id: str,
        *,
        limit: int = 200,
        offset: int = 0,
        statuses: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        with managed_conn() as conn:
            try:
                use_statuses = statuses or ["PENDING", "HELD"]
                if not use_statuses:
                    return []
                placeholders = ",".join(["?"] * len(use_statuses))
                rows = conn.execute(
                    f"""
                    SELECT *
                    FROM pending_actions
                    WHERE thread_id = ?
                      AND status IN ({placeholders})
                    ORDER BY created_at ASC
                    LIMIT ? OFFSET ?
                    """,
                    (thread_id, *use_statuses, int(limit), int(offset)),
                ).fetchall()
                return [dict(row) for row in rows]
            except Exception:
                logger.exception("[PendingActionsRepo] get_pending_actions failed")
                return []

    def count_pending_actions(self, thread_id: str) -> int:
        with managed_conn() as conn:
            try:
                row = conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM pending_actions
                    WHERE thread_id = ?
                      AND status IN ('PENDING','HELD')
                    """,
                    (thread_id,),
                ).fetchone()
                return int(row[0]) if row else 0
            except Exception:
                logger.exception("[PendingActionsRepo] count_pending_actions failed")
                return 0

    def try_update_status(
        self,
        *,
        id: str,
        next_status: str,
        reason: Optional[str],
        now: float,
    ) -> bool:
        with managed_conn() as conn:
            try:
                cur = conn.execute(
                    """
                    UPDATE pending_actions
                    SET status = ?, reason = ?, updated_at = ?
                    WHERE id = ?
                      AND status IN ('PENDING','HELD')
                    """,
                    (next_status, reason, float(now), id),
                )
                return cur.rowcount > 0
            except Exception:
                logger.exception("[PendingActionsRepo] try_update_status failed id=%s", id)
                return False

    def try_update_status_from(
        self,
        *,
        id: str,
        from_status: str,
        to_status: str,
        reason: Optional[str],
        now: float,
    ) -> bool:
        with managed_conn() as conn:
            try:
                cur = conn.execute(
                    """
                    UPDATE pending_actions
                    SET status = ?, reason = ?, updated_at = ?
                    WHERE id = ?
                      AND status = ?
                    """,
                    (to_status, reason, float(now), id, from_status),
                )
                return cur.rowcount > 0
            except Exception:
                logger.exception("[PendingActionsRepo] try_update_status_from failed id=%s", id)
                return False

    def try_update_status_in(
        self,
        *,
        id: str,
        from_statuses: List[str],
        to_status: str,
        reason: Optional[str],
        now: float,
    ) -> bool:
        if not from_statuses:
            return False
        with managed_conn() as conn:
            try:
                placeholders = ",".join(["?"] * len(from_statuses))
                cur = conn.execute(
                    f"""
                    UPDATE pending_actions
                    SET status = ?, reason = ?, updated_at = ?
                    WHERE id = ?
                      AND status IN ({placeholders})
                    """,
                    (to_status, reason, float(now), id, *from_statuses),
                )
                return cur.rowcount > 0
            except Exception:
                logger.exception("[PendingActionsRepo] try_update_status_in failed id=%s", id)
                return False

    def get_by_id(self, id: str) -> Optional[Dict[str, Any]]:
        with managed_conn() as conn:
            try:
                row = conn.execute(
                    "SELECT * FROM pending_actions WHERE id = ?",
                    (id,),
                ).fetchone()
                return dict(row) if row else None
            except Exception:
                logger.exception("[PendingActionsRepo] get_by_id failed id=%s", id)
                return None

    def get_by_dedupe_key(self, dedupe_key: str) -> Optional[Dict[str, Any]]:
        with managed_conn() as conn:
            try:
                row = conn.execute(
                    "SELECT * FROM pending_actions WHERE dedupe_key = ?",
                    (dedupe_key,),
                ).fetchone()
                return dict(row) if row else None
            except Exception:
                logger.exception("[PendingActionsRepo] get_by_dedupe_key failed key=%s", dedupe_key)
                return None


pending_actions_repo = PendingActionsRepo()
