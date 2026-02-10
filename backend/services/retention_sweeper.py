import asyncio
from backend.core.logger import logger
from backend.core.config import settings
from backend.services.retention_config import get_retention_config, PROFILES
from backend.services.chat_history_store import chat_history_store

def _get_int(name: str, default: int) -> int:
    try:
        return int(getattr(settings, name))
    except Exception:
        return default

async def retention_full_sweeper_loop():

    interval_sec = getattr(settings, "RETENTION_FULL_SWEEPER_EVERY_SEC", 900)
    since_hours  = getattr(settings, "RETENTION_FULL_SWEEPER_SINCE_H", 24)
    cfg = get_retention_config()

    while True:
        try:
            logger.info(
                "[RETENTION_CFG] profile=%s promote=%.2f background=%.2f grace=%.1f hl=(C%.1f/P%.1f/D%.1f/%.1f)",
                cfg.profile, cfg.th_promote, cfg.th_background, cfg.grace_days,
                cfg.half_life_days.get("CONSENT", 0.0),
                cfg.half_life_days.get("PONDERING", 0.0),
                cfg.half_life_days.get("DISSONANCE", 0.0),
                cfg.half_life_days.get("DEFAULT", 0.0),
            )
            await chat_history_store.sweep_and_promote_all_threads(since_h=since_hours)
            try:
                n = await chat_history_store.process_vector_sync_queue(limit=200)
                if n:
                    logger.info("[VECTOR_SYNC] processed=%s", n)
            except Exception:
                logger.exception("[VECTOR_SYNC] failed")
        except Exception:
            logger.exception("[RETENTION_FULL] loop error")

        await asyncio.sleep(max(30, interval_sec))  # 最低30秒
