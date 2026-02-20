"""Memory API router — reads from Memory v2 tables (memory_events, semantic_memories)."""
from datetime import datetime
import json
import logging
from fastapi import APIRouter, Query, HTTPException
from backend.core.db import get_conn

router = APIRouter()
logger = logging.getLogger(__name__)


def _payload_of(row: dict) -> dict:
    try:
        obj = json.loads(row.get("payload_json") or "{}")
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


@router.get("/memory/captures")
def list_episodic_events(
    thread_id: str = Query("default_thread"),
    limit: int = Query(50, ge=1, le=200),
):
    """
    UI向け: memory_events (エピソード記憶) を返す。
    """
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT event_id, thread_id, turn_id, message_id,
                   event_type, payload_json, created_at
            FROM memory_events
            WHERE thread_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (thread_id, int(limit)),
        ).fetchall()
    finally:
        conn.close()

    results = []
    for r in rows:
        row = dict(r)
        payload = _payload_of(row)
        created_at = row.get("created_at") or 0
        try:
            ts_iso = datetime.fromtimestamp(float(created_at)).isoformat()
        except Exception:
            ts_iso = ""
        raw_text = (
            payload.get("text")
            or payload.get("summary")
            or payload.get("details")
            or ""
        )
        summary = raw_text.strip().splitlines()[0][:120] if raw_text else ""
        results.append({
            "id": row.get("event_id"),
            "timestamp": ts_iso,
            "thread_id": row.get("thread_id"),
            "summary": summary,
            "details": {
                "raw_text": raw_text,
                "state_tag": payload.get("state_tag"),
                "retention": float(payload.get("retention") or 0.0),
                "stage": row.get("event_type"),
                "stream_id": payload.get("stream_id"),
                "message_id": row.get("message_id"),
                "origin_message_id": payload.get("origin_message_id"),
                "refs": payload.get("refs"),
                "tags": payload.get("tags"),
            },
        })
    return results


@router.get("/memory/long_term")
def list_semantic_memories(
    thread_id: str = Query("default_thread"),
    limit: int = Query(50, ge=1, le=200),
    status: str = Query(None),
):
    """
    UI向け: semantic_memories を返す。
    status フィルタなし → confirmed + inferred を表示。
    """
    # Normalize status (may be Query object in direct calls)
    status_str = status if isinstance(status, str) else None

    conn = get_conn()
    try:
        if status_str:
            rows = conn.execute(
                """
                SELECT id, thread_id, content, status, confidence,
                       state_tag, note, seed_retention, created_at, updated_at,
                       source_turn_ids, source_event_ids, valid_from, valid_to
                FROM semantic_memories
                WHERE thread_id = ? AND status = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (thread_id, status_str, int(limit)),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, thread_id, content, status, confidence,
                       state_tag, note, seed_retention, created_at, updated_at,
                       source_turn_ids, source_event_ids, valid_from, valid_to
                FROM semantic_memories
                WHERE thread_id = ? AND status IN ('confirmed', 'inferred')
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (thread_id, int(limit)),
            ).fetchall()
    finally:
        conn.close()

    results = []
    for r in rows:
        row = dict(r)
        created_at = row.get("created_at") or 0
        try:
            ts_iso = datetime.fromtimestamp(float(created_at)).isoformat()
        except Exception:
            ts_iso = ""
        results.append({
            "id": row.get("id"),
            "summary": (row.get("content") or "").strip().splitlines()[0][:120],
            "details": row.get("content") or "",
            "category": row.get("status") or "inferred",
            "created_at": ts_iso,
            "metadata": {
                "status": row.get("status"),
                "confidence": float(row.get("confidence") or 0.0),
                "state_tag": row.get("state_tag"),
                "note": row.get("note"),
                "seed_retention": float(row.get("seed_retention") or 0.0),
                "thread_id": row.get("thread_id"),
            },
        })
    return results


@router.delete("/memory/captures/{event_id}")
def delete_episodic_event(
    event_id: str,
    thread_id: str = Query("default_thread"),
):
    """
    UI向け: memory_events から1件削除。
    """
    conn = get_conn()
    try:
        cur = conn.execute(
            "DELETE FROM memory_events WHERE event_id = ? AND thread_id = ?",
            (event_id, thread_id),
        )
    finally:
        conn.close()

    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="episodic event not found")
    return {"ok": True, "deleted": event_id}


@router.delete("/memory/long_term/{semantic_id}")
def delete_semantic_memory(
    semantic_id: str,
    thread_id: str = Query("default_thread"),
):
    """
    UI向け: semantic_memories から1件削除。
    """
    conn = get_conn()
    try:
        cur = conn.execute(
            "DELETE FROM semantic_memories WHERE id = ? AND thread_id = ?",
            (semantic_id, thread_id),
        )
    finally:
        conn.close()

    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="semantic memory not found")
    return {"ok": True, "deleted": semantic_id}


@router.get("/memory/integrity")
async def memory_integrity(
    thread_id: str = Query("default_thread"),
):
    """Memory integrity check (v2: event/semantic counts)."""
    conn = get_conn()
    try:
        ev_count = conn.execute(
            "SELECT COUNT(*) FROM memory_events WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()[0]
        sem_count = conn.execute(
            "SELECT COUNT(*) FROM semantic_memories WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()[0]
        wk_count = conn.execute(
            "SELECT COUNT(*) FROM working_items WHERE thread_id = ? AND status = 'open'",
            (thread_id,),
        ).fetchone()[0]
    finally:
        conn.close()

    return {
        "thread_id": thread_id,
        "episodic_events": ev_count,
        "semantic_memories": sem_count,
        "working_items_open": wk_count,
    }
