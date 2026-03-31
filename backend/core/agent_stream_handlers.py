"""Event handlers for the streaming agent pipeline.

Extracted from agent_stream.py for readability.
All handlers take StreamingContext as their first argument.
"""
import asyncio
import logging
import re
import time
from typing import Any

from backend.core.config import settings
from backend.core.decision_events import build_decision_event_payload
from backend.core.logger import logger
from backend.core.agent_helpers import (
    PONDERING_TAG_RE,
    _extract_emotion_tags,
    _extract_llm_text_from_output,
    _extract_text,
    _sanitize_stream_chunk,
    _split_tts_units,
    _strip_speaker_prefix,
)
from backend.services.speech_sanitizer import SILENCE_DEFAULT, strip_llm_special_tokens
from backend.core.agent_graph.review_window import (
    build_hold_cancelled_event,
    build_hold_request_event,
)

# Re-use the <think> block regex from agent_stream (imported at call site)
_THINK_FULL_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


# ── TTS enqueue helper ───────────────────────────────────────


async def _emit_decision_telemetry(ctx, payload: dict[str, Any]) -> None:
    telemetry_sink = None
    if isinstance(getattr(ctx, "ports", None), dict):
        telemetry_sink = ctx.ports.get("telemetry")
    if telemetry_sink is None:
        return
    try:
        await telemetry_sink.event(getattr(ctx, "thread_id", None), "decision_event", payload)
    except Exception:
        logger.debug("[DECISION_EVENT] telemetry emit failed", exc_info=True)

async def _generate_audio_chained(ctx, text, vid, prev_task, queue, tid):
    """Fire-and-forget TTS generation with dedup."""
    if not text or str(text).strip() == "WAIT":
        return
    norm = " ".join(str(text).split())
    dedupe_key = f"{ctx.stream_id}|{vid}|{norm}"
    if ctx.last_tts_dedupe_key == dedupe_key:
        logger.info("[TTS] dedupe skip")
        return
    ctx.last_tts_dedupe_key = dedupe_key
    logger.info("[TTS] fire-and-forget text_len=%d voice_id=%s", len(norm), str(vid))

    async def _job() -> None:
        try:
            audio_url = await ctx.ports["tts"].generate_audio_url(
                text=text,
                voice_id=str(vid),
                thread_id=str(tid),
                stream_id=str(ctx.stream_id) if ctx.stream_id else None,
            )
            if not audio_url:
                return
            meta = None
            try:
                meta = await ctx.ports["tts"].get_audio_meta(audio_url)
            except Exception:
                meta = None

            payload = dict(meta or {})
            payload.setdefault("url", audio_url)
            payload.setdefault("text_content", text)

            event = {
                "type": "audio",
                "thread_id": str(tid),
                "stream_id": str(ctx.stream_id) if ctx.stream_id else None,
                "message_id": str(ctx.message_id) if ctx.message_id else None,
                "data": payload,
            }
            await queue.put(event)
            logger.info(
                "[TTS] audio ready url=%s duration_ms=%s gen_ms=%s",
                payload.get("url"),
                payload.get("duration_ms"),
                payload.get("gen_ms"),
            )
        except Exception as e:
            logger.exception("TTS job failed: %s", e)
            await queue.put({
                "type": "audio",
                "thread_id": str(tid),
                "stream_id": str(ctx.stream_id) if ctx.stream_id else None,
                "message_id": str(ctx.message_id) if ctx.message_id else None,
                "data": {"error": str(e), "text_content": text},
            })

    await _job()


# ── Text chunk processing ────────────────────────────────────

