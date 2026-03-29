# backend/controllers/api/manager_router.py
"""
Manager Context API — read-only endpoint for Nero to fetch Nia's context.

Returns identity, semantic memories, reflections, and recent conversations.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from fastapi import APIRouter, Query

from backend.core.config import settings
from backend.core.db import managed_conn

router = APIRouter()
logger = logging.getLogger(__name__)


def _read_identity() -> str:
    """Read identity.md content."""
    path = settings.PROJECT_ROOT / "identity.md"
    try:
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    except Exception:
        logger.warning("[ManagerRouter] Failed to read identity.md", exc_info=True)
    return ""


@router.get("/manager/context")
def get_manager_context(
    thread_id: str = Query("default_thread"),
    memory_limit: int = Query(15, ge=1, le=50),
    reflection_limit: int = Query(7, ge=1, le=30),
    conversation_limit: int = Query(20, ge=1, le=100),
):
    """
    Nero 用コンテキスト取得 API（読み取り専用）。

    GET /api/manager/context?thread_id=default_thread

    Returns identity, semantic memories, recent reflections,
    and recent conversation turns.
    """
    identity = _read_identity()

    with managed_conn() as conn:
        # Semantic memories (confirmed + inferred)
        sem_rows = conn.execute(
            """SELECT content, state_tag, confidence
               FROM semantic_memories
               WHERE thread_id = ? AND status IN ('confirmed', 'inferred')
               ORDER BY confidence DESC, created_at DESC
               LIMIT ?""",
            (thread_id, memory_limit),
        ).fetchall()

        semantic_memories = [
            {
                "content": row["content"],
                "state_tag": row["state_tag"] or "",
                "confidence": row["confidence"],
            }
            for row in sem_rows
        ]

        # Daily reflections (daily_log phase)
        ref_rows = conn.execute(
            """SELECT reflection_date, content_json
               FROM daily_reflections
               WHERE thread_id = ? AND phase = 'daily_log'
               ORDER BY reflection_date DESC
               LIMIT ?""",
            (thread_id, reflection_limit),
        ).fetchall()

        recent_reflections = []
        for row in reversed(ref_rows):
            try:
                data = json.loads(row["content_json"])
            except (ValueError, TypeError):
                continue
            recent_reflections.append({
                "date": row["reflection_date"],
                "summary": data.get("summary", ""),
                "topics": data.get("key_topics", []),
            })

        # Recent conversations (conversation_turn events)
        conv_rows = conn.execute(
            """SELECT payload_json, created_at
               FROM memory_events
               WHERE event_type = 'conversation_turn' AND thread_id = ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (thread_id, conversation_limit),
        ).fetchall()

        recent_conversations = []
        for row in reversed(conv_rows):
            try:
                payload = json.loads(row["payload_json"])
            except (ValueError, TypeError):
                continue
            created_at = row["created_at"]
            try:
                ts_iso = datetime.fromtimestamp(float(created_at)).isoformat()
            except Exception:
                ts_iso = ""
            recent_conversations.append({
                "user": payload.get("user_text", ""),
                "nia": payload.get("ai_response", ""),
                "ts": ts_iso,
            })

        # Telemetry / somatic indicators for Nero
        _SOMATIC_KEYS = (
            "awareness_average", "confidence_variance", "dissonance_streak",
            "topic_shift_count", "contradiction_recent",
        )
        kv_rows = conn.execute(
            "SELECT k, v FROM telemetry_kv WHERE k IN ({})".format(
                ",".join("?" for _ in _SOMATIC_KEYS)
            ),
            _SOMATIC_KEYS,
        ).fetchall()
        telemetry = {row["k"]: row["v"] for row in kv_rows}

        # Recent somatic outcomes (last 10)
        try:
            somatic_rows = conn.execute(
                """SELECT sense_text, outcome, intensity
                   FROM somatic_log
                   WHERE thread_id = ?
                   ORDER BY created_at DESC
                   LIMIT 10""",
                (thread_id,),
            ).fetchall()
            somatic_outcomes = [
                {
                    "sense": row["sense_text"],
                    "outcome": row["outcome"],
                    "intensity": row["intensity"],
                }
                for row in somatic_rows
            ]
        except Exception:
            somatic_outcomes = []

    return {
        "identity": identity,
        "semantic_memories": semantic_memories,
        "recent_reflections": recent_reflections,
        "recent_conversations": recent_conversations,
        "telemetry": telemetry,
        "somatic_outcomes": somatic_outcomes,
    }
