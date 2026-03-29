# backend/controllers/api/livestream_router.py
"""
配信機能APIエンドポイント

設計ドキュメント: docs/livestream_design.md
"""

from __future__ import annotations

import json
import time
import uuid
import re
from typing import Any, Dict, Optional, List

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.core.config import settings
from backend.core.logger import logger
from backend.core.rate_limit import limiter
from backend.services.livestream_queue import (
    get_livestream_queue,
    Comment,
    UserRole,
    QueueResult,
)
from backend.core.confidence.metrics import SteeringRiskCalculator

router = APIRouter()


# ---------- Request/Response Models ----------

class CommentRequest(BaseModel):
    """コメント投稿リクエスト"""
    text: str
    user_id: str = "anonymous"
    user_name: str = "視聴者"
    role: str = "viewer"  # "origin" or "viewer"
    timestamp: Optional[float] = None


class CommentResponse(BaseModel):
    """コメント投稿レスポンス"""
    ok: bool
    queued: bool = False
    queue_position: int = 0
    estimated_wait_seconds: float = 0.0
    reason: str = ""


class NextCommentResponse(BaseModel):
    """次のコメント取得レスポンス"""
    comment: Optional[Dict[str, Any]] = None
    queue_remaining: int = 0


class DiagnosticsResponse(BaseModel):
    """Diagnosticsレスポンス"""
    timestamp: float
    thread_id: str
    scalars: Dict[str, float]
    depth: Dict[str, Any]
    queue: Dict[str, int]
    memory: Dict[str, int]
    external: Dict[str, Any]


# ---------- Helpers ----------

def _detect_addressed_to_nia(text: str) -> bool:
    """ニア宛てのコメントかどうかを自動推論"""
    patterns = [
        r"@ニア",
        r"ニアちゃん",
        r"ニアさん",
        r"ニア、",
        r"ニアに",
    ]
    return any(re.search(p, text) for p in patterns)


def _calculate_info_sufficiency(text: str) -> float:
    """コメントの情報充足度を簡易計算"""
    # 長すぎず短すぎないコメントは高スコア
    text_len = len(text)
    if text_len < 10:
        return 0.3
    elif text_len < 30:
        return 0.5
    elif text_len < 100:
        return 0.7
    else:
        return 0.6  # 長すぎると少し下がる


def _format_livestream_input(comment: Comment) -> str:
    """視聴者コメントをエージェント入力形式にフォーマット"""
    role_label = "配信者" if comment.role == UserRole.ORIGIN else "視聴者"
    return f"[LIVE: {comment.user_name} ({role_label})] {comment.text}"


def _sse_json(obj: dict) -> str:
    """SSEイベント用JSON文字列"""
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


# ---------- Endpoints ----------

@router.post("/livestream/comment", response_model=CommentResponse)
@limiter.limit(lambda: settings.RATE_LIMIT_LIVESTREAM)
async def submit_comment(req: CommentRequest, request: Request) -> CommentResponse:
    """
    コメントを投稿
    
    POST /api/livestream/comment
    """
    queue = get_livestream_queue()
    
    # ロール判定
    role = UserRole.ORIGIN if req.role == "origin" else UserRole.VIEWER
    
    # steering_risk計算
    steering_risk = SteeringRiskCalculator.calculate(req.text)
    
    # info_sufficiency計算
    info_sufficiency = _calculate_info_sufficiency(req.text)
    
    # ニア宛て判定
    addressed_to_nia = _detect_addressed_to_nia(req.text)
    
    # コメントオブジェクト作成
    comment = Comment(
        id=uuid.uuid4().hex,
        text=req.text,
        user_id=req.user_id,
        user_name=req.user_name,
        role=role,
        timestamp=req.timestamp or time.time(),
        steering_risk=steering_risk,
        info_sufficiency=info_sufficiency,
        addressed_to_nia=addressed_to_nia,
    )
    
    # キューに追加
    result = await queue.enqueue(comment)
    
    return CommentResponse(
        ok=result.ok,
        queued=result.queued,
        queue_position=result.queue_position,
        estimated_wait_seconds=result.estimated_wait_seconds,
        reason=result.reason,
    )


