import time

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel

from backend.core.auth import verify_system_token
from backend.core.config import settings
from backend.core.logger import logger
from backend.services.public_status import read_public_status, update_public_status
from backend.scripts.sleep_cycle import integrated_sleep_cycle
from backend.scripts.chapter_reflection import ChapterEngine

router = APIRouter()


def _ms() -> int:
    return int(time.time() * 1000)


class VisionRequest(BaseModel):
    enabled: bool


@router.post("/system/sleep", dependencies=[Depends(verify_system_token)])
async def trigger_sleep_cycle(background_tasks: BackgroundTasks):
    """手動で睡眠サイクル（記憶整理）を発火させる"""
    logger.info("Manual Sleep Cycle Triggered via API")
    background_tasks.add_task(integrated_sleep_cycle)
    return {"status": "ok", "message": "Sleep cycle initiated."}


@router.post("/system/reflect", dependencies=[Depends(verify_system_token)])
async def trigger_reflection(background_tasks: BackgroundTasks):
    """手動で週次振り返り（Reflection）を発火させる"""
    logger.info("Manual Reflection Triggered via API")
    engine = ChapterEngine()
    background_tasks.add_task(engine.reflect, days=7)
    return {"status": "ok", "message": "Reflection started."}


@router.get("/status")
async def get_public_status():
    """フロントエンドがポーリングする公開ステータス"""
    try:
        status = {
            "vision_enabled": False,
            "mood": "neutral",
            "last_updated": _ms(),
        }

        saved = read_public_status(default={})
        if saved:
            status.update(saved)

        # 感情状態も混ぜる
        try:
            from backend.core.state import avatar_state
            status["mood"] = avatar_state.current_emotion
        except Exception as e:
            logger.warning("[status] failed to get avatar_state: %s", e)

        return status
    except Exception as e:
        logger.exception("[status] API error: %s", e)
        return {"ok": False, "error": str(e)}


@router.post("/system/vision", dependencies=[Depends(verify_system_token)])
async def set_vision_status(req: VisionRequest):
    update_public_status({"vision_enabled": req.enabled})

    logger.info(f"Vision Status Changed: {req.enabled}")
    return {"status": "success", "vision_enabled": req.enabled}
