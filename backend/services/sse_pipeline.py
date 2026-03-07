"""SSE streaming helpers and event handlers for agent_orchestrator.

Extracted from agent_orchestrator.py to keep the orchestrator class focused
on coordination.  All functions are stateless with respect to the orchestrator
— they receive an ``SSEContext`` (mutable state bag) and an ``orchestrator``
reference where telemetry calls are needed.
"""

from __future__ import annotations

import json
import time
import logging
import asyncio
from dataclasses import dataclass
from typing import Any, Dict

from backend.core.logger import logger
from backend.core.model_adapter import THINK_RE as _THINK_RE
from backend.core.constants.nia_spine_v10 import NIA_SPINE_V10_VERSION
from backend.services.lint_output import (
    lint_output,
    semantic_lint_output,
    rewrite_output_if_needed,
    build_output_lint_log,
)
from backend.services.speech_sanitizer import (
    finalize_output,
    detect_internal_leak,
    is_critical_leak,
    TAG_LINE_RE,
    INTERNAL_PLAN_LINE_RE,
    _looks_like_plan_line,
)

SSE_DEBUG_EVERY = int(__import__("os").getenv("SSE_DEBUG_EVERY", "50"))


# ── Utility functions ─────────────────────────────────────────

def _ms() -> int:
    return int(time.time() * 1000)


def _ensure_str(chunk: Any) -> str:
    if isinstance(chunk, (bytes, bytearray)):
        return chunk.decode("utf-8", errors="ignore")
    return str(chunk)


def _sse_json(obj: Dict[str, Any]) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _should_emit_text_event(ev: Dict[str, Any]) -> bool:
    # final=True means definitive text, final=False means suppress.
    # Missing final is treated as normal streaming text.
    return ev.get("final") is not False


# ── SSE streaming context ────────────────────────────────────

@dataclass
class SSEContext:
    """Mutable state bag for a single stream_sse() invocation."""
    thread_id: str
    stream_id: str | None
    sse_min_interval_ms: int
    t0: int  # start timestamp for telemetry
    done_sent: bool = False
    done_pending: bool = False
    current_turn_id: int | None = None
    visible_ai_text: str = ""
    final_text: str | None = None
    stream_error: str | None = None
    stream_buffer: str = ""
    first_token_sent: bool = False
    last_event: dict | None = None
    last_event_type: str | None = None
    last_raw_content_type: str | None = None
    last_state_tag: str | None = None
    text_seq: int = 0
    output_lint_logged: bool = False
    lint_message_id: str | None = None
    last_text_emit_ms: int = 0


# ── SSE helpers ───────────────────────────────────────────────

def _sse_emit(event: dict, stream_id: str | None) -> str:
    if stream_id:
        event = dict(event)
        event["stream_id"] = stream_id
    return _sse_json(event)


async def _sse_text_append(sctx: SSEContext, part: str) -> str:
    """Append text to visible_ai_text and return SSE string."""
    if not part:
        return ""
    safe_part = str(part)
    sctx.visible_ai_text = str(sctx.visible_ai_text) + safe_part
    if sctx.sse_min_interval_ms > 0:
        now = _ms()
        wait_ms = sctx.sse_min_interval_ms - (now - sctx.last_text_emit_ms)
        if wait_ms > 0:
            await asyncio.sleep(wait_ms / 1000)
        sctx.last_text_emit_ms = _ms()
    return _sse_emit({"type": "text", "content": safe_part}, sctx.stream_id)