@router.get("/livestream/next", response_model=NextCommentResponse)
async def get_next_comment() -> NextCommentResponse:
    """
    次のコメントを取得（配信側が呼ぶ）
    
    GET /api/livestream/next
    """
    queue = get_livestream_queue()
    
    comment = await queue.get_next()
    stats = queue.get_stats()
    
    if comment is None:
        return NextCommentResponse(
            comment=None,
            queue_remaining=stats.pending,
        )
    
    return NextCommentResponse(
        comment={
            "id": comment.id,
            "text": comment.text,
            "user_id": comment.user_id,
            "user_name": comment.user_name,
            "role": comment.role.value,
            "steering_risk": comment.steering_risk,
            "info_sufficiency": comment.info_sufficiency,
            "addressed_to_nia": comment.addressed_to_nia,
            "selected_reason": "info_sufficiency高" if comment.info_sufficiency > 0.5 else "default",
        },
        queue_remaining=stats.pending,
    )


@router.get("/diagnostics", response_model=DiagnosticsResponse)
async def get_diagnostics(thread_id: str = "live_stream") -> DiagnosticsResponse:
    """
    Diagnostics情報を取得
    
    GET /api/diagnostics
    """
    queue = get_livestream_queue()
    stats = queue.get_stats()

    # エージェント状態から実データを取得
    scalars = {"steering_risk": 0.0, "info_sufficiency": 0.5, "question_clarity": 0.5}
    depth = {"current": 0, "reason": "default"}
    memory = {"pending": 0, "approved_today": 0}
    external = {
        "used": False,
        "confidence": 0.0,
        "contradiction_flag": False,
        "reason": None,
        "surprise_score": 0.0,
    }

    try:
        from backend.core.agent_graph.graph import workflow
        from backend.services.checkpointer import checkpointer_service

        async with checkpointer_service.get_async_checkpointer_conn() as checkpointer:
            app_instance = workflow.compile(checkpointer=checkpointer)
            config = {"configurable": {"thread_id": thread_id}}
            state = await app_instance.aget_state(config)
            values = getattr(state, "values", {}) or {}

            metrics = values.get("confidence_metrics") or {}
            if metrics:
                scalars = {
                    "steering_risk": metrics.get("steering_risk", 0.0),
                    "info_sufficiency": metrics.get("info_sufficiency", 0.5),
                    "question_clarity": metrics.get("question_clarity", 0.5),
                }

            depth = {
                "current": values.get("selected_depth", 0),
                "reason": values.get("depth_action", "default"),
            }
            external = {
                "used": bool(values.get("external_used", False)),
                "confidence": float(values.get("external_confidence") or 0.0),
                "contradiction_flag": bool(values.get("contradiction_flag", False)),
                "reason": values.get("external_reason"),
                "surprise_score": float(values.get("surprise_score") or 0.0),
            }
    except Exception as e:
        logger.warning(f"[DIAGNOSTICS] Failed to read agent state: {e}")
    
    return DiagnosticsResponse(
        timestamp=time.time(),
        thread_id=thread_id,
        scalars=scalars,
        depth=depth,
        queue={
            "pending": stats.pending,
            "processed_last_minute": stats.processed_last_minute,
            "rejected_last_minute": stats.rejected_last_minute,
        },
        memory=memory,
        external=external,
    )


@router.post("/livestream/process_next")
async def process_next_comment(thread_id: str = "live_stream") -> Dict[str, Any]:
    """
    キューから次のコメントを取得し、ニアの応答を生成して返す（非ストリーミング）

    POST /api/livestream/process_next
    """
    queue = get_livestream_queue()
    comment = await queue.get_next()
    stats = queue.get_stats()

    if comment is None:
        return {
            "ok": True,
            "has_comment": False,
            "comment": None,
            "response": None,
            "thread_id": thread_id,
            "queue_remaining": stats.pending,
        }

    agent_input = _format_livestream_input(comment)

    from backend.services.agent_orchestrator import get_default_orchestrator
    orchestrator = get_default_orchestrator()

    t0 = time.time()
    response_text = await orchestrator.collect_text_from_agent_stream(agent_input, thread_id)
    processing_ms = int((time.time() - t0) * 1000)

    return {
        "ok": True,
        "has_comment": True,
        "comment": {
            "id": comment.id,
            "text": comment.text,
            "user_name": comment.user_name,
            "role": comment.role.value,
            "steering_risk": comment.steering_risk,
            "info_sufficiency": comment.info_sufficiency,
            "addressed_to_nia": comment.addressed_to_nia,
        },
        "response": response_text,
        "thread_id": thread_id,
        "queue_remaining": stats.pending,
        "processing_ms": processing_ms,
    }


