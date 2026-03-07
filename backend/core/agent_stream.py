"""Streaming agent execution pipeline.

Contains run_agent_stream() and its helper functions.
Extracted from agent.py for readability.
Phase 7 refactored: StreamingContext dataclass + extracted handlers.
"""
import re
import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from langchain_core.messages import HumanMessage

from backend.core.agent_graph.state import AgentState
from backend.core.agent_graph.review_window import (
    build_hold_cancelled_event,
    build_hold_request_event,
    get_review_token,
)
from backend.core.agent_graph.graph import workflow
from backend.core.agent_graph.utils import _log_task_exception
from backend.core.config import settings
from backend.core.logger import logger
from backend.services.speech_sanitizer import (
    SILENCE_DEFAULT,
    detect_internal_leak,
    finalize_output,
    is_critical_leak,
    strip_llm_special_tokens,
    StreamSanitizer,
)

from backend.core.agent_helpers import (
    PONDERING_TAG_RE,
    _build_user_content,
    _current_voice_id,
    _extract_emotion_tags,
    _extract_keywords_from_user,
    _extract_llm_text_from_output,
    _extract_text,
    _final_state_from_text,
    _resolve_voice_id,
    _sanitize_stream_chunk,
    _split_tts_units,
    _strip_hearing_ack,
    _strip_speaker_prefix,
)
from backend.core.agent_stream_handlers import (
    _generate_audio_chained,
    _handle_action_end,
    _handle_llm_end,
    _handle_merge_end,
    _handle_safety_end,
    _handle_stream_chunk,
    _process_chunk,
)


# ── <think> block filter for streaming ──────────────────────
_THINK_FULL_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


class ThinkBlockFilter:
    """Stateful filter that strips <think>...</think> blocks from streamed text.

    Accumulates text while inside a <think> block and drops it on </think>.
    Text outside <think> blocks passes through immediately.
    """

    def __init__(self) -> None:
        self._inside = False
        self._buf = ""

    def feed(self, text: str) -> str:
        """Feed a chunk and return the portion outside any <think> block."""
        if not text:
            return ""

        result: list[str] = []
        i = 0
        combined = self._buf + text if self._buf else text
        self._buf = ""

        while i < len(combined):
            if self._inside:
                end = combined.find("</think>", i)
                if end == -1:
                    # Still inside, buffer everything
                    self._buf = combined[i:]
                    self._inside = True
                    break
                # Skip past </think> and any trailing whitespace
                end += len("</think>")
                while end < len(combined) and combined[end] in (" ", "\t", "\r", "\n"):
                    end += 1
                i = end
                self._inside = False
            else:
                start = combined.find("<think>", i)
                if start == -1:
                    # Check if buffer ends with a partial "<think" prefix
                    tail = combined[i:]
                    for plen in range(min(6, len(tail)), 0, -1):
                        if "<think>"[:plen] == tail[-plen:]:
                            result.append(tail[:-plen])
                            self._buf = tail[-plen:]
                            break
                    else:
                        result.append(tail)
                    break
                result.append(combined[i:start])
                i = start + len("<think>")
                self._inside = True

        return "".join(result)

    def flush(self) -> str:
        """Flush any remaining buffer (e.g. partial <think that never closed)."""
        buf = self._buf
        self._buf = ""
        self._inside = False
        return buf


