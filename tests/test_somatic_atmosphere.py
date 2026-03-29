"""Tests for Contract 2: Somatic Atmosphere."""
import pytest

from backend.services.room.runtime_facts import (
    PipVisible,
    RoomChange,
    RuntimeFacts,
    SilenceGap,
    TimeOfDay,
)
from backend.services.room.somatic_atmosphere import (
    _detect_modifiers,
    _detect_triggers,
    _SOMATIC_TEMPLATES,
    build_somatic_atmosphere,
)


# ── Modifier detection ────────────────────────────────────────


class TestDetectModifiers:
    def test_no_modifiers(self):
        facts = RuntimeFacts(
            time_of_day=TimeOfDay.DAY,
            silence_gap=SilenceGap.NONE,
            pip_visible=PipVisible.RESTING,
            pip_position_near=False,
            room_change=RoomChange.NONE,
        )
        assert _detect_modifiers(facts, TimeOfDay.DAY) is None

    def test_m1_long_silence(self):
        facts = RuntimeFacts(
            time_of_day=TimeOfDay.DAY,
            silence_gap=SilenceGap.LONG,
            pip_visible=PipVisible.RESTING,
            pip_position_near=False,
            room_change=RoomChange.NONE,
        )
        assert _detect_modifiers(facts, TimeOfDay.DAY) == "M1"

    def test_m5_time_changed(self):
        facts = RuntimeFacts(
            time_of_day=TimeOfDay.NIGHT,
            silence_gap=SilenceGap.NONE,
            pip_visible=PipVisible.RESTING,
            pip_position_near=False,
            room_change=RoomChange.NONE,
        )
        assert _detect_modifiers(facts, TimeOfDay.DAY) == "M5"

    def test_m1_m5_combined(self):
        facts = RuntimeFacts(
            time_of_day=TimeOfDay.NIGHT,
            silence_gap=SilenceGap.VERY_LONG,
            pip_visible=PipVisible.RESTING,
            pip_position_near=False,
            room_change=RoomChange.NONE,
        )
        assert _detect_modifiers(facts, TimeOfDay.DAY) == "M1+M5"


# ── Trigger detection ─────────────────────────────────────────


class TestDetectTriggers:
    def _make_facts(self, **kwargs):
        defaults = dict(
            time_of_day=TimeOfDay.DAY,
            silence_gap=SilenceGap.NONE,
            pip_visible=PipVisible.RESTING,
            pip_position_near=False,
            room_change=RoomChange.NONE,
        )
        defaults.update(kwargs)
        return RuntimeFacts(**defaults)

    def test_no_triggers(self):
        facts = self._make_facts()
        triggers = _detect_triggers(
            facts, PipVisible.RESTING, TimeOfDay.DAY, "test", [],
        )
        assert triggers == []

    def test_t4_room_change(self):
        facts = self._make_facts(room_change=RoomChange.ART_HUNG)
        triggers = _detect_triggers(
            facts, PipVisible.RESTING, TimeOfDay.DAY, "test", [],
        )
        assert "T4" in triggers

    def test_t3_pip_changed(self):
        facts = self._make_facts(pip_visible=PipVisible.SLEEPING)
        triggers = _detect_triggers(
            facts, PipVisible.RESTING, TimeOfDay.DAY, "test", [],
        )
        assert "T3" in triggers

    def test_t2_pip_near(self):
        facts = self._make_facts(pip_position_near=True)
        triggers = _detect_triggers(
            facts, PipVisible.RESTING, TimeOfDay.DAY, "test", [],
        )
        assert "T2" in triggers

    def test_t3_absorbs_t2(self):
        """When T3 fires, T2 should not fire separately."""
        facts = self._make_facts(
            pip_visible=PipVisible.NEAR,
            pip_position_near=True,
        )
        triggers = _detect_triggers(
            facts, PipVisible.RESTING, TimeOfDay.DAY, "test", [],
        )
        assert "T3" in triggers
        assert "T2" not in triggers

    def test_t4_and_t3_both_fire(self):
        facts = self._make_facts(
            room_change=RoomChange.OBJECT_ADDED,
            pip_visible=PipVisible.LOOKING,
        )
        triggers = _detect_triggers(
            facts, PipVisible.RESTING, TimeOfDay.DAY, "test", [],
        )
        assert "T4" in triggers
        assert "T3" in triggers

    def test_no_trigger_on_same_pip_visible(self):
        facts = self._make_facts(pip_visible=PipVisible.LOOKING)
        triggers = _detect_triggers(
            facts, PipVisible.LOOKING, TimeOfDay.DAY, "test", [],
        )
        assert "T3" not in triggers

    def test_no_prev_pip_visible_no_t3(self):
        """First turn — no previous pip visible, T3 should not fire."""
        facts = self._make_facts(pip_visible=PipVisible.SLEEPING)
        triggers = _detect_triggers(
            facts, None, TimeOfDay.DAY, "test", [],
        )
        assert "T3" not in triggers


