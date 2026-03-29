from __future__ import annotations

import json
from typing import Any, Optional

from backend.core.db import managed_conn
from backend.core.logger import logger

_CAPTURE_EVENT_TYPES = ("capture_recorded", "legacy_capture_imported")


def _coerce_json_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        try:
            decoded = json.loads(raw)
        except Exception:
            return []
        if isinstance(decoded, list):
            return decoded
    return []


def _coerce_json_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return {}
        try:
            decoded = json.loads(raw)
        except Exception:
            return {}
        if isinstance(decoded, dict):
            return decoded
    return {}


def build_capture_recorded_payload(payload: dict[str, Any]) -> dict[str, Any]:
    stage = str(payload.get("stage") or "capture")
    return {
        "legacy_capture_id": payload.get("id"),
        "raw_text": str(payload.get("raw_text") or ""),
        "state_tag": payload.get("state_tag"),
        "emotion_tags": _coerce_json_list(payload.get("emotion_tags")),
        "stream_id": payload.get("stream_id"),
        "origin_message_id": payload.get("origin_message_id"),
        "surprise": float(payload.get("surprise") or 0.0),
        "keywords": _coerce_json_list(payload.get("keywords")),
        "entities": _coerce_json_list(payload.get("entities")),
        "tags": _coerce_json_list(payload.get("tags")),
        "refs": _coerce_json_dict(payload.get("refs")),
        "retention": float(payload.get("retention") or 0.0),
        "stage": stage,
        "scope": stage,
        "text_hash": payload.get("text_hash"),
    }


def find_existing_capture_event_id(
    *,
    thread_id: str,
    text_hash: Optional[str] = None,
    message_id: Optional[str] = None,
) -> Optional[str]:
    if not thread_id:
        return None
    if not text_hash and not message_id:
        return None

    with managed_conn() as conn:
        if text_hash:
            try:
                row = conn.execute(
                    """
                    SELECT event_id
                    FROM memory_events
                    WHERE thread_id = ?
                      AND event_type IN (?, ?)
                      AND json_extract(payload_json, '$.text_hash') = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (thread_id, *_CAPTURE_EVENT_TYPES, text_hash),
                ).fetchone()
                if row:
                    return str(row["event_id"])
            except Exception:
                logger.debug("[CaptureEvent] json_extract lookup failed", exc_info=True)

        if message_id:
            row = conn.execute(
                """
                SELECT event_id
                FROM memory_events
                WHERE thread_id = ?
                  AND event_type IN (?, ?)
                  AND message_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (thread_id, *_CAPTURE_EVENT_TYPES, message_id),
            ).fetchone()
            if row:
                return str(row["event_id"])

        if not text_hash:
            return None

        rows = conn.execute(
            """
            SELECT event_id, payload_json
            FROM memory_events
            WHERE thread_id = ?
              AND event_type IN (?, ?)
            ORDER BY created_at DESC
            LIMIT 2000
            """,
            (thread_id, *_CAPTURE_EVENT_TYPES),
        ).fetchall()

    for row in rows:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except Exception:
            continue
        if isinstance(payload, dict) and str(payload.get("text_hash") or "") == text_hash:
            return str(row["event_id"])
    return None
