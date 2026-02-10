import re
import asyncio
import base64
import json
import datetime
import logging
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

# --- New Refactored Modules ---
from backend.core.agent_graph.state import AgentState
from backend.core.agent_graph.review_window import (
    build_hold_cancelled_event,
    build_hold_request_event,
    get_review_token,
)
from backend.core.agent_graph.graph import workflow
from backend.core.agent_graph.utils import _log_task_exception

# --- Services ---
from backend.core.config import settings
from backend.core.logger import logger
from backend.services.memory_manager import memory_manager
from backend.services.voicevox_client import voicevox_client
from backend.services.speech_sanitizer import (
    SILENCE_DEFAULT,
    detect_internal_leak,
    extract_metadata,
    finalize_output,
    is_critical_leak,
    StreamSanitizer,
)
from backend.services.pending_actions_service import enqueue_memory_add
PONDERING_TAG_RE = re.compile(r"\[PONDERING\]", re.IGNORECASE)
HEARING_QUERY_RE = re.compile(r"(聞こえ|聞こえる|声|マイク|音声)", re.IGNORECASE)
UNCERTAIN_RE = re.compile(r"(わからない|分からない|不明|判断できない|難しい|確信がない)")


def _split_tts_units(text: str, max_chars: int = 90) -> list[str]:
    s = str(text or "").strip()
    if not s:
        return []
    parts = re.split(r"(?<=[。！？!?\.])\s+|[\r\n]+", s)
    units: list[str] = []
    for part in parts:
        p = str(part or "").strip()
        if not p:
            continue
        if len(p) <= max_chars:
            units.append(p)
            continue
        i = 0
        while i < len(p):
            chunk = p[i : i + max_chars].strip()
            if chunk:
                units.append(chunk)
            i += max_chars
    return units

def _resolve_voice_id(voice_id: Optional[str]) -> str:
    if not voice_id or voice_id == "undefined":
        return str(settings.DEFAULT_VOICE_ID)
    return str(voice_id)


def _current_voice_id(voice_id: str) -> Optional[str]:
    if voice_id == "off":
        return None
    return voice_id


def _fallback_for_silence(input_text: str) -> str:
    # 以前は自己紹介などを返していたが、ニアの「沈黙する権利」を優先し、既定の沈黙文のみを返す。
    return SILENCE_DEFAULT


def _handle_silence(
    sanitized: str,
    *,
    has_user_text: bool,
    input_text: str,
    last_sent_text: str,
) -> str:
    # sanitized が SILENCE_DEFAULT の場合、そのまま通す。
    # 以前のように強制的に _fallback_for_silence で言葉を埋めることはしない。
    return sanitized


async def _build_user_content(input_text: str, image_data: Optional[str], *, log_context: str = "", vision_gateway=None) -> str:
    if image_data:
        if vision_gateway is not None:
            content = await vision_gateway.build_user_input(input_text, image_data)
        else:
            from backend.services.vision_client import build_user_input_with_image
            content = await build_user_input_with_image(input_text, image_data)
        if log_context:
            logger.info(f"[AGENT] Image processed via Vision ({log_context}), content length: {len(content)} chars")
        return content
    return input_text


def _get_final_message(result: dict) -> str:
    messages = result.get("messages") if isinstance(result, dict) else None
    if messages:
        return messages[-1].content
    return "[SILENCE]"


def _strip_speaker_prefix(text: str) -> str:
    return re.sub(r"^(応答|ニア|Response|A|Speech|Layer\s*3)\s*[:：]\s*", "", text, flags=re.IGNORECASE)



TOOL_BLOCK_RE = re.compile(
    r"\[(SEARCH_MEMORY|MEMORY_JSON|INTERNAL_LOG)\].*?\[END_\1\]\s*",
    re.DOTALL | re.IGNORECASE
)

