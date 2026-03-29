"""Tests for Contract 3: Motion Events."""
import pytest

from backend.services.room.motion_events import (
    ConversationState,
    MotionAction,
    MotionEvent,
    build_conversation_state_message,
    build_snapshot,
    generate_motion_events,
)
from backend.services.room.runtime_facts import (
    PipVisible,
    RoomChange,
    RuntimeFacts,
    SilenceGap,
    TimeOfDay,
)


# ── ConversationState enum ────────────────────────────────────


class TestConversationState:
    def test_values(self):
        assert ConversationState.IDLE.value == "idle"
        assert ConversationState.LISTENING.value == "listening"
        assert ConversationState.THINKING.value == "thinking"
        assert ConversationState.SPEAKING.value == "speaking"


# ── MotionAction registry ────────────────────────────────────


class TestMotionAction:
    def test_pip_actions(self):
        pip_actions = [
            MotionAction.PIP_SLEEP, MotionAction.PIP_WAKE,
            MotionAction.PIP_LOOK, MotionAction.PIP_PLAY,
            MotionAction.PIP_SNUGGLE, MotionAction.PIP_DROWSY,
            MotionAction.PIP_APPROACH, MotionAction.PIP_WITHDRAW,
        ]
        assert len(pip_actions) == 8

    def test_room_actions(self):
        room_actions = [
            MotionAction.OBJECT_ADDED, MotionAction.OBJECT_REMOVED,
            MotionAction.ART_HUNG, MotionAction.ART_REMOVED,
        ]
        assert len(room_actions) == 4

    def test_time_shift_action(self):
        assert MotionAction.LIGHTING_CHANGE.value == "lighting_change"


# ── MotionEvent ───────────────────────────────────────────────


class TestMotionEvent:
    def test_to_ws_message(self):
        event = MotionEvent(
            event_id="abc123",
            category="pip_reaction",
            action="pip_sleep",
            intensity=0.4,
            source_trigger="T3",
            ts=1000.0,
            duration_ms=None,
        )
        msg = event.to_ws_message()
        assert msg["type"] == "motion"
        assert msg["event_id"] == "abc123"
        assert msg["category"] == "pip_reaction"
        assert msg["action"] == "pip_sleep"
        assert msg["duration_ms"] is None


# ── generate_motion_events ────────────────────────────────────


def _make_facts(**kwargs):
    defaults = dict(
        time_of_day=TimeOfDay.DAY,
        silence_gap=SilenceGap.NONE,
        pip_visible=PipVisible.RESTING,
        pip_position_near=False,
        room_change=RoomChange.NONE,
    )
    defaults.update(kwargs)
    return RuntimeFacts(**defaults)


class TestGenerateMotionEvents:
    def test_no_transitions_no_events(self):
        facts = _make_facts()
        events = generate_motion_events(
            facts=facts,
            prev_pip_visible=PipVisible.RESTING,
            prev_pip_position_near=False,
            prev_time_of_day=TimeOfDay.DAY,
        )
        assert events == []

    def test_pip_visible_transition(self):
        facts = _make_facts(pip_visible=PipVisible.SLEEPING)
        events = generate_motion_events(
            facts=facts,
            prev_pip_visible=PipVisible.RESTING,
        )
        assert len(events) == 1
        assert events[0].category == "pip_reaction"
        assert events[0].action == MotionAction.PIP_SLEEP.value

    def test_pip_wake_transition(self):
        facts = _make_facts(pip_visible=PipVisible.LOOKING)
        events = generate_motion_events(
            facts=facts,
            prev_pip_visible=PipVisible.SLEEPING,
        )
        assert len(events) == 1
        assert events[0].action == MotionAction.PIP_WAKE.value

    def test_pip_approach(self):
        facts = _make_facts(pip_position_near=True)
        events = generate_motion_events(
            facts=facts,
            prev_pip_position_near=False,
        )
        approach_events = [e for e in events if e.action == MotionAction.PIP_APPROACH.value]
        assert len(approach_events) == 1
        assert approach_events[0].duration_ms is None  # sustained

    def test_pip_withdraw(self):
        facts = _make_facts(pip_position_near=False)
        events = generate_motion_events(
            facts=facts,
            prev_pip_position_near=True,
        )
        withdraw_events = [e for e in events if e.action == MotionAction.PIP_WITHDRAW.value]
        assert len(withdraw_events) == 1

    def test_room_event(self):
        facts = _make_facts(room_change=RoomChange.ART_HUNG)
        events = generate_motion_events(facts=facts)
        room_events = [e for e in events if e.category == "room_event"]
        assert len(room_events) == 1
        assert room_events[0].action == MotionAction.ART_HUNG.value
        assert room_events[0].duration_ms == 3000

    def test_time_shift(self):
        facts = _make_facts(time_of_day=TimeOfDay.NIGHT)
        events = generate_motion_events(
            facts=facts,
            prev_time_of_day=TimeOfDay.DAY,
        )
        time_events = [e for e in events if e.category == "time_shift"]
        assert len(time_events) == 1
        assert time_events[0].action == MotionAction.LIGHTING_CHANGE.value
        assert time_events[0].duration_ms == 5000

    def test_multiple_events_same_turn(self):
        facts = _make_facts(
            pip_visible=PipVisible.SLEEPING,
            room_change=RoomChange.OBJECT_ADDED,
            time_of_day=TimeOfDay.NIGHT,
        )
        events = generate_motion_events(
            facts=facts,
            prev_pip_visible=PipVisible.RESTING,
            prev_time_of_day=TimeOfDay.DAY,
        )
        categories = {e.category for e in events}
        assert "pip_reaction" in categories
        assert "room_event" in categories
        assert "time_shift" in categories

    def test_no_event_on_same_pip_visible(self):
        facts = _make_facts(pip_visible=PipVisible.LOOKING)
        events = generate_motion_events(
            facts=facts,
            prev_pip_visible=PipVisible.LOOKING,
        )
        pip_events = [e for e in events if e.category == "pip_reaction"]
        assert len(pip_events) == 0


# ── Snapshot ──────────────────────────────────────────────────


class TestBuildSnapshot:
    def test_snapshot_structure(self):
        snap = build_snapshot(
            conversation_state=ConversationState.THINKING,
            pip_visible=PipVisible.SLEEPING,
            pip_position_near=True,
            time_of_day=TimeOfDay.NIGHT,
        )
        assert snap["type"] == "snapshot"
        assert snap["conversation_state"] == "thinking"
        assert snap["pip_visible"] == "sleeping"
        assert snap["pip_position_near"] is True
        assert snap["time_of_day"] == "night"
        assert "ts" in snap


# ── Conversation state message ────────────────────────────────


class TestConversationStateMessage:
    def test_message_structure(self):
        msg = build_conversation_state_message(ConversationState.SPEAKING)
        assert msg["type"] == "state"
        assert msg["key"] == "conversation_state"
        assert msg["value"] == "speaking"
        assert "ts" in msg
