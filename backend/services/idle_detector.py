"""
Idle Detector (Phase R.1) — Background loop for Autonomous Reflection trigger.

Checks periodically whether:
  1. reflection_pending flag is set (turn threshold exceeded)
  2. User has been idle for IDLE_THRESHOLD_MINUTES

When both conditions are met, triggers reflection (Phase R.2 adds actual engine).
Resets counters after triggering to allow next session.
"""
from __future__ import annotations

import asyncio
import time

from backend.core.config import settings
from backend.core.db import get_conn
from backend.core.logger import logger


def _read_kv(conn, key: str) -> str | None:
    row = conn.execute("SELECT v FROM telemetry_kv WHERE k=?", (key,)).fetchone()
    return row[0] if row else None


def _write_kv(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO telemetry_kv (k, v, updated_at) VALUES (?, ?, ?)",
        (key, value, int(time.time())),
    )


async def idle_detector_loop() -> None:
    """
    Background coroutine: poll telemetry_kv for reflection readiness.

    Loop runs every IDLE_CHECK_INTERVAL_SEC (default 120s).
    Exits cleanly on CancelledError (server shutdown).
    """
    interval = getattr(settings, "IDLE_CHECK_INTERVAL_SEC", 120)
    idle_threshold = getattr(settings, "IDLE_THRESHOLD_MINUTES", 30)

    logger.info("[IdleDetector] started (interval=%ds, idle_threshold=%dmin)", interval, idle_threshold)

    while True:
        await asyncio.sleep(interval)
        try:
            conn = get_conn()
            try:
                # 1. Check reflection_pending
                pending = _read_kv(conn, "reflection_pending")
                if pending != "1":
                    continue

                # 2. Check idle duration
                last_msg_str = _read_kv(conn, "last_message_at")
                if not last_msg_str:
                    continue

                last_msg = float(last_msg_str)
                idle_minutes = (time.time() - last_msg) / 60.0

                if idle_minutes < idle_threshold:
                    logger.debug(
                        "[IdleDetector] pending but not idle yet (%.1fmin < %dmin)",
                        idle_minutes, idle_threshold,
                    )
                    continue

                # 3. Conditions met → trigger reflection
                turn_count_str = _read_kv(conn, "daily_turn_count") or "0"
                logger.info(
                    "[IdleDetector] reflection trigger: idle=%.1fmin turns=%s",
                    idle_minutes, turn_count_str,
                )

                # Close conn before long-running LLM calls (60-90s)
                conn.close()
                conn = None

                # Phase R.2: Run autonomous reflection engine
                try:
                    from backend.services.reflection_engine import run_reflection
                    reflection_result = await run_reflection(thread_id="default_thread")
                    logger.info("[IdleDetector] reflection completed: %s", reflection_result)
                except Exception:
                    logger.warning("[IdleDetector] reflection engine failed", exc_info=True)

                # 4. Reset counters (ALWAYS — even if engine fails)
                conn = get_conn()
                _write_kv(conn, "reflection_pending", "0")
                _write_kv(conn, "daily_turn_count", "0")
                logger.info("[IdleDetector] counters reset. Ready for next session.")

            finally:
                if conn:
                    conn.close()

        except asyncio.CancelledError:
            logger.info("[IdleDetector] shutting down")
            raise
        except Exception:
            logger.warning("[IdleDetector] loop error", exc_info=True)