def _strip_tool_blocks(text: str) -> str:
    if not text:
        return ""
    # Remove standard blocks
    cleaned = TOOL_BLOCK_RE.sub("", text).strip()
    return cleaned

def _strip_hearing_ack(text: str, user_text: str) -> str:
    """Strip '聞こえます' responses only when user asked a hearing-related question."""
    if not text:
        return text
    # Only strip if user DIDN'T ask about hearing (avoid redundant "聞こえます" for non-hearing queries)
    # When user DID ask (聞こえ/マイク/テスト/音), keep the response as it's contextually appropriate.
    if user_text and HEARING_QUERY_RE.search(user_text):
        return text  # User asked about hearing -> keep the acknowledgment
    # User didn't ask about hearing -> strip the redundant ack
    return re.sub(
        r"^\s*(はい、?\s*)?聞こえ(てる|ている|ます|ています)(?:[。\.！!…]+)?\s*",
        "",
        text,
    )


def _sanitize_stream_chunk(
    sentence_raw: str,
    *,
    has_user_text: bool,
    input_text: str,
    last_sent_text: str,
    log_label: str,
) -> str:
    """
    Non-destructive sanitization for stream chunks.
    Only checks for critical leaks and handles specific hearing acks.
    Heavy cleaning is handled by RollingStreamCleaner (SSE loop) 
    and finalize_output (post-stream).
    """
    leak = detect_internal_leak(sentence_raw)
    if is_critical_leak(leak):
        logger.warning(f"[Safety] Leak detected in {log_label}: {leak['critical']}")
        return "", "critical_leak"
    
    # We pass the raw sentence through a few minimal filters
    sanitized = str(sentence_raw)
    
    sanitized = _handle_silence(
        sanitized,
        has_user_text=has_user_text,
        input_text=input_text,
        last_sent_text=last_sent_text,
    )
    
    after_ack = _strip_hearing_ack(sanitized, input_text)
    if not after_ack.strip() and sanitized.strip():
        return "", "hearing_ack_strip"
        
    return after_ack, None


def _extract_emotion_tags(text: str):
    if not text:
        return "", []
    cleaned, _primary_tag, all_tags = extract_metadata(text)
    tags = [t.lower() for t in all_tags]
    return cleaned, tags


def _final_state_from_text(text: str) -> str:
    if not text:
        return "CONSENT"
    if UNCERTAIN_RE.search(text):
        return "DISSONANCE"
    return "CONSENT"

# --- Keyword extraction (lightweight, non-generative) ---
_KEYWORD_SPLIT_RE = re.compile(r"[^\w\u3040-\u30ff\u4e00-\u9fff]+")
_KEYWORD_STOP = {
    "こと", "これ", "それ", "あれ", "よう", "ため", "ので", "から", "けど", "でも",
    "です", "ます", "する", "して", "した", "いる", "ある", "なる", "できる",
}

def _extract_keywords_from_user(text: str, *, max_items: int = 6) -> list[str]:
    if not text:
        return []
    tokens = [t for t in _KEYWORD_SPLIT_RE.split(text) if t]
    picked: list[str] = []
    for t in tokens:
        if len(t) < 2:
            continue
        if t in _KEYWORD_STOP:
            continue
        if t not in picked:
            picked.append(t)
        if len(picked) >= max_items:
            break
    return picked

# --- SSE Fallback Helpers ---
def _content_to_text(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict):
                parts.append(p.get("text") or p.get("content") or "")
        return "".join(parts)
    return str(content)

def _extract_text(obj) -> str:
    if obj is None:
        return ""
    if isinstance(obj, str):
        s = obj.strip()
        if s in {"safe", "merge", "depth0", "depth1", "dissonance", "safety", "END"}:
            return ""
        return obj
    if hasattr(obj, "content"):
        return _content_to_text(getattr(obj, "content", None))
    if isinstance(obj, dict):
        if "safety_route" in obj or "user_text" in obj or "draft" in obj or "depth1_text" in obj:
            return ""
        if "final_text" in obj:
            return _content_to_text(obj.get("final_text"))
        if "merge" in obj and isinstance(obj.get("merge"), dict):
            return _content_to_text(obj["merge"].get("final_text"))
        for k in ("content", "text", "answer", "final", "output"):
            if k in obj:
                return _content_to_text(obj[k])
    return str(obj)

