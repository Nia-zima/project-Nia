from __future__ import annotations

import json
import time
import logging
import asyncio
from typing import Optional, Iterable, Any, Dict

from backend.core.ports import MemoryGateway, ThoughtGateway, TelemetrySink, TTSGateway, VisionGateway, HistoryGateway, InnerMonologueLogger, ToolRegistry, CheckpointerGateway, MemoryCaptureGateway, VectorGateway, CaptureBuilderGateway
from backend.core.logger import logger
from backend.services.lint_output import (
    lint_output,
    semantic_lint_output,
    rewrite_output_if_needed,
    build_output_lint_log,
)
from backend.core.constants.nia_spine_v10 import NIA_SPINE_V10_VERSION
from backend.core.config import settings
from backend.services.speech_sanitizer import finalize_output

SSE_DEBUG_EVERY = int(__import__("os").getenv("SSE_DEBUG_EVERY", "50"))

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


class DefaultAgentOrchestrator:
    """
    Orchestrator skeleton.
    Responsibility split:
    - Input prep
    - Invoke core agent/graph
    - Stream transformation (SSE mapping stays in controller for now)
    """

    def __init__(
        self,
        *,
        memory: MemoryGateway,
        thought: ThoughtGateway,
        history: HistoryGateway,
        inner_monologue: InnerMonologueLogger,
        tools: ToolRegistry,
        checkpointer: CheckpointerGateway,
        memory_capture: MemoryCaptureGateway,
        capture_builder: CaptureBuilderGateway,
        vector_store: VectorGateway,
        telemetry: TelemetrySink,
        tts: TTSGateway,
        vision: VisionGateway,
    ) -> None:
        self._memory = memory
        self._thought = thought
        self._history = history
        self._inner_monologue = inner_monologue
        self._tools = tools
        self._checkpointer = checkpointer
        self._memory_capture = memory_capture
        self._capture_builder = capture_builder
        self._vector_store = vector_store
        self._telemetry = telemetry
        self._tts = tts
        self._vision = vision

    async def _telemetry_event(self, thread_id: str, event_type: str, payload: dict) -> None:
        try:
            await self._telemetry.event(thread_id, event_type, payload)
        except Exception:
            pass

    async def stream_chat(
        self,
        *,
        input_text: str,
        thread_id: str,
        voice_id: str,
        image_data: Optional[str],
        mode: str,
        stream_id: Optional[str],
        message_id: Optional[str],
    ) -> Iterable[dict]:
        """
        Temporary pass-through to existing core stream.
        Step 2 will migrate logic from controllers/agent.py here.
        """
        from backend.core.agent import run_agent_stream

        logger.debug("[Orchestrator] stream_chat passthrough thread=%s mode=%s", thread_id, mode)
        if not stream_id:
            async for ev in run_agent_stream(
                input_text=input_text,
                thread_id=thread_id,
                voice_id=voice_id,
                image_data=image_data,
                mode=mode,
                memory_refs={
                    "conversation_id": thread_id,
                    "message_id": message_id,
                    "stream_id": stream_id,
                },
                ports={
                    "memory": self._memory,
                    "thought": self._thought,
                    "history": self._history,
                    "inner_monologue": self._inner_monologue,
                    "tools": self._tools,
                    "checkpointer": self._checkpointer,
                    "memory_capture": self._memory_capture,
                    "capture_builder": self._capture_builder,
                    "vector_store": self._vector_store,
                    "telemetry": self._telemetry,
                    "tts": self._tts,
                    "vision": self._vision,
                },
            ):
                yield ev
            return

        llm_iter = run_agent_stream(
            input_text=input_text,
            thread_id=thread_id,
            voice_id=voice_id,
            image_data=image_data,
            mode=mode,
            memory_refs={
                "conversation_id": thread_id,
                "message_id": message_id,
                "stream_id": stream_id,
            },
            ports={
                "memory": self._memory,
                "thought": self._thought,
                "history": self._history,
                "inner_monologue": self._inner_monologue,
                "tools": self._tools,
                "checkpointer": self._checkpointer,
                "memory_capture": self._memory_capture,
                "capture_builder": self._capture_builder,
                "vector_store": self._vector_store,
                "telemetry": self._telemetry,
                "tts": self._tts,
                "vision": self._vision,
            },
        )
        async for ev in llm_iter:
            yield ev
        return

    async def stream_sse(
        self,
        *,
        input_text: str,
        thread_id: str,
        voice_id: str,
        image_data: Optional[str],
        mode: str,
        stream_id: Optional[str],
        message_id: Optional[str],
    ) -> Iterable[str]:
        """
        SSE-safe stream generator (moved from controller).
        """
        done_sent = False
        done_pending = False
        current_turn_id = None
        visible_ai_text = ""
        final_text: str | None = None
        stream_error: str | None = None
        stream_buffer = ""
        first_token_sent = False
        last_event: dict | None = None
        last_event_type: str | None = None
        last_raw_content_type: str | None = None
        debug_logged_other = False
        last_state_tag: str | None = None
        text_seq = 0
        output_lint_logged = False
        lint_message_id: str | None = None
        last_text_emit_ms = 0
        sse_min_interval_ms = int(getattr(settings, "SSE_MIN_INTERVAL_MS", 0) or 0)

        async def _apply_output_lint(text: str) -> tuple[str, list, list, list, bool]:
            # Evidence is optional; pass when available.
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

        async def _emit_output_lint_log(
            *,
            violations: list,
            post_violations: list,
            semantic_violations: list,
            rewrite_applied: bool,
            text_len_before: int,
            text_len_after: int,
        ) -> None:
            nonlocal output_lint_logged
            if output_lint_logged:
                return
            payload = build_output_lint_log(
                violations=violations,
                post_violations=post_violations,
                semantic_violations=semantic_violations,
                rewrite_applied=rewrite_applied,
                text_len_before=text_len_before,
                text_len_after=text_len_after,
                message_id=lint_message_id,
                thread_id=thread_id,
                turn_id=current_turn_id,
            )
            payload["spine_version"] = NIA_SPINE_V10_VERSION
            payload["spine_anchor_used"] = {
                "depth0": True,
                "rewrite": rewrite_applied,
                "gate": False,
            }
            d_lint = payload.get("dissonance_delta_lint") or 0.0
            if isinstance(d_lint, (int, float)) and d_lint > 0:
                await self._telemetry_event(
                    thread_id,
                    "telemetry_kv_add",
                    {"key": f"dissonance_lint_total:{thread_id}", "delta": float(d_lint)},
                )
            await self._telemetry_event(thread_id, "commit_log", payload)
            output_lint_logged = True

        def emit(event: dict) -> str:
            if stream_id:
                event = dict(event)
                event["stream_id"] = stream_id
            return _sse_json(event)

        async def _emit_text_append(part: str) -> str:
            nonlocal visible_ai_text, last_text_emit_ms
            if not part:
                return ""
            safe_part = str(part)
            visible_ai_text = str(visible_ai_text)
            visible_ai_text += safe_part
            if sse_min_interval_ms > 0:
                now = _ms()
                wait_ms = sse_min_interval_ms - (now - last_text_emit_ms)
                if wait_ms > 0:
                    await asyncio.sleep(wait_ms / 1000)
                last_text_emit_ms = _ms()
            return emit({"type": "text", "content": safe_part})

        try:
            from backend.services.chat_history_store import chat_history_store
            from backend.services.speech_sanitizer import detect_internal_leak, is_critical_leak, TAG_LINE_RE, INTERNAL_PLAN_LINE_RE, _looks_like_plan_line

            t0 = _ms()
            await self._telemetry_event(thread_id, "chat_received", {
                "user_len": len(input_text or ""),
                "has_image": bool(image_data),
            })

            # --- 画像をURL化（履歴保存用）---
            image_url = None
            if image_data:
                from backend.services.image_store import save_image_dataurl_to_file
                image_url, save_err = save_image_dataurl_to_file(image_data, thread_id=thread_id)
                if save_err:
                    logger.warning(f"[API] Failed to save image: {save_err}")
                else:
                    logger.info(f"[API] Image saved: {image_url}")

            current_turn_id = await chat_history_store.get_next_turn_id(thread_id)

            # content を OpenAI 互換の multipart 形式で構築
            if image_url:
                user_content = [
                    {"type": "text", "text": input_text or ""},
                    {"type": "image_url", "image_url": {"url": image_url}}
                ]
            else:
                user_content = {"text": input_text}

            user_message_id = await chat_history_store.append_message(
                thread_id=thread_id,
                turn_id=current_turn_id,
                role="user",
                content=user_content,
                attachments=[]
            )
            lint_message_id = str(message_id or user_message_id)

            await self._telemetry_event(thread_id, "stream_started", {
                "mode": "stream_chat",
            })

            # --- 夢配信（SSE開始直後、本編の前に1回だけ）---
            try:
                from backend.services.dream_store import claim_unread_dream
                dream = claim_unread_dream()
                if dream:
                    logger.info(f"[API] Delivering dream: {dream.id}")
                    yield emit({
                        "type": "dream",
                        "text": dream.dream_text,
                        "mood": dream.mood,
                        "dream_id": dream.id,
                        "created_at": dream.created_at,
                    })
            except Exception as e:
                logger.warning(f"[API] Dream delivery failed: {e}")

            async for ev in self.stream_chat(
                input_text=input_text,
                thread_id=thread_id,
                voice_id=voice_id,
                image_data=image_data,
                mode=mode,
                stream_id=stream_id,
                message_id=message_id or user_message_id,
            ):
                last_event = ev if isinstance(ev, dict) else {"type": "non_dict", "value": str(ev)}
                if not isinstance(ev, dict):
                    logger.error(f"non-dict event received: {type(ev)} {ev}")
                    yield emit({"type": "error", "content": f"Internal Error: non-dict event {type(ev)}"})
                    continue

                msg_type = ev.get("type")
                last_event_type = str(msg_type)

                if msg_type == "event" and ev.get("name") == "final_result":
                    payload = ev.get("payload") or {}
                    if isinstance(payload, dict):
                        ft = payload.get("final_text")
                        if isinstance(ft, str) and ft.strip():
                            final_text = ft
                    yield emit(ev)
                    continue

                if msg_type == "text":
                    if not _should_emit_text_event(ev):
                        continue
                    raw_content = ev.get("content", "")
                    chunk_content = "" if raw_content is None else str(raw_content)
                    last_raw_content_type = type(raw_content).__name__

                    if chunk_content:
                        text_seq += 1
                        if logger.isEnabledFor(logging.DEBUG):
                            if text_seq == 1 or (SSE_DEBUG_EVERY > 0 and text_seq % SSE_DEBUG_EVERY == 0):
                                logger.debug(
                                    "[DEBUG_SSE_TEXT] seq=%s stream_id=%s len=%s head=%s",
                                    text_seq,
                                    stream_id,
                                    len(chunk_content),
                                    chunk_content[:80],
                                )

                    if (not first_token_sent) and chunk_content:
                        first_token_sent = True
                        await self._telemetry_event(thread_id, "stream_first_token", {
                            "ms_from_start": _ms() - t0
                        })

                    stream_buffer = str(stream_buffer) + chunk_content

                    while "\n" in stream_buffer:
                        line, stream_buffer = stream_buffer.split("\n", 1)
                        stripped = line.strip()

                        if stripped and TAG_LINE_RE.fullmatch(stripped):
                            if not debug_logged_other:
                                if logger.isEnabledFor(logging.DEBUG):
                                    logger.debug("[DEBUG_SSE_EVENT] type=internal stream_id=%s", stream_id)
                                debug_logged_other = True
                            yield emit({"type": "internal", "content": stripped})
                            continue
                        if stripped and _looks_like_plan_line(stripped):
                            # Drop leaked planner bullets from stream output
                            continue

                        if line:
                            leak_reasons = detect_internal_leak(line)
                            if is_critical_leak(leak_reasons):
                                stream_error = "safety_block"
                                await self._telemetry_event(thread_id, "safety_block", {
                                    "scope": "stream_chat",
                                    "reasons": leak_reasons,
                                })
                            else:
                                res = await _emit_text_append(line + "\n")
                                if res:
                                    yield res
                        else:
                            res = await _emit_text_append("\n")
                            if res:
                                yield res

                    if stream_buffer and not stream_buffer.lstrip().startswith("[["):
                        # Drop leaked planner bullets even if no newline arrived.
                        # If plan line is glued to response (no newline), strip prefix only.
                        sb_stripped = stream_buffer.lstrip()
                        if _looks_like_plan_line(sb_stripped):
                            # Remove the leading plan line prefix; keep the rest
                            # (handles cases like "- Briefly ...マインクラフト...")
                            cleaned = INTERNAL_PLAN_LINE_RE.sub("", sb_stripped, count=1).lstrip()
                            stream_buffer = cleaned
                            if not stream_buffer:
                                continue
                        leak_reasons = detect_internal_leak(stream_buffer)
                        if is_critical_leak(leak_reasons):
                            stream_error = "safety_block"
                            await self._telemetry_event(thread_id, "safety_block", {
                                "scope": "stream_chat",
                                "reasons": leak_reasons,
                            })
                        else:
                            res = await _emit_text_append(stream_buffer)
                            if res:
                                yield res
                        stream_buffer = ""

                elif msg_type == "emotion":
                    if not debug_logged_other:
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug("[DEBUG_SSE_EVENT] type=emotion stream_id=%s payload=%s", stream_id, ev)
                        debug_logged_other = True
                    yield emit(ev)

                elif msg_type == "state":
                    tag = ev.get("tag") if isinstance(ev, dict) else None
                    if tag != last_state_tag:
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug("[DEBUG_SSE_EVENT] type=state stream_id=%s payload=%s", stream_id, ev)
                        last_state_tag = tag
                    yield emit(ev)

                elif msg_type == "gesture":
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug("[DEBUG_SSE_EVENT] type=gesture stream_id=%s payload=%s", stream_id, ev)
                    yield emit(ev)

                elif msg_type == "audio":
                    if not debug_logged_other:
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug("[DEBUG_SSE_EVENT] type=audio stream_id=%s", stream_id)
                        debug_logged_other = True
                    try:
                        payload = ev.get("data") or ev
                        logger.info("[SSE_AUDIO] stream_id=%s keys=%s", stream_id, list(payload.keys()) if isinstance(payload, dict) else type(payload))
                    except Exception:
                        logger.info("[SSE_AUDIO] stream_id=%s", stream_id)
                    yield emit(ev)

                elif msg_type == "error":
                    stream_error = str(ev.get("content") or "stream_error")
                    if not debug_logged_other:
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug("[DEBUG_SSE_EVENT] type=error stream_id=%s", stream_id)
                        debug_logged_other = True
                    yield emit(ev)

                elif msg_type == "done":
                    done_pending = True
                    if final_text:
                        linted, violations, post_violations, semantic_violations, rewrite_applied = await _apply_output_lint(final_text)
                        await _emit_output_lint_log(
                            violations=violations,
                            post_violations=post_violations,
                            semantic_violations=semantic_violations,
                            rewrite_applied=rewrite_applied,
                            text_len_before=len(final_text),
                            text_len_after=len(linted),
                        )
                        res = await _emit_text_append(linted)
                        if res:
                            yield res
                    if stream_buffer:
                        tail = stream_buffer
                        stream_buffer = ""
                        stripped = tail.strip()
                        if stripped and TAG_LINE_RE.fullmatch(stripped):
                            yield emit({"type": "internal", "content": stripped})
                        elif stripped and _looks_like_plan_line(stripped):
                            pass
                        else:
                            leak_reasons = detect_internal_leak(tail)
                            if is_critical_leak(leak_reasons):
                                stream_error = "safety_block"
                                await self._telemetry_event(thread_id, "safety_block", {
                                    "scope": "stream_chat",
                                    "reasons": leak_reasons,
                                })
                            else:
                                linted, violations, post_violations, semantic_violations, rewrite_applied = await _apply_output_lint(tail)
                                await _emit_output_lint_log(
                                    violations=violations,
                                    post_violations=post_violations,
                                    semantic_violations=semantic_violations,
                                    rewrite_applied=rewrite_applied,
                                    text_len_before=len(tail),
                                    text_len_after=len(linted),
                                )
                                res = await _emit_text_append(linted)
                                if res:
                                    yield res
                    if not debug_logged_other:
                        logger.info("[DEBUG_SSE_EVENT] type=done stream_id=%s", stream_id)
                        debug_logged_other = True
                    continue

                else:
                    if not debug_logged_other:
                        logger.info("[DEBUG_SSE_EVENT] type=%s stream_id=%s", msg_type, stream_id)
                        debug_logged_other = True
                    yield emit(ev)

        except Exception as e:
            stream_error = str(e)
            logger.exception(
                "safe_stream_generator failed: %s | types: visible_ai_text=%s stream_buffer=%s last_event_type=%s last_raw_content_type=%s last_event=%s",
                e,
                type(visible_ai_text).__name__,
                type(stream_buffer).__name__,
                last_event_type,
                last_raw_content_type,
                last_event,
            )
            yield emit({"type": "error", "content": str(e)})

        finally:
            try:
                from backend.services.chat_history_store import chat_history_store
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

                _raw_save = (final_text or visible_ai_text or "").strip()
                text_to_save = finalize_output(_raw_save) if _raw_save else ""
                done_for_log = done_sent or done_pending
                if current_turn_id is not None and text_to_save and not _looks_like_broken_output(text_to_save):
                    await chat_history_store.append_message(
                        thread_id=thread_id,
                        turn_id=current_turn_id,
                        role="assistant",
                        content={
                            "text": text_to_save,
                            "meta": {
                                "incomplete": not done_for_log,
                                "error": bool(stream_error)
                            }
                        },
                        attachments=[]
                    )

                    if done_for_log:
                        await self._telemetry_event(thread_id, "chat_completed", {
                            "len": len(text_to_save),
                            "ms": _ms() - t0
                        })
            except Exception as log_err:
                logger.warning(f"A-layer assistant log failed: {log_err}")

            if not done_sent:
                yield emit({"type": "done"})
                done_sent = True

    async def collect_text_from_agent_stream(self, input_text: str, thread_id: str) -> str:
        """
        run_agent_stream を内部で回し、type=text の content だけ結合して返す。
        """
        full_text = ""
        try:
            async for chunk in self.stream_chat(input_text=input_text, thread_id=thread_id, voice_id="14", image_data=None, mode="normal", stream_id=None, message_id=None):
                if isinstance(chunk, dict):
                    if chunk.get("type") == "text":
                        content = chunk.get("content", "")
                        full_text += "" if content is None else str(content)
                    elif chunk.get("type") == "done":
                        break
                    continue

                chunk_str = _ensure_str(chunk).strip()
                if not chunk_str.startswith("data: "):
                    continue

                payload = chunk_str[6:].strip()
                if payload == "[DONE]":
                    break

                try:
                    data = json.loads(payload)
                except Exception:
                    continue

                if isinstance(data, dict):
                    if data.get("type") == "text":
                        content = data.get("content", "")
                        full_text += "" if content is None else str(content)
                    elif data.get("type") == "done":
                        break

        except Exception as e:
            logger.error(f"collect_text_from_agent_stream failed: {e}")

        return full_text

    async def run_non_stream(
        self,
        *,
        input_text: str,
        thread_id: str,
        voice_id: str,
        image_data: Optional[str],
        mode: str,
    ) -> dict:
        from backend.core.agent import run_agent_non_stream

        return await run_agent_non_stream(
            input_text=input_text,
            thread_id=thread_id,
            voice_id=voice_id,
            image_data=image_data,
            mode=mode,
            ports={
                "memory": self._memory,
                "thought": self._thought,
                "history": self._history,
                "inner_monologue": self._inner_monologue,
                "tools": self._tools,
                "checkpointer": self._checkpointer,
                "memory_capture": self._memory_capture,
                "vector_store": self._vector_store,
                "telemetry": self._telemetry,
                "tts": self._tts,
                "vision": self._vision,
            },
        )

