"""Motion Events — backend state/event contract for livestream (Contract 3).

Design doc: docs/pip_room_temporal_livestream_integration.md §8

Backend sends state updates and transition events to Unity via /ws/room.
Idle micro motion (breathing, blink) is Unity-local — not sent from backend.

Principle: 動きは演出ではなく状態の結果。
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum

from backend.services.room.runtime_facts import (
    PipVisible,
    RoomChange,
    RuntimeFacts,
    TimeOfDay,
)


# ═══════════════════════════════════════════════════════════════
# Conversation state (backend → Unity as state update)
# ═══════════════════════════════════════════════════════════════


class ConversationState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


# ═══════════════════════════════════════════════════════════════
# Motion action registry (shared between backend and Unity)
# ═══════════════════════════════════════════════════════════════


class MotionAction(str, Enum):
    # pip_reaction
    PIP_SLEEP = "pip_sleep"
    PIP_WAKE = "pip_wake"
    PIP_LOOK = "pip_look"
    PIP_PLAY = "pip_play"
    PIP_SNUGGLE = "pip_snuggle"
    PIP_DROWSY = "pip_drowsy"
    PIP_APPROACH = "pip_approach"
    PIP_WITHDRAW = "pip_withdraw"
    # room_event
    OBJECT_ADDED = "object_added"
    OBJECT_REMOVED = "object_removed"
    ART_HUNG = "art_hung"
    ART_REMOVED = "art_removed"
    # time_shift
    LIGHTING_CHANGE = "lighting_change"


# ═══════════════════════════════════════════════════════════════
# Motion event dataclass
# ═══════════════════════════════════════════════════════════════


@dataclass
class MotionEvent:
    """A motion event sent to Unity via WebSocket."""

    event_id: str
    category: str        # "pip_reaction" | "room_event" | "time_shift"
    action: str          # MotionAction value
    intensity: float     # 0.0-1.0
    source_trigger: str  # "T3" | "T4" | "T5"
    ts: float            # emit timestamp
    duration_ms: int | None = None  # None = sustained state change

    def to_ws_message(self) -> dict:
        """Convert to WebSocket message format."""
        return {
            "type": "motion",
            "event_id": self.event_id,
            "category": self.category,
            "action": self.action,
            "intensity": self.intensity,
            "source_trigger": self.source_trigger,
            "ts": self.ts,
            "duration_ms": self.duration_ms,
        }


# ═══════════════════════════════════════════════════════════════
# Pip transition → action mapping
# ═══════════════════════════════════════════════════════════════

# (from_visible, to_visible) → MotionAction
# Use None as wildcard for "any" state.
_PIP_TRANSITION_MAP: list[tuple[PipVisible | None, PipVisible | None, MotionAction]] = [
    # Specific transitions first (higher priority)
    (PipVisible.SLEEPING, None, MotionAction.PIP_WAKE),
    (None, PipVisible.SLEEPING, MotionAction.PIP_SLEEP),
    (None, PipVisible.LOOKING, MotionAction.PIP_LOOK),
    (None, PipVisible.PLAYFUL, MotionAction.PIP_PLAY),
    (None, PipVisible.NEAR, MotionAction.PIP_SNUGGLE),
    (None, PipVisible.SLEEPY, MotionAction.PIP_DROWSY),
]


def _resolve_pip_action(
    from_vis: PipVisible,
    to_vis: PipVisible,
) -> MotionAction | None:
    """Resolve which MotionAction to emit for a pip visible transition."""
    for from_match, to_match, action in _PIP_TRANSITION_MAP:
        if from_match is not None and from_match != from_vis:
            continue
        if to_match is not None and to_match != to_vis:
            continue
        return action
    return None


# Room change → action mapping
_ROOM_CHANGE_ACTION: dict[RoomChange, MotionAction] = {
    RoomChange.OBJECT_ADDED: MotionAction.OBJECT_ADDED,
    RoomChange.OBJECT_REMOVED: MotionAction.OBJECT_REMOVED,
    RoomChange.ART_HUNG: MotionAction.ART_HUNG,
    RoomChange.ART_REMOVED: MotionAction.ART_REMOVED,
}


# ═══════════════════════════════════════════════════════════════
# Event generation (transition-only)
# ═══════════════════════════════════════════════════════════════


def generate_motion_events(
    *,
    facts: RuntimeFacts,
    prev_pip_visible: PipVisible | None = None,
    prev_pip_position_near: bool = False,
    prev_time_of_day: TimeOfDay | None = None,
) -> list[MotionEvent]:
    """Generate motion events from state transitions.

    Only emits events when state *changes*. Unity holds the current
    state and only needs to know about transitions.
    """
    events: list[MotionEvent] = []
    now = time.time()

    # Pip visible transition
    if prev_pip_visible is not None and facts.pip_visible != prev_pip_visible:
        action = _resolve_pip_action(prev_pip_visible, facts.pip_visible)
        if action:
            events.append(MotionEvent(
                event_id=str(uuid.uuid4())[:8],
                category="pip_reaction",
                action=action.value,
                intensity=0.4,
                source_trigger="T3",
                ts=now,
                duration_ms=None,
            ))

    # Pip position near transition
    if facts.pip_position_near and not prev_pip_position_near:
        events.append(MotionEvent(
            event_id=str(uuid.uuid4())[:8],
            category="pip_reaction",
            action=MotionAction.PIP_APPROACH.value,
            intensity=0.3,
            source_trigger="T3",
            ts=now,
            duration_ms=None,
        ))
    elif not facts.pip_position_near and prev_pip_position_near:
        events.append(MotionEvent(
            event_id=str(uuid.uuid4())[:8],
            category="pip_reaction",
            action=MotionAction.PIP_WITHDRAW.value,
            intensity=0.3,
            source_trigger="T3",
            ts=now,
            duration_ms=None,
        ))

    # Room change
    if facts.room_change != RoomChange.NONE:
        action = _ROOM_CHANGE_ACTION.get(facts.room_change)
        if action:
            events.append(MotionEvent(
                event_id=str(uuid.uuid4())[:8],
                category="room_event",
                action=action.value,
                intensity=0.5,
                source_trigger="T4",
                ts=now,
                duration_ms=3000,
            ))

    # Time-of-day transition
    if prev_time_of_day is not None and facts.time_of_day != prev_time_of_day:
        events.append(MotionEvent(
            event_id=str(uuid.uuid4())[:8],
            category="time_shift",
            action=MotionAction.LIGHTING_CHANGE.value,
            intensity=0.3,
            source_trigger="T5",
            ts=now,
            duration_ms=5000,
        ))

    return events


# ═══════════════════════════════════════════════════════════════
# Snapshot (for WS reconnection)
# ═══════════════════════════════════════════════════════════════


def build_snapshot(
    *,
    conversation_state: ConversationState = ConversationState.IDLE,
    pip_visible: PipVisible = PipVisible.RESTING,
    pip_position_near: bool = False,
    time_of_day: TimeOfDay = TimeOfDay.DAY,
) -> dict:
    """Build a full state snapshot for WS reconnection.

    Sent once on /ws/room connect so late subscribers know current state.
    """
    return {
        "type": "snapshot",
        "conversation_state": conversation_state.value,
        "pip_visible": pip_visible.value,
        "pip_position_near": pip_position_near,
        "time_of_day": time_of_day.value,
        "ts": time.time(),
    }


def build_conversation_state_message(state: ConversationState) -> dict:
    """Build a conversation state update message for WS."""
    return {
        "type": "state",
        "key": "conversation_state",
        "value": state.value,
        "ts": time.time(),
    }
