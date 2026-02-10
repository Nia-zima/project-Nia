from datetime import datetime
import json
import logging
from fastapi import APIRouter, Query, Request, HTTPException
from backend.services.memory_manager import memory_manager
from backend.core.db import get_conn
from backend.core.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)


def _rows_from_event_index(thread_id: str, *, scope: str | None, limit: int) -> list[dict]:
    idx_rows = memory_manager.query_memory_index(
        thread_id=thread_id,
        scope=scope,
        limit=max(int(limit), 1),
    )
    event_ids = [str(r.get("event_id")) for r in idx_rows if r.get("event_id")]
    if not event_ids:
        return []
    event_rows = memory_manager.load_memory_events(event_ids)
    by_id = {str(r.get("event_id")): r for r in event_rows}
    ordered: list[dict] = []
    for idx in idx_rows:
        eid = str(idx.get("event_id") or "")
        ev = by_id.get(eid)
        if ev:
            ordered.append({"index": idx, "event": ev})
    return ordered


def _payload_of(event_row: dict) -> dict:
    try:
        obj = json.loads(event_row.get("payload_json") or "{}")
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}

@router.get("/memory/integrity")
async def memory_integrity(
    request: Request,
    thread_id: str = Query("default_thread"),
    force: int = Query(0)
):
    """
    明示的にメモリ整合性チェックを実行する。
    MEM_DEBUG=1 でのみ実行されるが、force=1かつローカルからなら強制実行可。
    """
    client_host = request.client.host if request.client else "127.0.0.1"
    return await memory_manager.run_integrity_check(
        thread_id=thread_id,
        force=bool(force),
        client_host=client_host
    )

@router.get("/memory/pending")
def list_pending_daily_memories(
    thread_id: str = Query("default_thread"),
    limit: int = Query(50, ge=1, le=200),
):
    """
    UI向け: daily_memories (processed=0) を返す。
    """
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT id, created_at, thread_id, user_input, summary, surprise, importance, grounded
            FROM daily_memories
            WHERE processed = 0 AND thread_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (thread_id, int(limit)),
        ).fetchall()
    finally:
        conn.close()

    results = []
    for r in rows:
        created_at = r["created_at"] or 0
        try:
            ts_iso = datetime.fromtimestamp(int(created_at)).isoformat()
        except Exception:
            ts_iso = ""
        results.append({
            "id": r["id"],
            "timestamp": ts_iso,
            "thread_id": r["thread_id"],
            "summary": r["summary"] or "",
            "details": {
                "user_input": r["user_input"] or "",
                "surprise": float(r["surprise"] or 0.0),
                "importance": float(r["importance"] or 0.0),
                "grounded": bool(r["grounded"]),
            },
            "confidence": float(r["importance"] or 0.0),
        })
    return results


@router.get("/memory/captures")
def list_pending_captures(
    thread_id: str = Query("default_thread"),
    stage: str = Query("capture"),
    limit: int = Query(50, ge=1, le=200),
):
    """
    UI向け: episodic_captures を返す（デフォルトは stage='capture'）。
    """
    # Step5: prefer MemoryService event/index path first.
    # stage='capture' is mapped to generic thought/state events.
    scope = None if stage == "capture" else stage
    rows_event = _rows_from_event_index(thread_id, scope=scope, limit=limit)
    if rows_event:
        results = []
        for row in rows_event:
            ev = row["event"]
            idx = row["index"]
            payload = _payload_of(ev)
            created_at = ev.get("created_at") or 0
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
                "id": ev.get("event_id"),
                "timestamp": ts_iso,
                "thread_id": ev.get("thread_id"),
                "summary": summary,
                "details": {
                    "raw_text": raw_text,
                    "state_tag": payload.get("state_tag"),
                    "retention": float(payload.get("retention") or 0.0),
                    "stage": idx.get("scope"),
                    "stream_id": payload.get("stream_id"),
                    "message_id": ev.get("message_id"),
                    "origin_message_id": payload.get("origin_message_id"),
                    "refs": payload.get("refs"),
                    "tags": payload.get("tags"),
                },
            })
        return results

    logger.info(
        "list_pending_captures: no event-index rows thread_id=%s stage=%s",
        thread_id,
        stage,
    )
    return []


