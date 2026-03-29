from __future__ import annotations

import json
import time
import asyncio
from typing import Optional, Iterable

from backend.core.ports import MemoryGateway, ThoughtGateway, TelemetrySink, TTSGateway, VisionGateway, HistoryGateway, InnerMonologueLogger, ToolRegistry, CheckpointerGateway, MemoryCaptureGateway, VectorGateway, CaptureBuilderGateway
from backend.core.logger import logger
from backend.core.config import settings
from backend.services.sse_pipeline import (
    SSEContext,
    _ms,
    _ensure_str,
    _sse_emit,
    _should_emit_text_event,
    _handle_sse_text,
    _handle_sse_done,
    _persist_stream_result,
    strip_think_leaks,
)


# ── Orchestrator class ───────────────────────────────────────

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

    async def _broadcast_conversation_state(self, state: str) -> None:
        """Contract 3: Broadcast conversation state transition to Unity WS clients."""
        if not getattr(settings, "RUNTIME_FACTS_ENABLED", False):
            return
        try:
            from backend.controllers.ws_room import room_manager
            await room_manager.broadcast_conversation_state(state)
        except Exception:
            logger.debug("[ORCHESTRATOR] conversation_state broadcast failed", exc_info=True)

    def _build_ports(self) -> dict:
        """Build ports dict for run_agent_stream / run_agent_non_stream."""
        return {
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
        }

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
        turn_id: Optional[str] = None,
        test_mode: bool = False,
    ) -> Iterable[dict]:
        """Pass-through to core agent stream."""
        from backend.core.agent import run_agent_stream

        logger.debug("[Orchestrator] stream_chat passthrough thread=%s mode=%s test_mode=%s", thread_id, mode, test_mode)
        async for ev in run_agent_stream(
            input_text=input_text,
            thread_id=thread_id,
            voice_id=voice_id,
            image_data=image_data,
            mode=mode,
            memory_refs={
                "conversation_id": thread_id,
                "turn_id": turn_id,
                "message_id": message_id,
                "stream_id": stream_id,
                "test_mode": test_mode,
            },
            ports=self._build_ports(),
        ):
            yield ev

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
        test_mode: bool = False,
    ) -> Iterable[str]:
        """SSE-safe stream generator (moved from controller)."""
        sctx = SSEContext(
            thread_id=thread_id,
            stream_id=stream_id,
            sse_min_interval_ms=int(getattr(settings, "SSE_MIN_INTERVAL_MS", 0) or 0),
            t0=_ms(),
            test_mode=bool(test_mode),
        )

        def emit(event: dict) -> str:
            return _sse_emit(event, stream_id)

        try:
            from backend.services.chat_history_store import chat_history_store

            if not test_mode:
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

            sctx.current_turn_id = await chat_history_store.get_next_turn_id(thread_id)

            # content を OpenAI 互換の multipart 形式で構築
            if image_url:
                user_content = [
                    {"type": "text", "text": input_text or ""},
                    {"type": "image_url", "image_url": {"url": image_url}}
                ]
            else:
                user_content = {"text": input_text}
                if test_mode:
                    user_content["meta"] = {"test_mode": True}

            user_message_id = await chat_history_store.append_message(
                thread_id=thread_id,
                turn_id=sctx.current_turn_id,
                role="user",
                content=user_content,
                attachments=[]
            )
            sctx.lint_message_id = str(message_id or user_message_id)

            if not test_mode:
                await self._telemetry_event(thread_id, "stream_started", {
                    "mode": "stream_chat",
                })

            # --- 夢配信（SSE開始直後、本編の前に1回だけ）---
            if not test_mode:
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

            # Contract 3: Broadcast conversation state transitions
            await self._broadcast_conversation_state("listening")

            # Contract 3: LISTENING → THINKING when LLM processing begins
            await self._broadcast_conversation_state("thinking")

            # ── Main event loop (dispatch to handlers) ──
            async for ev in self.stream_chat(
                input_text=input_text,
                thread_id=thread_id,
                voice_id=voice_id,
                image_data=image_data,
                mode=mode,
                stream_id=stream_id,
                message_id=message_id or user_message_id,
                turn_id=str(sctx.current_turn_id) if sctx.current_turn_id is not None else None,
                test_mode=test_mode,
            ):
                sctx.last_event = ev if isinstance(ev, dict) else {"type": "non_dict", "value": str(ev)}
                if not isinstance(ev, dict):
                    logger.error(f"non-dict event received: {type(ev)} {ev}")
                    yield emit({"type": "error", "content": f"Internal Error: non-dict event {type(ev)}"})
                    continue

                msg_type = ev.get("type")
                sctx.last_event_type = str(msg_type)

                if msg_type == "event" and ev.get("name") == "final_result":
                    # Contract 3: THINKING → SPEAKING when response is ready
                    await self._broadcast_conversation_state("speaking")
                    payload = ev.get("payload") or {}
                    if isinstance(payload, dict):
                        ft = payload.get("final_text")
                        if isinstance(ft, str) and ft.strip():
                            # Safety net: strip <think> blocks + orphan </think>
                            ft = strip_think_leaks(ft)
                            payload["final_text"] = ft
                            sctx.final_text = ft
                    yield emit(ev)
                elif msg_type == "text":
                    for sse_str in await _handle_sse_text(sctx, ev, self):
                        yield sse_str
                elif msg_type in ("emotion", "gesture", "audio"):
                    yield emit(ev)
                elif msg_type == "state":
                    tag = ev.get("tag") if isinstance(ev, dict) else None
                    if tag != sctx.last_state_tag:
                        sctx.last_state_tag = tag
                    yield emit(ev)
                elif msg_type == "error":
                    sctx.stream_error = str(ev.get("content") or "stream_error")
                    yield emit(ev)
                elif msg_type == "done":
                    for sse_str in await _handle_sse_done(sctx, ev, self):
                        yield sse_str
                else:
                    yield emit(ev)

        except Exception as e:
            sctx.stream_error = str(e)
            logger.exception(
                "safe_stream_generator failed: %s | types: visible_ai_text=%s stream_buffer=%s last_event_type=%s last_raw_content_type=%s last_event=%s",
                e,
                type(sctx.visible_ai_text).__name__,
                type(sctx.stream_buffer).__name__,
                sctx.last_event_type,
                sctx.last_raw_content_type,
                sctx.last_event,
            )
            yield emit({"type": "error", "content": str(e)})

        finally:
            await _persist_stream_result(sctx, self)
            if not sctx.done_sent:
                yield emit({"type": "done"})
                sctx.done_sent = True

    async def collect_text_from_agent_stream(self, input_text: str, thread_id: str) -> str:
        """
        run_agent_stream を内部で回し、最終テキストを返す。

        final_result イベントの final_text（merge 済み・タグ除去済み）を優先。
        なければストリーミングチャンクの結合テキストにフォールバック。
        """
        import uuid as _uuid
        streaming_text = ""
        final_text = ""
        try:
            async for chunk in self.stream_chat(input_text=input_text, thread_id=thread_id, voice_id="14", image_data=None, mode="normal", stream_id=_uuid.uuid4().hex, message_id=_uuid.uuid4().hex):
                if isinstance(chunk, dict):
                    if chunk.get("type") == "text":
                        content = chunk.get("content", "")
                        streaming_text += "" if content is None else str(content)
                    elif chunk.get("type") == "event" and chunk.get("name") == "final_result":
                        ft = (chunk.get("payload") or {}).get("final_text", "")
                        if ft and ft != "WAIT":
                            final_text = ft
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
                        streaming_text += "" if content is None else str(content)
                    elif data.get("type") == "event" and data.get("name") == "final_result":
                        ft = (data.get("payload") or {}).get("final_text", "")
                        if ft and ft != "WAIT":
                            final_text = ft
                    elif data.get("type") == "done":
                        break

        except Exception as e:
            logger.error(f"collect_text_from_agent_stream failed: {e}")

        result = final_text or streaming_text
        # Strip <think>...</think> blocks and orphan </think>
        result = strip_think_leaks(result)
        return result

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
            ports=self._build_ports(),
        )

_default_orchestrator: DefaultAgentOrchestrator | None = None

def build_default_orchestrator() -> DefaultAgentOrchestrator:
    from backend.services.memory_manager import memory_manager
    from backend.services.checkpointer import checkpointer_service
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
        checkpointer=checkpointer_service,
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
