from typing import Any, Dict, Optional, List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
import json
import time

from backend.services.pending_actions_repo import pending_actions_repo
from backend.services.pending_actions_service import (
    enqueue_memory_add,
    hold_pending_action,
    reject_pending_action,
    approve_pending_action,
    archive_pending_action,
)
from backend.core.db import get_conn
from backend.core.agent_graph.graph import workflow
from backend.services.memory_manager import memory_manager
from backend.core.actions import action_registry, action_executor
from dataclasses import replace as dataclass_replace
from backend.services.telemetry_logger import telemetry

router = APIRouter()


class MemoryAddEnqueueRequest(BaseModel):
    thread_id: str
    message_id: str
    payload: Dict[str, Any]
    review_window_id: Optional[str] = None


class ActionReasonRequest(BaseModel):
    reason: Optional[str] = None

class Phase5ActionDecisionRequest(BaseModel):
    thread_id: str
    pending_id: Optional[str] = None
    reason: Optional[str] = None

async def _load_state(thread_id: str):
    async with memory_manager.get_async_checkpointer_conn() as checkpointer:
        app_instance = workflow.compile(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": thread_id}}
        state = await app_instance.aget_state(config)
        values = getattr(state, "values", {}) or {}
        return app_instance, config, values

def _find_pending(
    pending_actions: List[Dict[str, Any]],
    *,
    action_id: str,
    pending_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    if pending_id:
        for item in pending_actions:
            if item.get("pending_id") == pending_id:
                return item
        return None
    for item in pending_actions:
        if item.get("action_id") == action_id:
            return item
    return None


@router.post("/actions/memory_add/enqueue")
async def enqueue_memory_add_action(req: MemoryAddEnqueueRequest) -> Dict[str, Any]:
    result = await enqueue_memory_add(
        req.thread_id,
        req.message_id,
        req.payload,
        review_window_id=req.review_window_id,
    )
    return result


@router.get("/actions/pending")
async def list_pending_actions(
    thread_id: str = Query(...),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None),
) -> Dict[str, Any]:
    statuses = None
    if status:
        statuses = [s.strip().upper() for s in status.split(",") if s.strip()]
    raw_items = pending_actions_repo.get_pending_actions(
        thread_id,
        limit=limit,
        offset=offset,
        statuses=statuses,
    )
    items = []
    for item in raw_items:
        action_type = item.get("action_type")
        kind = "memory_add" if action_type == "memory_add" else "unknown"
        schema_version = None
        try:
            payload = item.get("payload_json") or "{}"
            parsed = json.loads(payload) if isinstance(payload, str) else {}
            schema_version = parsed.get("schema_version")
        except Exception:
            schema_version = None
        item = dict(item)
        item["kind"] = kind
        if schema_version:
            item["schema_version"] = schema_version
        items.append(item)
    pending_count = pending_actions_repo.count_pending_actions(thread_id)
    dissonance_delta = min(0.15, pending_count * 0.01)
    return {
        "items": items,
        "meta": {
            "pending_count": pending_count,
            "dissonance_delta": dissonance_delta,
        },
    }


@router.get("/actions/commit_log/latest")
async def get_latest_commit_log(thread_id: str = Query(...)) -> Dict[str, Any]:
    conn = get_conn()
    try:
        conn.row_factory = None
        row = conn.execute(
            """
            SELECT payload_json, thread_id
            FROM events
            WHERE event_type = 'commit_log' AND thread_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (thread_id,),
        ).fetchone()
        if not row:
            return {"item": None}
        payload_json = row[0]
        try:
            payload = json.loads(payload_json) if payload_json else {}
        except Exception:
            payload = {"line": None}
        return {"item": payload}
    finally:
        conn.close()


@router.post("/actions/{id}/hold")
async def hold_action(id: str, req: ActionReasonRequest) -> Dict[str, Any]:
    ok = await hold_pending_action(id, req.reason)
    if not ok:
        raise HTTPException(status_code=409, detail="state_conflict")
    return {"ok": True}


@router.post("/actions/{id}/reject")
async def reject_action(id: str, req: ActionReasonRequest) -> Dict[str, Any]:
    ok = await reject_pending_action(id, req.reason)
    if not ok:
        raise HTTPException(status_code=409, detail="state_conflict")
    return {"ok": True}


@router.post("/actions/{id}/approve")
async def approve_action(id: str, req: ActionReasonRequest) -> Dict[str, Any]:
    result = await approve_pending_action(id, req.reason)
    if result == "CONFLICT":
        raise HTTPException(status_code=409, detail="state_conflict")
    return {"ok": True, "result": result}

@router.post("/actions/{id}/archive")
async def archive_action(id: str, req: ActionReasonRequest) -> Dict[str, Any]:
    ok = await archive_pending_action(id, req.reason)
    if not ok:
        raise HTTPException(status_code=409, detail="state_conflict")
    return {"ok": True}


# =============================================================================
# Phase 5: Generic Action System Endpoints
# =============================================================================

@router.get("/actions/phase5/pending")
async def list_phase5_pending_actions(thread_id: str = Query(...)) -> Dict[str, Any]:
    _, _, values = await _load_state(thread_id)
    pending = list(values.get("pending_actions") or [])
    return {
        "items": pending,
        "review_token": values.get("review_token"),
        "hold_kind": values.get("hold_kind"),
        "hold_required": bool(values.get("hold_required")),
    }


@router.get("/actions/phase5/results")
async def list_phase5_action_results(thread_id: str = Query(...)) -> Dict[str, Any]:
    _, _, values = await _load_state(thread_id)
    results = list(values.get("action_results") or [])
    return {"items": results}

@router.get("/actions/phase5/results/history")
async def list_phase5_action_results_history(
    thread_id: str = Query(...),
    limit: int = Query(50, ge=1, le=200),
) -> Dict[str, Any]:
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT payload_json
            FROM events
            WHERE event_type = 'phase5_action_result'
              AND thread_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (thread_id, int(limit)),
        ).fetchall()
        items = []
        for row in rows:
            payload_json = row[0]
            try:
                payload = json.loads(payload_json) if payload_json else {}
            except Exception:
                payload = {}
            items.append(payload)
        return {"items": items}
    finally:
        conn.close()


@router.post("/actions/phase5/{action_id}/approve")
async def approve_phase5_action(action_id: str, req: Phase5ActionDecisionRequest) -> Dict[str, Any]:
    app_instance, config, values = await _load_state(req.thread_id)
    pending = list(values.get("pending_actions") or [])
    target = _find_pending(pending, action_id=action_id, pending_id=req.pending_id)
    if not target:
        raise HTTPException(status_code=404, detail="pending_action_not_found")

    payload = target.get("payload") or {}
    action_obj = action_registry.get(action_id)
    if action_obj is None:
        raise HTTPException(status_code=404, detail="action_not_registered")
    action_instance = dataclass_replace(action_obj, payload=payload)

    try:
        result = await action_executor.execute(action_instance)
        action_result = {
            "action_id": action_id,
            "status": "success",
            "result": result,
            "approved_by": "user",
            "ts": time.time(),
        }
    except Exception as e:
        action_result = {
            "action_id": action_id,
            "status": "error",
            "result": {"status": "error", "message": str(e)},
            "approved_by": "user",
            "ts": time.time(),
        }
    await telemetry.event(
        req.thread_id,
        "phase5_action_result",
        {**action_result, "source": "review"},
    )

    target_id = target.get("pending_id")
    updated_pending = [p for p in pending if (p.get("pending_id") != target_id)]
    approved_actions = list(values.get("approved_actions") or [])
    approved_actions.append({
        **{k: v for k, v in target.items() if k != "decision"},
        "status": "APPROVED_BY_USER",
        "approved_at": action_result["ts"],
    })
    action_results = list(values.get("action_results") or [])
    action_results.append(action_result)

    update = {
        "pending_actions": updated_pending,
        "approved_actions": approved_actions,
        "action_results": action_results,
    }
    # phase5_review node is not part of the graph; persist via an existing node.
    await app_instance.aupdate_state(config, update, as_node="action_processing")
    return {"ok": True, "result": action_result}


@router.post("/actions/phase5/{action_id}/reject")
async def reject_phase5_action(action_id: str, req: Phase5ActionDecisionRequest) -> Dict[str, Any]:
    app_instance, config, values = await _load_state(req.thread_id)
    pending = list(values.get("pending_actions") or [])
    target = _find_pending(pending, action_id=action_id, pending_id=req.pending_id)
    if not target:
        raise HTTPException(status_code=404, detail="pending_action_not_found")

    target_id = target.get("pending_id")
    updated_pending = [p for p in pending if (p.get("pending_id") != target_id)]
    rejected_actions = list(values.get("rejected_actions") or [])
    rejected_actions.append({
        **{k: v for k, v in target.items() if k != "decision"},
        "status": "REJECTED_BY_USER",
        "reason": req.reason or "user_rejected",
        "rejected_at": time.time(),
    })
    update = {
        "pending_actions": updated_pending,
        "rejected_actions": rejected_actions,
    }
    # phase5_review node is not part of the graph; persist via an existing node.
    await app_instance.aupdate_state(config, update, as_node="action_processing")
    return {"ok": True}
