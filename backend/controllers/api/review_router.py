from typing import Optional
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.core.agent_graph.state_normalizer import normalize_checkpoint_state
from backend.core.agent_graph.graph import workflow
from backend.core.agent_graph.nodes import s5_commit
from backend.core.agent_graph.review_window import (
    apply_review_decision,
    build_hold_approved_event,
    build_hold_rejected_event,
    get_review_token,
)
from backend.core.decision_events import build_decision_event_payload
from backend.core.logger import logger
from backend.services.telemetry_logger import telemetry
from backend.services.checkpointer import checkpointer_service

router = APIRouter()


class ReviewDecisionRequest(BaseModel):
    thread_id: str = Field(..., min_length=1, max_length=256)
    token: Optional[str] = Field(None, max_length=128)
    review_token: Optional[str] = Field(None, max_length=128)


def _hold_from_merge(merge_mode: Optional[str]) -> str:
    if not merge_mode:
        return "auto"
    if isinstance(merge_mode, str) and merge_mode.startswith("review:"):
        return "ask"
    if merge_mode in {"block", "clarify"}:
        return "block"
    return "auto"


def _checkpoint_join_fields(values: dict | None, *, thread_id: str) -> dict[str, str | None]:
    payload = dict(values or {})
    return {
        "thread_id": thread_id,
        "turn_id": str(payload.get("turn_id") or "") or None,
        "message_id": str(payload.get("message_id") or "") or None,
        "stream_id": str(payload.get("stream_id") or "") or None,
    }


