"""Learn Minecraft strategies from gameplay videos.

Pipeline:
  1. Video → ffmpeg frame extraction → Qwen3-VL scene descriptions
  2. Scene descriptions → LLM strategy extraction (1 call)
  3. Strategy → semantic memory storage
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Optional

from backend.core.config import settings

logger = logging.getLogger(__name__)

STRATEGY_EXTRACTION_PROMPT = """\
以下はMinecraftのゲームプレイ動画から抽出した場面の説明です。
これらの場面から、実際に使えるゲームプレイの知識・戦略・手順を抽出してください。

ルール:
- 各知識を1行ずつ、箇条書きで書く
- 実行可能な具体的アドバイスにする（「○○すると良い」「○○の順番が効率的」など）
- 曖昧な一般論は除外する
- 最大10項目まで

=== 場面の説明 ===
{scenes}
"""


async def learn_from_video(
    video_path: str,
    *,
    llm_call: Any = None,
    interval_sec: int | None = None,
    max_frames: int | None = None,
) -> dict:
    """Full pipeline: video → frames → vision → LLM strategy → memory.

    Args:
        video_path: Path to video file.
        llm_call: async callable(system, user) -> str for strategy extraction.
        interval_sec: Override frame extraction interval.
        max_frames: Override max frame count.

    Returns:
        {success, frame_count, scenes, strategies, memory_ids}
    """
    if not getattr(settings, "VIDEO_LEARNING_ENABLED", True):
        return {"success": False, "error": "Video learning disabled"}

    from backend.services.video_analyzer import analyze_video

    # Step 1: Extract and analyze frames
    logger.info("[VideoLearner] Analyzing video: %s", video_path)
    scenes = await analyze_video(
        video_path,
        interval_sec=interval_sec,
        max_frames=max_frames,
    )

    if not scenes:
        return {"success": False, "error": "No frames could be analyzed", "frame_count": 0}

    logger.info("[VideoLearner] Got %d scene descriptions", len(scenes))

    # Step 2: Extract strategies via LLM
    strategies: list[str] = []
    if llm_call:
        strategies = await _extract_strategies(scenes, llm_call)
        logger.info("[VideoLearner] Extracted %d strategies", len(strategies))

    # Step 3: Save to semantic memory
    memory_ids = _save_to_memory(strategies, video_path)

    return {
        "success": True,
        "frame_count": len(scenes),
        "scenes": scenes,
        "strategies": strategies,
        "memory_ids": memory_ids,
    }


async def _extract_strategies(
    scenes: list[str], llm_call: Any
) -> list[str]:
    """Use LLM to extract actionable strategies from scene descriptions."""
    scenes_text = "\n".join(f"{i+1}. {s}" for i, s in enumerate(scenes))
    user_prompt = STRATEGY_EXTRACTION_PROMPT.format(scenes=scenes_text)

    try:
        response = await llm_call(
            "あなたはMinecraftの攻略アドバイザーです。",
            user_prompt,
        )
    except Exception:
        logger.exception("[VideoLearner] Strategy extraction LLM call failed")
        return []

    # Parse bullet points from response
    lines = response.strip().split("\n")
    strategies = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Remove bullet markers
        for prefix in ("- ", "・ ", "* ", "• "):
            if line.startswith(prefix):
                line = line[len(prefix):]
                break
        # Remove numbered prefixes like "1. ", "2. "
        if len(line) > 2 and line[0].isdigit() and line[1] in (".", ")"):
            line = line[2:].strip()
        elif len(line) > 3 and line[:2].isdigit() and line[2] in (".", ")"):
            line = line[3:].strip()

        if line and len(line) >= 5:
            strategies.append(line)

    return strategies[:10]


def _save_to_memory(
    strategies: list[str],
    source_video: str,
    thread_id: str = "minecraft",
) -> list[str]:
    """Save extracted strategies to semantic memory."""
    if not strategies:
        return []

    try:
        from backend.services.memory.semantic_store import upsert
        from backend.services.memory.models import SemanticMemory
        from backend.core.db import managed_conn
    except ImportError:
        logger.warning("[VideoLearner] Could not import semantic_store")
        return []

    now = time.time()
    ids: list[str] = []
    with managed_conn() as conn:
        try:
            for strategy in strategies:
                mem_id = str(uuid.uuid4())
                mem = SemanticMemory(
                    id=mem_id,
                    thread_id=thread_id,
                    content=f"[動画学習] {strategy}",
                    valid_from=now,
                    created_at=now,
                    updated_at=now,
                    status="inferred",
                    confidence=0.6,
                    state_tag="video_knowledge",
                    source_turn_ids="",
                    source_event_ids="",
                    note=f"auto:video_learn:{source_video}",
                    seed_retention=0.6,
                    vector_sync_pending=1,
                )
                upsert(conn, mem)
                ids.append(mem_id)

            logger.info(
                "[VideoLearner] Saved %d strategies to semantic memory", len(ids),
            )
        except Exception:
            logger.exception("[VideoLearner] Failed to save strategies")

    return ids


async def react_to_video(
    video_path: str,
    *,
    max_frames: int = 10,
    interval_sec: int = 3,
) -> list[str]:
    """Analyze a video and return scene descriptions for reaction content.

    Unlike learn_from_video, this is for "Nia watches a video and reacts".
    Returns raw scene descriptions (no strategy extraction).
    """
    from backend.services.video_analyzer import analyze_video

    scenes = await analyze_video(
        video_path,
        prompt="この画像を見て、何が映っているか日本語で簡潔に説明して。面白いポイントがあれば一言コメントして。",
        interval_sec=interval_sec,
        max_frames=max_frames,
    )
    return scenes