# ── Template coverage ─────────────────────────────────────────


class TestTemplates:
    def test_all_trigger_modifier_combos_have_base(self):
        """All triggers must have at least a (trigger, None) template."""
        for trigger in ["T2", "T3", "T4"]:
            assert (trigger, None) in _SOMATIC_TEMPLATES


# ── build_somatic_atmosphere ──────────────────────────────────


class TestBuildSomaticAtmosphere:
    def test_no_triggers_empty(self):
        facts = RuntimeFacts(
            time_of_day=TimeOfDay.DAY,
            silence_gap=SilenceGap.NONE,
            pip_visible=PipVisible.RESTING,
            pip_position_near=False,
            room_change=RoomChange.NONE,
        )
        text = build_somatic_atmosphere(
            facts=facts,
            prev_pip_visible=PipVisible.RESTING,
            prev_time_of_day=TimeOfDay.DAY,
            thread_id="test",
            turn_id="t1",
        )
        assert text == ""

    def test_t4_fires(self):
        facts = RuntimeFacts(
            time_of_day=TimeOfDay.DAY,
            silence_gap=SilenceGap.NONE,
            pip_visible=PipVisible.RESTING,
            pip_position_near=False,
            room_change=RoomChange.ART_HUNG,
        )
        text = build_somatic_atmosphere(
            facts=facts,
            prev_pip_visible=PipVisible.RESTING,
            prev_time_of_day=TimeOfDay.DAY,
            thread_id="test",
            turn_id="t1",
        )
        assert "=== 場の空気 ===" in text
        assert "部屋の空気" in text

    def test_t3_with_m1(self):
        facts = RuntimeFacts(
            time_of_day=TimeOfDay.DAY,
            silence_gap=SilenceGap.VERY_LONG,
            pip_visible=PipVisible.SLEEPING,
            pip_position_near=False,
            room_change=RoomChange.NONE,
        )
        text = build_somatic_atmosphere(
            facts=facts,
            prev_pip_visible=PipVisible.RESTING,
            prev_time_of_day=TimeOfDay.DAY,
            thread_id="test",
            turn_id="t1",
        )
        assert "静けさの中で" in text
        assert "隣の気配が変わった" in text

    def test_max_two_lines(self):
        facts = RuntimeFacts(
            time_of_day=TimeOfDay.DAY,
            silence_gap=SilenceGap.NONE,
            pip_visible=PipVisible.LOOKING,
            pip_position_near=True,
            room_change=RoomChange.ART_HUNG,
        )
        text = build_somatic_atmosphere(
            facts=facts,
            prev_pip_visible=PipVisible.RESTING,
            prev_time_of_day=TimeOfDay.DAY,
            thread_id="test",
            turn_id="t1",
        )
        # T4 + T3 fire, T2 absorbed by T3. Max 2 lines.
        lines = [l for l in text.split("\n") if l.startswith("- ")]
        assert len(lines) <= 2

    def test_section_name_no_annotation(self):
        """Section should not have an annotation comment."""
        facts = RuntimeFacts(
            time_of_day=TimeOfDay.DAY,
            silence_gap=SilenceGap.NONE,
            pip_visible=PipVisible.SLEEPING,
            pip_position_near=False,
            room_change=RoomChange.NONE,
        )
        text = build_somatic_atmosphere(
            facts=facts,
            prev_pip_visible=PipVisible.RESTING,
            prev_time_of_day=TimeOfDay.DAY,
            thread_id="test",
            turn_id="t1",
        )
        if text:
            assert "指示ではない" not in text
            assert "（これは" not in text
