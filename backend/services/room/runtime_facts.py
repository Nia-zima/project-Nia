"""Runtime Facts — minimal facts about Nia's current environment.

Design doc: docs/pip_room_temporal_livestream_integration.md §6 (Contract 1)

Nia receives these as-is (not body-feeling). Internal enums are stable;
Japanese labels are produced only at injection time.

Principle: 時間帯（体験）と時刻（情報）は分離する。
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from backend.core.logger import logger


# ═══════════════════════════════════════════════════════════════
# Enums (stable internal values)
# ═══════════════════════════════════════════════════════════════


class TimeOfDay(str, Enum):
    MORNING = "morning"        # 5-10
    DAY = "day"                # 10-20
    NIGHT = "night"            # 20-1
    LATE_NIGHT = "late_night"  # 1-5


class SilenceGap(str, Enum):
    NONE = "none"              # < 10s
    SHORT = "short"            # < 300s
    LONG = "long"              # < 1800s
    VERY_LONG = "very_long"    # >= 1800s


class PipVisible(str, Enum):
    RESTING = "resting"        # idle
    LOOKING = "looking"        # curious, alert
    PLAYFUL = "playful"        # playful
    SLEEPY = "sleepy"          # sleepy
    SLEEPING = "sleeping"      # sleeping
    NEAR = "near"              # comfort, empathy (high-bond)


class RoomChange(str, Enum):
    OBJECT_ADDED = "object_added"
    OBJECT_REMOVED = "object_removed"
    ART_HUNG = "art_hung"
    ART_REMOVED = "art_removed"
    NONE = "none"


# ═══════════════════════════════════════════════════════════════
# Dataclass
# ═══════════════════════════════════════════════════════════════


@dataclass
class RuntimeFacts:
    """Minimal facts about Nia's current environment."""

    time_of_day: TimeOfDay
    silence_gap: SilenceGap
    pip_visible: PipVisible
    pip_position_near: bool
    room_change: RoomChange  # latched event — emitted once


# ═══════════════════════════════════════════════════════════════
# Shared visible-state mapper (mood → PipVisible)
# Used by both runtime_facts and room_context.
# ═══════════════════════════════════════════════════════════════

MOOD_TO_VISIBLE: dict[str, PipVisible] = {
    "idle": PipVisible.RESTING,
    "curious": PipVisible.LOOKING,
    "playful": PipVisible.PLAYFUL,
    "sleepy": PipVisible.SLEEPY,
    "sleeping": PipVisible.SLEEPING,
    "alert": PipVisible.LOOKING,
    "comfort": PipVisible.NEAR,
    "empathy": PipVisible.NEAR,
}


def mood_to_visible(mood: str) -> PipVisible:
    """Convert Pip mood to observable visible state."""
    return MOOD_TO_VISIBLE.get(mood, PipVisible.RESTING)


# ═══════════════════════════════════════════════════════════════
# Label tables (enum → Japanese, used only at injection time)
# ═══════════════════════════════════════════════════════════════

_TIME_LABELS: dict[TimeOfDay, str] = {
    TimeOfDay.MORNING: "朝",
    TimeOfDay.DAY: "昼",
    TimeOfDay.NIGHT: "夜",
    TimeOfDay.LATE_NIGHT: "深夜",
}

_VISIBLE_LABELS: dict[PipVisible, str] = {
    PipVisible.RESTING: "静かにしている",
    PipVisible.LOOKING: "こちらを見ている",
    PipVisible.PLAYFUL: "楽しそうにしている",
    PipVisible.SLEEPY: "眠そうにしている",
    PipVisible.SLEEPING: "眠っている",
    PipVisible.NEAR: "そばにいる",
}

_GAP_LABELS: dict[SilenceGap, str] = {
    SilenceGap.LONG: "少し間があった",
    SilenceGap.VERY_LONG: "しばらくぶり",
}

_ROOM_CHANGE_LABELS: dict[RoomChange, str] = {
    RoomChange.OBJECT_ADDED: "部屋に物が増えた",
    RoomChange.OBJECT_REMOVED: "部屋の物が減った",
    RoomChange.ART_HUNG: "壁に絵が飾られた",
    RoomChange.ART_REMOVED: "壁の絵が外された",
}


# ═══════════════════════════════════════════════════════════════
# Time-of-day computation
# ═══════════════════════════════════════════════════════════════


def hour_to_time_of_day(hour: int) -> TimeOfDay:
    """Convert hour (0-23) to TimeOfDay enum."""
    if 5 <= hour < 10:
        return TimeOfDay.MORNING
    elif 10 <= hour < 20:
        return TimeOfDay.DAY
    elif 20 <= hour or hour < 1:
        return TimeOfDay.NIGHT
    else:  # 1-4
        return TimeOfDay.LATE_NIGHT


# ═══════════════════════════════════════════════════════════════
# Silence gap computation (thread-scoped)
# ═══════════════════════════════════════════════════════════════


