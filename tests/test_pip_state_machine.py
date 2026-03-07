"""Tests for Pip State Machine (Phase P.1).

Design doc: docs/pip_and_room_design.md
"""
import pytest

from backend.services.pip.pip_state import (
    PipState,
    NiaContext,
    BOND_RULES,
    BOND_MIN,
    BOND_MAX,
    clamp_bond,
    apply_bond_delta,
    apply_interaction_bond,
    apply_time_decay,
    dict_to_pip,
    pip_to_dict,
)
from backend.services.pip.state_machine import (
    PipStateMachine,
    IDLE,
    CURIOUS,
    PLAYFUL,
    SLEEPY,
    SLEEPING,
    ALERT,
    COMFORT,
    EMPATHY,
    ENERGY_SLEEPY,
    ENERGY_SLEEP,
    ENERGY_WAKE,
)
from backend.services.pip.interaction_detector import (
    NiaInteractionDetector,
    interaction_detector,
)


# ═══════════════════════════════════════════════════════════════
# PipState & Bond Rules
# ═══════════════════════════════════════════════════════════════


class TestPipState:
    def test_defaults(self):
        pip = PipState()
        assert pip.bond == 0.0
        assert pip.mood == "idle"
        assert pip.energy == 1.0
        assert pip.position == "center"
        assert pip.animation == "idle"

    def test_clamp_bond_upper(self):
        assert clamp_bond(1.5) == BOND_MAX

    def test_clamp_bond_lower(self):
        assert clamp_bond(-1.5) == BOND_MIN

    def test_clamp_bond_normal(self):
        assert clamp_bond(0.5) == 0.5

    def test_apply_bond_delta(self):
        pip = PipState(bond=0.3)
        apply_bond_delta(pip, 0.05)
        assert abs(pip.bond - 0.35) < 1e-6

    def test_apply_bond_delta_clamped(self):
        pip = PipState(bond=0.98)
        apply_bond_delta(pip, 0.05)
        assert pip.bond == BOND_MAX


class TestInteractionBond:
    def test_name_call_increases_bond(self):
        pip = PipState(bond=0.0)
        ctx = NiaContext(called_pip=True)
        delta = apply_interaction_bond(pip, ctx)
        assert delta == BOND_RULES["nia_calls_name"]
        assert pip.bond > 0.0
        assert pip.last_interaction > 0

    def test_draw_pip_highest_bonus(self):
        pip = PipState(bond=0.0)
        ctx = NiaContext(drew_pip=True)
        delta = apply_interaction_bond(pip, ctx)
        assert delta == BOND_RULES["nia_draws_pip"]

    def test_multiple_interactions_stack(self):
        pip = PipState(bond=0.0)
        ctx = NiaContext(called_pip=True, drew_pip=True, placed_near_pip=True)
        delta = apply_interaction_bond(pip, ctx)
        expected = (
            BOND_RULES["nia_draws_pip"]
            + BOND_RULES["nia_calls_name"]
            + BOND_RULES["nia_places_near_pip"]
        )
        assert abs(delta - expected) < 1e-6

    def test_no_interaction_no_change(self):
        pip = PipState(bond=0.3)
        ctx = NiaContext()
        delta = apply_interaction_bond(pip, ctx)
        assert delta == 0.0
        assert pip.bond == 0.3

    def test_mentioned_but_not_called(self):
        pip = PipState(bond=0.0)
        ctx = NiaContext(mentioned_pip=True)  # mentioned but not called
        delta = apply_interaction_bond(pip, ctx)
        assert delta == BOND_RULES["nia_calls_name"] * 0.5


class TestTimeDecay:
    def test_decay_after_one_hour(self):
        pip = PipState(bond=0.5)
        delta = apply_time_decay(pip, hours_since_interaction=1.0)
        assert delta < 0
        assert abs(delta - BOND_RULES["decay_per_hour"]) < 1e-6

    def test_decay_caps_at_zero(self):
        pip = PipState(bond=0.01)
        apply_time_decay(pip, hours_since_interaction=100.0)
        assert pip.bond >= BOND_RULES["decay_cap"]

    def test_no_decay_below_cap(self):
        pip = PipState(bond=0.0)
        delta = apply_time_decay(pip, hours_since_interaction=5.0)
        assert delta == 0.0
        assert pip.bond == 0.0

    def test_long_ignore_penalty(self):
        pip = PipState(bond=0.5)
        delta_12h = apply_time_decay(PipState(bond=0.5), hours_since_interaction=12.0)
        delta_2h = apply_time_decay(PipState(bond=0.5), hours_since_interaction=2.0)
        # 12h has extra penalty
        assert abs(delta_12h) > abs(delta_2h) * 5  # Significantly more