# ── Streaming context: replaces 27+ nonlocal variables ──────
@dataclass
class StreamingContext:
    """Mutable state bag for a single run_agent_stream() invocation."""

    # Identifiers
    thread_id: str
    stream_id: str | None
    message_id: str | None
    input_text: str
    has_user_text: bool
    mode: str

    # Port references (immutable for the stream's lifetime)
    ports: dict
    output_queue: asyncio.Queue

    # Voice
    voice_id: str
    current_voice_id: str

    # Streaming accumulators
    last_chunk: str = ""
    raw_buffer: str = ""
    full_response: str = ""
    full_raw_parts: list = field(default_factory=list)
    last_sent_text: str = ""
    raw_logged: bool = False
    sent_any_text: bool = False

    # Text processing tools
    think_filter: ThinkBlockFilter = field(default_factory=ThinkBlockFilter)
    stream_san: StreamSanitizer | None = None

    # Semantic state
    consent_seen: bool = False
    dissonance_seen: bool = False
    emotion_tags_seen: set = field(default_factory=set)
    last_state_seen: str | None = None

    # Control flags
    is_pondering_sent: bool = False
    state_started: bool = False
    suppress_stream_text: bool = False
    final_result_emitted: bool = False

    # Merge / review
    final_text_override: str = ""
    merge_final_text: str = ""
    hold_request_sent: bool = False
    hold_cancelled_sent: bool = False
    prev_review_token: str | None = None
    prev_merge_mode: str | None = None

    # TTS
    tts_enqueued: bool = False
    tts_enqueued_stream_ids: set = field(default_factory=set)
    last_tts_task: asyncio.Task | None = None
    last_tts_dedupe_key: str | None = None


# ── Stream lifecycle: finalize + cleanup ─────────────────────