def _looks_like_broken_output(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    if "LLMResult" in t or "generations" in t:
        return True
    if "内部でエラーが発生しました" in t:
        return True
    if t.startswith("- ") and "Acknowledge" in t:
        return True
    if "\n- " in t and "Acknowledge" in t:
        return True
    return False


async def _apply_output_lint(text: str) -> tuple[str, list, list, list, bool]:
    """Run regex + semantic lint on output text."""
    violations = lint_output(text, evidence=None)
    rewritten = text
    rewrite_applied = False
    post_violations = []
    if any(v.severity == "hard" for v in violations):
        rewritten = await rewrite_output_if_needed(text, violations)
        rewrite_applied = rewritten != text
        if rewrite_applied:
            post_violations = lint_output(rewritten, evidence=None)
    semantic_violations = await semantic_lint_output(rewritten)
    return rewritten, violations, post_violations, semantic_violations, rewrite_applied


async def _sse_emit_lint_log(
    sctx: SSEContext,
    orchestrator,
    *,
    violations: list,
    post_violations: list,
    semantic_violations: list,
    rewrite_applied: bool,
    text_len_before: int,
    text_len_after: int,
) -> None:
    """Emit output lint telemetry event (once per stream)."""
    if sctx.output_lint_logged:
        return
    payload = build_output_lint_log(
        violations=violations,
        post_violations=post_violations,
        semantic_violations=semantic_violations,
        rewrite_applied=rewrite_applied,
        text_len_before=text_len_before,
        text_len_after=text_len_after,
        message_id=sctx.lint_message_id,
        thread_id=sctx.thread_id,
        turn_id=sctx.current_turn_id,
    )
    payload["spine_version"] = NIA_SPINE_V10_VERSION
    payload["spine_anchor_used"] = {
        "depth0": True,
        "rewrite": rewrite_applied,
        "gate": False,
    }
    d_lint = payload.get("dissonance_delta_lint") or 0.0
    if isinstance(d_lint, (int, float)) and d_lint > 0:
        await orchestrator._telemetry_event(
            sctx.thread_id,
            "telemetry_kv_add",
            {"key": f"dissonance_lint_total:{sctx.thread_id}", "delta": float(d_lint)},
        )
    await orchestrator._telemetry_event(sctx.thread_id, "commit_log", payload)
    sctx.output_lint_logged = True


# ── SSE event handlers ───────────────────────────────────────


async def _handle_sse_text(sctx: SSEContext, ev: dict, orchestrator) -> list[str]:
    """Handle text event: buffer, leak-detect, emit SSE strings."""
    results: list[str] = []

    if not _should_emit_text_event(ev):
        return results

    raw_content = ev.get("content", "")
    chunk_content = "" if raw_content is None else str(raw_content)
    # Safety net: strip residual <think>...</think> blocks
    if "<think>" in chunk_content:
        chunk_content = _THINK_RE.sub("", chunk_content).strip()
        if not chunk_content:
            return results
    sctx.last_raw_content_type = type(raw_content).__name__

    if chunk_content:
        sctx.text_seq += 1
        if logger.isEnabledFor(logging.DEBUG):
            if sctx.text_seq == 1 or (SSE_DEBUG_EVERY > 0 and sctx.text_seq % SSE_DEBUG_EVERY == 0):
                logger.debug(
                    "[DEBUG_SSE_TEXT] seq=%s stream_id=%s len=%s head=%s",
                    sctx.text_seq,
                    sctx.stream_id,
                    len(chunk_content),
                    chunk_content[:80],
                )

    if (not sctx.first_token_sent) and chunk_content:
        sctx.first_token_sent = True
        await orchestrator._telemetry_event(sctx.thread_id, "stream_first_token", {
            "ms_from_start": _ms() - sctx.t0
        })

    sctx.stream_buffer = str(sctx.stream_buffer) + chunk_content

    while "\n" in sctx.stream_buffer:
        line, sctx.stream_buffer = sctx.stream_buffer.split("\n", 1)
        stripped = line.strip()

        if stripped and TAG_LINE_RE.fullmatch(stripped):
            results.append(_sse_emit({"type": "internal", "content": stripped}, sctx.stream_id))
            continue
        if stripped and _looks_like_plan_line(stripped):
            # Drop leaked planner bullets from stream output
            continue

        if line:
            leak_reasons = detect_internal_leak(line)
            if is_critical_leak(leak_reasons):
                sctx.stream_error = "safety_block"
                await orchestrator._telemetry_event(sctx.thread_id, "safety_block", {
                    "scope": "stream_chat",
                    "reasons": leak_reasons,
                })
            else:
                res = await _sse_text_append(sctx, line + "\n")
                if res:
                    results.append(res)
        else:
            res = await _sse_text_append(sctx, "\n")
            if res:
                results.append(res)

    if sctx.stream_buffer and not sctx.stream_buffer.lstrip().startswith("[["):
        # Drop leaked planner bullets even if no newline arrived.
        sb_stripped = sctx.stream_buffer.lstrip()
        if _looks_like_plan_line(sb_stripped):
            cleaned = INTERNAL_PLAN_LINE_RE.sub("", sb_stripped, count=1).lstrip()
            sctx.stream_buffer = cleaned
            if not sctx.stream_buffer:
                return results
        leak_reasons = detect_internal_leak(sctx.stream_buffer)
        if is_critical_leak(leak_reasons):
            sctx.stream_error = "safety_block"
            await orchestrator._telemetry_event(sctx.thread_id, "safety_block", {
                "scope": "stream_chat",
                "reasons": leak_reasons,
            })
        else:
            res = await _sse_text_append(sctx, sctx.stream_buffer)
            if res:
                results.append(res)
        sctx.stream_buffer = ""

    return results


async def _handle_sse_done(sctx: SSEContext, ev: dict, orchestrator) -> list[str]:
    """Handle done event: flush buffer, lint, emit done SSE."""
    results: list[str] = []
    sctx.done_pending = True

    # --- Emit remaining text immediately (no LLM lint) ---
    _lint_target: str | None = None
    if sctx.final_text:
        _fast_violations = lint_output(sctx.final_text, evidence=None)
        _fast_linted = sctx.final_text
        if any(v.severity == "hard" for v in _fast_violations):
            _fast_linted = await rewrite_output_if_needed(sctx.final_text, _fast_violations)
        res = await _sse_text_append(sctx, _fast_linted)
        if res:
            results.append(res)
        _lint_target = _fast_linted

    if sctx.stream_buffer:
        tail = sctx.stream_buffer
        sctx.stream_buffer = ""
        stripped = tail.strip()
        if stripped and TAG_LINE_RE.fullmatch(stripped):
            results.append(_sse_emit({"type": "internal", "content": stripped}, sctx.stream_id))
        elif stripped and _looks_like_plan_line(stripped):
            pass
        else:
            leak_reasons = detect_internal_leak(tail)
            if is_critical_leak(leak_reasons):
                sctx.stream_error = "safety_block"
                await orchestrator._telemetry_event(sctx.thread_id, "safety_block", {
                    "scope": "stream_chat",
                    "reasons": leak_reasons,
                })
            else:
                res = await _sse_text_append(sctx, tail)
                if res:
                    results.append(res)
                if not _lint_target:
                    _lint_target = tail

    # Yield done immediately so frontend can clear loading state
    results.append(_sse_emit(ev, sctx.stream_id))
    sctx.done_sent = True

    # Fire-and-forget: semantic lint in background (non-blocking)
    if _lint_target:
        async def _bg_lint(text: str) -> None:
            try:
                _linted, _v, _pv, _sv, _rw = await _apply_output_lint(text)
                await _sse_emit_lint_log(
                    sctx, orchestrator,
                    violations=_v,
                    post_violations=_pv,
                    semantic_violations=_sv,
                    rewrite_applied=_rw,
                    text_len_before=len(text),
                    text_len_after=len(_linted),
                )
            except Exception:
                logger.debug("[BG_LINT] failed", exc_info=True)
        asyncio.create_task(_bg_lint(_lint_target))

    return results


async def _persist_stream_result(sctx: SSEContext, orchestrator) -> None:
    """Finally block: persist assistant message and emit telemetry."""
    try:
        from backend.services.chat_history_store import chat_history_store

        _raw_save = (sctx.final_text or sctx.visible_ai_text or "").strip()
        text_to_save = finalize_output(_raw_save) if _raw_save else ""
        done_for_log = sctx.done_sent or sctx.done_pending
        if sctx.current_turn_id is not None and text_to_save and not _looks_like_broken_output(text_to_save):
            await chat_history_store.append_message(
                thread_id=sctx.thread_id,
                turn_id=sctx.current_turn_id,
                role="assistant",
                content={
                    "text": text_to_save,
                    "meta": {
                        "incomplete": not done_for_log,
                        "error": bool(sctx.stream_error)
                    }
                },
                attachments=[]
            )

            if done_for_log:
                await orchestrator._telemetry_event(sctx.thread_id, "chat_completed", {
                    "len": len(text_to_save),
                    "ms": _ms() - sctx.t0
                })
                # Phase R.1: Update last_message_at for idle detection
                try:
                    from backend.core.db import managed_conn as _managed_conn
                    with _managed_conn() as _rconn:
                        _rconn.execute(
                            "INSERT OR REPLACE INTO telemetry_kv (k, v, updated_at) VALUES ('last_message_at', ?, ?)",
                            (str(time.time()), int(time.time())),
                        )
                except Exception:
                    pass
    except Exception as log_err:
        logger.warning(f"A-layer assistant log failed: {log_err}")
