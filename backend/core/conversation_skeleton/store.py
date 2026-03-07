"""SkeletonCore DB 保存・取得.

fire-and-forget パターン: 失敗してもリクエストをブロックしない。
"""

from __future__ import annotations

import time
import uuid

from backend.core.db import managed_conn
from backend.core.logger import logger

from .schema import (
    ConversationSkeleton,
    Focus,
    QuestionIntent,
    ResponseIntent,
)


def save_skeleton(
    *,
    turn_id: str,
    session_id: str,
    skeleton: ConversationSkeleton,
) -> str | None:
    """conversation_skeletons テーブルに保存。row_id or None を返す。"""
    try:
        row_id = uuid.uuid4().hex
        now = time.time()
        with managed_conn() as conn:
            conn.execute(
                """INSERT INTO conversation_skeletons
                   (id, turn_id, session_id, focus, response_intent,
                    question_intent, source, confidence, rule_trace, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    row_id,
                    turn_id,
                    session_id,
                    skeleton.focus.value,
                    skeleton.response_intent.value,
                    skeleton.question_intent.value if skeleton.question_intent else None,
                    skeleton.source,
                    skeleton.confidence,
                    ",".join(skeleton.rule_trace),
                    now,
                ),
            )
        return row_id
    except Exception:
        logger.warning("[SKELETON] save failed", exc_info=True)
        return None


def get_recent_skeletons(
    session_id: str,
    *,
    limit: int = 3,
) -> list[ConversationSkeleton]:
    """直近 N 件の skeleton を取得（oldest-first で返す）。"""
    try:
        with managed_conn() as conn:
            rows = conn.execute(
                """SELECT focus, response_intent, question_intent,
                          source, confidence, rule_trace
                   FROM conversation_skeletons
                   WHERE session_id = ?
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (session_id, limit),
            ).fetchall()
        result: list[ConversationSkeleton] = []
        for row in reversed(rows):  # oldest first
            qi = QuestionIntent(row[2]) if row[2] else None
            result.append(
                ConversationSkeleton(
                    focus=Focus(row[0]),
                    response_intent=ResponseIntent(row[1]),
                    question_intent=qi,
                    source=row[3] or "nia_internal",
                    confidence=row[4] or 0.5,
                    rule_trace=(row[5] or "").split(",") if row[5] else [],
                )
            )
        return result
    except Exception:
        logger.debug("[SKELETON] load recent failed", exc_info=True)
        return []
