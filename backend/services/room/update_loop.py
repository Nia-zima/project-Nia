"""
Room Update Loop — background asyncio loop updating room state every minute.

Design doc: docs/pip_and_room_design.md §4.3
Phase P.2: lighting, Pip state machine, Bond decay, position history, favorite spot.
"""
from __future__ import annotations

import asyncio
import time
from collections import Counter
from datetime import datetime

from backend.core.config import settings
from backend.core.logger import logger
from backend.services.room.room_state import (
    RoomState,
    compute_lighting,
    apply_lamp_bonus,
    load_room_state,
    save_room_state,
)
from backend.services.pip.pip_state import (
    PipState,
    NiaContext,
    BOND_RULES,
    apply_time_decay,
    dict_to_pip,
    pip_to_dict,
)
from backend.services.pip.state_machine import pip_state_machine


# Maximum position history entries (48h at 1 entry/min)
MAX_POSITION_HISTORY = 2880

# Minimum positions to compute favorite spot
MIN_POSITIONS_FOR_FAVORITE = 60


async def room_update_loop() -> None:
    """Background loop: update room state every 60 seconds.

    Updates:
    1. Time-of-day lighting
    2. Pip state machine (mood/animation/position)
    3. Bond natural decay
    4. Position history recording
    5. Favorite spot computation
    """
    logger.info("[Room] update_loop started")

    prev_pip_mood = ""
    prev_pip_animation = ""
    prev_pip_position = ""
    prev_tod = ""
    prev_intensity = 0.0

    while True:
        try:
            room = load_room_state()
            now_dt = datetime.now()
            now_ts = time.time()

            # 1. Lighting
            tod, intensity, color = compute_lighting(now_dt.hour)
            room.time_of_day = tod
            room.light_intensity = intensity
            room.light_color = color
            apply_lamp_bonus(room)

            # 2. Pip state machine update
            pip = dict_to_pip(room.pip_state)
            _sync_bond_from_telemetry(pip)
            is_night = tod in ("night", "late_night")
            nia_ctx = _load_last_nia_context()
            pip_state_machine.update(pip, nia_context=nia_ctx, is_night=is_night)

            # 3. Bond natural decay
            if pip.last_interaction > 0:
                hours_since = (now_ts - pip.last_interaction) / 3600
                apply_time_decay(pip, hours_since)

            # 4. Position history
            room.pip_position_history.append(pip.position)
            if len(room.pip_position_history) > MAX_POSITION_HISTORY:
                room.pip_position_history = room.pip_position_history[-MAX_POSITION_HISTORY:]

            # 5. Favorite spot
            _update_favorite_spot(pip, room.pip_position_history)

            # Write back pip state
            room.pip_state = pip_to_dict(pip)

            save_room_state(room)

            # 6. WebSocket broadcast (diff-based)
            await _broadcast_changes(
                room,
                prev_pip_mood, prev_pip_animation, prev_pip_position,
                prev_tod, prev_intensity,
            )
            prev_pip_mood = room.pip_state.get("mood", "")
            prev_pip_animation = room.pip_state.get("animation", "")
            prev_pip_position = room.pip_state.get("position", "")
            prev_tod = room.time_of_day
            prev_intensity = room.light_intensity

        except Exception:
            logger.warning("[Room] update_loop tick failed", exc_info=True)

        await asyncio.sleep(60)


def run_single_update(room: RoomState) -> RoomState:
    """Run a single update tick (for testing). Returns updated room."""
    now_dt = datetime.now()
    now_ts = time.time()

    tod, intensity, color = compute_lighting(now_dt.hour)
    room.time_of_day = tod
    room.light_intensity = intensity
    room.light_color = color
    apply_lamp_bonus(room)

    pip = dict_to_pip(room.pip_state)
    _sync_bond_from_telemetry(pip)
    is_night = tod in ("night", "late_night")
    nia_ctx = _load_last_nia_context()
    pip_state_machine.update(pip, nia_context=nia_ctx, is_night=is_night)

    if pip.last_interaction > 0:
        hours_since = (now_ts - pip.last_interaction) / 3600
        apply_time_decay(pip, hours_since)

    room.pip_position_history.append(pip.position)
    if len(room.pip_position_history) > MAX_POSITION_HISTORY:
        room.pip_position_history = room.pip_position_history[-MAX_POSITION_HISTORY:]

    _update_favorite_spot(pip, room.pip_position_history)
    room.pip_state = pip_to_dict(pip)

    return room


# ── Helpers ───────────────────────────────────────────────────


def _sync_bond_from_telemetry(pip: PipState) -> None:
    """Sync bond from telemetry_kv (written by s5_commit) into pip.

    This bridges the gap between s5_commit (writes telemetry_kv)
    and update_loop (reads room_state.json).
    """
    import json
    try:
        from backend.core.db import managed_conn
        with managed_conn() as conn:
            row = conn.execute(
                "SELECT v FROM telemetry_kv WHERE k = 'pip_state'"
            ).fetchone()
            if row:
                data = json.loads(row[0])
                pip.bond = data.get("bond", pip.bond)
                pip.last_interaction = data.get("last_interaction", pip.last_interaction)
    except Exception:
        pass  # non-critical; keep existing values


def _load_last_nia_context() -> NiaContext | None:
    """Load most recent NiaContext from telemetry_kv.

    Returns None if no data or data is stale (>5 minutes).
    """
    import json
    try:
        from backend.core.db import managed_conn
        with managed_conn() as conn:
            row = conn.execute(
                "SELECT v FROM telemetry_kv WHERE k = 'last_nia_context'"
            ).fetchone()
            if not row:
                return None
            data = json.loads(row[0])
            if time.time() - data.get("timestamp", 0) > 300:
                return None
            return NiaContext(
                is_talking=data.get("is_talking", False),
                emotional_state=data.get("emotional_state", "neutral"),
                called_pip=data.get("called_pip", False),
                mentioned_pip=data.get("mentioned_pip", False),
            )
    except Exception:
        return None


def _update_favorite_spot(pip: PipState, history: list[str]) -> None:
    """Set Pip's favorite spot based on position history.

    Requires Bond >= 0.4 and at least 60 data points (1 hour).
    """
    if pip.bond < 0.4:
        pip.favorite_spot = ""
        return

    if len(history) < MIN_POSITIONS_FOR_FAVORITE:
        return

    # Use last 24h of data (1440 entries at 1/min)
    recent = history[-1440:]
    counts = Counter(recent)

    # Exclude special positions from favorite
    excluded = {"near_nia", "next_to_nia"}
    for pos in excluded:
        counts.pop(pos, None)

    if counts:
        pip.favorite_spot = counts.most_common(1)[0][0]


async def _broadcast_changes(
    room: RoomState,
    prev_mood: str,
    prev_animation: str,
    prev_position: str,
    prev_tod: str,
    prev_intensity: float,
) -> None:
    """Broadcast state changes to connected Unity clients (if any)."""
    try:
        from backend.controllers.ws_room import room_manager
    except ImportError:
        return

    if not room_manager.has_connections:
        return

    pip = room.pip_state or {}
    pip_changed = (
        pip.get("mood", "") != prev_mood
        or pip.get("animation", "") != prev_animation
        or pip.get("position", "") != prev_position
    )
    lighting_changed = (
        room.time_of_day != prev_tod
        or room.light_intensity != prev_intensity
    )

    if pip_changed:
        await room_manager.broadcast_pip_update(pip)
    if lighting_changed:
        await room_manager.broadcast_lighting_update(
            room.time_of_day, room.light_intensity, room.light_color,
        )