async def _apply_review(thread_id: str, token: str, decision: str) -> dict:
    async with checkpointer_service.get_async_checkpointer_conn() as checkpointer:
        app_instance = workflow.compile(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": thread_id}}

        async def _emit_decision_event_raw(
            *,
            decision_name: str,
            status: str,
            actor: str,
            refs: dict[str, str | None],
            reason: str | None = None,
            reason_codes: list | None = None,
            review_token: str | None = None,
        ) -> None:
            """Emit a decision_event for router-specific edge cases (token_mismatch)."""
            payload = build_decision_event_payload(
                source="review_window",
                entity_kind="say",
                decision=decision_name,
                status=status,
                thread_id=thread_id,
                actor=actor,
                turn_id=refs.get("turn_id"),
                message_id=refs.get("message_id"),
                stream_id=refs.get("stream_id"),
                review_token=review_token,
                item_kind="say",
                reason=reason,
                reason_codes=reason_codes,
            )
            await telemetry.event(thread_id, "decision_event", payload)

        async def _token_mismatch_response(current_values: dict) -> dict:
            short = (token or "")[:8]
            logger.debug(
                "[REVIEW_API] token_mismatch action=%s thread=%s token=%s",
                decision,
                thread_id,
                short,
            )
            before_d = current_values.get("dissonance") or 0.0
            hold = _hold_from_merge(current_values.get("merge_mode"))
            refs = _checkpoint_join_fields(current_values, thread_id=thread_id)
            payload = build_commit_log_payload(
                say_applied=0,
                rejected=0,
                before_d=before_d,
                after_d=before_d,
                hold=hold,
                reasons=["system_review_token_mismatch"],
                decision="token_mismatch",
                actor="system",
                review_token=token,
                thread_id=refs.get("thread_id"),
                turn_id=refs.get("turn_id"),
                message_id=refs.get("message_id"),
                stream_id=refs.get("stream_id"),
            )
            await emit_commit_log(thread_id, payload, telemetry_sink=telemetry)
            await _emit_decision_event_raw(
                decision_name="token_mismatch",
                status="ignored",
                actor="system",
                refs=refs,
                reason="token_mismatch",
                reason_codes=["system_review_token_mismatch"],
                review_token=token,
            )
            return {"ok": True, "applied": False, "reason": "token_mismatch"}

        state = await app_instance.aget_state(config)
        values = normalize_checkpoint_state(getattr(state, "values", {}) or {})
        expected = get_review_token(values)
        if not expected or expected != token:
            return await _token_mismatch_response(values)

        # Re-read just before apply to avoid stale-approve races with hold cancel.
        latest_state = await app_instance.aget_state(config)
        latest_values = normalize_checkpoint_state(getattr(latest_state, "values", {}) or {})
        latest_expected = get_review_token(latest_values)
        if not latest_expected or latest_expected != token:
            return await _token_mismatch_response(latest_values)

        update = apply_review_decision(latest_values, token=token, decision=decision)
        if not update:
            return {"ok": True, "applied": False, "reason": None}
        # Graph has no dedicated "review" node; use an existing node name for checkpoint updates.
        await app_instance.aupdate_state(config, update, as_node="merge")
        if decision == "approve":
            merged_state = dict(latest_values)
            merged_state.update(update)
            merged_state["thread_id"] = thread_id
            commit_update = await s5_commit(merged_state)
            if commit_update.get("commit_result") is not None:
                await app_instance.aupdate_state(config, commit_update, as_node="s5_commit")
        before_d = latest_values.get("dissonance") or 0.0
        after_d = update.get("dissonance", before_d)
        before_merge = latest_values.get("merge_mode") or "none"
        reasons = update.get("reason_codes") or []
        refs = _checkpoint_join_fields(latest_values, thread_id=thread_id)
        payload = build_commit_log_payload(
            say_applied=1 if decision == "approve" else 0,
            rejected=1 if decision == "reject" else 0,
            before_d=before_d,
            after_d=after_d,
            hold=_hold_from_merge(before_merge),
            reasons=reasons,
            decision=decision,
            actor="user",
            review_token=token,
            thread_id=refs.get("thread_id"),
            turn_id=refs.get("turn_id"),
            message_id=refs.get("message_id"),
            stream_id=refs.get("stream_id"),
        )
        await emit_commit_log(thread_id, payload, telemetry_sink=telemetry)
        # Decision event via review_window builders
        if decision == "approve":
            event = build_hold_approved_event(
                token,
                text=update.get("final_text"),
                thread_id=refs.get("thread_id"),
                turn_id=refs.get("turn_id"),
                message_id=refs.get("message_id"),
                stream_id=refs.get("stream_id"),
                reason_codes=reasons,
            )
        else:
            event = build_hold_rejected_event(
                token,
                text=update.get("final_text"),
                thread_id=refs.get("thread_id"),
                turn_id=refs.get("turn_id"),
                message_id=refs.get("message_id"),
                stream_id=refs.get("stream_id"),
                reason_codes=reasons,
            )
        if event:
            await telemetry.event(thread_id, "decision_event", event["payload"])
        return {"ok": True, "applied": True, "reason": None}


def _fmt_d(value: float) -> str:
    return f"{value:.2f}"


def build_commit_log_line(
    *,
    say_applied: int,
    rejected: int,
    before_d: float,
    after_d: float,
    hold: str,
    reasons: list,
) -> str:
    reason_str = ",".join([str(r) for r in reasons if r])
    return (
        f"[COMMIT] say:{int(bool(say_applied))} rejected:{int(bool(rejected))} "
        f"D:{_fmt_d(before_d)}->{_fmt_d(after_d)} "
        f"hold:{hold} reasons:{reason_str}"
    )


def build_commit_log_payload(
    *,
    say_applied: int,
    rejected: int,
    before_d: float,
    after_d: float,
    hold: str,
    reasons: list,
    decision: str | None = None,
    actor: str | None = None,
    review_token: str | None = None,
    thread_id: str | None = None,
    turn_id: str | None = None,
    message_id: str | None = None,
    stream_id: str | None = None,
    ts: float | None = None,
) -> dict:
    line = build_commit_log_line(
        say_applied=say_applied,
        rejected=rejected,
        before_d=before_d,
        after_d=after_d,
        hold=hold,
        reasons=reasons,
    )
    return {
        "schema_version": "commit_log.v2",
        "line": line,
        "say_applied": int(bool(say_applied)),
        "rejected": int(bool(rejected)),
        "before_d": float(before_d),
        "after_d": float(after_d),
        "hold": hold,
        "reason_codes": [str(reason) for reason in reasons if reason],
        "decision": decision,
        "actor": actor,
        "review_token": review_token,
        "thread_id": thread_id,
        "turn_id": turn_id,
        "message_id": message_id,
        "stream_id": stream_id,
        "ts": float(ts if ts is not None else time.time()),
    }


async def emit_commit_log(thread_id: str, payload: dict | str, *, telemetry_sink=telemetry) -> None:
    normalized = {"line": payload} if isinstance(payload, str) else dict(payload)
    await telemetry_sink.event(thread_id, "commit_log", normalized)


@router.post("/review/approve")
async def review_approve(req: ReviewDecisionRequest) -> dict:
    token = req.token or req.review_token
    if not token:
        raise HTTPException(status_code=400, detail="token_missing")
    result = await _apply_review(req.thread_id, token, "approve")
    if not result.get("applied") and result.get("reason") == "token_mismatch":
        raise HTTPException(status_code=409, detail="token_mismatch")
    return result


@router.post("/review/reject")
async def review_reject(req: ReviewDecisionRequest) -> dict:
    token = req.token or req.review_token
    if not token:
        raise HTTPException(status_code=400, detail="token_missing")
    result = await _apply_review(req.thread_id, token, "reject")
    if not result.get("applied") and result.get("reason") == "token_mismatch":
        raise HTTPException(status_code=409, detail="token_mismatch")
    return result