@router.delete("/memory/captures/{capture_id}")
def delete_capture(
    capture_id: str,
    thread_id: str = Query("default_thread"),
):
    """
    UI向け: episodic_captures から1件削除（念のため long_term_memories と vector_sync_queue も削除）。
    """
    if getattr(settings, "LEGACY_MEMORY_READ_ONLY", False):
        raise HTTPException(
            status_code=409,
            detail="legacy memory tables are read-only (LEGACY_MEMORY_READ_ONLY=1)",
        )

    conn = get_conn()
    try:
        cur = conn.execute(
            "DELETE FROM episodic_captures WHERE id = ? AND thread_id = ?",
            (capture_id, thread_id),
        )
        conn.execute(
            "DELETE FROM long_term_memories WHERE capture_id = ? AND thread_id = ?",
            (capture_id, thread_id),
        )
        conn.execute(
            "DELETE FROM vector_sync_queue WHERE capture_id = ? AND thread_id = ?",
            (capture_id, thread_id),
        )
    finally:
        conn.close()

    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="capture not found")

    return {"ok": True, "deleted": capture_id}


@router.delete("/memory/long_term/{capture_id}")
def delete_long_term(
    capture_id: str,
    thread_id: str = Query("default_thread"),
):
    """
    UI向け: long_term_memories の1件削除（関連する capture も削除）。
    """
    if getattr(settings, "LEGACY_MEMORY_READ_ONLY", False):
        raise HTTPException(
            status_code=409,
            detail="legacy memory tables are read-only (LEGACY_MEMORY_READ_ONLY=1)",
        )

    conn = get_conn()
    try:
        cur = conn.execute(
            "DELETE FROM long_term_memories WHERE capture_id = ? AND thread_id = ?",
            (capture_id, thread_id),
        )
        conn.execute(
            "DELETE FROM episodic_captures WHERE id = ? AND thread_id = ?",
            (capture_id, thread_id),
        )
        conn.execute(
            "DELETE FROM vector_sync_queue WHERE capture_id = ? AND thread_id = ?",
            (capture_id, thread_id),
        )
    finally:
        conn.close()

    # vector store cleanup (best-effort)
    try:
        memory_manager.vector_store.delete_by_ids([capture_id], collection_type="episodic")
    except Exception:
        pass

    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="long_term not found")

    return {"ok": True, "deleted": capture_id}

@router.get("/memory/long_term")
def list_long_term_memories(
    thread_id: str = Query("default_thread"),
    limit: int = Query(50, ge=1, le=200),
):
    """
    UI向け: long_term_memories + episodic_captures を返す。
    """
    # Step5: prefer MemoryService event/index path first.
    rows_event = _rows_from_event_index(thread_id, scope="episode", limit=limit)
    if not rows_event:
        rows_event = _rows_from_event_index(thread_id, scope="general", limit=limit)
    if rows_event:
        results = []
        for row in rows_event:
            ev = row["event"]
            idx = row["index"]
            payload = _payload_of(ev)
            created_at = ev.get("created_at") or 0
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
                "id": ev.get("event_id"),
                "summary": summary,
                "details": raw_text,
                "category": idx.get("scope") or "long_term",
                "created_at": ts_iso,
                "metadata": {
                    "state_tag": payload.get("state_tag"),
                    "retention": float(payload.get("retention") or 0.0),
                    "stage": idx.get("scope"),
                    "thread_id": ev.get("thread_id"),
                    "stream_id": payload.get("stream_id"),
                    "message_id": ev.get("message_id"),
                },
            })
        return results

    logger.info(
        "list_long_term_memories: no event-index rows thread_id=%s",
        thread_id,
    )
    return []