async def _process_chunk(ctx, text: str, label: str) -> bool:
    """Sanitize, extract emotions, emit text/emotion/gesture events."""
    if ctx.suppress_stream_text:
        logger.debug("[PROCESS_CHUNK_SKIPPED] label=%s reason=suppressed_after_hold", label)
        return False

    sanitized, reason = _sanitize_stream_chunk(
        text,
        has_user_text=ctx.has_user_text,
        input_text=ctx.input_text,
        last_sent_text=ctx.last_sent_text,
        log_label=label,
    )
    if not sanitized:
        logger.debug("[DROP] label=%s stage=sanitize reason=%s", label, reason or "unknown")
        return False

    # Stateful rolling buffer cleaning
    safe_fragment = ctx.stream_san.push(sanitized)
    if not safe_fragment:
        return True  # Neutral skip (waiting for tail)

    if sanitized == SILENCE_DEFAULT and ctx.last_sent_text == SILENCE_DEFAULT:
        return False

    cleaned, tags, gestures = _extract_emotion_tags(safe_fragment)
    if not cleaned:
        return True  # Might be empty after emotion tag removal

    if not ctx.state_started:
        logger.debug("[STATE_EMIT] stream_id=%s tag=%s", ctx.stream_id, "PONDERING")
        await ctx.output_queue.put({"type": "state", "tag": "PONDERING"})
        ctx.state_started = True

    for tag in tags:
        if tag == "consent":
            ctx.consent_seen = True
            ctx.last_state_seen = "CONSENT"
        elif tag == "dissonance":
            ctx.dissonance_seen = True
            ctx.last_state_seen = "DISSONANCE"
        elif tag and tag not in {"pondering"}:
            ctx.emotion_tags_seen.add(tag)
        await ctx.output_queue.put({"type": "emotion", "tag": tag})

    for gesture in gestures:
        await ctx.output_queue.put({"type": "gesture", "tag": gesture})

    await ctx.output_queue.put({"type": "text", "content": cleaned})
    ctx.full_response = str(ctx.full_response) + cleaned
    ctx.last_sent_text = cleaned

    # Voice switching logic
    tail = ctx.full_response[-50:].lower()
    for emo, vid in settings.EMOTION_VOICE_MAP.items():
        if f"[{emo}]" in tail:
            ctx.current_voice_id = str(vid)
            break

    logger.debug("[TTS] chunk enqueue disabled; waiting for final_text")
    return True


# ── Event handlers ───────────────────────────────────────────

