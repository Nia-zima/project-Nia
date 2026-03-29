"""
Idle Detector (Phase R.1 + N.4) — Background loop for Autonomous Reflection trigger.

R.1: Timer-based trigger (pending + idle threshold)
N.4: State-driven trigger (metacog stats cross thresholds)

New hybrid flow:
  - pending=1 AND idle>=30min → reflect (timer)
  - idle>=5min AND state trigger met → reflect (state)
  - 60min cooldown between state-driven triggers
"""
from __future__ import annotations

import asyncio
import json
import time

from backend.core.config import settings
from backend.core.db import managed_conn
from backend.core.logger import logger


def _read_kv(conn, key: str) -> str | None:
    row = conn.execute("SELECT v FROM telemetry_kv WHERE k=?", (key,)).fetchone()
    return row["v"] if row else None


def _write_kv(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO telemetry_kv (k, v, updated_at) VALUES (?, ?, ?)",
        (key, value, int(time.time())),
    )


# ── N.4: State-Driven Trigger ──────────────────────────────


def should_trigger_reflection(conn) -> tuple[bool, str]:
    """Check if internal metacog stats warrant reflection.

    Returns (should_trigger, reason).
    """
    if not getattr(settings, "STATE_TRIGGER_ENABLED", True):
        return False, ""

    # 1. Awareness high
    avg_str = _read_kv(conn, "awareness_average")
    if avg_str:
        try:
            if float(avg_str) > 0.25:
                return True, "awareness_high"
        except ValueError:
            pass

    # 2. Confidence variance high
    var_str = _read_kv(conn, "confidence_variance")
    if var_str:
        try:
            if float(var_str) > 0.08:
                return True, "confidence_variance_high"
        except ValueError:
            pass

    # 3. Dissonance streak
    streak_str = _read_kv(conn, "dissonance_streak")
    if streak_str:
        try:
            if int(streak_str) >= 3:
                return True, "dissonance_streak"
        except ValueError:
            pass

    # 4. Contradiction recent
    contra_str = _read_kv(conn, "contradiction_recent")
    if contra_str == "1":
        return True, "contradiction_detected"

    # 5. Topic shifts
    shifts_str = _read_kv(conn, "topic_shift_count")
    if shifts_str:
        try:
            if int(shifts_str) >= 3:
                return True, "topic_shifts"
        except ValueError:
            pass

    return False, ""


def _check_state_trigger_cooldown(conn) -> bool:
    """Return True if state trigger is in cooldown period."""
    cooldown_min = getattr(settings, "STATE_TRIGGER_COOLDOWN_MINUTES", 60)
    last_str = _read_kv(conn, "last_state_trigger_at")
    if not last_str:
        return False
    try:
        elapsed = (time.time() - float(last_str)) / 60.0
        return elapsed < cooldown_min
    except ValueError:
        return False


def _reset_metacog_stats(conn) -> None:
    """Reset accumulated metacog stats after reflection triggers."""
    now = time.time()
    for key in ("confidence_history", "confidence_variance", "dissonance_streak",
                "contradiction_recent", "topic_shift_count"):
        _write_kv(conn, key, "0" if key != "confidence_history" else "[]")


# ── Main Loop ──────────────────────────────────────────────