async def _finalize_stream(
    ctx: StreamingContext,
    app_instance,
    config: dict,
    analyze_and_save_memory,
    memory_refs: dict | None,
) -> None:
    """Post-event-loop finalization: flush buffer, TTS wait, memory capture, final_result."""
    # Flush remaining buffer
    if ctx.raw_buffer.strip():
        sentence_raw = _strip_speaker_prefix(ctx.raw_buffer.strip())
        await _process_chunk(ctx, sentence_raw, "trailing_chunk")

    # Wait for TTS finalization
    if ctx.last_tts_task:
        try:
            await asyncio.wait_for(
                ctx.last_tts_task,
                timeout=float(settings.TTS_FINALIZE_TIMEOUT_SEC),
            )
        except asyncio.TimeoutError:
            logger.warning("[TTS] Finalize timeout; finishing stream without waiting for audio.")
        except Exception:
            pass

    # Memory capture & final_result emit
    if ctx.full_response:
        leak_reasons = detect_internal_leak(ctx.full_response)
        if is_critical_leak(leak_reasons):
            logger.warning(
                "[CAPTURE_SKIP] reason=critical_leak leak_reasons=%s",
                ";".join(
                    list(leak_reasons.get("critical", []))
                    + list(leak_reasons.get("warn", []))
                ) if leak_reasons else "unknown",
            )
            ctx.full_response = ""
        else:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("[DEBUG_RAW_STREAM_FINAL] %s", ctx.full_response[:200])

            # High-precision finalization using full raw buffer
            full_raw = "".join(ctx.full_raw_parts)
            ultimate_response = ctx.merge_final_text or finalize_output(full_raw)

            ultimate_response = _strip_hearing_ack(ultimate_response, ctx.input_text)
            final_state = ctx.last_state_seen or ("CONSENT" if ctx.consent_seen else ("DISSONANCE" if ctx.dissonance_seen else None))
            if final_state is None:
                final_state = _final_state_from_text(ultimate_response)

            # Emit final_result once (Phase1: single-shot authoritative output)
            try:
                state = await app_instance.aget_state(config)
                values = getattr(state, "values", {}) or {}
                merge_mode = values.get("merge_mode")
                is_wait = (ultimate_response.strip() == "WAIT")
                await ctx.output_queue.put({
                    "type": "event",
                    "name": "final_result",
                    "payload": {
                        "final_text": ultimate_response,
                        "merge_mode": merge_mode,
                        "is_wait": is_wait,
                        "dissonance": values.get("dissonance"),
                        "dissonance_on": values.get("dissonance_on"),
                        "need_depth1": values.get("need_depth1"),
                    }
                })
                ctx.final_result_emitted = True
            except Exception:
                logger.debug("[FINAL_RESULT] failed to attach", exc_info=True)

            # Attach thinking_hint event only when WAIT
            try:
                if ultimate_response.strip() == "WAIT":
                    state = await app_instance.aget_state(config)
                    values = getattr(state, "values", {}) or {}
                    thinking_hint = {
                        "dissonance": values.get("dissonance"),
                        "dissonance_on": values.get("dissonance_on"),
                        "merge_mode": values.get("merge_mode"),
                        "reason_codes": values.get("reason_codes") or [],
                        "extracted_keywords": _extract_keywords_from_user(ctx.input_text),
                    }
                    await ctx.output_queue.put({"type": "event", "name": "thinking_hint", "payload": thinking_hint})
            except Exception:
                logger.debug("[THINKING_HINT] failed to attach", exc_info=True)

            if final_state:
                if final_state == "CONSENT":
                    ctx.consent_seen = True
                elif final_state == "DISSONANCE":
                    ctx.dissonance_seen = True
                logger.info("[STATE_EMIT] stream_id=%s tag=%s", ctx.stream_id, final_state)
                await ctx.output_queue.put({"type": "state", "tag": final_state})
            if ultimate_response.strip() != "WAIT":
                if getattr(settings, "ORCHESTRATOR_S5_ENABLED", False):
                    logger.info("[CAPTURE_SKIP] reason=s5_handles_episodic")
                else:
                    t = asyncio.create_task(
                        analyze_and_save_memory(
                            ctx.input_text,
                            ultimate_response,
                            ctx.thread_id,
                            consent_seen=ctx.consent_seen,
                            dissonance_seen=ctx.dissonance_seen,
                            emotion_tags=list(ctx.emotion_tags_seen),
                            final_state_tag=final_state,
                            refs=memory_refs,
                            ports=ctx.ports,
                        )
                    )
                    t.add_done_callback(_log_task_exception)
            else:
                logger.info("[CAPTURE_SKIP] reason=wait_final_text")
    else:
        logger.info(
            "[CAPTURE_SKIP] reason=empty_full_response sent_any_text=%s final_text_override=%s raw_buffer_len=%s",
            ctx.sent_any_text,
            bool(ctx.final_text_override),
            len(ctx.raw_buffer or ""),
        )

    # Safety blocked: emit safety_text to frontend
    if not ctx.final_result_emitted:
        try:
            state = await app_instance.aget_state(config)
            values = getattr(state, "values", {}) or {}
            if values.get("safety_route") == "blocked":
                _safety_text = values.get("safety_text", "")
                if _safety_text:
                    await ctx.output_queue.put({"type": "text", "content": _safety_text})
                await ctx.output_queue.put({
                    "type": "event",
                    "name": "final_result",
                    "payload": {
                        "final_text": _safety_text,
                        "safety_blocked": True,
                    },
                })
                ctx.final_result_emitted = True
        except Exception:
            logger.debug("[SAFETY_BLOCKED_EMIT] failed", exc_info=True)

    # If we never built full_response but have a merge final_text, emit final_result anyway.
    _fallback_ft = ctx.final_text_override or ctx.merge_final_text
    if (not ctx.final_result_emitted) and _fallback_ft:
        try:
            state = await app_instance.aget_state(config)
            values = getattr(state, "values", {}) or {}
            merge_mode = values.get("merge_mode")
            is_wait = (_fallback_ft.strip() == "WAIT")
            await ctx.output_queue.put({
                "type": "event",
                "name": "final_result",
                "payload": {
                    "final_text": _fallback_ft,
                    "merge_mode": merge_mode,
                    "is_wait": is_wait,
                    "dissonance": values.get("dissonance"),
                    "dissonance_on": values.get("dissonance_on"),
                    "need_depth1": values.get("need_depth1"),
                }
            })
            ctx.final_result_emitted = True
        except Exception:
            logger.debug("[FINAL_RESULT_FALLBACK] failed to attach", exc_info=True)


