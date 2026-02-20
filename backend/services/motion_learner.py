"""Learn VRM motion patterns from VTuber/animation videos.

Pipeline:
  1. Video → ffmpeg frame extraction → Qwen3-VL scene descriptions (motion-focused)
  2. Scene descriptions → LLM motion pattern extraction (1 call)
  3. Patterns → Motion Library + Semantic Memory
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from backend.core.config import settings

logger = logging.getLogger(__name__)

MOTION_VISION_PROMPT = (
    "この画像に映っている人物・キャラクターの体のポーズと動きを詳しく描写してください。"
    "特に手・腕・頭・体の向き・表情に注目してください。"
)

MOTION_EXTRACTION_PROMPT = """\
以下はVTuber/アニメーションの動画から抽出したフレームの説明です。
キャラクターの体の動き・ジェスチャーのパターンを抽出してください。

ルール:
- 各パターンをJSON形式で1行ずつ出力する
- フォーマット: {{"name": "動作名（英語snake_case）", "context": "どんな場面で使うか", "bones": "体のどの部位がどう動くか"}}
- name は既存プリセットとの重複を避ける（既存: nod, wave, shrug, tilt_head, bow, point, fist_pump, clap）
- 最大8パターンまで
- 曖昧・微小な動きは除外する

=== 場面の説明 ===
{scenes}
"""


async def learn_motion_from_video(
    video_path: str,
    *,
    llm_call: Any = None,
    interval_sec: int | None = None,
    max_frames: int | None = None,
) -> dict:
    """Full pipeline: video → frames → vision → LLM motion extraction → library + memory.

    Args:
        video_path: Path to video file.
        llm_call: async callable(system, user) -> str for motion extraction.
        interval_sec: Override frame extraction interval.
        max_frames: Override max frame count.

    Returns:
        {success, frame_count, scenes, patterns, library_ids, memory_ids}
    """
    if not getattr(settings, "VIDEO_LEARNING_ENABLED", True):
        return {"success": False, "error": "Video learning disabled"}

    from backend.services.video_analyzer import analyze_video

    # Step 1: Extract and analyze frames with motion-focused prompt
    logger.info("[MotionLearner] Analyzing video: %s", video_path)
    scenes = await analyze_video(
        video_path,
        prompt=MOTION_VISION_PROMPT,
        interval_sec=interval_sec,
        max_frames=max_frames,
    )

    if not scenes:
        return {"success": False, "error": "No frames could be analyzed", "frame_count": 0}

    logger.info("[MotionLearner] Got %d scene descriptions", len(scenes))

    # Step 2: Extract motion patterns via LLM
    patterns: list[dict] = []
    if llm_call:
        patterns = await _extract_patterns(scenes, llm_call)
        logger.info("[MotionLearner] Extracted %d motion patterns", len(patterns))

    # Step 3: Save to Motion Library and Semantic Memory
    library_ids = _save_to_library(patterns, video_path)
    memory_ids = _save_to_memory(patterns, video_path)

    return {
        "success": True,
        "frame_count": len(scenes),
        "scenes": scenes,
        "patterns": patterns,
        "library_ids": library_ids,
        "memory_ids": memory_ids,
    }


async def _extract_patterns(
    scenes: list[str], llm_call: Any
) -> list[dict]:
    """Use LLM to extract motion patterns from scene descriptions."""
    scenes_text = "\n".join(f"{i+1}. {s}" for i, s in enumerate(scenes))
    user_prompt = MOTION_EXTRACTION_PROMPT.format(scenes=scenes_text)

    try:
        response = await llm_call(
            "あなたはVTuberモーション分析の専門家です。動画のフレーム説明からジェスチャーパターンを抽出してください。",
            user_prompt,
        )
    except Exception:
        logger.exception("[MotionLearner] Pattern extraction LLM call failed")
        return []

    # Parse JSON objects from response
    patterns = []
    for line in response.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        # Try to find JSON in line
        start = line.find("{")
        end = line.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                obj = json.loads(line[start:end])
                if "name" in obj:
                    patterns.append(obj)
            except json.JSONDecodeError:
                continue

    return patterns[:8]


def _save_to_library(
    patterns: list[dict],
    source_video: str,
) -> list[str]:
    """Save extracted patterns to Motion Library."""
    if not patterns:
        return []

    from backend.services.motion_library import motion_library

    ids: list[str] = []
    for pattern in patterns:
        name = pattern.get("name", "").strip()
        if not name:
            continue

        # Store the pattern description as a placeholder keyframe definition
        # The actual bone animation data would need manual refinement or future auto-generation
        keyframes_data = {
            "keyframes": [],
            "totalDuration": 500,
            "returnDuration": 300,
            "raw_description": pattern.get("bones", ""),
        }

        result = motion_library.save(
            name=name,
            description=pattern.get("context", name),
            keyframes_json=json.dumps(keyframes_data),
            tags=["video_learned"],
            context_hint=pattern.get("context", ""),
            source="video_learn",
        )
        ids.append(result["id"])

    if ids:
        logger.info("[MotionLearner] Saved %d patterns to Motion Library", len(ids))
    return ids


def _save_to_memory(
    patterns: list[dict],
    source_video: str,
    thread_id: str = "default_thread",
) -> list[str]:
    """Save extracted patterns to semantic memory for Sleep Cycle processing."""
    if not patterns:
        return []

    try:
        from backend.services.memory.semantic_store import upsert
        from backend.services.memory.models import SemanticMemory
        from backend.core.db import get_conn
    except ImportError:
        logger.warning("[MotionLearner] Could not import semantic_store")
        return []

    now = time.time()
    ids: list[str] = []
    conn = get_conn()
    try:
        for pattern in patterns:
            name = pattern.get("name", "unknown")
            context = pattern.get("context", "")
            bones = pattern.get("bones", "")

            mem_id = str(uuid.uuid4())
            content = f"[モーション学習] {name}: {context} ({bones})"
            mem = SemanticMemory(
                id=mem_id,
                thread_id=thread_id,
                content=content,
                status="inferred",
                confidence=0.5,
                state_tag="motion_knowledge",
                source_turn_ids="",
                source_event_ids="",
                note=f"auto:motion_learn:{source_video}",
                seed_retention=0.5,
                vector_sync_pending=1,
                created_at=now,
                updated_at=now,
            )
            upsert(conn, mem)
            ids.append(mem_id)

        logger.info("[MotionLearner] Saved %d patterns to semantic memory", len(ids))
    except Exception:
        logger.exception("[MotionLearner] Failed to save patterns to memory")
    finally:
        conn.close()

    return ids