async def _handle_merge_end(ctx, data: dict) -> None:
    """Process merge node completion: hold_request, TTS enqueue, final_result emit."""
    output = data.get("output") or {}
    if not ctx.hold_request_sent:
        ev = build_hold_request_event(
            output,
            thread_id=getattr(ctx, "thread_id", None),
            turn_id=getattr(ctx, "turn_id", None),
            message_id=getattr(ctx, "message_id", None),
            stream_id=getattr(ctx, "stream_id", None),
        )
        if ev:
            payload = ev.get("payload") or {}
            token = payload.get("review_token") or ""
            short = token[:8] if isinstance(token, str) else ""
            reasons = payload.get("reason_codes") or []
            preview_text = payload.get("preview_text") or ""
            logger.info(
                "[REVIEW_EV] hold_request sent=1 token=%s merge_mode=%s reasons=%s preview_len=%s",
                short,
                output.get("merge_mode"),
                ",".join(reasons),
                len(preview_text),
            )
            await ctx.output_queue.put(ev)
            await _emit_decision_telemetry(ctx, payload)
            ctx.hold_request_sent = True
    else:
        logger.debug("[REVIEW_EV] hold_request skipped=already_sent")

    # Check for stale events (replay from checkpoint)
    gen_at = float(output.get("generated_at") or 0.0)
    if gen_at > 0:
        age = time.time() - gen_at
        if age > 10.0:
            logger.info(f"[TTS] skipped stale event (age={age:.1f}s)")
            return

    final_text = output.get("final_text")
    is_wait = bool(output.get("is_wait"))
    hold_required = bool(output.get("hold_required"))
    final_text_str = str(final_text or "").strip()

    # Extract gesture/emotion tags from final_text, emit SSE, use clean text for TTS
    if final_text_str and final_text_str != "WAIT":
        cleaned_final, _ftags, _fgestures = _extract_emotion_tags(final_text_str)
        for _gt in _fgestures:
            await ctx.output_queue.put({"type": "gesture", "tag": _gt})
        for _et in _ftags:
            if _et and _et not in {"pondering"}:
                await ctx.output_queue.put({"type": "emotion", "tag": _et})
        final_text_str = cleaned_final.strip() if cleaned_final else final_text_str

    if final_text_str:
        # Safety net: strip residual LLM tokens (ChatML sections etc.)
        final_text_str = strip_llm_special_tokens(final_text_str).strip() or final_text_str
        ctx.merge_final_text = final_text_str

    # Strip draw fences from TTS input (DrawingCard handles visual display)
    # Unified pattern: ```draw and ```draw-intent
    import re
    tts_text = final_text_str or ""
    tts_text = re.sub(r"```draw(?:-intent)?\b[ \t]*\n?[\s\S]*?```", "", tts_text, flags=re.IGNORECASE)
    # Also strip unclosed fence (truncated draw blocks)
    tts_text = re.sub(r"```draw(?:-intent)?\b[ \t]*\n?[\s\S]*$", "", tts_text, flags=re.IGNORECASE)
    tts_text = tts_text.strip()
    ctx.suppress_stream_text = hold_required or is_wait or final_text_str.startswith("WAIT")

    if hold_required:
        logger.info("[TTS] skipped final_text enqueue: hold_required")
    elif is_wait or final_text_str.startswith("WAIT"):
        logger.info("[TTS] skipped final_text enqueue: WAIT")
    elif final_text_str:
        if ctx.current_voice_id:
            if not ctx.tts_enqueued:
                if ctx.stream_id and str(ctx.stream_id) in ctx.tts_enqueued_stream_ids:
                    logger.info("[TTS] skipped final_text enqueue: stream already enqueued")
                    return
                # Use tts_text (draw fences stripped) for speech.
                # If tts_text is empty (draw-only turn), skip TTS entirely.
                _tts_input = tts_text
                if not _tts_input:
                    logger.info("[TTS] skipped final_text enqueue: draw-only (no speech text)")
                    ctx.tts_enqueued = True
                    return
                if bool(getattr(settings, "TTS_SENTENCE_CHUNKING", True)):
                    max_chars = int(getattr(settings, "TTS_SENTENCE_MAX_CHARS", 90) or 90)
                    units = _split_tts_units(_tts_input, max_chars=max_chars)
                else:
                    units = [_tts_input]
                if not units:
                    units = [_tts_input]
                logger.info(
                    "[TTS] enqueue (final_text) text_len=%d units=%d voice_id=%s",
                    len(final_text_str),
                    len(units),
                    str(ctx.current_voice_id),
                )
                for unit in units:
                    task = asyncio.create_task(
                        _generate_audio_chained(
                            ctx, unit, ctx.current_voice_id, ctx.last_tts_task, ctx.output_queue, ctx.thread_id
                        )
                    )
                    ctx.last_tts_task = task
                ctx.tts_enqueued = True
                if ctx.stream_id:
                    ctx.tts_enqueued_stream_ids.add(str(ctx.stream_id))
            else:
                logger.info("[TTS] skipped final_text enqueue: already enqueued")
        else:
            logger.info("[TTS] skipped final_text enqueue: voice_id=off or unset")

    # Emit final_result from merge handler (Phase1 authoritative output).
    if final_text_str and final_text_str != "WAIT" and not ctx.final_result_emitted:
        await ctx.output_queue.put({
            "type": "event",
            "name": "final_result",
            "payload": {
                "final_text": final_text_str,
                "merge_mode": output.get("merge_mode"),
                "is_wait": False,
            },
        })
        ctx.final_result_emitted = True
        logger.info(
            "[FINAL_RESULT] emitted from merge handler len=%d",
            len(final_text_str),
        )


async def _handle_safety_end(ctx, data: dict) -> None:
    """Process safety node completion: emit hold_cancelled if applicable."""
    if not ctx.hold_cancelled_sent:
        output = data.get("output") or {}
        reasons = output.get("reason_codes") or []
        if "system_hold_cancelled_new_input" in reasons:
            ev = build_hold_cancelled_event(
                ctx.prev_review_token,
                thread_id=getattr(ctx, "thread_id", None),
                turn_id=getattr(ctx, "turn_id", None),
                message_id=getattr(ctx, "message_id", None),
                stream_id=getattr(ctx, "stream_id", None),
            )
            if ev:
                short = (ctx.prev_review_token or "")[:8]
                logger.info(
                    "[REVIEW_EV] hold_cancelled sent=1 token=%s reason=new_user_input prev_mode=%s",
                    short,
                    ctx.prev_merge_mode,
                )
                await ctx.output_queue.put(ev)
                await _emit_decision_telemetry(ctx, ev.get("payload") or {})
                ctx.hold_cancelled_sent = True
    else:
        logger.debug("[REVIEW_EV] hold_cancelled skipped=already_sent")