@router.get("/livestream/stream_next")
async def stream_next_comment(thread_id: str = "live_stream"):
    """
    キューから次のコメントを取得し、SSEストリームで応答を返す（TTS付き）

    GET /api/livestream/stream_next

    SSEイベント:
    1. comment_selected - 選択されたコメント情報
    2. text - テキストチャンク（ストリーミング）
    3. emotion - 感情タグ
    4. audio - TTS音声URL
    5. done - 完了
    """
    queue = get_livestream_queue()
    comment = await queue.get_next()
    stats = queue.get_stats()

    if comment is None:
        async def _empty_stream():
            yield _sse_json({"type": "idle", "queue_remaining": stats.pending})
            yield _sse_json({"type": "done"})

        return StreamingResponse(
            _empty_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    agent_input = _format_livestream_input(comment)

    async def _response_stream():
        try:
            from backend.services.agent_orchestrator import get_default_orchestrator
            orchestrator = get_default_orchestrator()

            # コメント情報を先に送信
            yield _sse_json({
                "type": "comment_selected",
                "comment": {
                    "id": comment.id,
                    "text": comment.text,
                    "user_name": comment.user_name,
                    "role": comment.role.value,
                    "addressed_to_nia": comment.addressed_to_nia,
                },
                "queue_remaining": stats.pending,
            })

            # エージェント応答をストリーム（text, emotion, audio, done）
            async for sse_chunk in orchestrator.stream_sse(
                input_text=agent_input,
                thread_id=thread_id,
                voice_id="14",
                image_data=None,
                mode="normal",
                stream_id=None,
                message_id=None,
            ):
                yield sse_chunk
        except Exception as e:
            logger.exception("[LIVESTREAM] stream error")
            yield _sse_json({"type": "error", "content": str(e)})
            yield _sse_json({"type": "done"})

    return StreamingResponse(
        _response_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.post("/livestream/clear")
async def clear_queue() -> Dict[str, Any]:
    """
    キューをクリア（配信終了時）

    POST /api/livestream/clear
    """
    queue = get_livestream_queue()
    await queue.clear()

    # Also stop chat bridges
    try:
        from backend.services.chat_bridge import chat_bridge
        await chat_bridge.stop_all()
    except Exception:
        pass

    return {"ok": True, "message": "Queue cleared, bridges stopped"}


# ---------- Chat Bridge Endpoints ----------


class BridgeStartRequest(BaseModel):
    """ブリッジ開始リクエスト"""
    video_id: str = ""
    channel: str = ""


@router.post("/livestream/bridge/youtube/start")
async def start_youtube_bridge(req: BridgeStartRequest) -> Dict[str, Any]:
    """YouTube Live Chat ブリッジ開始"""
    from backend.services.chat_bridge import chat_bridge
    return await chat_bridge.start_youtube(video_id=req.video_id or None)


@router.post("/livestream/bridge/twitch/start")
async def start_twitch_bridge(req: BridgeStartRequest) -> Dict[str, Any]:
    """Twitch Chat ブリッジ開始"""
    from backend.services.chat_bridge import chat_bridge
    return await chat_bridge.start_twitch(channel=req.channel or None)


@router.post("/livestream/bridge/stop")
async def stop_bridge() -> Dict[str, Any]:
    """全ブリッジ停止"""
    from backend.services.chat_bridge import chat_bridge
    return await chat_bridge.stop_all()


@router.get("/livestream/bridge/status")
async def bridge_status() -> Dict[str, Any]:
    """ブリッジ接続状態 + 統計"""
    from backend.services.chat_bridge import chat_bridge
    return chat_bridge.get_status()
