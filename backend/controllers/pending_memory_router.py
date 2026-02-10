import json
import logging
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.services.memory_manager import memory_manager
from backend.services.telemetry_logger import telemetry

router = APIRouter(prefix="/api/pending_memories", tags=["Pending Memories"])
logger = logging.getLogger(__name__)

class PendingMemoryItem(BaseModel):
    id: str
    timestamp: str
    thread_id: str
    summary: str
    details: Optional[Dict[str, Any]] = None
    confidence: float

class ReviewRequest(BaseModel):
    event_id: str
    confirm: str # "APPROVE" or "REJECT"
    tags_override: Optional[List[str]] = None
    note: Optional[str] = None

@router.get("", response_model=List[PendingMemoryItem])
def list_pending_memories(limit: int = 50, thread_id: str = "default_thread"):
    """B層の 'memory_pending' イベントを取得（memory_events path only）"""
    try:
        idx_rows = memory_manager.query_memory_index(thread_id=thread_id, limit=max(int(limit) * 10, 100))
        event_ids = [str(r.get("event_id")) for r in idx_rows if r.get("event_id")]
        event_rows = memory_manager.load_memory_events(event_ids)
        by_id = {str(r.get("event_id")): r for r in event_rows}

        pending: dict[str, dict] = {}
        resolved_ids: set[str] = set()
        for eid in event_ids:
            ev = by_id.get(eid)
            if not ev:
                continue
            et = str(ev.get("event_type") or "")
            try:
                payload = json.loads(ev.get("payload_json") or "{}")
                if not isinstance(payload, dict):
                    payload = {}
            except Exception:
                payload = {}
            if et == "memory_pending":
                pending[eid] = ev
            elif et in {"memory_approved", "memory_rejected"}:
                ref = payload.get("ref_event_id")
                if ref is not None:
                    resolved_ids.add(str(ref))

        results: list[dict] = []
        for eid, ev in pending.items():
            if eid in resolved_ids:
                continue
            try:
                payload = json.loads(ev.get("payload_json") or "{}")
                if not isinstance(payload, dict):
                    payload = {}
            except Exception:
                payload = {}
            created_at = float(ev.get("created_at") or 0.0)
            ts = datetime.fromtimestamp(created_at, tz=timezone.utc).isoformat() if created_at > 0 else ""
            results.append({
                "id": eid,
                "timestamp": ts,
                "thread_id": str(ev.get("thread_id") or thread_id),
                "summary": payload.get("summary", "(No Summary)"),
                "details": payload,
                "confidence": float(payload.get("importance") or 0.0),
            })
        if results:
            results.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
            return results[: int(limit)]
    except Exception as e:
        logger.exception("list_pending_memories failed thread_id=%s", thread_id)
        raise HTTPException(status_code=500, detail=f"Internal Error: {str(e)}")
    return []

@router.post("/approve")
async def approve_memory(req: ReviewRequest):
    if req.confirm != "APPROVE":
        raise HTTPException(status_code=400, detail="Confirmation needed (APPROVE)")

    # 1. 元のイベントを取得
    payload = {}
    thread_id = "default_thread"
    found = False

    # New memory_events path first
    try:
        event_rows = memory_manager.load_memory_events([str(req.event_id)])
        if event_rows:
            ev = event_rows[0]
            payload = json.loads(ev.get("payload_json") or "{}")
            if not isinstance(payload, dict):
                payload = {}
            thread_id = str(ev.get("thread_id") or "default_thread")
            found = True
    except Exception:
        found = False

    if not found:
        raise HTTPException(status_code=404, detail="Event not found")
    
    summary = payload.get("summary")
    surprise = payload.get("surprise", 0.0)
    importance = payload.get("importance", 0.0)
    
    # 2. C層へ保存
    await memory_manager.register_thought(
        text=summary,
        surprise=surprise,
        confidence=importance,
        source="manual_approval",
        thread_id=thread_id,
        tags=req.tags_override or ["approved"]
    )
    
    # 3. 承認ログ記録
    await telemetry.event(thread_id, "memory_approved", {
        "ref_event_id": req.event_id,
        "summary": summary,
        "note": req.note
    })
    # New append-only event log (best-effort)
    try:
        memory_manager.append_memory_event(
            thread_id=thread_id,
            event_type="memory_approved",
            payload={
                "ref_event_id": str(req.event_id),
                "summary": summary,
                "note": req.note,
                "scope": "review",
            },
        )
    except Exception:
        pass
    
    return {"ok": True}

@router.post("/reject")
async def reject_memory(req: ReviewRequest):
    if req.confirm != "REJECT":
        raise HTTPException(status_code=400, detail="Confirmation needed (REJECT)")
        
    # 記録だけ残す
    thread_id = "unknown"
    found = False
    try:
        event_rows = memory_manager.load_memory_events([str(req.event_id)])
        if event_rows:
            thread_id = str(event_rows[0].get("thread_id") or "unknown")
            found = True
    except Exception:
        found = False

    if not found:
        raise HTTPException(status_code=404, detail="Event not found")

    await telemetry.event(thread_id, "memory_rejected", {
        "ref_event_id": req.event_id,
        "note": req.note
    })
    # New append-only event log (best-effort)
    try:
        memory_manager.append_memory_event(
            thread_id=thread_id,
            event_type="memory_rejected",
            payload={
                "ref_event_id": str(req.event_id),
                "note": req.note,
                "scope": "review",
            },
        )
    except Exception:
        pass
    
    return {"ok": True}