# ═══════════════════════════════════════════════════════════════
# State Machine
# ═══════════════════════════════════════════════════════════════


class TestStateMachine:
    def setup_method(self):
        self.sm = PipStateMachine()

    def test_idle_default(self):
        pip = PipState(energy=0.5, bond=0.0)
        result = self.sm.update(pip)
        assert result.mood == IDLE
        assert result.animation == "idle"

    def test_sleepy_when_low_energy(self):
        pip = PipState(energy=ENERGY_SLEEPY - 0.01, mood="idle")
        result = self.sm.update(pip)
        assert result.mood == SLEEPY
        assert result.animation == "yawn"

    def test_sleeping_from_sleepy(self):
        pip = PipState(energy=ENERGY_SLEEP - 0.01, mood="sleepy")
        result = self.sm.update(pip)
        assert result.mood == SLEEPING
        assert result.animation == "sleeping"

    def test_sleeping_goes_to_favorite_spot(self):
        pip = PipState(energy=ENERGY_SLEEP - 0.01, mood="sleepy", favorite_spot="bookshelf")
        result = self.sm.update(pip)
        assert result.position == "bookshelf"

    def test_sleeping_default_corner(self):
        pip = PipState(energy=ENERGY_SLEEP - 0.01, mood="sleepy", favorite_spot="")
        result = self.sm.update(pip)
        assert result.position == "corner"

    def test_wake_up_from_energy(self):
        pip = PipState(energy=ENERGY_WAKE + 0.01, mood="sleeping")
        result = self.sm.update(pip)
        assert result.mood == ALERT
        assert result.animation == "wake_up"

    def test_wake_up_from_call(self):
        pip = PipState(energy=0.3, mood="sleeping")
        ctx = NiaContext(called_pip=True)
        result = self.sm.update(pip, ctx)
        assert result.mood == ALERT

    def test_sleeping_stays_asleep(self):
        pip = PipState(energy=0.5, mood="sleeping")
        result = self.sm.update(pip)
        assert result.mood == SLEEPING

    def test_energy_recovers_while_sleeping(self):
        pip = PipState(energy=0.5, mood="sleeping")
        result = self.sm.update(pip)
        assert result.energy > 0.5

    def test_energy_drains_while_awake(self):
        pip = PipState(energy=0.5, mood="idle")
        result = self.sm.update(pip)
        assert result.energy < 0.5

    def test_energy_drains_faster_at_night(self):
        pip1 = PipState(energy=0.5, mood="idle")
        pip2 = PipState(energy=0.5, mood="idle")
        self.sm.update(pip1, is_night=False)
        self.sm.update(pip2, is_night=True)
        assert pip2.energy < pip1.energy

    def test_curious_when_nia_talking(self):
        pip = PipState(energy=0.5, bond=0.2)
        ctx = NiaContext(is_talking=True)
        result = self.sm.update(pip, ctx)
        assert result.mood == CURIOUS
        assert result.animation == "head_tilt"
        assert result.position == "near_nia"

    def test_curious_requires_bond(self):
        pip = PipState(energy=0.5, bond=0.0)
        ctx = NiaContext(is_talking=True)
        result = self.sm.update(pip, ctx)
        assert result.mood == IDLE  # bond too low

    def test_playful_with_energy_and_bond(self):
        pip = PipState(energy=0.6, bond=0.5)
        result = self.sm.update(pip)
        assert result.mood == PLAYFUL
        assert result.animation in ("tail_wag", "spin", "look_around")

    def test_comfort_high_bond_talking(self):
        pip = PipState(energy=0.5, bond=0.8)
        ctx = NiaContext(is_talking=True)
        result = self.sm.update(pip, ctx)
        assert result.mood == COMFORT
        assert result.animation == "snuggle"
        assert result.position == "next_to_nia"

    def test_empathy_high_bond_low_mood(self):
        pip = PipState(energy=0.5, bond=0.8)
        ctx = NiaContext(emotional_state="low")
        result = self.sm.update(pip, ctx)
        assert result.mood == EMPATHY
        assert result.animation == "lean_against"

    def test_alert_transitions_to_idle(self):
        pip = PipState(energy=0.3, mood="alert")
        result = self.sm.update(pip)
        assert result.mood == IDLE

    def test_alert_transitions_to_curious(self):
        pip = PipState(energy=0.6, mood="alert")
        result = self.sm.update(pip)
        assert result.mood == CURIOUS


