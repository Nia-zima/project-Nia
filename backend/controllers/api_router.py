import json
import re
import time
import asyncio
import logging
import uuid # Added for request ID
from typing import Any, Dict, Optional, List

from backend.services.telemetry_logger import telemetry

def _ms() -> int:
    return int(time.time() * 1000)

from backend.services.tool_tag_parser import parse_tool_tags
from backend.services.memory_manager import memory_manager

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from backend.scripts.sleep_cycle import integrated_sleep_cycle
from backend.scripts.chapter_reflection import ChapterEngine

from backend.core.logger import logger

router = APIRouter(prefix="/api", tags=["api"])



# --- Helpers ---
_AFFECT_RE = re.compile(r"^\[([A-Za-z0-9_\-]+)\]\s*(.*)$", re.DOTALL)

def _split_affect(text: str) -> tuple[str | None, str]:
    """
    "[neutral] hello" -> ("neutral", "hello")
    Otherwise -> (None, original)
    """
    if not text:
        return None, text
    m = _AFFECT_RE.match(text.strip())
    if not m:
        return None, text
    affect = m.group(1)
    body = m.group(2)
    return affect, body


# ---------- Request Models ----------

class StreamChatRequest(BaseModel):
    text: str # Changed from message to text to match frontend
    thread_id: str = "default_thread"
    voice_id: Optional[str] = "14"
    image_data: Optional[str] = None
    mode: Optional[str] = "normal" # Added mode field


class LivestreamChatRequest(BaseModel):
    text: str
    thread_id: str = "live_stream"
    audience_meta: Optional[Dict[str, Any]] = None


# ---------- Helpers ----------

def _ensure_str(chunk: Any) -> str:
    if isinstance(chunk, (bytes, bytearray)):
        return chunk.decode("utf-8", errors="ignore")
    return str(chunk)


def _sse_json(obj: Dict[str, Any]) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