async def _cleanup_stream(ctx: StreamingContext) -> None:
    """Finally block: flush StreamSanitizer, emit done event."""
    logger.info("[PRODUCER_EXIT] stream_id=%s", ctx.stream_id)

    # Flush StreamSanitizer (Commit any remaining safe text)
    try:
        if ctx.suppress_stream_text:
            logger.info("[SSE_FLUSH] skipped flush_tail reason=suppressed_after_hold")
            final_tail = ""
        else:
            # Always flush StreamSanitizer buffer.
            # Even when merge_final_text is set, the frontend uses
            # finalTextLocked to ignore duplicate text, so flushing
            # here is safe and ensures text is delivered if final_result
            # was missed for any reason.
            final_tail = ctx.stream_san.flush()
            if final_tail and ctx.merge_final_text:
                logger.info("[SSE_FLUSH] flush_tail as safety net (merge_final_text also present)")
        cleaned_tail = ""
        tags = []
        gestures_tail = []
        if final_tail:
            # Strip any residual <think>...</think> blocks
            final_tail = _THINK_FULL_RE.sub("", final_tail).strip()
            # Also flush the think filter in case of partial tags
            think_tail = ctx.think_filter.flush()
            if think_tail:
                final_tail = _THINK_FULL_RE.sub("", think_tail + final_tail).strip()
        if final_tail:
            cleaned_tail, tags, gestures_tail = _extract_emotion_tags(final_tail)
        if cleaned_tail:
            await ctx.output_queue.put({"type": "text", "content": cleaned_tail})
            for tag in tags:
                await ctx.output_queue.put({"type": "emotion", "tag": tag})
            for gesture in gestures_tail:
                await ctx.output_queue.put({"type": "gesture", "tag": gesture})
    except Exception:
        logger.exception("[SSE_FLUSH] failed")

    if ctx.is_pondering_sent:
        await ctx.output_queue.put({"type": "thinking", "value": False})
    await ctx.output_queue.put({"type": "done"})


