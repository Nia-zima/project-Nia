"""Streaming agent execution pipeline.

Contains run_agent_stream() and its nested closures (generate_audio_chained,
llm_producer, process_chunk).  Extracted from agent.py for readability.
"""
import re
import asyncio
import logging
import time
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
    StreamSanitizer,
)

from backend.core.agent_helpers import (
    PONDERING_TAG_RE,
    _build_user_content,
    _content_to_text,
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

    voice_id = _resolve_voice_id(voice_id)
    current_voice_id = _current_voice_id(voice_id)
    logger.info("[TTS] init voice_id=%s current_voice_id=%s", str(voice_id), str(current_voice_id))

    last_tts_dedupe_key = None
    # TTS Helper (URL-based audio)
    async def generate_audio_chained(text, vid, prev_task, queue, tid):
        nonlocal last_tts_dedupe_key
        if not text or str(text).strip() == "WAIT":
            return
        norm = " ".join(str(text).split())
        dedupe_key = f"{stream_id}|{vid}|{norm}"
        if last_tts_dedupe_key == dedupe_key:
            logger.info("[TTS] dedupe skip")
            return
        last_tts_dedupe_key = dedupe_key
        logger.info("[TTS] fire-and-forget text_len=%d voice_id=%s", len(norm), str(vid))

        async def _job() -> None:
            try:
                audio_url = await ports["tts"].generate_audio_url(
                    text=text,
                    voice_id=str(vid),
                    thread_id=str(tid),
                    stream_id=str(stream_id) if stream_id else None,
                )
                if not audio_url:
                    return
                meta = None
                try:
                    meta = await ports["tts"].get_audio_meta(audio_url)
                except Exception:
                    meta = None

                payload = dict(meta or {})
                payload.setdefault("url", audio_url)
                payload.setdefault("text_content", text)

                event = {
                    "type": "audio",
                    "thread_id": str(tid),
                    "stream_id": str(stream_id) if stream_id else None,
                    "message_id": str(message_id) if message_id else None,
                    "data": payload,
                }
                # Send audio event via main SSE stream (output_queue) instead of separate tts_event_bus
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
                    "stream_id": str(stream_id) if stream_id else None,
                    "message_id": str(message_id) if message_id else None,
                    "data": {"error": str(e), "text_content": text},
                })

        await _job()

    async def llm_producer():
        nonlocal current_voice_id
        # Lazy import to avoid circular dependency (agent.py re-exports run_agent_stream)
        from backend.core.agent import analyze_and_save_memory

        think_filter = ThinkBlockFilter()

        last_chunk = ""
        consent_seen = False
        dissonance_seen = False
        emotion_tags_seen: set[str] = set()
        last_state_seen: str | None = None
        is_pondering_sent = False
        raw_logged = False
        state_started = False
        raw_buffer = ""
        full_response = ""
        full_raw_parts = []
        final_text_override = ""
        merge_final_text = ""
        suppress_stream_text = False
        final_result_emitted = False
        tts_enqueued = False
        tts_enqueued_stream_ids: set[str] = set()
        stream_san = StreamSanitizer(keep_chars=80, max_buf=8192)

        try:
            # Use persistent AsyncSqliteSaver via checkpointer gateway
            async with ports["checkpointer"].get_async_checkpointer_conn() as checkpointer:
                # Compile workflow with the persistent checkpointer
                # Note: workflow is imported from backend.core.agent_graph.graph
                app_instance = workflow.compile(checkpointer=checkpointer)

                has_user_text = bool(input_text.strip() and input_text.strip() != "[SILENCE]")
                config = {
                    "configurable": {
                        "thread_id": thread_id,
                        "mode": mode,
                        "ports": ports or {},
                    }
                }

                # Prepare content (vision analysis may take 20-30s)
                if image_data:
                    await output_queue.put({"type": "thinking", "value": True})
                    # Run vision with periodic keepalive to prevent SSE timeout
                    vision_task = asyncio.ensure_future(
                        _build_user_content(input_text, image_data, log_context="stream", vision_gateway=ports["vision"])
                    )
                    while not vision_task.done():
                        try:
                            await asyncio.wait_for(asyncio.shield(vision_task), timeout=8.0)
                        except asyncio.TimeoutError:
                            await output_queue.put({"type": "keepalive"})
                    content = vision_task.result()
                else:
                    content = await _build_user_content(input_text, image_data, log_context="stream", vision_gateway=ports["vision"])

                inputs: AgentState = {
                    "messages": [HumanMessage(content=content)],
                    "has_user_text": has_user_text,
                    # Prevent stale checkpoint values from leaking across turns.
                    "draft": "",
                    "depth1_text": "",
                    "depth2_text": "",
                }

                raw_buffer = ""
                full_response = ""
                last_tts_task = asyncio.create_task(asyncio.sleep(0))
                last_sent_text = ""
                hold_request_sent = False
                hold_cancelled_sent = False
                prev_review_token = None
                prev_merge_mode = None

                try:
                    prev_state = await app_instance.aget_state(config)
                    prev_values = getattr(prev_state, "values", {}) or {}
                    prev_review_token = get_review_token(prev_values)
                    prev_merge_mode = prev_values.get("merge_mode")
                    prev_final_text = str(prev_values.get("final_text") or "").strip()
                except Exception:
                    prev_review_token = None
                    prev_merge_mode = None
                    prev_final_text = ""

                sent_any_text = False

                # Inner Processing Helper
                async def process_chunk(text: str, label: str):
                    nonlocal full_response, last_sent_text, state_started, last_tts_task, current_voice_id, consent_seen, dissonance_seen, last_state_seen
                    if suppress_stream_text:
                        logger.debug("[PROCESS_CHUNK_SKIPPED] label=%s reason=suppressed_after_hold", label)
                        return False

                    # Note: Model no longer outputs [PONDERING] tags.
                    # State emit happens right before first text is sent (see below).

                    sanitized, reason = _sanitize_stream_chunk(
                        text,
                        has_user_text=has_user_text,
                        input_text=input_text,
                        last_sent_text=last_sent_text,
                        log_label=label,
                    )
                    if not sanitized:
                        logger.debug("[DROP] label=%s stage=sanitize reason=%s", label, reason or "unknown")
                        return False

                    # Stateful rolling buffer cleaning
                    safe_fragment = stream_san.push(sanitized)
                    if not safe_fragment:
                        return True # Neutral skip (waiting for tail)

                    # Note: We NO LONGER call _strip_tool_blocks here because it is not stateful.
                    # RollingStreamCleaner in the SSE loop handles cross-chunk tool blocks.

                    if sanitized == SILENCE_DEFAULT and last_sent_text == SILENCE_DEFAULT: return False

                    cleaned, tags, gestures = _extract_emotion_tags(safe_fragment)
                    if not cleaned:
                        return True # Might be empty after emotion tag removal

                    if not state_started:
                        # Fallback state emit if not emitted yet
                        logger.debug("[STATE_EMIT] stream_id=%s tag=%s", stream_id, "PONDERING")
                        await output_queue.put({"type": "state", "tag": "PONDERING"})
                        state_started = True

                    for tag in tags:
                        if tag == "consent":
                            consent_seen = True
                            last_state_seen = "CONSENT"
                        elif tag == "dissonance":
                            dissonance_seen = True
                            last_state_seen = "DISSONANCE"
                        elif tag and tag not in {"pondering"}:
                            emotion_tags_seen.add(tag)
                        await output_queue.put({"type": "emotion", "tag": tag})

                    for gesture in gestures:
                        await output_queue.put({"type": "gesture", "tag": gesture})

                    await output_queue.put({"type": "text", "content": cleaned})
                    full_response = str(full_response) + cleaned
                    last_sent_text = cleaned

                    # Voice switching logic
                    tail = full_response[-50:].lower()
                    for emo, vid in settings.EMOTION_VOICE_MAP.items():
                        if f"[{emo}]" in tail:
                            current_voice_id = str(vid)
                            break

                    logger.debug("[TTS] chunk enqueue disabled; waiting for final_text")
                    return True

                async for event in app_instance.astream_events(inputs, config=config, version="v1", recursion_limit=50):
                    et = event.get("event")
                    nm = event.get("name")
                    data = event.get("data") or {}
                    dk = list(data.keys())

                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug("[EV] %s name=%s data_keys=%s", et, nm, dk)

                    if et == "on_chain_end" and nm == "merge":
                        output = data.get("output") or {}
                        if not hold_request_sent:
                            ev = build_hold_request_event(output)
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
                                await output_queue.put(ev)
                                hold_request_sent = True
                        else:
                            logger.debug("[REVIEW_EV] hold_request skipped=already_sent")
                        # Check for stale events (replay from checkpoint)
                        gen_at = float(output.get("generated_at") or 0.0)
                        if gen_at > 0:
                            age = time.time() - gen_at
                            if age > 10.0:
                                logger.info(f"[TTS] skipped stale event (age={age:.1f}s)")
                                continue

                        final_text = output.get("final_text")
                        is_wait = bool(output.get("is_wait"))
                        hold_required = bool(output.get("hold_required"))
                        final_text_str = str(final_text or "").strip()

                        # Extract gesture/emotion tags from final_text, emit SSE, use clean text for TTS
                        if final_text_str and final_text_str != "WAIT":
                            cleaned_final, _ftags, _fgestures = _extract_emotion_tags(final_text_str)
                            for _gt in _fgestures:
                                await output_queue.put({"type": "gesture", "tag": _gt})
                            for _et in _ftags:
                                if _et and _et not in {"pondering"}:
                                    await output_queue.put({"type": "emotion", "tag": _et})
                            final_text_str = cleaned_final.strip() if cleaned_final else final_text_str

                        if final_text_str:
                            # Safety net: strip residual LLM tokens (ChatML sections etc.)
                            from backend.services.speech_sanitizer import strip_llm_special_tokens as _strip_tokens
                            final_text_str = _strip_tokens(final_text_str).strip() or final_text_str
                            merge_final_text = final_text_str
                        suppress_stream_text = hold_required or is_wait or final_text_str.startswith("WAIT")
                        if hold_required:
                            logger.info("[TTS] skipped final_text enqueue: hold_required")
                        elif is_wait or final_text_str.startswith("WAIT"):
                            logger.info("[TTS] skipped final_text enqueue: WAIT")
                        elif final_text_str:
                            if current_voice_id:
                                if not tts_enqueued:
                                    if stream_id and str(stream_id) in tts_enqueued_stream_ids:
                                        logger.info("[TTS] skipped final_text enqueue: stream already enqueued")
                                        continue
                                    if bool(getattr(settings, "TTS_SENTENCE_CHUNKING", True)):
                                        max_chars = int(getattr(settings, "TTS_SENTENCE_MAX_CHARS", 90) or 90)
                                        units = _split_tts_units(final_text_str, max_chars=max_chars)
                                    else:
                                        units = [final_text_str]
                                    if not units:
                                        units = [final_text_str]
                                    logger.info(
                                        "[TTS] enqueue (final_text) text_len=%d units=%d voice_id=%s",
                                        len(final_text_str),
                                        len(units),
                                        str(current_voice_id),
                                    )
                                    for unit in units:
                                        task = asyncio.create_task(
                                            generate_audio_chained(
                                                unit, current_voice_id, last_tts_task, output_queue, thread_id
                                            )
                                        )
                                        last_tts_task = task
                                    tts_enqueued = True
                                    if stream_id:
                                        tts_enqueued_stream_ids.add(str(stream_id))
                                else:
                                    logger.info("[TTS] skipped final_text enqueue: already enqueued")
                            else:
                                logger.info("[TTS] skipped final_text enqueue: voice_id=off or unset")

                        # Emit final_result from merge handler (Phase1 authoritative output).
                        # The emit at line ~738 is unreachable because this block `continue`s,
                        # and the emit at line ~845 requires non-empty full_response which
                        # may be empty when StreamSanitizer buffers short responses.
                        if final_text_str and final_text_str != "WAIT" and not final_result_emitted:
                            await output_queue.put({
                                "type": "event",
                                "name": "final_result",
                                "payload": {
                                    "final_text": final_text_str,
                                    "merge_mode": output.get("merge_mode"),
                                    "is_wait": False,
                                },
                            })
                            final_result_emitted = True
                            logger.info(
                                "[FINAL_RESULT] emitted from merge handler len=%d",
                                len(final_text_str),
                            )
                        continue

                    if et == "on_chain_end" and nm == "safety":
                        if not hold_cancelled_sent:
                            output = data.get("output") or {}
                            reasons = output.get("reason_codes") or []
                            if "system_hold_cancelled_new_input" in reasons:
                                ev = build_hold_cancelled_event(prev_review_token)
                                if ev:
                                    short = (prev_review_token or "")[:8]
                                    logger.info(
                                        "[REVIEW_EV] hold_cancelled sent=1 token=%s reason=new_user_input prev_mode=%s",
                                        short,
                                        prev_merge_mode,
                                    )
                                    await output_queue.put(ev)
                                    hold_cancelled_sent = True
                        else:
                            logger.debug("[REVIEW_EV] hold_cancelled skipped=already_sent")
                        continue

                    if et == "on_chain_end" and nm == "action_processing":
                        output = data.get("output") or {}
                        proposed = output.get("proposed_actions") or []
                        pending = output.get("pending_actions") or []
                        rejected = output.get("rejected_actions") or []
                        results = output.get("action_results") or []

                        for item in proposed:
                            payload = {
                                "action_id": item.get("action_id"),
                                "name": item.get("name"),
                                "risk_level": item.get("risk_level"),
                                "category": item.get("category"),
                            }
                            await output_queue.put({"type": "event", "name": "action_proposed", "payload": payload})

                        for item in results:
                            payload = {
                                "action_id": item.get("action_id"),
                                "status": item.get("status"),
                                "result": item.get("result"),
                            }
                            await output_queue.put({"type": "event", "name": "action_approved", "payload": payload})

                        for item in pending:
                            payload = {
                                "action_id": item.get("action_id"),
                                "name": item.get("name"),
                                "risk_level": item.get("risk_level"),
                                "reason": (item.get("decision") or {}).get("reason"),
                                "requires_confirmation": (item.get("decision") or {}).get("requires_confirmation"),
                            }
                            await output_queue.put({"type": "event", "name": "action_blocked", "payload": payload})

                        for item in rejected:
                            payload = {
                                "action_id": item.get("action_id"),
                                "name": item.get("name"),
                                "risk_level": item.get("risk_level"),
                                "reason": item.get("reason"),
                            }
                            await output_queue.put({"type": "event", "name": "action_blocked", "payload": payload})
                        continue

                    # 1. Stream Event (Normal)
                    if et in ("on_chat_model_stream", "on_llm_stream"):
                        chunk_obj = data.get("chunk")
                        chunk = _extract_text(chunk_obj)

                        if not chunk: continue

                        full_raw_parts.append(chunk)

                        # Apply bracket filter to remove [PONDERING], [SEARCH_*] etc from chunked stream
                        # MOVED TO SSE LOOP: chunk = bracket_filter.feed(chunk)

                        sent_any_text = True  # Signal that we received valid stream content

                        chunk_raw = chunk
                        if last_chunk is not None:
                            if chunk_raw == last_chunk: continue
                            if chunk_raw.startswith(last_chunk):
                                chunk = chunk_raw[len(last_chunk):]
                            else:
                                chunk = chunk_raw
                        last_chunk = chunk_raw

                        if not chunk: continue

                        # Strip <think>...</think> blocks from streaming chunks
                        chunk = think_filter.feed(chunk)
                        if not chunk: continue

                        raw_buffer += chunk
                        if not raw_logged and raw_buffer.strip():
                            if logger.isEnabledFor(logging.DEBUG):
                                logger.debug("[DEBUG_RAW_STREAM] %s", raw_buffer[:200])
                            raw_logged = True

                        if not is_pondering_sent and PONDERING_TAG_RE.search(raw_buffer):
                            is_pondering_sent = True
                            await output_queue.put({"type": "thinking", "value": True})

                        parts = re.split(r"([。！\n.!？?]+)", raw_buffer)
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

                                ok = await process_chunk(sentence_raw, "stream_chunk")
                                if ok:
                                    sent_any_text = True
                                else:
                                    logger.debug("[PROCESS_CHUNK_DROPPED] label=%s", "stream_chunk")

                            raw_buffer = parts[-1]

                    # 2. Fallback Event (No Stream)
                    elif et in ("on_chat_model_end", "on_llm_end", "on_chain_end"):
                        out = data.get("output")

                        # Emit final_result as soon as merge finishes (Phase1)
                        if et == "on_chain_end" and (nm or "") == "merge":
                            if isinstance(out, dict):
                                ft = out.get("final_text")
                                if isinstance(ft, str) and ft.strip():
                                    await output_queue.put({
                                        "type": "event",
                                        "name": "final_result",
                                        "payload": {
                                            "final_text": ft.strip(),
                                            "merge_mode": out.get("merge_mode"),
                                        },
                                    })

                        # stream で完全文が作れなかった場合の残りを flush
                        if raw_buffer.strip() and not sent_any_text:
                            tail = _strip_speaker_prefix(raw_buffer.strip())
                            if tail and not PONDERING_TAG_RE.fullmatch(tail):
                                ok = await process_chunk(tail, "stream_flush_end")
                                if ok:
                                    sent_any_text = True
                                else:
                                    logger.info("[PROCESS_CHUNK_DROPPED] label=%s preview=%r", "stream_flush_end", tail[:120])
                            raw_buffer = ""

                        if sent_any_text:
                            continue

                        # Phase1: only accept LangGraph terminal output here
                        if et == "on_chain_end":
                            name = nm or ""
                            if name != "LangGraph":
                                continue

                            cand = data.get("output") or {}
                            final_text = None
                            if isinstance(cand, dict):
                                if "final_text" in cand:
                                    final_text = cand.get("final_text")
                                elif isinstance(cand.get("merge"), dict):
                                    final_text = cand["merge"].get("final_text")

                            if final_text:
                                final_text_override = str(final_text)
                                sentence_raw = _strip_speaker_prefix(str(final_text))
                                if await process_chunk(sentence_raw, "final_text"):
                                    sent_any_text = True
                            continue

                        # LLM-only fallback (non-graph)
                        cand = data.get("output") or data.get("outputs") or data.get("result") or data.get("response")
                        text = _extract_llm_text_from_output(cand)

                        if text:
                            # Strip <think>...</think> blocks from fallback text
                            text = _THINK_FULL_RE.sub("", text).strip()
                            if not text:
                                continue
                            full_raw_parts.append(text)
                            # For fallback, treat as single chunk
                            sentence_raw = _strip_speaker_prefix(text)
                            if await process_chunk(sentence_raw, "fallback_end"):
                                sent_any_text = True

                # Flush remaining buffer
                if raw_buffer.strip():
                    sentence_raw = _strip_speaker_prefix(raw_buffer.strip())
                    await process_chunk(sentence_raw, "trailing_chunk")




                if last_tts_task:
                    try:
                        await asyncio.wait_for(
                            last_tts_task,
                            timeout=float(settings.TTS_FINALIZE_TIMEOUT_SEC),
                        )
                    except asyncio.TimeoutError:
                        logger.warning("[TTS] Finalize timeout; finishing stream without waiting for audio.")
                    except Exception:
                        pass

                if full_response:
                    leak_reasons = detect_internal_leak(full_response)
                    if is_critical_leak(leak_reasons):
                        logger.warning(
                            "[CAPTURE_SKIP] reason=critical_leak leak_reasons=%s",
                            ";".join(
                                list(leak_reasons.get("critical", []))
                                + list(leak_reasons.get("warn", []))
                            ) if leak_reasons else "unknown",
                        )
                        full_response = ""
                    else:
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug("[DEBUG_RAW_STREAM_FINAL] %s", full_response[:200])

                        # High-precision finalization using full raw buffer
                        full_raw = "".join(full_raw_parts)
                        ultimate_response = merge_final_text or finalize_output(full_raw)

                        ultimate_response = _strip_hearing_ack(ultimate_response, input_text)
                        final_state = last_state_seen or ("CONSENT" if consent_seen else ("DISSONANCE" if dissonance_seen else None))
                        if final_state is None:
                            final_state = _final_state_from_text(ultimate_response)

                        # Emit final_result once (Phase1: single-shot authoritative output)
                        try:
                            state = await app_instance.aget_state(config)
                            values = getattr(state, "values", {}) or {}
                            merge_mode = values.get("merge_mode")
                            is_wait = (ultimate_response.strip() == "WAIT")
                            await output_queue.put({
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
                            final_result_emitted = True
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
                                    "extracted_keywords": _extract_keywords_from_user(input_text),
                                }
                                await output_queue.put({"type": "event", "name": "thinking_hint", "payload": thinking_hint})
                        except Exception:
                            logger.debug("[THINKING_HINT] failed to attach", exc_info=True)

                        if final_state:
                            if final_state == "CONSENT":
                                consent_seen = True
                            elif final_state == "DISSONANCE":
                                dissonance_seen = True
                            logger.info("[STATE_EMIT] stream_id=%s tag=%s", stream_id, final_state)
                            await output_queue.put({"type": "state", "tag": final_state})
                        if ultimate_response.strip() != "WAIT":
                            if getattr(settings, "ORCHESTRATOR_S5_ENABLED", False):
                                logger.info("[CAPTURE_SKIP] reason=s5_handles_episodic")
                            else:
                                t = asyncio.create_task(
                                    analyze_and_save_memory(
                                        input_text,
                                        ultimate_response,
                                        thread_id,
                                        consent_seen=consent_seen,
                                        dissonance_seen=dissonance_seen,
                                        emotion_tags=list(emotion_tags_seen),
                                        final_state_tag=final_state,
                                        refs=memory_refs,
                                        ports=ports,
                                    )
                                )
                                t.add_done_callback(_log_task_exception)
                        else:
                            logger.info("[CAPTURE_SKIP] reason=wait_final_text")
                else:
                    logger.info(
                        "[CAPTURE_SKIP] reason=empty_full_response sent_any_text=%s final_text_override=%s raw_buffer_len=%s",
                        sent_any_text,
                        bool(final_text_override),
                        len(raw_buffer or ""),
                    )

                # Safety blocked: emit safety_text to frontend
                if not final_result_emitted:
                    try:
                        state = await app_instance.aget_state(config)
                        values = getattr(state, "values", {}) or {}
                        if values.get("safety_route") == "blocked":
                            _safety_text = values.get("safety_text", "")
                            if _safety_text:
                                await output_queue.put({"type": "text", "content": _safety_text})
                            await output_queue.put({
                                "type": "event",
                                "name": "final_result",
                                "payload": {
                                    "final_text": _safety_text,
                                    "safety_blocked": True,
                                },
                            })
                            final_result_emitted = True
                    except Exception:
                        logger.debug("[SAFETY_BLOCKED_EMIT] failed", exc_info=True)

                # If we never built full_response but have a merge final_text, emit final_result anyway.
                _fallback_ft = final_text_override or merge_final_text
                if (not final_result_emitted) and _fallback_ft:
                    try:
                        state = await app_instance.aget_state(config)
                        values = getattr(state, "values", {}) or {}
                        merge_mode = values.get("merge_mode")
                        is_wait = (_fallback_ft.strip() == "WAIT")
                        await output_queue.put({
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
                        final_result_emitted = True
                    except Exception:
                        logger.debug("[FINAL_RESULT_FALLBACK] failed to attach", exc_info=True)

        except Exception as e:
            logger.error("LLM Producer Error", exc_info=True)
            logger.error(
                "[Safety] Stream types: raw_buffer=%s full_response=%s last_chunk=%s",
                type(raw_buffer).__name__,
                type(full_response).__name__,
                type(last_chunk).__name__,
            )
            await output_queue.put({"type": "error", "content": str(e)})
        finally:
            logger.info("[PRODUCER_EXIT] stream_id=%s", stream_id)

            # Flush StreamSanitizer (Commit any remaining safe text)
            try:
                if suppress_stream_text:
                    logger.info("[SSE_FLUSH] skipped flush_tail reason=suppressed_after_hold")
                    final_tail = ""
                else:
                    # Always flush StreamSanitizer buffer.
                    # Even when merge_final_text is set, the frontend uses
                    # finalTextLocked to ignore duplicate text, so flushing
                    # here is safe and ensures text is delivered if final_result
                    # was missed for any reason.
                    final_tail = stream_san.flush()
                    if final_tail and merge_final_text:
                        logger.info("[SSE_FLUSH] flush_tail as safety net (merge_final_text also present)")
                cleaned_tail = ""
                tags = []
                gestures_tail = []
                if final_tail:
                    # Strip any residual <think>...</think> blocks
                    final_tail = _THINK_FULL_RE.sub("", final_tail).strip()
                    # Also flush the think filter in case of partial tags
                    think_tail = think_filter.flush()
                    if think_tail:
                        final_tail = _THINK_FULL_RE.sub("", think_tail + final_tail).strip()
                if final_tail:
                    cleaned_tail, tags, gestures_tail = _extract_emotion_tags(final_tail)
                if cleaned_tail:
                    await output_queue.put({"type": "text", "content": cleaned_tail})
                    for tag in tags:
                        await output_queue.put({"type": "emotion", "tag": tag})
                    for gesture in gestures_tail:
                        await output_queue.put({"type": "gesture", "tag": gesture})
            except Exception:
                logger.exception("[SSE_FLUSH] failed")

            if is_pondering_sent:
                await output_queue.put({"type": "thinking", "value": False})
            await output_queue.put({"type": "done"})

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
