from typing import Any, Dict, Optional, List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
import json
import logging
import time

logger = logging.getLogger(__name__)

from backend.services.pending_actions_repo import pending_actions_repo
from backend.services.pending_actions_service import (
    enqueue_memory_add,
    hold_pending_action,
    reject_pending_action,
    approve_pending_action,
    archive_pending_action,
)
from backend.core.agent_graph.state_normalizer import normalize_checkpoint_state
from backend.core.agent_graph.review_window import get_review_token
from backend.core.decision_events import build_decision_event_payload
from backend.core.db import managed_conn
from backend.core.agent_graph.graph import workflow
from backend.services.checkpointer import checkpointer_service
from backend.core.actions import action_registry, action_executor
from dataclasses import replace as dataclass_replace
from backend.services.telemetry_logger import telemetry
from backend.services.x_post_service import XPostError, x_post_service

router = APIRouter()


class MemoryAddEnqueueRequest(BaseModel):
    thread_id: str = Field(..., min_length=1, max_length=256)
    message_id: str = Field(..., min_length=1, max_length=256)
    payload: Dict[str, Any]
    review_window_id: Optional[str] = Field(None, max_length=128)


class ActionReasonRequest(BaseModel):
    reason: Optional[str] = Field(None, max_length=1000)

class Phase5ActionDecisionRequest(BaseModel):
    thread_id: str = Field(..., min_length=1, max_length=256)
    pending_id: Optional[str] = Field(None, max_length=128)
    reason: Optional[str] = Field(None, max_length=1000)