# ── Main entry point ─────────────────────────────────────────
async def run_agent_stream(
    input_text: str,
    thread_id: str = "default_thread",
    voice_id: str = "14",
    image_data: str = None,
    mode: str = "normal",
    memory_refs: Optional[dict] = None,
    ports: Optional[dict] = None,
):
    if not ports or not isinstance(ports, dict):
        raise RuntimeError("ports is required for run_agent_stream")
    if "checkpointer" not in ports:
        raise RuntimeError("ports.checkpointer is required for run_agent_stream")
    if "tts" not in ports:
        raise RuntimeError("ports.tts is required for run_agent_stream")
    if "vision" not in ports:
        raise RuntimeError("ports.vision is required for run_agent_stream")
    logger.info(f"Stream Start: Thread={thread_id} Mode={mode}")

    stream_id = None
    message_id = None
    if isinstance(memory_refs, dict):
        stream_id = memory_refs.get("stream_id")
        message_id = memory_refs.get("message_id")

    output_queue = asyncio.Queue()
    resolved_voice_id = _resolve_voice_id(voice_id)
    resolved_current_voice_id = _current_voice_id(resolved_voice_id)
    logger.info("[TTS] init voice_id=%s current_voice_id=%s", str(resolved_voice_id), str(resolved_current_voice_id))

    has_user_text = bool(input_text.strip() and input_text.strip() != "[SILENCE]")

    ctx = StreamingContext(
        thread_id=thread_id,
        stream_id=stream_id,
        message_id=message_id,
        input_text=input_text,
        has_user_text=has_user_text,
        mode=mode,
        ports=ports,
        output_queue=output_queue,
        voice_id=resolved_voice_id,
        current_voice_id=resolved_current_voice_id,
        stream_san=StreamSanitizer(keep_chars=80, max_buf=8192),
    )

    async def llm_producer():
        # Lazy import to avoid circular dependency (agent.py re-exports run_agent_stream)
        from backend.core.agent import analyze_and_save_memory

        try:
            # Use persistent AsyncSqliteSaver via checkpointer gateway
            async with ctx.ports["checkpointer"].get_async_checkpointer_conn() as checkpointer:
                # Compile workflow with the persistent checkpointer
                app_instance = workflow.compile(checkpointer=checkpointer)

                config = {
                    "configurable": {
                        "thread_id": ctx.thread_id,
                        "mode": ctx.mode,
                        "ports": ctx.ports or {},
                    }
                }

                # Prepare content (vision analysis may take 20-30s)
                if image_data:
                    await ctx.output_queue.put({"type": "thinking", "value": True})
                    vision_task = asyncio.ensure_future(
                        _build_user_content(input_text, image_data, log_context="stream", vision_gateway=ctx.ports["vision"])
                    )
                    while not vision_task.done():
                        try:
                            await asyncio.wait_for(asyncio.shield(vision_task), timeout=8.0)
                        except asyncio.TimeoutError:
                            await ctx.output_queue.put({"type": "keepalive"})
                    content = vision_task.result()
                else:
                    content = await _build_user_content(input_text, image_data, log_context="stream", vision_gateway=ctx.ports["vision"])

                inputs: AgentState = {
                    "messages": [HumanMessage(content=content)],
                    "has_user_text": ctx.has_user_text,
                    # Prevent stale checkpoint values from leaking across turns.
                    "draft": "",
                    "depth1_text": "",
                    "depth2_text": "",
                }

                ctx.raw_buffer = ""
                ctx.full_response = ""
                ctx.last_tts_task = asyncio.create_task(asyncio.sleep(0))
                ctx.last_sent_text = ""
                ctx.hold_request_sent = False
                ctx.hold_cancelled_sent = False
                ctx.prev_review_token = None
                ctx.prev_merge_mode = None

                try:
                    prev_state = await app_instance.aget_state(config)
                    prev_values = getattr(prev_state, "values", {}) or {}
                    ctx.prev_review_token = get_review_token(prev_values)
                    ctx.prev_merge_mode = prev_values.get("merge_mode")
                except Exception:
                    ctx.prev_review_token = None
                    ctx.prev_merge_mode = None

                ctx.sent_any_text = False

                # ── Main event loop (dispatch to handlers) ──
                async for event in app_instance.astream_events(inputs, config=config, version="v1", recursion_limit=50):
                    et = event.get("event")
                    nm = event.get("name")
                    data = event.get("data") or {}

                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug("[EV] %s name=%s data_keys=%s", et, nm, list(data.keys()))

                    if et == "on_chain_end" and nm == "merge":
                        await _handle_merge_end(ctx, data)
                    elif et == "on_chain_end" and nm == "safety":
                        await _handle_safety_end(ctx, data)
                    elif et == "on_chain_end" and nm == "action_processing":
                        await _handle_action_end(ctx, data)
                    elif et in ("on_chat_model_stream", "on_llm_stream"):
                        await _handle_stream_chunk(ctx, data)
                    elif et in ("on_chat_model_end", "on_llm_end", "on_chain_end"):
                        await _handle_llm_end(ctx, data, et, nm)

                await _finalize_stream(ctx, app_instance, config, analyze_and_save_memory, memory_refs)

        except Exception as e:
            logger.error("LLM Producer Error", exc_info=True)
            logger.error(
                "[Safety] Stream types: raw_buffer=%s full_response=%s last_chunk=%s",
                type(ctx.raw_buffer).__name__,
                type(ctx.full_response).__name__,
                type(ctx.last_chunk).__name__,
            )
            await ctx.output_queue.put({"type": "error", "content": str(e)})
        finally:
            await _cleanup_stream(ctx)

    producer_task = asyncio.create_task(llm_producer())
    try:
        while True:
            item = await output_queue.get()
            if item is None:
                break

            yield item
            output_queue.task_done()

            if isinstance(item, dict) and item.get("type") == "done":
                break
    finally:
        if not producer_task.done():
            producer_task.cancel()
        try:
            await producer_task
        except Exception:
            pass