async def _handle_action_end(ctx, data: dict) -> None:
    """Process action_processing node completion: emit action events."""
    output = data.get("output") or {}
    proposed = output.get("proposed_actions") or []
    pending = output.get("pending_actions") or []
    # Use new_rejected_actions (this-turn only) for SSE to avoid replaying
    # historical rejects. Do not fall back when the explicit value is [].
    if "new_rejected_actions" in output:
        rejected = output.get("new_rejected_actions") or []
    else:
        rejected = output.get("rejected_actions") or []
    results = output.get("action_results") or []

    for item in proposed:
        payload = build_decision_event_payload(
            source="phase5",
            entity_kind="action",
            decision="propose",
            status="proposed",
            thread_id=getattr(ctx, "thread_id", None),
            actor="gate",
            turn_id=getattr(ctx, "turn_id", None),
            message_id=getattr(ctx, "message_id", None),
            stream_id=getattr(ctx, "stream_id", None),
            action_id=item.get("action_id"),
            item_kind=str(item.get("kind") or "action"),
            extras={
                "name": item.get("name"),
                "risk_level": item.get("risk_level"),
                "category": item.get("category"),
            },
        )
        await ctx.output_queue.put({"type": "event", "name": "action_proposed", "payload": payload})
        await _emit_decision_telemetry(ctx, payload)

    for item in results:
        result_status = str(item.get("status") or "success")
        is_error = result_status == "error"
        payload = build_decision_event_payload(
            source="phase5",
            entity_kind="action",
            decision="reject" if is_error else "approve",
            status=result_status,
            thread_id=getattr(ctx, "thread_id", None),
            actor="gate",
            turn_id=getattr(ctx, "turn_id", None),
            message_id=getattr(ctx, "message_id", None),
            stream_id=getattr(ctx, "stream_id", None),
            action_id=item.get("action_id"),
            item_kind=str(item.get("kind") or "action"),
            approved_by=item.get("approved_by") or "gate",
            result=item.get("result"),
        )
        event_name = "action_failed" if is_error else "action_approved"
        await ctx.output_queue.put({"type": "event", "name": event_name, "payload": payload})
        await _emit_decision_telemetry(ctx, payload)

    for item in pending:
        payload = build_decision_event_payload(
            source="phase5",
            entity_kind="action",
            decision="hold",
            status="pending_confirmation",
            thread_id=getattr(ctx, "thread_id", None),
            actor="gate",
            turn_id=getattr(ctx, "turn_id", None),
            message_id=getattr(ctx, "message_id", None),
            stream_id=getattr(ctx, "stream_id", None),
            pending_id=item.get("pending_id"),
            action_id=item.get("action_id"),
            item_kind=str(item.get("kind") or "action"),
            reason=(item.get("decision") or {}).get("reason"),
            extras={
                "name": item.get("name"),
                "risk_level": item.get("risk_level"),
                "category": item.get("category"),
                "requires_confirmation": (item.get("decision") or {}).get("requires_confirmation"),
            },
        )
        await ctx.output_queue.put({"type": "event", "name": "action_blocked", "payload": payload})
        await _emit_decision_telemetry(ctx, payload)

    for item in rejected:
        payload = build_decision_event_payload(
            source="phase5",
            entity_kind="action",
            decision="reject",
            status=str(item.get("status") or "rejected"),
            thread_id=getattr(ctx, "thread_id", None),
            actor="gate",
            turn_id=getattr(ctx, "turn_id", None),
            message_id=getattr(ctx, "message_id", None),
            stream_id=getattr(ctx, "stream_id", None),
            pending_id=item.get("pending_id"),
            action_id=item.get("action_id"),
            item_kind=str(item.get("kind") or "action"),
            reason=item.get("reason"),
            extras={
                "name": item.get("name"),
                "risk_level": item.get("risk_level"),
                "category": item.get("category"),
            },
        )
        await ctx.output_queue.put({"type": "event", "name": "action_blocked", "payload": payload})
        await _emit_decision_telemetry(ctx, payload)