def _get_thread_gap_seconds(thread_id: str) -> float:
    """Get gap since last turn in the same thread.

    Uses turn_fingerprints table (thread-scoped) instead of
    telemetry_kv global last_turn_timestamp to avoid cross-thread
    contamination between default_thread and nero_meeting_*.
    """
    try:
        from backend.core.db import managed_conn

        with managed_conn() as conn:
            row = conn.execute(
                "SELECT timestamp FROM turn_fingerprints "
                "WHERE thread_id = ? ORDER BY timestamp DESC LIMIT 1",
                (thread_id,),
            ).fetchone()
        if not row:
            return 0.0
        return max(0.0, time.time() - row["timestamp"])
    except Exception:
        logger.debug("[RuntimeFacts] gap query failed", exc_info=True)
        return 0.0


def seconds_to_gap(seconds: float) -> SilenceGap:
    """Convert raw gap seconds to SilenceGap enum."""
    if seconds >= 1800:
        return SilenceGap.VERY_LONG
    elif seconds >= 300:
        return SilenceGap.LONG
    elif seconds >= 10:
        return SilenceGap.SHORT
    return SilenceGap.NONE


# ═══════════════════════════════════════════════════════════════
# Room change latch
# ═══════════════════════════════════════════════════════════════


def _room_content_hash(objects: list[dict], wall_art: list[dict]) -> str:
    """Compute a stable hash of room content for change detection."""
    obj_ids = sorted(o.get("id", "") for o in objects)
    art_ids = sorted(a.get("id", "") for a in wall_art)
    raw = f"obj:{'|'.join(obj_ids)}|art:{'|'.join(art_ids)}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _detect_room_change(
    objects: list[dict],
    wall_art: list[dict],
    prev_objects: list[dict],
    prev_wall_art: list[dict],
    *,
    last_emitted_hash: str | None,
) -> tuple[RoomChange, str]:
    """Detect room change as a latched event.

    Returns (change, current_hash). If change != NONE, caller should
    persist current_hash as last_emitted_hash.
    """
    current_hash = _room_content_hash(objects, wall_art)

    if last_emitted_hash == current_hash:
        return RoomChange.NONE, current_hash

    # Determine what changed
    cur_obj_ids = {o.get("id", "") for o in objects}
    prev_obj_ids = {o.get("id", "") for o in prev_objects}
    cur_art_ids = {a.get("id", "") for a in wall_art}
    prev_art_ids = {a.get("id", "") for a in prev_wall_art}

    if cur_art_ids - prev_art_ids:
        return RoomChange.ART_HUNG, current_hash
    if prev_art_ids - cur_art_ids:
        return RoomChange.ART_REMOVED, current_hash
    if cur_obj_ids - prev_obj_ids:
        return RoomChange.OBJECT_ADDED, current_hash
    if prev_obj_ids - cur_obj_ids:
        return RoomChange.OBJECT_REMOVED, current_hash

    return RoomChange.NONE, current_hash


# ═══════════════════════════════════════════════════════════════
# Builder
# ═══════════════════════════════════════════════════════════════


def build_runtime_facts(
    *,
    thread_id: str = "default_thread",
    pip_mood: str = "idle",
    pip_position_near: bool = False,
    room_objects: list[dict] | None = None,
    room_wall_art: list[dict] | None = None,
    prev_room_objects: list[dict] | None = None,
    prev_room_wall_art: list[dict] | None = None,
    last_emitted_room_hash: str | None = None,
    gap_seconds: float | None = None,
) -> tuple[RuntimeFacts, str]:
    """Build RuntimeFacts from current state.

    Returns (facts, room_hash) — caller should persist room_hash
    for next invocation's last_emitted_room_hash.

    If gap_seconds is None, queries turn_fingerprints for thread-scoped gap.
    """
    from datetime import datetime

    # Time of day
    tod = hour_to_time_of_day(datetime.now().hour)

    # Silence gap
    if gap_seconds is None:
        gap_seconds = _get_thread_gap_seconds(thread_id)
    gap = seconds_to_gap(gap_seconds)

    # Pip visible state
    vis = mood_to_visible(pip_mood)

    # Room change (latched)
    change, room_hash = _detect_room_change(
        room_objects or [],
        room_wall_art or [],
        prev_room_objects or [],
        prev_room_wall_art or [],
        last_emitted_hash=last_emitted_room_hash,
    )

    facts = RuntimeFacts(
        time_of_day=tod,
        silence_gap=gap,
        pip_visible=vis,
        pip_position_near=pip_position_near,
        room_change=change,
    )
    return facts, room_hash


# ═══════════════════════════════════════════════════════════════
# Formatter (enum → Japanese, for LLM context injection)
# ═══════════════════════════════════════════════════════════════


def format_runtime_facts(facts: RuntimeFacts) -> str:
    """Format RuntimeFacts as '=== 今の場所と時間 ===' section.

    Returns empty string if nothing meaningful to show.
    """
    lines: list[str] = []

    # Time of day (always present)
    lines.append(f"{_TIME_LABELS[facts.time_of_day]}。")

    # Silence gap (only LONG and VERY_LONG)
    gap_label = _GAP_LABELS.get(facts.silence_gap)
    if gap_label:
        lines.append(f"{gap_label}。")

    # Pip visible state
    lines.append(f"Pipは{_VISIBLE_LABELS[facts.pip_visible]}。")

    # Room change (only when something changed)
    change_label = _ROOM_CHANGE_LABELS.get(facts.room_change)
    if change_label:
        lines.append(f"{change_label}。")

    return "=== 今の場所と時間 ===\n" + "\n".join(lines)
