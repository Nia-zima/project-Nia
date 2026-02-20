from __future__ import annotations

import asyncio
from os import getenv
from typing import Any
import base64

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel

from backend.core.logger import logger
from backend.services.stt_service import stt_service, StreamingDecoder
from backend.services.voice_session_manager import voice_session_manager

router = APIRouter()


def _allowed_ws_origins() -> set[str]:
    raw = getenv(
        "VOICE_WS_ALLOWED_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001",
    )
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def _is_ws_origin_allowed(origin: str | None) -> bool:
    if not origin:
        return True
    allowed = _allowed_ws_origins()
    if "*" in allowed:
        return True
    return origin.strip().lower() in allowed


def _voice_verbose_log() -> bool:
    raw = str(getenv("VOICE_VERBOSE_LOG", "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


class VoiceSessionStartRequest(BaseModel):
    thread_id: str = "default_thread"
    client_id: str = "default_client"


class VoiceSessionStopRequest(BaseModel):
    session_id: str
    reason: str = "stopped"


@router.post("/voice/session/start")
async def voice_session_start(req: VoiceSessionStartRequest) -> dict[str, Any]:
    session = await voice_session_manager.start_session(
        thread_id=req.thread_id,
        client_id=req.client_id,
    )
    return {"ok": True, "session": session}


@router.post("/voice/session/stop")
async def voice_session_stop(req: VoiceSessionStopRequest) -> dict[str, Any]:
    session = await voice_session_manager.stop_session(
        session_id=req.session_id,
        reason=req.reason,
    )
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    return {"ok": True, "session": session}


@router.get("/voice/session/{session_id}")
async def voice_session_get(session_id: str) -> dict[str, Any]:
    session = await voice_session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    return {"ok": True, "session": session}


@router.websocket("/voice/ws")
async def voice_ws(websocket: WebSocket, session_id: str, client_id: str = "default_client") -> None:
    origin = websocket.headers.get("origin")
    if not _is_ws_origin_allowed(origin):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    session = await voice_session_manager.get_session(session_id)
    if not session:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    if str(session.get("client_id") or "") != client_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    verbose_log = _voice_verbose_log()
    await websocket.accept()
    await voice_session_manager.attach_connection(session_id)
    latest = await voice_session_manager.get_session(session_id)
    await websocket.send_json({"type": "voice_session_state", "session": latest})
    logger.info("[VOICE_WS] connected session_id=%s client_id=%s", session_id, client_id)
    turns: dict[str, dict[str, Any]] = {}

    def _turn_state(utterance_id: str) -> dict[str, Any]:
        state = turns.get(utterance_id)
        if state is not None:
            return state
        state: dict[str, Any] = {
            "decoder": None,       # StreamingDecoder（最初のチャンクで作成）
            "chunk_count": 0,
            "last_partial": "",
            "last_seq": -1,
        }
        turns[utterance_id] = state
        # runaway protection for old orphan utterances
        if len(turns) > 8:
            oldest = next(iter(turns.keys()))
            if oldest != utterance_id:
                old_state = turns.pop(oldest, None)
                if old_state and old_state.get("decoder"):
                    old_state["decoder"].cleanup()
        return state

    try:
        while True:
            current = await voice_session_manager.get_session(session_id)
            if not current or current.get("ended_at"):
                await websocket.send_json({"type": "voice_session_closed"})
                break

            message = await websocket.receive_json()
            msg_type = str(message.get("type") or "").strip().lower()
            await voice_session_manager.touch(session_id)

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            if msg_type == "barge_in":
                await websocket.send_json({"type": "barge_in_ack"})
                continue

            # Step 1 placeholder for upcoming audio chunks
            if msg_type in {"voice_chunk", "audio_chunk"}:
                seq = message.get("seq")
                try:
                    seq_int = int(seq)
                except Exception:
                    seq_int = -1
                utterance_id = str(message.get("utterance_id") or "default")
                payload_b64 = str(message.get("payload_b64") or "")
                mime_type = str(message.get("mime_type") or "audio/webm")
                state = _turn_state(utterance_id)
                if seq_int >= 0 and seq_int <= int(state["last_seq"]):
                    await websocket.send_json(
                        {"type": "voice_chunk_ack", "seq": seq, "utterance_id": utterance_id, "duplicate": True}
                    )
                    continue
                if seq_int >= 0:
                    state["last_seq"] = seq_int
                if payload_b64:
                    try:
                        chunk_bytes = base64.b64decode(payload_b64)
                        if chunk_bytes:
                            # StreamingDecoder が無ければ作成（最初のチャンク = webm header）
                            if state["decoder"] is None:
                                state["decoder"] = StreamingDecoder(stt_service.ffmpeg_bin, mime_type, max_buffer_bytes=stt_service.max_buffer_bytes)
                            # チャンクを ffmpeg に feed（リアルタイムで PCM 変換）
                            await asyncio.to_thread(state["decoder"].feed, chunk_bytes)
                            state["chunk_count"] = int(state["chunk_count"]) + 1
                    except Exception:
                        logger.warning("[VOICE_WS] failed to decode voice_chunk base64 seq=%s", str(seq))
                await websocket.send_json({"type": "voice_chunk_ack", "seq": seq, "utterance_id": utterance_id})

                # opportunistic partial transcript every few chunks
                interval = max(1, int(getattr(stt_service, "partial_interval_chunks", 8)))
                min_partial_pcm = max(0, int(getattr(stt_service, "partial_min_buffer_bytes", 0)))
                decoder = state.get("decoder")
                if (
                    decoder is not None
                    and int(state["chunk_count"]) > 0
                    and int(state["chunk_count"]) % interval == 0
                ):
                    pcm = decoder.get_pcm()
                    if pcm and len(pcm) >= min_partial_pcm:
                        stt_res = await stt_service.transcribe_pcm_bytes(pcm)
                        text = str(stt_res.get("text") or "").strip()
                        if text and text != str(state["last_partial"]):
                            state["last_partial"] = text
                            await websocket.send_json(
                                {
                                    "type": "stt_partial",
                                    "utterance_id": utterance_id,
                                    "text": text,
                                    "provider": stt_res.get("provider"),
                                }
                            )
                continue

            if msg_type in {"voice_turn_end", "audio_turn_end"}:
                utterance_id = str(message.get("utterance_id") or "default")
                source = str(message.get("source") or "unknown")
                speech_ms = message.get("speech_ms")
                chunks = message.get("chunks")
                rms = message.get("rms")
                state = _turn_state(utterance_id)
                decoder = state.get("decoder")
                pcm_len = len(decoder.get_pcm()) if decoder else 0
                turn_log = (
                    "[VOICE_WS] turn_end source=%s utterance=%s chunks=%s speech_ms=%s rms=%s pcm_bytes=%s"
                )
                turn_args = (
                    source,
                    utterance_id,
                    str(chunks),
                    str(speech_ms),
                    str(rms),
                    pcm_len,
                )
                if verbose_log:
                    logger.info(turn_log, *turn_args)
                else:
                    logger.debug(turn_log, *turn_args)

                # StreamingDecoder から最終 PCM を取得して transcribe
                if decoder:
                    pcm = await asyncio.to_thread(decoder.finish)
                    if pcm:
                        stt_res = await stt_service.transcribe_pcm_bytes(pcm)
                    else:
                        stt_res = {"ok": False, "text": "", "provider": stt_service.provider, "reason": "no pcm"}
                    decoder.cleanup()
                else:
                    stt_res = {"ok": False, "text": "", "provider": stt_service.provider, "reason": "no decoder"}

                text = str(stt_res.get("text") or "").strip()
                if not text and state["last_partial"]:
                    # 最終確定が空でも、直近partialがあれば救済して確定扱いにする
                    text = str(state["last_partial"])
                await websocket.send_json(
                    {
                        "type": "stt_final",
                        "utterance_id": utterance_id,
                        "text": text,
                        "provider": stt_res.get("provider"),
                        "ok": bool(stt_res.get("ok")),
                        "reason": stt_res.get("reason"),
                    }
                )
                turns.pop(utterance_id, None)
                continue

            await websocket.send_json({"type": "ack", "received_type": msg_type or "unknown"})
    except WebSocketDisconnect:
        logger.info("[VOICE_WS] disconnected session_id=%s client_id=%s", session_id, client_id)
    except Exception:
        logger.exception("[VOICE_WS] error session_id=%s client_id=%s", session_id, client_id)
    finally:
        # 残っている StreamingDecoder を cleanup
        for _uid, _st in turns.items():
            dec = _st.get("decoder")
            if dec:
                dec.cleanup()
        turns.clear()
        await voice_session_manager.detach_connection(session_id)
