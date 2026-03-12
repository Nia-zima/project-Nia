import json
import uuid
import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.core.logger import logger
from backend.core.config import settings
from backend.core.rate_limit import limiter
from backend.services.llm_client import call_llm

router = APIRouter()

# ---------- Request Models ----------

class StreamChatRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=10000)
    thread_id: str = Field("default_thread", min_length=1, max_length=256)
    voice_id: Optional[str] = Field("14", max_length=50)
    image_data: Optional[str] = None
    mode: Optional[str] = Field("normal", max_length=50)
    stream_id: Optional[str] = Field(None, max_length=128)
    message_id: Optional[str] = Field(None, max_length=128)


class LivestreamChatRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    thread_id: str = Field("live_stream", min_length=1, max_length=256)
    audience_meta: Optional[Dict[str, Any]] = None


class StreamTimeoutRequest(BaseModel):
    thread_id: str = Field("default_thread", min_length=1, max_length=256)
    stream_id: Optional[str] = Field(None, max_length=128)
    turn_id: Optional[str] = Field(None, max_length=128)
    reason: Optional[str] = Field(None, max_length=500)


# ---------- Helpers ----------
def _has_japanese(text: str) -> bool:
    if not text:
        return False
    return bool(re.search(r"[\u3040-\u30FF\u4E00-\u9FFF]", text))


async def _translate_to_ja(text: str) -> str:
    if not text:
        return text
    if _has_japanese(text):
        return text
    if len(text) > settings.MAX_TRANSLATE_CHARS:
        return text

    prompt = (
        "以下を自然な日本語に翻訳してください。\n"
        "- 意味を変えない\n"
        "- 改行は保つ\n"
        "- 余計な解説はしない\n\n"
        f"{text}"
    )
    result = await call_llm([
        {"role": "system", "content": "You are a translation assistant. Output only the translation in Japanese."},
        {"role": "user", "content": prompt},
    ], temperature=0.2, max_tokens=1200)
    return result.strip() if isinstance(result, str) and result.strip() else text


async def _safe_stream_generator(
    input_text: str,
    thread_id: str,
    voice_id: str,
    image_data: Optional[str] = None,
    mode: str = "normal",
    stream_id: Optional[str] = None,
    message_id: Optional[str] = None,
):
    """
    SSE整形は Orchestrator に委譲する。
    致命的エラー時もクライアントにエラーイベントを送信してストリームを正常終了する。
    """
    try:
        from backend.services.agent_orchestrator import get_default_orchestrator
        orchestrator = get_default_orchestrator()

        async for sse in orchestrator.stream_sse(
            input_text=input_text,
            thread_id=thread_id,
            voice_id=voice_id,
            image_data=image_data,
            mode=mode,
            stream_id=stream_id,
            message_id=message_id,
        ):
            yield sse
    except Exception as e:
        logger.exception("[STREAM] Fatal error in stream generator")
        yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"


async def _collect_text_from_agent_stream(input_text: str, thread_id: str) -> str:
    """
    run_agent_stream(SSE) を内部で回し、type=text の content だけ結合して返す。
    [DONE] / {"type":"done"} 両対応。
    """
    from backend.services.agent_orchestrator import get_default_orchestrator
    orchestrator = get_default_orchestrator()
    return await orchestrator.collect_text_from_agent_stream(input_text, thread_id)


# ---------- Endpoints ----------