# ═══════════════════════════════════════════════════════════════
# Interaction Detector
# ═══════════════════════════════════════════════════════════════


class TestInteractionDetector:
    def setup_method(self):
        self.detector = NiaInteractionDetector()

    def test_detect_pip_name_english(self):
        ctx = self.detector.detect("Pipかわいいね")
        assert ctx.called_pip is True
        assert ctx.mentioned_pip is True

    def test_detect_pip_name_katakana(self):
        ctx = self.detector.detect("ピップが寝てる")
        assert ctx.called_pip is True

    def test_detect_pip_name_hiragana(self):
        ctx = self.detector.detect("ぴっぷ、おいで")
        assert ctx.called_pip is True

    def test_detect_reference_kono_ko(self):
        ctx = self.detector.detect("この子、かわいいね")
        assert ctx.called_pip is False
        assert ctx.mentioned_pip is True

    def test_detect_reference_dog(self):
        ctx = self.detector.detect("犬が寝てるよ")
        assert ctx.mentioned_pip is True

    def test_detect_drew_pip_from_actions(self):
        ctx = self.detector.detect("描いてみた", ["draw_pip"])
        assert ctx.drew_pip is True

    def test_detect_drew_pip_from_text(self):
        ctx = self.detector.detect("Pipの絵を描いたよ")
        assert ctx.drew_pip is True

    def test_detect_placed_near_pip(self):
        ctx = self.detector.detect("", ["place_object:near_pip:cushion"])
        assert ctx.placed_near_pip is True

    def test_no_interaction(self):
        ctx = self.detector.detect("今日はいい天気だね")
        assert ctx.called_pip is False
        assert ctx.mentioned_pip is False
        assert ctx.drew_pip is False
        assert ctx.placed_near_pip is False

    def test_empty_input(self):
        ctx = self.detector.detect("")
        assert ctx.called_pip is False
        assert ctx.mentioned_pip is False

    def test_is_talking_passthrough(self):
        ctx = self.detector.detect("hello", is_talking=True)
        assert ctx.is_talking is True

    def test_emotional_state_passthrough(self):
        ctx = self.detector.detect("", emotional_state="low")
        assert ctx.emotional_state == "low"

    def test_singleton_works(self):
        ctx = interaction_detector.detect("Pipがいるね")
        assert ctx.called_pip is True


# ═══════════════════════════════════════════════════════════════
# Integration: Bond + State Machine
# ═══════════════════════════════════════════════════════════════


class TestBondStateMachineIntegration:
    def test_bond_buildup_unlocks_playful(self):
        pip = PipState(energy=0.8, bond=0.0)
        sm = PipStateMachine()

        # Simulate many interactions to build bond
        for _ in range(25):
            ctx = NiaContext(called_pip=True)
            apply_interaction_bond(pip, ctx)

        assert pip.bond >= 0.4

        # Now state machine should produce PLAYFUL
        result = sm.update(pip)
        assert result.mood == PLAYFUL

    def test_bond_buildup_unlocks_comfort(self):
        pip = PipState(energy=0.5, bond=0.0)
        sm = PipStateMachine()

        # Many interactions (drew_pip is the biggest bonus)
        for _ in range(15):
            ctx = NiaContext(drew_pip=True)
            apply_interaction_bond(pip, ctx)

        assert pip.bond >= 0.7

        ctx = NiaContext(is_talking=True)
        result = sm.update(pip, ctx)
        assert result.mood == COMFORT

    def test_decay_resets_to_idle(self):
        pip = PipState(energy=0.5, bond=0.3)
        sm = PipStateMachine()

        # Significant time passes
        apply_time_decay(pip, hours_since_interaction=100.0)
        assert pip.bond == 0.0

        result = sm.update(pip)
        assert result.mood == IDLE


# =============================================================================
# Phase P.4: Bond Deepening
# =============================================================================


class TestDictConversion:
    """Test public dict_to_pip / pip_to_dict conversion functions."""

    def test_roundtrip(self):
        pip = PipState(bond=0.5, mood="curious", energy=0.8, favorite_spot="corner_ne")
        d = pip_to_dict(pip)
        restored = dict_to_pip(d)
        assert restored.bond == pytest.approx(0.5)
        assert restored.mood == "curious"
        assert restored.favorite_spot == "corner_ne"

    def test_dict_to_pip_defaults(self):
        pip = dict_to_pip({})
        assert pip.bond == 0.0
        assert pip.mood == "idle"
        assert pip.energy == 1.0

    def test_pip_to_dict_rounds_bond(self):
        pip = PipState(bond=0.12345678)
        d = pip_to_dict(pip)
        assert d["bond"] == pytest.approx(0.1235, abs=0.001)


