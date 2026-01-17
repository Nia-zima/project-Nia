from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import json
import sqlite3
import traceback

from backend.services.memory_manager import memory_manager
from backend.services.telemetry_logger import telemetry
from backend.core.config import settings
from backend.core.db import get_conn

router = APIRouter(prefix="/api/pending_memories", tags=["Pending Memories"])

class PendingMemoryItem(BaseModel):
    id: int # event table id
    timestamp: str
    thread_id: str
    summary: str
    details: Optional[Dict[str, Any]] = None
    confidence: float

class ReviewRequest(BaseModel):
    event_id: int
    confirm: str # "APPROVE" or "REJECT"
    tags_override: Optional[List[str]] = None
    note: Optional[str] = None

@router.get("", response_model=List[PendingMemoryItem])
def list_pending_memories(limit: int = 50):
    """B層の 'memory_pending' イベントを取得"""
    conn = get_conn()
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Exclude already approved or rejected memories
        cursor.execute("""
            SELECT id, ts as timestamp, thread_id, payload_json 
            FROM events 
            WHERE event_type = 'memory_pending' 
            AND id NOT IN (
                SELECT CAST(json_extract(payload_json, '$.ref_event_id') AS INTEGER)
                FROM events 
                WHERE event_type IN ('memory_approved', 'memory_rejected')
                AND json_extract(payload_json, '$.ref_event_id') IS NOT NULL
            )
            ORDER BY id DESC 
            LIMIT ?
        """, (limit,))

        
        rows = cursor.fetchall()
        results = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
                results.append({
                    "id": row["id"],
                    "timestamp": row["timestamp"],
                    "thread_id": row["thread_id"],
                    "summary": payload.get("summary", "(No Summary)"),
                    "details": payload,
                    "confidence": payload.get("importance", 0.0)
                })
            except:
                continue
        return results
    except Exception as e:
        print("ERROR in list_pending_memories:")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Internal Error: {str(e)}")
    finally:
        if conn:
            conn.close()

@router.post("/approve")
async def approve_memory(req: ReviewRequest):
    if req.confirm != "APPROVE":
        raise HTTPException(status_code=400, detail="Confirmation needed (APPROVE)")

    # 1. 元のイベントを取得
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT payload_json, thread_id FROM events WHERE id = ?", (req.event_id,))
        row = cursor.fetchone()
    finally:
        conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="Event not found")
        
    payload = json.loads(row[0])
    thread_id = row[1]
    
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
    
    return {"ok": True}

@router.post("/reject")
async def reject_memory(req: ReviewRequest):
    if req.confirm != "REJECT":
        raise HTTPException(status_code=400, detail="Confirmation needed (REJECT)")
        
    # 記録だけ残す
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT thread_id FROM events WHERE id = ?", (req.event_id,))
        row = cursor.fetchone()
    finally:
        conn.close()
    
    thread_id = row[0] if row else "unknown"

    await telemetry.event(thread_id, "memory_rejected", {
        "ref_event_id": req.event_id,
        "note": req.note
    })
    
    return {"ok": True}