async def _load_state(thread_id: str):
    async with checkpointer_service.get_async_checkpointer_conn() as checkpointer:
        app_instance = workflow.compile(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": thread_id}}
        state = await app_instance.aget_state(config)
        values = normalize_checkpoint_state(getattr(state, "values", {}) or {})
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
        except (json.JSONDecodeError, TypeError):
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
    with managed_conn() as conn:
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
        payload_json = row["payload_json"]
        try:
            payload = json.loads(payload_json) if payload_json else {}
        except (json.JSONDecodeError, TypeError):
            payload = {"line": None}
        return {"item": payload}


@router.post("/actions/pending/{id}/hold")
async def hold_action(id: str, req: ActionReasonRequest) -> Dict[str, Any]:
    ok = await hold_pending_action(id, req.reason)
    if not ok:
        raise HTTPException(status_code=409, detail="state_conflict")
    return {"ok": True}


@router.post("/actions/pending/{id}/reject")
async def reject_action(id: str, req: ActionReasonRequest) -> Dict[str, Any]:
    ok = await reject_pending_action(id, req.reason)
    if not ok:
        raise HTTPException(status_code=409, detail="state_conflict")
    return {"ok": True}


@router.post("/actions/pending/{id}/approve")
async def approve_action(id: str, req: ActionReasonRequest) -> Dict[str, Any]:
    result = await approve_pending_action(id, req.reason)
    if result == "CONFLICT":
        raise HTTPException(status_code=409, detail="state_conflict")
    return {"ok": True, "result": result}

@router.post("/actions/pending/{id}/archive")
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
    review_token = get_review_token(values)
    review_actions: List[Dict[str, Any]] = []
    if review_token:
        review_actions = list(values.get("review_pending_actions") or [])
    pending = list(values.get("pending_actions") or [])
    if review_token:
        review_actions = [
            {
                **item,
                "review_token": item.get("review_token") or review_token,
            }
            for item in review_actions
            if isinstance(item, dict)
        ]
    return {
        "items": review_actions + pending,
        "review_token": review_token,
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
    with managed_conn() as conn:
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
            except (json.JSONDecodeError, TypeError):
                payload = {}
            items.append(payload)
        return {"items": items}


@router.post("/actions/phase5/{action_id}/approve")
async def approve_phase5_action(action_id: str, req: Phase5ActionDecisionRequest) -> Dict[str, Any]:
    app_instance, config, values = await _load_state(req.thread_id)
    pending = list(values.get("pending_actions") or [])
    target = _find_pending(pending, action_id=action_id, pending_id=req.pending_id)
    if not target:
        raise HTTPException(status_code=404, detail="pending_action_not_found")

    payload = dict(target.get("payload") or {})
    payload.setdefault("thread_id", req.thread_id)
    payload.setdefault("turn_id", target.get("turn_id"))
    payload.setdefault("message_id", target.get("message_id"))
    payload.setdefault("stream_id", target.get("stream_id"))
    if req.pending_id:
        payload.setdefault("_pending_id", req.pending_id)
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
    await telemetry.event(
        req.thread_id,
        "decision_event",
        build_decision_event_payload(
            source="phase5",
            entity_kind="action",
            decision="approve",
            status=action_result["status"],
            thread_id=req.thread_id,
            actor="user",
            turn_id=target.get("turn_id"),
            message_id=target.get("message_id"),
            stream_id=target.get("stream_id"),
            pending_id=target.get("pending_id"),
            action_id=action_id,
            item_kind=str(target.get("kind") or "action"),
            reason=req.reason,
            approved_by="user",
            result=action_result.get("result"),
            ts=action_result["ts"],
            extras={
                "name": target.get("name"),
                "risk_level": target.get("risk_level"),
                "category": target.get("category"),
            },
        ),
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
    await telemetry.event(
        req.thread_id,
        "decision_event",
        build_decision_event_payload(
            source="phase5",
            entity_kind="action",
            decision="reject",
            status="rejected_by_user",
            thread_id=req.thread_id,
            actor="user",
            turn_id=target.get("turn_id"),
            message_id=target.get("message_id"),
            stream_id=target.get("stream_id"),
            pending_id=target.get("pending_id"),
            action_id=action_id,
            item_kind=str(target.get("kind") or "action"),
            reason=req.reason or "user_rejected",
            extras={
                "name": target.get("name"),
                "risk_level": target.get("risk_level"),
                "category": target.get("category"),
            },
        ),
    )
    return {"ok": True}


# =============================================================================
# Twitter (X) Tweet Proposals (from Reflection Engine)
# =============================================================================

class TweetProposalDecisionRequest(BaseModel):
    proposal_id: str = Field(..., min_length=1, max_length=128)
    reason: Optional[str] = Field(None, max_length=1000)


class ManualTweetRequest(BaseModel):
    style: str = Field("casual", pattern=r"^(casual|diary)$")
    task: str = Field("", pattern=r"^(self_introduction|reaction|announcement|)$")
    context: str = Field("", max_length=1000)
    thread_id: str = Field("default_thread", min_length=1, max_length=256)


@router.get("/actions/tweet/pending")
async def get_pending_tweet(
    thread_id: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
) -> Dict[str, Any]:
    """Get pending X post proposals."""
    items = x_post_service.list_pending_proposals(limit=limit, thread_id=thread_id)
    return {"items": items, "proposal": items[0] if items else None}


@router.post("/actions/tweet/approve")
async def approve_tweet(req: TweetProposalDecisionRequest) -> Dict[str, Any]:
    """Approve and publish a stored X post proposal."""
    try:
        result = await x_post_service.approve_proposal(proposal_id=req.proposal_id, actor="user")
    except XPostError as exc:
        raise HTTPException(status_code=409, detail=exc.code) from exc

    proposal = result.get("proposal") or {}
    await telemetry.event(
        proposal.get("thread_id"),
        "decision_event",
        build_decision_event_payload(
            source="x_post",
            entity_kind="tweet_proposal",
            decision="approve",
            status="posted" if result.get("success") else "failed",
            thread_id=proposal.get("thread_id"),
            actor="user",
            turn_id=proposal.get("turn_id"),
            message_id=proposal.get("message_id"),
            stream_id=proposal.get("stream_id"),
            pending_id=req.proposal_id,
            item_kind="tweet_proposal",
            reason=req.reason,
            result={
                "success": bool(result.get("success")),
                "tweet_id": result.get("tweet_id"),
                "error": result.get("error"),
            },
            extras={
                "proposal_id": req.proposal_id,
                "tweet_source": proposal.get("source"),
            },
        ),
    )
    if not result.get("success"):
        raise HTTPException(status_code=409, detail=result.get("error") or "tweet_publish_failed")
    return {"ok": True, "tweet_id": result.get("tweet_id"), "proposal": proposal}


@router.post("/actions/tweet/reject")
async def reject_tweet(req: TweetProposalDecisionRequest) -> Dict[str, Any]:
    """Reject a stored X post proposal."""
    try:
        proposal = await x_post_service.reject_proposal(
            proposal_id=req.proposal_id,
            actor="user",
            reason=req.reason,
        )
    except XPostError as exc:
        raise HTTPException(status_code=409, detail=exc.code) from exc

    await telemetry.event(
        proposal.get("thread_id"),
        "decision_event",
        build_decision_event_payload(
            source="x_post",
            entity_kind="tweet_proposal",
            decision="reject",
            status="rejected",
            thread_id=proposal.get("thread_id"),
            actor="user",
            turn_id=proposal.get("turn_id"),
            message_id=proposal.get("message_id"),
            stream_id=proposal.get("stream_id"),
            pending_id=req.proposal_id,
            item_kind="tweet_proposal",
            reason=req.reason,
            extras={
                "proposal_id": req.proposal_id,
                "tweet_source": proposal.get("source"),
            },
        ),
    )
    return {"ok": True, "proposal": proposal}


@router.post("/actions/tweet/generate")
async def generate_tweet_manual(req: ManualTweetRequest) -> Dict[str, Any]:
    """Manually generate a tweet and store it as an approval proposal."""
    try:
        proposal = await x_post_service.generate_manual_proposal(
            thread_id=req.thread_id,
            style=req.style,
            task=req.task,
            context=req.context,
        )
    except XPostError as exc:
        status_code = 503 if exc.code == "twitter_disabled" else 400
        raise HTTPException(status_code=status_code, detail=exc.code) from exc
    return {"proposal": proposal, "tweet_text": proposal.get("tweet_text"), "char_count": len(proposal.get("tweet_text") or "")}


@router.get("/actions/tweet/history")
async def get_tweet_history(limit: int = Query(20, ge=1, le=100)) -> Dict[str, Any]:
    """Get recently posted tweets."""
    return {"items": x_post_service.get_recent_posts(limit=limit)}


# ── Diary ────────────────────────────────────────────────────

@router.get("/diary/recent")
async def get_recent_diaries(limit: int = Query(7, ge=1, le=30)) -> List[Dict[str, Any]]:
    """Get recent diary entries from Sleep Cycle."""
    with managed_conn() as conn:
        rows = conn.execute(
            """SELECT reflection_date, content_json, created_at
               FROM daily_reflections
               WHERE phase = 'diary' AND thread_id = 'default_thread'
               ORDER BY reflection_date DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [
        {
            "date": r["reflection_date"],
            "content": json.loads(r["content_json"]),
            "created_at": r["created_at"],
        }
        for r in rows
    ]