async def _handle_stream_chunk(ctx, data: dict) -> None:
    """Process streaming LLM token: dedup, filter <think>, sentence-split, emit."""
    chunk_obj = data.get("chunk")
    chunk = _extract_text(chunk_obj)

    if not chunk:
        return

    ctx.full_raw_parts.append(chunk)
    ctx.sent_any_text = True  # Signal that we received valid stream content

    chunk_raw = chunk
    if ctx.last_chunk is not None:
        if chunk_raw == ctx.last_chunk:
            return
        if chunk_raw.startswith(ctx.last_chunk):
            chunk = chunk_raw[len(ctx.last_chunk):]
        else:
            chunk = chunk_raw
    ctx.last_chunk = chunk_raw

    if not chunk:
        return

    # Strip <think>...</think> blocks from streaming chunks
    chunk = ctx.think_filter.feed(chunk)
    if not chunk:
        return

    ctx.raw_buffer += chunk
    if not ctx.raw_logged and ctx.raw_buffer.strip():
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("[DEBUG_RAW_STREAM] %s", ctx.raw_buffer[:200])
        ctx.raw_logged = True

    if not ctx.is_pondering_sent and PONDERING_TAG_RE.search(ctx.raw_buffer):
        ctx.is_pondering_sent = True
        await ctx.output_queue.put({"type": "thinking", "value": True})

    parts = re.split(r"([。！\n.!？?]+)", ctx.raw_buffer)
    if len(parts) > 1:
        complete_sentences = []
        for i in range(0, len(parts) - 1, 2):
            sentence_raw = (parts[i] + parts[i + 1]).strip()
            if sentence_raw:
                complete_sentences.append(sentence_raw)

        for sentence_raw in complete_sentences:
            sentence_raw = _strip_speaker_prefix(sentence_raw)

            # Skip [PONDERING] only lines (handled by thinking event)
            if PONDERING_TAG_RE.fullmatch(sentence_raw.strip()):
                continue

            ok = await _process_chunk(ctx, sentence_raw, "stream_chunk")
            if ok:
                ctx.sent_any_text = True
            else:
                logger.debug("[PROCESS_CHUNK_DROPPED] label=%s", "stream_chunk")

        ctx.raw_buffer = parts[-1]


async def _handle_llm_end(ctx, data: dict, et: str, nm: str) -> None:
    """Process LLM/chain end event: flush buffer, extract final text."""
    out = data.get("output")

    # stream で完全文が作れなかった場合の残りを flush
    if ctx.raw_buffer.strip() and not ctx.sent_any_text:
        tail = _strip_speaker_prefix(ctx.raw_buffer.strip())
        if tail and not PONDERING_TAG_RE.fullmatch(tail):
            ok = await _process_chunk(ctx, tail, "stream_flush_end")
            if ok:
                ctx.sent_any_text = True
            else:
                logger.info("[PROCESS_CHUNK_DROPPED] label=%s preview=%r", "stream_flush_end", tail[:120])
        ctx.raw_buffer = ""

    if ctx.sent_any_text:
        return

    # Phase1: only accept LangGraph terminal output here
    if et == "on_chain_end":
        name = nm or ""
        if name != "LangGraph":
            return

        cand = data.get("output") or {}
        final_text = None
        if isinstance(cand, dict):
            if "final_text" in cand:
                final_text = cand.get("final_text")
            elif isinstance(cand.get("merge"), dict):
                final_text = cand["merge"].get("final_text")

        if final_text:
            ctx.final_text_override = str(final_text)
            sentence_raw = _strip_speaker_prefix(str(final_text))
            if await _process_chunk(ctx, sentence_raw, "final_text"):
                ctx.sent_any_text = True
        return

    # LLM-only fallback (non-graph)
    cand = data.get("output") or data.get("outputs") or data.get("result") or data.get("response")
    text = _extract_llm_text_from_output(cand)

    if text:
        # Strip <think>...</think> blocks from fallback text
        text = _THINK_FULL_RE.sub("", text).strip()
        if not text:
            return
        ctx.full_raw_parts.append(text)
        # For fallback, treat as single chunk
        sentence_raw = _strip_speaker_prefix(text)
        if await _process_chunk(ctx, sentence_raw, "fallback_end"):
            ctx.sent_any_text = True
