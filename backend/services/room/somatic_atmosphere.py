"""Somatic Atmosphere — conditional injection of '=== 場の空気 ===' section.

Design doc: docs/pip_room_temporal_livestream_integration.md §7 (Contract 2)

Triggered by environmental *changes* (not static state).
Main triggers: T4 (room change), T3 (pip visible changed), T2 (pip near).
Modifiers: M1 (long silence), M5 (time-of-day changed).

Principle: 場の空気は「何かが起きた時」だけ出す。常態化させない。
"""
from __future__ import annotations

import time
from typing import Any

from backend.core.logger import logger
from backend.services.room.runtime_facts import (
    PipVisible,
    RoomChange,
    RuntimeFacts,
    SilenceGap,
    TimeOfDay,
)


# ═══════════════════════════════════════════════════════════════
# Somatic templates (trigger × modifier → text)
# ═══════════════════════════════════════════════════════════════

_SOMATIC_TEMPLATES: dict[tuple[str, str | None], str] = {
    # T4: room change
    ("T4", None): "部屋の空気が少し変わった",
    ("T4", "M5"): "光が動いて、部屋の空気が変わった",
    ("T4", "M1"): "静けさの中で、部屋の空気が変わった",
    ("T4", "M1+M5"): "静かな時間が動いて、部屋の空気が変わった",

    # T3: pip visible changed
    ("T3", None): "隣の気配が変わった",
    ("T3", "M1"): "静けさの中で、隣の気配が変わった",
    ("T3", "M5"): "光の変わり目に、隣の気配が変わった",
    ("T3", "M1+M5"): "静かな時間が移り変わる中で、隣の気配が変わった",

    # T2: pip near (low priority)
    ("T2", None): "そばに静かな気配がある",
    ("T2", "M1"): "ふと気づくと、そばに気配がある",
    ("T2", "M5"): "光が変わる中に、そばの気配がある",
    ("T2", "M1+M5"): "静かな時間の中に、そばの気配がある",
}

# Cooldown: minimum turns between emissions of the same trigger
_COOLDOWN_TURNS: dict[str, int] = {
    "T4": 1,  # room event fires once per latch anyway
    "T3": 3,  # pip change — 3 turns gap
    "T2": 5,  # pip near — 5 turns gap
}

# Priority: T4 > T3 > T2 (events over continuous state)
_TRIGGER_PRIORITY = ["T4", "T3", "T2"]

# Max lines in === 場の空気 === section
_MAX_LINES = 2


# ═══════════════════════════════════════════════════════════════
# Cooldown helpers (telemetry_kv, thread-scoped)
# ═══════════════════════════════════════════════════════════════


def _cooldown_key(thread_id: str, trigger_id: str) -> str:
    return f"somatic_emit:{thread_id}:{trigger_id}"


def _get_last_emit_turn_id(thread_id: str, trigger_id: str) -> str | None:
    """Get the turn_id of the last emit for this trigger in this thread."""
    try:
        from backend.core.db import managed_conn
        with managed_conn() as conn:
            row = conn.execute(
                "SELECT v FROM telemetry_kv WHERE k = ?",
                (_cooldown_key(thread_id, trigger_id),),
            ).fetchone()
            return row["v"] if row else None
    except Exception:
        return None


def _record_emit(thread_id: str, trigger_id: str, turn_id: str) -> None:
    """Record that this trigger was emitted at this turn."""
    try:
        from backend.core.db import managed_conn
        with managed_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO telemetry_kv (k, v, updated_at) VALUES (?, ?, ?)",
                (_cooldown_key(thread_id, trigger_id), turn_id, time.time()),
            )
    except Exception:
        logger.debug("[ATMOSPHERE] failed to record emit", exc_info=True)


def _is_cooled_down(
    thread_id: str,
    trigger_id: str,
    recent_turn_ids: list[str],
) -> bool:
    """Check if enough turns have passed since the last emit.

    recent_turn_ids: ordered list of recent turn IDs (newest first).
    Uses the position of last_emit_turn_id in this list to count turns.
    """
    last_emit = _get_last_emit_turn_id(thread_id, trigger_id)
    if last_emit is None:
        return True  # never emitted — ok to fire

    required = _COOLDOWN_TURNS.get(trigger_id, 3)

    if last_emit not in recent_turn_ids:
        return True  # too old to find — ok to fire

    idx = recent_turn_ids.index(last_emit)
    return idx >= required


# ═══════════════════════════════════════════════════════════════
# Trigger detection
# ═══════════════════════════════════════════════════════════════


def _detect_triggers(
    facts: RuntimeFacts,
    prev_pip_visible: PipVisible | None,
    prev_time_of_day: TimeOfDay | None,
    thread_id: str,
    recent_turn_ids: list[str],
) -> list[str]:
    """Detect active main triggers, respecting cooldown and absorption rules.

    Returns list of trigger IDs in priority order.
    """
    active: list[str] = []

    # T4: room change
    if facts.room_change != RoomChange.NONE:
        if _is_cooled_down(thread_id, "T4", recent_turn_ids):
            active.append("T4")

    # T3: pip visible changed
    if prev_pip_visible is not None and facts.pip_visible != prev_pip_visible:
        if _is_cooled_down(thread_id, "T3", recent_turn_ids):
            active.append("T3")

    # T2: pip near (absorbed by T3 if T3 is active)
    if facts.pip_position_near and "T3" not in active:
        if _is_cooled_down(thread_id, "T2", recent_turn_ids):
            active.append("T2")

    return active


def _detect_modifiers(
    facts: RuntimeFacts,
    prev_time_of_day: TimeOfDay | None,
) -> str | None:
    """Detect active modifiers. Returns None, "M1", "M5", or "M1+M5"."""
    m1 = facts.silence_gap in (SilenceGap.LONG, SilenceGap.VERY_LONG)
    m5 = prev_time_of_day is not None and facts.time_of_day != prev_time_of_day

    if m1 and m5:
        return "M1+M5"
    if m1:
        return "M1"
    if m5:
        return "M5"
    return None


# ═══════════════════════════════════════════════════════════════
# Builder
# ═══════════════════════════════════════════════════════════════


def build_somatic_atmosphere(
    *,
    facts: RuntimeFacts,
    prev_pip_visible: PipVisible | None = None,
    prev_time_of_day: TimeOfDay | None = None,
    thread_id: str = "default_thread",
    turn_id: str = "",
    recent_turn_ids: list[str] | None = None,
) -> str:
    """Build '=== 場の空気 ===' section if any trigger fires.

    Returns formatted section string, or empty string if no triggers.
    Records emit history for cooldown tracking.
    """
    recent = recent_turn_ids or []

    triggers = _detect_triggers(
        facts, prev_pip_visible, prev_time_of_day,
        thread_id, recent,
    )

    if not triggers:
        return ""

    modifier = _detect_modifiers(facts, prev_time_of_day)

    lines: list[str] = []
    for trigger_id in triggers[:_MAX_LINES]:
        text = _SOMATIC_TEMPLATES.get((trigger_id, modifier))
        if text is None:
            text = _SOMATIC_TEMPLATES.get((trigger_id, None), "")
        if text:
            lines.append(f"- {text}")
            # Record emit for cooldown
            if turn_id:
                _record_emit(thread_id, trigger_id, turn_id)

    if not lines:
        return ""

    return "=== 場の空気 ===\n" + "\n".join(lines)
