import asyncio
import time

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.core.auth import verify_system_token
from backend.core.config import settings
from backend.core.logger import logger
from backend.services.public_status import read_public_status, update_public_status
from backend.scripts.sleep_cycle import integrated_sleep_cycle
from backend.services.training_dataset_snapshot import run_daily_training_dataset_snapshot_if_due

router = APIRouter()


def _ms() -> int:
    return int(time.time() * 1000)


class VisionRequest(BaseModel):
    enabled: bool


class TrainingDatasetSnapshotRequest(BaseModel):
    thread_id: str | None = Field(default=None, max_length=256)
    format: str = Field(default="jsonl", pattern="^(jsonl|csv)$")
    force: bool = True


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
        raise HTTPException(status_code=500, detail="status_fetch_failed")


@router.post("/system/vision", dependencies=[Depends(verify_system_token)])
async def set_vision_status(req: VisionRequest):
    update_public_status({"vision_enabled": req.enabled})

    logger.info(f"Vision Status Changed: {req.enabled}")
    return {"status": "success", "vision_enabled": req.enabled}


@router.post("/system/training_dataset_snapshot", dependencies=[Depends(verify_system_token)])
async def trigger_training_dataset_snapshot(req: TrainingDatasetSnapshotRequest):
    result = await asyncio.to_thread(
        run_daily_training_dataset_snapshot_if_due,
        thread_id=req.thread_id,
        fmt=req.format,
        force=bool(req.force),
    )
    return result


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

    training_scope = (getattr(settings, "TRAINING_DATASET_SNAPSHOT_THREAD_ID", None) or "all_threads").strip() or "all_threads"
    snapshot_kv = {
        "last_date": kv.get(f"training_dataset_snapshot:last_date:{training_scope}"),
        "last_run_at": kv.get(f"training_dataset_snapshot:last_run_at:{training_scope}"),
        "last_status": kv.get(f"training_dataset_snapshot:last_status:{training_scope}"),
        "last_row_count": kv.get(f"training_dataset_snapshot:last_row_count:{training_scope}"),
        "last_baseline_ts": kv.get(f"training_dataset_snapshot:last_baseline_ts:{training_scope}"),
        "latest_data_path": kv.get(f"training_dataset_snapshot:latest_data_path:{training_scope}"),
        "latest_summary_path": kv.get(f"training_dataset_snapshot:latest_summary_path:{training_scope}"),
        "last_error": kv.get(f"training_dataset_snapshot:last_error:{training_scope}"),
    }

    return {
        "event_counts_24h": event_counts,
        "memory": {"semantic_active": sem_count, "working_open": working_count},
        "telemetry_kv": kv,
        "training_dataset_snapshot": snapshot_kv,
        "service_health": service_health.get_all(),
        "ts": int(time.time()),
    }