async def idle_detector_loop() -> None:
    """
    Background coroutine: poll telemetry_kv for reflection readiness.

    Loop runs every IDLE_CHECK_INTERVAL_SEC (default 120s).
    Exits cleanly on CancelledError (server shutdown).
    """
    interval = getattr(settings, "IDLE_CHECK_INTERVAL_SEC", 120)
    idle_threshold = getattr(settings, "IDLE_THRESHOLD_MINUTES", 30)
    state_min_idle = getattr(settings, "STATE_TRIGGER_MIN_IDLE_MINUTES", 5)

    logger.info("[IdleDetector] started (interval=%ds, idle_threshold=%dmin)", interval, idle_threshold)

    while True:
        await asyncio.sleep(interval)
        try:
            # Phase 1: Read KV state
            with managed_conn() as conn:
                last_msg_str = _read_kv(conn, "last_message_at")
                if not last_msg_str:
                    continue

                last_msg = float(last_msg_str)
                idle_minutes = (time.time() - last_msg) / 60.0

                pending = _read_kv(conn, "reflection_pending")
                timer_trigger = pending == "1" and idle_minutes >= idle_threshold
                turn_count_str = _read_kv(conn, "daily_turn_count") or "0" if timer_trigger else "0"

                # Pre-check state trigger conditions while conn is open
                state_trigger = False
                state_reason = ""
                if not timer_trigger and idle_minutes >= state_min_idle:
                    if not _check_state_trigger_cooldown(conn):
                        state_trigger, state_reason = should_trigger_reflection(conn)
                        if state_trigger:
                            _write_kv(conn, "last_state_trigger_at", str(time.time()))

            # Path 1: R.1 timer-based trigger (pending + idle)
            if timer_trigger:
                logger.info(
                    "[IdleDetector] timer trigger: idle=%.1fmin turns=%s",
                    idle_minutes, turn_count_str,
                )
                await _trigger_reflection("timer")
                with managed_conn() as conn:
                    _write_kv(conn, "reflection_pending", "0")
                    _write_kv(conn, "daily_turn_count", "0")
                    _reset_metacog_stats(conn)
                logger.info("[IdleDetector] counters reset. Ready for next session.")
                continue

            # Path 2: N.4 state-driven trigger (lower idle threshold)
            if state_trigger:
                logger.info(
                    "[IdleDetector] state trigger: reason=%s idle=%.1fmin",
                    state_reason, idle_minutes,
                )
                await _trigger_reflection(f"state:{state_reason}")
                with managed_conn() as conn:
                    _reset_metacog_stats(conn)
                logger.info("[IdleDetector] state trigger complete, stats reset.")
                continue

        except asyncio.CancelledError:
            logger.info("[IdleDetector] shutting down")
            raise
        except Exception:
            logger.warning("[IdleDetector] loop error", exc_info=True)


async def _trigger_reflection(reason: str) -> None:
    """Execute reflection engine with given trigger reason."""
    try:
        from backend.services.reflection_engine import run_reflection
        reflection_result = await run_reflection(thread_id="default_thread")
        logger.info("[IdleDetector] reflection completed (reason=%s): %s", reason, reflection_result)

        if reflection_result.get("success") and reflection_result.get("daily_log_saved"):
            await _maybe_request_nero_meeting(reason)
    except Exception:
        logger.warning("[IdleDetector] reflection engine failed (reason=%s)", reason, exc_info=True)


async def _maybe_request_nero_meeting(trigger: str) -> None:
    """Fire-and-forget: request Nero meeting if reflection has unresolved topics."""
    if not getattr(settings, "NERO_MEETING_REQUEST_ENABLED", False):
        return
    nero_url = getattr(settings, "NERO_WEBHOOK_URL", "")
    if not nero_url:
        return

    try:
        with managed_conn() as conn:
            row = conn.execute(
                """SELECT content_json FROM daily_reflections
                   WHERE thread_id = 'default_thread' AND phase = 'daily_log'
                   ORDER BY created_at DESC LIMIT 1"""
            ).fetchone()
        if not row:
            return
        log_data = json.loads(row["content_json"])
        unresolved = log_data.get("unresolved", [])
        if not unresolved:
            return

        import httpx

        payload = {
            "topic": unresolved[0],
            "trigger": trigger,
            "unresolved": unresolved[:3],
        }
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(f"{nero_url}/nero/hooks/meeting-request", json=payload)
        logger.info("[IdleDetector] Nero meeting request sent (topic=%s)", unresolved[0][:60])
    except Exception:
        logger.debug("[IdleDetector] Nero meeting request failed (non-critical)", exc_info=True)