async def _safe_stream_generator(
    input_text: str,
    thread_id: str,
    voice_id: str,
    image_data: Optional[str] = None,
    mode: str = "normal",
):
    """
    Agentのイベント辞書を受け取り、統一的にSSEに変換して送出する。
    - run_agent_stream は純粋な dict を yield する (data: 接頭辞なし)
    - _sse_json() が唯一の SSE 化責任を持つ
    - 思考プロセスの隠蔽(Filter)はここで継続
    """
    done_sent = False
    current_turn_id = None
    visible_ai_text = ""
    stream_error: str | None = None

    # Helper to emit SSE
    def emit(event: dict) -> str:
        return _sse_json(event)

    def _emit_text_append(part: str) -> str:
        nonlocal visible_ai_text
        if not part:
            return ""
        visible_ai_text += part
        return emit({"type": "text", "content": part})

    try:
        # ★ Lazy import
        from backend.core.agent import run_agent_stream
        from backend.services.chat_history_store import chat_history_store

        t0 = _ms()
        # 1) chat_received
        await telemetry.event(thread_id, "chat_received", {
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
        
        # --- A-Layer: Log User Message (OpenAI互換形式) ---
        current_turn_id = await chat_history_store.get_next_turn_id(thread_id)
        
        # content を OpenAI 互換の multipart 形式で構築
        if image_url:
            user_content = [
                {"type": "text", "text": input_text or ""},
                {"type": "image_url", "image_url": {"url": image_url}}
            ]
        else:
            user_content = {"text": input_text}
        
        await chat_history_store.append_message(
            thread_id=thread_id,
            turn_id=current_turn_id,
            role="user",
            content=user_content,
            attachments=[] 
        )
        
        first_token_sent = False
        
        # --- Tool Hiding State ---
        tool_hidden_mode = False
        stream_buffer = "" 
        
        # 2) stream_started
        await telemetry.event(thread_id, "stream_started", {
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
            # 夢配信は失敗しても本編に影響させない
            logger.warning(f"[API] Dream delivery failed: {e}")

        async for ev in run_agent_stream(
            input_text=input_text,
            thread_id=thread_id,
            voice_id=voice_id,
            image_data=image_data,
            mode=mode,
        ):
            # ev is expected to be a dict
            if not isinstance(ev, dict):
                 logger.error(f"non-dict event received: {type(ev)} {ev}")
                 yield emit({"type": "error", "content": f"Internal Error: non-dict event {type(ev)}"})
                 continue

            msg_type = ev.get("type")

            # --- TEXT: Apply Filter ---
            if msg_type == "text":
                chunk_content = ev.get("content", "")
                
                # (Telemetry for first token if needed)
                if (not first_token_sent) and chunk_content:
                    first_token_sent = True
                    await telemetry.event(thread_id, "stream_first_token", {
                        "ms_from_start": _ms() - t0
                    })

                # --- ROBUST FILTER LOGIC ---
                stream_buffer += chunk_content
                
                while stream_buffer:
                    if tool_hidden_mode:
                        # In hidden mode, look for end tag "]]"
                        end_idx = stream_buffer.find("]]")
                        if end_idx != -1:
                            tool_hidden_mode = False
                            stream_buffer = stream_buffer[end_idx+2:]
                        else:
                            stream_buffer = "" # All hidden / consumed
                            break
                    else:
                        # In visible mode, look for start tag "[["
                        start_idx = stream_buffer.find("[[")
                        if start_idx != -1:
                            # Yield visible part before tag
                            visible_part = stream_buffer[:start_idx]
                            if visible_part:
                                res = _emit_text_append(visible_part)
                                if res: yield res
                            
                            tool_hidden_mode = True
                            stream_buffer = stream_buffer[start_idx:]
                        else:
                            # Check for partial tag at end (e.g. "[")
                            if stream_buffer.endswith("["):
                                visible_part = stream_buffer[:-1]
                                if visible_part:
                                    res = _emit_text_append(visible_part)
                                    if res: yield res
                                stream_buffer = "[" 
                            else:
                                # Safe to yield all
                                res = _emit_text_append(stream_buffer)
                                if res: yield res
                                stream_buffer = ""
                            break
            
            # --- AUDIO ---
            elif msg_type == "audio":
                # Phase A: Pass-through (base64 in 'audio' field)
                # Phase B: Will change to URL
                yield emit(ev)

            # --- ERROR ---
            elif msg_type == "error":
                yield emit(ev)

            # --- DONE ---
            elif msg_type == "done":
                done_sent = True
                yield emit({"type": "done"})
                break
            
            # --- META / DEBUG / OTHER ---
            else:
                yield emit(ev)

    except Exception as e:
        stream_error = str(e)
        logger.error(f"safe_stream_generator failed: {e}")
        yield emit({"type": "error", "content": str(e)})

    finally:
        # A-Layer: Log Assistant Message (Visible Text Only)
        try:
            if current_turn_id is not None and visible_ai_text:
                await chat_history_store.append_message(
                    thread_id=thread_id,
                    turn_id=current_turn_id,
                    role="assistant",
                    content={
                        "text": visible_ai_text,
                        "meta": {
                            "incomplete": not done_sent,
                            "error": bool(stream_error)
                        }
                    },
                    attachments=[]
                )
                
                # Telemetry
                if done_sent:
                     try:
                        await telemetry.event(thread_id, "chat_completed", {
                            "len": len(visible_ai_text),
                            "ms": _ms() - t0
                        })
                     except: pass

        except Exception as log_err:
            logger.warning(f"A-layer assistant log failed: {log_err}")
        
        # Last resort DONE
        if not done_sent:
            yield emit({"type": "done"})


async def _collect_text_from_agent_stream(input_text: str, thread_id: str) -> str:
    """
    run_agent_stream(SSE) を内部で回し、type=text の content だけ結合して返す。
    [DONE] / {"type":"done"} 両対応。
    """
    full_text = ""

    try:
        from backend.core.agent import run_agent_stream

        async for chunk in run_agent_stream(input_text=input_text, thread_id=thread_id):
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
                    full_text += data.get("content", "")
                elif data.get("type") == "done":
                    break

    except Exception as e:
        logger.error(f"collect_text_from_agent_stream failed: {e}")

    return full_text


# ---------- Endpoints ----------

@router.post("/stream_chat")
async def stream_chat(req: StreamChatRequest, request: Request):
    # SSE Streaming (Phase 3: Plan B - Canonical)
    # ストリーミングを復活させ、_safe_stream_generator で安全に中継・整形する。
    # API Router が唯一の入り口となる。
    
    rid = uuid.uuid4().hex[:8]
    logger.info(f"[CHAT_START] rid={rid} from={request.client.host} mode={req.mode}")
    logger.info(f"📨 Chat Request (SSE): {req.text[:20]}... (Thread: {req.thread_id}) Mode: {req.mode}")

    return StreamingResponse(
        _safe_stream_generator(
            input_text=req.text,
            thread_id=req.thread_id,
            voice_id=req.voice_id,
            image_data=req.image_data,
            mode=req.mode
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/livestream_chat")
async def livestream_chat(req: LivestreamChatRequest) -> Dict[str, Any]:
    """
    配信コメント用: JSON一括返却
    - 内部でストリームを消費してテキスト結合
    """
    text = (req.message or "").strip()
    if not text:
        return {"ok": True, "thread_id": req.thread_id, "response": ""}

    resp_text = await _collect_text_from_agent_stream(text, req.thread_id)
    return {"ok": True, "thread_id": req.thread_id, "response": resp_text}


@router.get("/history/{thread_id}")
async def get_history(thread_id: str):
    """
    会話履歴取得
    - Agent側の get_thread_history を呼ぶ (Lazy Import)
    """
    try:
        from backend.core.agent import get_thread_history
        hist = await get_thread_history(thread_id)
        return {"ok": True, "history": hist}
    except Exception as e:
        logger.warning(f"History fetch failed: {e}")
        return {"ok": True, "history": []}



@router.get("/memories")
def list_recent_memories(limit: int = 50):
    """Retrieve recent episodes/memories"""
    from backend.services.memory_manager import memory_manager
    return memory_manager.get_recent_memories(limit)

@router.post("/reset")
async def reset(thread_id: str = "default_thread") -> Dict[str, Any]:
    return {"ok": True, "thread_id": thread_id}

@router.post("/system/sleep")
async def trigger_sleep_cycle(background_tasks: BackgroundTasks):
    """手動で睡眠サイクル（記憶整理）を発火させる"""
    logger.info("💤 Manual Sleep Cycle Triggered via API")
    background_tasks.add_task(integrated_sleep_cycle)
    return {"status": "ok", "message": "Sleep cycle initiated."}

@router.post("/system/reflect")
async def trigger_reflection(background_tasks: BackgroundTasks):
    """手動で週次振り返り（Reflection）を発火させる"""
    logger.info("🧬 Manual Reflection Triggered via API")
    engine = ChapterEngine()
    background_tasks.add_task(engine.reflect, days=7)
    return {"status": "ok", "message": "Reflection started."}

class VisionRequest(BaseModel):
    enabled: bool

# --- Profile API ---
class UserProfile(BaseModel):
    user_name: str
    bio: str = ""
    interests: List[str] = []
    traits: List[str] = []

@router.get("/profile")
async def get_user_profile():
    from backend.core.config import settings, PROJECT_ROOT
    json_path = PROJECT_ROOT / settings.USER_PROFILE_JSON
    
    if json_path.exists():
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})
    else:
        # Return default structure if missing
        return {
            "user_name": "Origin",
            "bio": "",
            "interests": [],
            "traits": []
        }

@router.post("/profile")
async def update_user_profile(profile: UserProfile):
    from backend.core.config import settings, PROJECT_ROOT
    json_path = PROJECT_ROOT / settings.USER_PROFILE_JSON
    
    # Load existing to preserve 'stats' or extra fields not in model
    existing = {}
    if json_path.exists():
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                existing = json.load(f)
        except: pass
        
    # Merge updates
    updated_data = {**existing, **profile.model_dump()}
    
    try:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(updated_data, f, ensure_ascii=False, indent=2)
        return {"status": "success", "profile": updated_data}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/status")
async def get_public_status():
    """フロントエンドがポーリングする公開ステータス"""
    from backend.core.config import settings, PROJECT_ROOT
    json_path = PROJECT_ROOT / settings.PUBLIC_STATUS_JSON
    
    status = {
        "vision_enabled": False,
        "mood": "neutral",
        "last_updated": _ms()
    }
    
    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
                status.update(saved)
        except: pass
    
    # 感情状態も混ぜる
    try:
        from backend.core.state import avatar_state
        status["mood"] = avatar_state.current_emotion
    except: pass
        
    return status

@router.post("/system/vision")
async def set_vision_status(req: VisionRequest):
    from backend.core.config import settings, PROJECT_ROOT
    
    json_path = PROJECT_ROOT / settings.PUBLIC_STATUS_JSON
    
    status = {}
    if json_path.exists():
        with open(json_path, "r", encoding="utf-8") as f:
            try:
                status = json.load(f)
            except: pass
            
    status["vision_enabled"] = req.enabled
    
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
        
    logger.info(f"👁️ Vision Status Changed: {req.enabled}")
    return {"status": "success", "vision_enabled": req.enabled}