_default_orchestrator: DefaultAgentOrchestrator | None = None

def build_default_orchestrator() -> DefaultAgentOrchestrator:
    from backend.services.memory_manager import memory_manager
    from backend.services.thought_engine import thought_engine
    from backend.services.telemetry_logger import telemetry
    from backend.services.voicevox_client import voicevox_client
    from backend.services.vision_client import build_user_input_with_image
    from backend.services.chat_history_store import chat_history_store
    from backend.services.inner_monologue_logger import log_inner_thought
    from backend.services.tools import tools as _tools
    from backend.services.memory_judge import build_capture

    class _VisionGateway:
        async def build_user_input(self, text: str, image_data: Optional[str]) -> str:
            if not image_data:
                return text
            return await build_user_input_with_image(text, image_data)

    class _TTSGateway:
        def __init__(self) -> None:
            self._meta_by_url: dict[str, dict] = {}
            # Default speaker ID for VOICEVOX (ずんだもん)
            self._default_speaker_id = 3

        async def generate_audio_url(
            self,
            text: str,
            voice_id: str,
            thread_id: str,
            stream_id: Optional[str] = None,
        ) -> Optional[str]:
            import time
            logger.info(
                "[TTS_WORKER] start text_len=%s voice_id=%s stream_id=%s",
                len(text or ""),
                str(voice_id),
                str(stream_id),
            )

            t0 = time.perf_counter()
            
            def _run() -> Optional[tuple[str, dict]]:
                # Convert voice_id to VOICEVOX speaker ID
                try:
                    speaker_id = int(voice_id)
                except (ValueError, TypeError):
                    speaker_id = self._default_speaker_id
                
                url = voicevox_client.generate_audio_to_file(text, speaker_id, thread_id)
                if not url:
                    return None
                
                gen_ms = int((time.perf_counter() - t0) * 1000)
                meta = {
                    "url": url,
                    "text_content": text,
                    "is_silence": False,
                    "gen_ms": gen_ms,
                    "duration_ms": 0,  # VOICEVOX doesn't return duration
                }
                return url, meta

            out = await asyncio.to_thread(_run)
            if not out:
                return None
            url, meta = out
            self._meta_by_url[url] = meta
            return url

        async def get_audio_meta(self, url: str) -> Optional[dict]:
            return self._meta_by_url.get(url)

        async def generate_audio(self, text: str, voice_id: str) -> Optional[bytes]:
            loop = __import__("asyncio").get_running_loop()

            def _run() -> Optional[bytes]:
                try:
                    speaker_id = int(voice_id)
                except (ValueError, TypeError):
                    speaker_id = self._default_speaker_id
                return voicevox_client.generate_audio(text, speaker_id)

            return await loop.run_in_executor(None, _run)

    class _HistoryGateway:
        async def get_history(self, thread_id: str, *, limit: int = 60) -> list[dict]:
            return await chat_history_store.get_history(thread_id, limit=limit)

    class _InnerMonologueLogger:
        def log(self, data: dict) -> None:
            log_inner_thought(data)

    class _ToolRegistry:
        def get_tools(self) -> list:
            return _tools

    class _CaptureBuilder:
        def build_capture(self, *, thread_id: str, raw_text: str, state_tag: Optional[str], emotion_tags: Optional[list[str]] = None, refs: Optional[dict] = None) -> dict:
            return build_capture(
                thread_id=thread_id,
                raw_text=raw_text,
                state_tag=state_tag,
                emotion_tags=emotion_tags,
                refs=refs,
            )

    class _VectorGateway:
        async def register_candidate(self, text: str, meta: dict, collection: str) -> None:
            await __import__("asyncio").to_thread(
                memory_manager.vector_store.register_memory_candidate,
                text,
                meta,
                collection,
            )

    return DefaultAgentOrchestrator(
        memory=memory_manager,
        thought=thought_engine,
        history=_HistoryGateway(),
        inner_monologue=_InnerMonologueLogger(),
        tools=_ToolRegistry(),
        checkpointer=memory_manager,
        memory_capture=chat_history_store,
        capture_builder=_CaptureBuilder(),
        vector_store=_VectorGateway(),
        telemetry=telemetry,
        tts=_TTSGateway(),
        vision=_VisionGateway(),
    )

def get_default_orchestrator() -> DefaultAgentOrchestrator:
    global _default_orchestrator
    if _default_orchestrator is None:
        _default_orchestrator = build_default_orchestrator()
    return _default_orchestrator


__all__ = ["DefaultAgentOrchestrator", "build_default_orchestrator", "get_default_orchestrator"]