class TestEmotionalStateInference:
    """Test _infer_emotional_state in actions.py."""

    def test_dissonance_returns_low(self):
        from backend.core.agent_graph.nodes.actions import _infer_emotional_state
        state = {"dissonance_on": True, "confidence": 0.7}
        assert _infer_emotional_state(state) == "low"

    def test_low_confidence_returns_low(self):
        from backend.core.agent_graph.nodes.actions import _infer_emotional_state
        state = {"confidence": 0.2}
        assert _infer_emotional_state(state) == "low"

    def test_somatic_contradiction_returns_low(self):
        from backend.core.agent_graph.nodes.actions import _infer_emotional_state
        state = {
            "confidence": 0.6,
            "somatic_senses": [{"text": "間違ってた。少し自信が持てない", "intensity": 0.7}],
        }
        assert _infer_emotional_state(state) == "low"

    def test_neutral_default(self):
        from backend.core.agent_graph.nodes.actions import _infer_emotional_state
        state = {"confidence": 0.6}
        assert _infer_emotional_state(state) == "neutral"

    def test_empty_state_returns_neutral(self):
        from backend.core.agent_graph.nodes.actions import _infer_emotional_state
        assert _infer_emotional_state({}) == "neutral"


class TestRoomChangeReaction:
    """Test Pip's reaction to room changes (P.4: room_action.py)."""

    def test_move_applies_bond_penalty(self):
        from backend.services.room.room_state import RoomState
        from backend.services.room.room_action import RoomAction, execute_room_action

        room = RoomState(
            objects=[{"id": "obj1", "name": "机", "template": "desk", "position": "center", "type": "furniture"}],
            pip_state={"bond": 0.5, "mood": "idle", "energy": 1.0,
                       "position": "center", "animation": "idle",
                       "favorite_spot": "", "last_interaction": 0.0,
                       "scrap_count": 0, "current_scrap_id": ""},
        )
        action = RoomAction(action_type="move", target_id="obj1", position="corner_ne")
        execute_room_action(room, action)

        assert room.pip_state["bond"] == pytest.approx(0.5 + BOND_RULES["nia_room_change"], abs=0.001)
        assert room.pip_state["animation"] == "look_around"

    def test_remove_applies_bond_penalty(self):
        from backend.services.room.room_state import RoomState
        from backend.services.room.room_action import RoomAction, execute_room_action

        room = RoomState(
            objects=[{"id": "obj1", "name": "机", "template": "desk", "position": "center", "type": "furniture"}],
            pip_state={"bond": 0.3, "mood": "idle", "energy": 1.0,
                       "position": "center", "animation": "idle",
                       "favorite_spot": "", "last_interaction": 0.0,
                       "scrap_count": 0, "current_scrap_id": ""},
        )
        action = RoomAction(action_type="remove", target_id="obj1")
        execute_room_action(room, action)

        assert room.pip_state["bond"] < 0.3
        assert room.pip_state["animation"] == "look_around"

    def test_hang_art_sets_react_animation(self):
        from backend.services.room.room_state import RoomState
        from backend.services.room.room_action import RoomAction, execute_room_action

        room = RoomState(
            pip_state={"bond": 0.2, "mood": "idle", "energy": 1.0,
                       "position": "center", "animation": "idle",
                       "favorite_spot": "", "last_interaction": 0.0,
                       "scrap_count": 0, "current_scrap_id": ""},
        )
        action = RoomAction(action_type="hang_art", art_image="/art/test.png")
        execute_room_action(room, action)

        assert room.pip_state["animation"] == "react_to_art"

    def test_place_no_penalty(self):
        from backend.services.room.room_state import RoomState
        from backend.services.room.room_action import RoomAction, execute_room_action

        room = RoomState(
            pip_state={"bond": 0.5, "mood": "idle", "energy": 1.0,
                       "position": "center", "animation": "idle",
                       "favorite_spot": "", "last_interaction": 0.0,
                       "scrap_count": 0, "current_scrap_id": ""},
        )
        action = RoomAction(action_type="place", template="desk", position="center")
        execute_room_action(room, action)

        # Place doesn't trigger pip reaction (animation stays idle)
        assert room.pip_state["bond"] == pytest.approx(0.5)
        assert room.pip_state["animation"] == "idle"