def _extract_llm_text_from_output(obj) -> str:
    """Handle LLMResult-like outputs safely (avoid dumping empty dicts)."""
    if obj is None:
        return ""
    if isinstance(obj, dict):
        if "safety_route" in obj or "user_text" in obj or "draft" in obj or "depth1_text" in obj:
            return ""
        if "final_text" in obj:
            return _content_to_text(obj.get("final_text"))
        if "merge" in obj and isinstance(obj.get("merge"), dict):
            return _content_to_text(obj["merge"].get("final_text"))
    if isinstance(obj, dict) and "generations" in obj:
        generations = obj.get("generations") or []
        for gen_list in generations:
            if not gen_list:
                continue
            for gen in gen_list:
                if isinstance(gen, dict):
                    if gen.get("text"):
                        return _content_to_text(gen.get("text"))
                    if gen.get("message"):
                        return _extract_text(gen.get("message"))
                else:
                    if hasattr(gen, "text"):
                        return _content_to_text(getattr(gen, "text", ""))
                    if hasattr(gen, "message"):
                        return _extract_text(getattr(gen, "message"))
        return ""
    return _extract_text(obj)

# --- Entry Points ---

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
            
                # Prepare content
                content = await _build_user_content(input_text, image_data, log_context="stream", vision_gateway=ports["vision"])
                
                inputs: AgentState = {
                    "messages": [HumanMessage(content=content)],
                    "has_user_text": has_user_text
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
                except Exception:
                    prev_review_token = None
                    prev_merge_mode = None
            
                sent_any_text = False

                # Inner Processing Helper
                async def process_chunk(text: str, label: str):
                    nonlocal full_response, last_sent_text, state_started, last_tts_task, current_voice_id, consent_seen, dissonance_seen, last_state_seen
                    
                    if text.strip():
                        logger.info("[RAW_CHUNK] label=%s text=%r", label, text[:120])
                    
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
                        logger.info("[DROP] label=%s stage=sanitize reason=%s raw=%r", label, reason or "unknown", text[:120])
                        return False
                    
                    # Stateful rolling buffer cleaning
                    safe_fragment = stream_san.push(sanitized)
                    if not safe_fragment:
                        return True # Neutral skip (waiting for tail)
                    
                    # Note: We NO LONGER call _strip_tool_blocks here because it is not stateful.
                    # RollingStreamCleaner in the SSE loop handles cross-chunk tool blocks.
                        
                    if sanitized == SILENCE_DEFAULT and last_sent_text == SILENCE_DEFAULT: return False

                    cleaned, tags = _extract_emotion_tags(safe_fragment)
                    if not cleaned:
                        return True # Might be empty after emotion tag removal

                    if not state_started:
                        # Fallback state emit if not emitted yet
                        logger.info("[STATE_EMIT] stream_id=%s tag=%s", stream_id, "PONDERING")
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

                    await output_queue.put({"type": "text", "content": cleaned})
                    full_response = str(full_response) + cleaned
                    last_sent_text = cleaned

                    # Voice switching logic
                    tail = full_response[-50:].lower()
                    for emo, vid in settings.EMOTION_VOICE_MAP.items():
                        if f"[{emo}]" in tail:
                            current_voice_id = str(vid)
                            break

                    logger.info("[TTS] chunk enqueue disabled; waiting for final_text")
                    return True
            
                async for event in app_instance.astream_events(inputs, config=config, version="v1", recursion_limit=50):
                    et = event.get("event")
                    nm = event.get("name")
                    data = event.get("data") or {}
                    dk = list(data.keys())
                    
                    if logger.isEnabledFor(logging.INFO):
                        logger.info("[EV] %s name=%s data_keys=%s", et, nm, dk)

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
                        final_text = output.get("final_text")
                        is_wait = bool(output.get("is_wait"))
                        final_text_str = str(final_text or "").strip()
                        if is_wait or final_text_str.startswith("WAIT"):
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
                        
                        # DEBUG: Inspect RAW Chunk content
                        if logger.isEnabledFor(logging.INFO):
                             raw_debug = _content_to_text(getattr(chunk_obj, "content", None))
                             logger.info("[RAW_CHUNK] %r", raw_debug[:120])

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
                                    logger.info("[PROCESS_CHUNK_DROPPED] label=%s preview=%r", "stream_chunk", sentence_raw[:120])
                            
                            raw_buffer = parts[-1]

                    # 2. Fallback Event (No Stream)
                    elif et in ("on_chat_model_end", "on_llm_end", "on_chain_end"):
                        out = data.get("output")
                        logger.info("[END_OUTPUT_TYPE] %s", type(out).__name__)
                        logger.info("[END_OUTPUT_PREVIEW] %r", str(out)[:300])

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
                            ",".join(leak_reasons) if leak_reasons else "unknown",
                        )
                        full_response = ""
                    else:
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug("[DEBUG_RAW_STREAM_FINAL] %s", full_response[:200])
                        
                        # High-precision finalization using full raw buffer
                        full_raw = "".join(full_raw_parts)
                        ultimate_response = finalize_output(full_raw)
                        
                        # Verify clean (Debug log)
                        if logger.isEnabledFor(logging.INFO):
                            logger.info("[FINALIZE_AGENT] from_full_raw=True has_tag=%s len=%d", 
                                        ("[PONDERING]" in ultimate_response), 
                                        len(ultimate_response or ""))

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
                    logger.info(
                        "[CAPTURE_SKIP] reason=empty_full_response sent_any_text=%s final_text_override=%s raw_buffer_len=%s",
                        sent_any_text,
                        bool(final_text_override),
                        len(raw_buffer or ""),
                    )

                # If we never built full_response but have a merge final_text, emit final_result anyway.
                if (not final_result_emitted) and final_text_override:
                    try:
                        state = await app_instance.aget_state(config)
                        values = getattr(state, "values", {}) or {}
                        merge_mode = values.get("merge_mode")
                        is_wait = (final_text_override.strip() == "WAIT")
                        await output_queue.put({
                            "type": "event",
                            "name": "final_result",
                            "payload": {
                                "final_text": final_text_override,
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
                final_tail = stream_san.flush()
                cleaned_tail = ""
                tags = []
                if final_tail:
                    cleaned_tail, tags = _extract_emotion_tags(final_tail)
                if cleaned_tail:
                    await output_queue.put({"type": "text", "content": cleaned_tail})
                    # Optional: full_response update depends on if we're saving to memory
                    # but in finally, we usually want to ensure UI gets it.
                    if logger.isEnabledFor(logging.INFO):
                        logger.info("[SSE_TEXT_OUT] flush_tail len=%d: %r", len(cleaned_tail), cleaned_tail[:80])
                    # Do not enqueue TTS on flush_tail to avoid double generation.
                    for tag in tags:
                        await output_queue.put({"type": "emotion", "tag": tag})
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

            if isinstance(item, dict):
                if logger.isEnabledFor(logging.INFO):
                    logger.info("[QUEUE_OUT] type=%s keys=%s", item.get("type"), list(item.keys()))
                if item.get("type") == "text" and logger.isEnabledFor(logging.INFO):
                    logger.info("[SSE_TEXT_OUT] %r", (item.get("content") or "")[:80])

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



async def analyze_and_save_memory(
    user_text: str,
    ai_response: str,
    thread_id: str,
    *,
    consent_seen: bool = False,
    dissonance_seen: bool = False,
    emotion_tags: Optional[list[str]] = None,
    final_state_tag: Optional[str] = None,
    refs: Optional[dict] = None,
    ports: Optional[dict] = None,
):
    """Background Task for Memory Analysis (unchanged logic)"""
    try:
        log = logging.getLogger("AI_Buddy")  # Local alias for safety
        if not ports or not isinstance(ports, dict):
            log.error("[CAPTURE_SAVE] ports missing; aborting")
            return
        capture_gateway = ports.get("memory_capture")
        builder = ports.get("capture_builder")
        vector_gateway = ports.get("vector_store")
        if not capture_gateway or not builder or not vector_gateway:
            log.error("[CAPTURE_SAVE] required ports missing; aborting")
            return

        state_tag = None
        if final_state_tag:
            state_tag = str(final_state_tag).upper()
        elif consent_seen:
            state_tag = "CONSENT"
        elif dissonance_seen:
            state_tag = "DISSONANCE"

        raw_text = f"USER: {user_text}\nASSISTANT: {ai_response}".strip()
        if not raw_text:
            return
        refs_payload = dict(refs or {})
        refs_payload.setdefault("thread_id", thread_id)
        refs_payload.setdefault("created_at_iso", datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat())

        log.info(
            "[CAPTURE_SAVE] consent_seen=%s dissonance_seen=%s final_state=%s emotions=%s refs=%s raw_len=%s",
            consent_seen,
            dissonance_seen,
            state_tag,
            emotion_tags,
            refs_payload,
            len(raw_text or ""),
        )

        capture = builder.build_capture(
            thread_id=thread_id,
            raw_text=raw_text,
            state_tag=state_tag,
            emotion_tags=emotion_tags or [],
            refs=refs_payload,
        )

        message_id = capture.get("message_id") or refs_payload.get("message_id") or "unknown"
        try:
            result = await enqueue_memory_add(
                thread_id,
                message_id,
                capture,
                review_window_id=None,
            )
            log.info(
                "[CAPTURE_ENQUEUE] thread_id=%s message_id=%s status=%s pending_action_id=%s",
                thread_id,
                message_id,
                result.get("status"),
                result.get("pending_action_id"),
            )
        except Exception as e:
            log.error("[CAPTURE_ENQUEUE] failed: %s", e, exc_info=True)
        return

    except Exception as e:
        log.error(f"Memory Analysis Failed: {e}", exc_info=True)


async def run_agent_non_stream(input_text: str, thread_id: str = "default_thread", voice_id: str = "14", image_data: str = None, mode: str = "normal", ports: Optional[dict] = None):
    """Internal use only. Prefer DefaultAgentOrchestrator.run_non_stream()."""
    logger.info(f"Non-Stream Start: Thread={thread_id} Mode={mode}")
    
    voice_id = _resolve_voice_id(voice_id)

    try:
        if ports and ports.get("checkpointer"):
            checkpointer_ctx = ports["checkpointer"].get_async_checkpointer_conn()
        else:
            checkpointer_ctx = memory_manager.get_async_checkpointer_conn()

        async with checkpointer_ctx as checkpointer:
            app_instance = workflow.compile(checkpointer=checkpointer)
            has_user_text = bool(input_text.strip() and input_text.strip() != "[SILENCE]")
            config = {
                "configurable": {
                    "thread_id": thread_id, 
                    "mode": mode
                }
            }

            vision_gateway = ports.get("vision") if ports else None
            content = await _build_user_content(input_text, image_data, vision_gateway=vision_gateway)
            
            inputs: AgentState = {
                "messages": [HumanMessage(content=content)],
                "has_user_text": has_user_text
            }
            
            result = await app_instance.ainvoke(inputs, config=config)
            
            final_msg = _get_final_message(result)
            if isinstance(final_msg, str) and final_msg.strip():
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("[DEBUG_RAW_NON_STREAM] %s", final_msg[:200])

            if is_critical_leak(detect_internal_leak(final_msg)):
                logger.warning("[Safety] Leak detected in non-stream output; forcing silence")
                final_msg = SILENCE_DEFAULT

            clean_text = finalize_output(final_msg)
            if is_critical_leak(detect_internal_leak(clean_text)):
                logger.warning("[Safety] Leak detected after sanitize; forcing silence")
                clean_text = SILENCE_DEFAULT

            clean_text, tags = _extract_emotion_tags(clean_text)
            consent_seen = "consent" in tags
            dissonance_seen = "dissonance" in tags

            clean_text = _handle_silence(
                clean_text,
                has_user_text=has_user_text,
                input_text=input_text,
                last_sent_text="",
            )
            tags = []
            
            if has_user_text:
                user_text_for_check = input_text if isinstance(input_text, str) else ""
                has_user_greeting = bool(re.search(r"(おはよう|こんにちは|こんばんは|はじめまして)", user_text_for_check))
                
                if not has_user_greeting:
                    original_clean = clean_text
                    stripped = clean_text.lstrip()
                    stripped = re.sub(r"^(おはようございます|おはよう|こんにちは|こんばんは|はじめまして)[。！!\s]*", "", stripped)
                    stripped = re.sub(r"^何か(お手伝い|お話)(したいこと|できること)?(は)?ありますか[？\?\s]*", "", stripped)
                    stripped = re.sub(r"^何かお手伝いできることはありますか[？\?\s]*", "", stripped)
                    stripped = stripped.strip()
                    
                    if stripped != original_clean:
                        if not stripped or len(stripped) < 3:
                            stripped = "うん。そのことについて、もう少し教えて？"
                        clean_text = stripped

            audio_b64 = None
            try:
                audio_data = None
                if ports and ports.get("tts"):
                    audio_data = await ports["tts"].generate_audio(clean_text, str(voice_id))
                else:
                    loop = asyncio.get_running_loop()
                    audio_data = await loop.run_in_executor(None, voicevox_client.generate_audio, clean_text, int(voice_id))
                if audio_data:
                    audio_b64 = base64.b64encode(audio_data).decode('utf-8')
            except Exception as ae:
                logger.error(f"Non-Stream TTS Error: {ae}")

            t = asyncio.create_task(analyze_and_save_memory(input_text, clean_text, thread_id, consent_seen=consent_seen, dissonance_seen=dissonance_seen, ports=ports))
            t.add_done_callback(_log_task_exception)

            return {
                "type": "text",
                "content": clean_text,
                "tags": tags,
                "audio": audio_b64
            }

    except Exception as e:
        logger.error(f"Non-Stream Agent Error: {e}", exc_info=True)
        return {
            "type": "error",
            "content": "申し訳ありません。内部でエラーが発生しました。"
        }

async def get_thread_history(thread_id: str):
    try:
        async with memory_manager.get_async_checkpointer_conn() as checkpointer:
            app_instance = workflow.compile(checkpointer=checkpointer)
            config = {"configurable": {"thread_id": thread_id}}
            state = await app_instance.aget_state(config)
            if not state.values or "messages" not in state.values: return []
            formatted = []
            for msg in state.values["messages"]:
                if isinstance(msg, SystemMessage): continue
                role = "user" if isinstance(msg, HumanMessage) else "ai" if isinstance(msg, AIMessage) else "unknown"
                if role == "unknown": continue
                formatted.append({"role": role, "content": getattr(msg, "content", "")})
            return formatted
    except Exception as e:
        logger.error("Get History Error", exc_info=True)
        return []

async def get_all_threads():
    return await memory_manager.get_all_threads()
    
async def delete_thread_history(thread_id: str):
    return await memory_manager.delete_thread_state_history(thread_id)