@router.post("/stream_chat")
@limiter.limit(lambda: settings.RATE_LIMIT_CHAT)
async def stream_chat(req: StreamChatRequest, request: Request):
    # SSE Streaming (Phase 3: Plan B - Canonical)
    # ストリーミングを復活させ、_safe_stream_generator で安全に中継・整形する。
    # API Router が唯一の入り口となる。

    rid = uuid.uuid4().hex[:8]
    client_host = request.client.host if request.client else "unknown"
    logger.info(f"[CHAT_START] rid={rid} from={client_host} mode={req.mode}")
    logger.info(f"📨 Chat Request (SSE): {req.text[:20]}... (Thread: {req.thread_id}) Mode: {req.mode}")

    # Auto-generate provenance IDs when client doesn't supply them
    stream_id = req.stream_id or uuid.uuid4().hex
    message_id = req.message_id or uuid.uuid4().hex

    return StreamingResponse(
        _safe_stream_generator(
            input_text=req.text,
            thread_id=req.thread_id,
            voice_id=req.voice_id,
            image_data=req.image_data,
            mode=req.mode,
            stream_id=stream_id,
            message_id=message_id,
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
    text = (req.text or "").strip()
    if not text:
        return {"ok": True, "thread_id": req.thread_id, "response": ""}

    resp_text = await _collect_text_from_agent_stream(text, req.thread_id)
    return {"ok": True, "thread_id": req.thread_id, "response": resp_text}


@router.post("/stream_timeout")
async def stream_timeout(req: StreamTimeoutRequest) -> Dict[str, Any]:
    """
    SSEタイムアウトを「システム状態イベント」として記録する。
    UIが生成した発話は保存しない。
    """
    try:
        from backend.services.memory_manager import memory_manager

        reason = req.reason or "SSE timeout / no events for 30s"
        link = f"thread:{req.thread_id}"
        if req.turn_id:
            link += f"#turn:{req.turn_id}"

        tags = [
            {"t": "sys", "v": "TIMEOUT"},
            {"t": "state", "v": "DISSONANCE"},
            {"t": "link", "v": link},
        ]
        if req.stream_id:
            tags.append({"t": "ref", "v": f"stream_id:{req.stream_id}"})

        await memory_manager.register_thought(
            text=reason,
            surprise=0.85,
            confidence=1.0,
            source="system",
            thread_id=req.thread_id,
            tags=tags,
        )

        return {"ok": True}
    except Exception as e:
        logger.error(f"[TIMEOUT] Failed to record timeout: {e}")
        raise HTTPException(status_code=500, detail="timeout_record_failed")


@router.get("/history/{thread_id}")
async def get_history(thread_id: str, limit_turns: int = 50):
    """
    会話履歴取得
    - A層の保存済み履歴を最新Nターン分返す
    """
    try:
        from backend.services.chat_history_store import chat_history_store
        hist = await chat_history_store.get_history(thread_id, limit=limit_turns)
        def normalize_content(content):
            if content is None:
                return ""
            if isinstance(content, str):
                return content
            # OpenAI multipart format (画像付きメッセージ) → そのまま返す
            if isinstance(content, list):
                return content
            if isinstance(content, dict) and "text" in content and isinstance(content["text"], str):
                return content["text"]
            try:
                return json.dumps(content, ensure_ascii=False)
            except Exception:
                return str(content)
        
        for m in hist:
            m["content"] = normalize_content(m.get("content"))
            # message_id (id) is already in m as per chat_history_store update
            
        return {"ok": True, "history": hist, "limit_turns": limit_turns}
    except Exception as e:
        logger.warning(f"History fetch failed: {e}")
        return {"ok": True, "history": []}


@router.delete("/history/{thread_id}")
async def delete_history(thread_id: str):
    """Delete chat history for a thread"""
    try:
        from backend.services.chat_history_store import chat_history_store
        await chat_history_store.clear_thread(thread_id)
        return {"ok": True, "thread_id": thread_id}
    except Exception as e:
        logger.warning(f"History delete failed: {e}")
        raise HTTPException(status_code=500, detail="history_delete_failed")


@router.get("/memories")
async def list_recent_memories(limit: int = 50, lang: Optional[str] = None):
    """Retrieve recent episodes/memories"""
    from backend.services.memory_manager import memory_manager

    memories = memory_manager.get_recent_memories(limit)
    if lang != "ja":
        return memories

    translated = 0
    for item in memories:
        if translated >= settings.MAX_TRANSLATE_ITEMS:
            break

        meta = item.get("metadata") or {}
        summary = item.get("summary", "")
        details = item.get("details", "") or ""

        summary_ja = meta.get("summary_ja")
        details_ja = meta.get("details_ja")

        if not summary_ja:
            summary_ja = await _translate_to_ja(summary)
        if details and not details_ja:
            details_ja = await _translate_to_ja(details)

        if summary_ja and summary_ja != summary:
            item["summary"] = summary_ja
        if details_ja and details_ja != details:
            item["details"] = details_ja

        if summary_ja or details_ja:
            new_meta = dict(meta)
            if summary_ja:
                new_meta["summary_ja"] = summary_ja
            if details_ja:
                new_meta["details_ja"] = details_ja
            if new_meta != meta and item.get("category") == "episode":
                await memory_manager.update_episode_metadata(item.get("id"), new_meta)
        translated += 1

    return memories


@router.post("/reset")
async def reset(thread_id: str = "default_thread") -> Dict[str, Any]:
    return {"ok": True, "thread_id": thread_id}
