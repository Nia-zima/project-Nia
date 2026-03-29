"""Agent entry-point module.

Public API:
    run_agent_stream        (re-exported from agent_stream)
    run_agent_non_stream
    analyze_and_save_memory
    get_thread_history
    get_all_threads
    delete_thread_history
"""
import re
import asyncio
import base64
import datetime
import logging
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

from backend.core.agent_graph.state import AgentState
from backend.core.agent_graph.graph import workflow
from backend.core.agent_graph.utils import _log_task_exception
from backend.core.config import settings
from backend.core.logger import logger
from backend.services.checkpointer import checkpointer_service
from backend.services.voicevox_client import voicevox_client
from backend.services.speech_sanitizer import (
    SILENCE_DEFAULT,
    detect_internal_leak,
    finalize_output,
    is_critical_leak,
)
from backend.services.pending_actions_service import enqueue_memory_add

from backend.core.agent_helpers import (
    _build_user_content,
    _current_voice_id,
    _extract_emotion_tags,
    _get_final_message,
    _handle_silence,
    _resolve_voice_id,
)

# Re-export run_agent_stream for backward compatibility
from backend.core.agent_stream import run_agent_stream  # noqa: F401


# ── Memory capture ────────────────────────────────────────────

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
        log = logging.getLogger("nia")  # Local alias for safety
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


# ── Non-stream entry point ────────────────────────────────────

async def run_agent_non_stream(input_text: str, thread_id: str = "default_thread", voice_id: str = "14", image_data: str = None, mode: str = "normal", ports: Optional[dict] = None):
    """Internal use only. Prefer DefaultAgentOrchestrator.run_non_stream()."""
    logger.info(f"Non-Stream Start: Thread={thread_id} Mode={mode}")

    voice_id = _resolve_voice_id(voice_id)

    try:
        if ports and ports.get("checkpointer"):
            checkpointer_ctx = ports["checkpointer"].get_async_checkpointer_conn()
        else:
            checkpointer_ctx = checkpointer_service.get_async_checkpointer_conn()

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
                "has_user_text": has_user_text,
                "thread_id": thread_id,
                # Prevent stale checkpoint values from leaking across turns.
                "draft": "",
                "depth1_text": "",
                "depth1_contract_ok": None,
                "depth2_text": "",
                "turn_role": None,
                "turn_role_source": None,
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

            clean_text, tags, _gestures_nonstream = _extract_emotion_tags(clean_text)
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

            if getattr(settings, "ORCHESTRATOR_S5_ENABLED", False):
                logger.info("[CAPTURE_SKIP] reason=s5_handles_episodic")
            else:
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


# ── Thread management ─────────────────────────────────────────

async def get_thread_history(thread_id: str):
    try:
        async with checkpointer_service.get_async_checkpointer_conn() as checkpointer:
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
    return await checkpointer_service.get_all_threads()

async def delete_thread_history(thread_id: str):
    return await checkpointer_service.delete_thread_state_history(thread_id)
