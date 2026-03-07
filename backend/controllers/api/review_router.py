from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from backend.core.agent_graph.graph import workflow
from backend.core.agent_graph.nodes import s5_commit
from backend.core.agent_graph.review_window import apply_review_decision, get_review_token
from backend.core.logger import logger
from backend.services.telemetry_logger import telemetry
from backend.services.checkpointer import checkpointer_service

router = APIRouter()


class ReviewDecisionRequest(BaseModel):
    thread_id: str
    token: Optional[str] = None
    review_token: Optional[str] = None


def _hold_from_merge(merge_mode: Optional[str]) -> str:
    if not merge_mode:
        return "auto"
    if isinstance(merge_mode, str) and merge_mode.startswith("review:"):
        return "ask"
    if merge_mode in {"block", "clarify"}:
        return "block"
    return "auto"


async def _apply_review(thread_id: str, token: str, decision: str) -> dict:
    async with checkpointer_service.get_async_checkpointer_conn() as checkpointer:
        app_instance = workflow.compile(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": thread_id}}

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
            line = build_commit_log_line(
                say_applied=0,
                rejected=0,
                before_d=before_d,
                after_d=before_d,
                hold=hold,
                reasons=["system_review_token_mismatch"],
            )
            await emit_commit_log(thread_id, line, telemetry_sink=telemetry)
            return {"ok": True, "applied": False, "reason": "token_mismatch"}

        state = await app_instance.aget_state(config)
        values = getattr(state, "values", {}) or {}
        expected = get_review_token(values)
        if not expected or expected != token:
            return await _token_mismatch_response(values)

        # Re-read just before apply to avoid stale-approve races with hold cancel.
        latest_state = await app_instance.aget_state(config)
        latest_values = getattr(latest_state, "values", {}) or {}
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
        line = build_commit_log_line(
            say_applied=1 if decision == "approve" else 0,
            rejected=1 if decision == "reject" else 0,
            before_d=before_d,
            after_d=after_d,
            hold=_hold_from_merge(before_merge),
            reasons=reasons,
        )
        await emit_commit_log(thread_id, line, telemetry_sink=telemetry)
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


async def emit_commit_log(thread_id: str, line: str, *, telemetry_sink=telemetry) -> None:
    await telemetry_sink.event(thread_id, "commit_log", {"line": line})


@router.post("/review/approve")
async def review_approve(req: ReviewDecisionRequest) -> dict:
    token = req.token or req.review_token
    if not token:
        return {"ok": True, "applied": False, "reason": "token_missing"}
    return await _apply_review(req.thread_id, token, "approve")


@router.post("/review/reject")
async def review_reject(req: ReviewDecisionRequest) -> dict:
    token = req.token or req.review_token
    if not token:
        return {"ok": True, "applied": False, "reason": "token_missing"}
    return await _apply_review(req.thread_id, token, "reject")
