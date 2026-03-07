import time

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel

from backend.core.auth import verify_system_token
from backend.core.config import settings
from backend.core.logger import logger
from backend.services.public_status import read_public_status, update_public_status
from backend.scripts.sleep_cycle import integrated_sleep_cycle

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


@router.get("/system/diagnostics", dependencies=[Depends(verify_system_token)])
async def system_diagnostics():
    """System-wide diagnostics (auth-required)."""
    from backend.core.db import managed_conn
    from backend.core.service_health import service_health

    with managed_conn() as conn:
        # Recent event counts by type (last 24h)
        rows = conn.execute(
            "SELECT event_type, COUNT(*) as cnt FROM events "
            "WHERE ts > datetime('now', '-1 day') GROUP BY event_type"
        ).fetchall()
        event_counts = {r["event_type"]: r["cnt"] for r in rows}

        # Memory stats
        sem_count = conn.execute(
            "SELECT COUNT(*) FROM semantic_memories WHERE status != 'revoked'"
        ).fetchone()[0]
        working_count = conn.execute(
            "SELECT COUNT(*) FROM working_items WHERE status = 'open'"
        ).fetchone()[0]

        # Telemetry KV snapshot
        kv_rows = conn.execute("SELECT k, v FROM telemetry_kv").fetchall()
        kv = {r["k"]: r["v"] for r in kv_rows}

    return {
        "event_counts_24h": event_counts,
        "memory": {"semantic_active": sem_count, "working_open": working_count},
        "telemetry_kv": kv,
        "service_health": service_health.get_all(),
        "ts": int(time.time()),
    }
