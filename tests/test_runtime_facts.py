"""Tests for Contract 1: RuntimeFacts."""
import pytest

from backend.services.room.runtime_facts import (
    PipVisible,
    RoomChange,
    RuntimeFacts,
    SilenceGap,
    TimeOfDay,
    _detect_room_change,
    _room_content_hash,
    build_runtime_facts,
    format_runtime_facts,
    hour_to_time_of_day,
    mood_to_visible,
    seconds_to_gap,
)


# ── hour_to_time_of_day ──────────────────────────────────────


class TestHourToTimeOfDay:
    @pytest.mark.parametrize("hour,expected", [
        (5, TimeOfDay.MORNING),
        (9, TimeOfDay.MORNING),
        (10, TimeOfDay.DAY),
        (15, TimeOfDay.DAY),
        (19, TimeOfDay.DAY),
        (20, TimeOfDay.NIGHT),
        (23, TimeOfDay.NIGHT),
        (0, TimeOfDay.NIGHT),
        (1, TimeOfDay.LATE_NIGHT),
        (4, TimeOfDay.LATE_NIGHT),
    ])
    def test_hour_boundaries(self, hour, expected):
        assert hour_to_time_of_day(hour) == expected


# ── seconds_to_gap ───────────────────────────────────────────


class TestSecondsToGap:
    @pytest.mark.parametrize("seconds,expected", [
        (0, SilenceGap.NONE),
        (5, SilenceGap.NONE),
        (10, SilenceGap.SHORT),
        (299, SilenceGap.SHORT),
        (300, SilenceGap.LONG),
        (1799, SilenceGap.LONG),
        (1800, SilenceGap.VERY_LONG),
        (99999, SilenceGap.VERY_LONG),
    ])
    def test_gap_boundaries(self, seconds, expected):
        assert seconds_to_gap(seconds) == expected


# ── mood_to_visible ──────────────────────────────────────────


class TestMoodToVisible:
    @pytest.mark.parametrize("mood,expected", [
        ("idle", PipVisible.RESTING),
        ("curious", PipVisible.LOOKING),
        ("alert", PipVisible.LOOKING),
        ("playful", PipVisible.PLAYFUL),
        ("sleepy", PipVisible.SLEEPY),
        ("sleeping", PipVisible.SLEEPING),
        ("comfort", PipVisible.NEAR),
        ("empathy", PipVisible.NEAR),
        ("unknown_mood", PipVisible.RESTING),
    ])
    def test_mood_mapping(self, mood, expected):
        assert mood_to_visible(mood) == expected


# ── room change detection ────────────────────────────────────


class TestRoomChangeDetection:
    def test_no_change_same_hash(self):
        objs = [{"id": "a"}, {"id": "b"}]
        art = [{"id": "x"}]
        h = _room_content_hash(objs, art)
        change, new_hash = _detect_room_change(
            objs, art, objs, art, last_emitted_hash=h,
        )
        assert change == RoomChange.NONE
        assert new_hash == h

    def test_object_added(self):
        prev = [{"id": "a"}]
        cur = [{"id": "a"}, {"id": "b"}]
        change, _ = _detect_room_change(
            cur, [], prev, [], last_emitted_hash=_room_content_hash(prev, []),
        )
        assert change == RoomChange.OBJECT_ADDED

    def test_object_removed(self):
        prev = [{"id": "a"}, {"id": "b"}]
        cur = [{"id": "a"}]
        change, _ = _detect_room_change(
            cur, [], prev, [], last_emitted_hash=_room_content_hash(prev, []),
        )
        assert change == RoomChange.OBJECT_REMOVED

    def test_art_hung(self):
        change, _ = _detect_room_change(
            [], [{"id": "x"}], [], [], last_emitted_hash=_room_content_hash([], []),
        )
        assert change == RoomChange.ART_HUNG

    def test_art_removed(self):
        prev_art = [{"id": "x"}]
        change, _ = _detect_room_change(
            [], [], [], prev_art,
            last_emitted_hash=_room_content_hash([], prev_art),
        )
        assert change == RoomChange.ART_REMOVED

    def test_art_priority_over_object(self):
        """Art changes take priority over object changes."""
        change, _ = _detect_room_change(
            [{"id": "b"}], [{"id": "y"}],
            [{"id": "a"}], [{"id": "x"}],
            last_emitted_hash="old",
        )
        assert change == RoomChange.ART_HUNG

    def test_first_emit_no_previous_hash(self):
        objs = [{"id": "a"}]
        change, _ = _detect_room_change(
            objs, [], [], [], last_emitted_hash=None,
        )
        assert change == RoomChange.OBJECT_ADDED


# ── build_runtime_facts ──────────────────────────────────────


class TestBuildRuntimeFacts:
    def test_basic_build(self):
        facts, room_hash = build_runtime_facts(
            thread_id="test",
            pip_mood="sleeping",
            pip_position_near=True,
            gap_seconds=500.0,
        )
        assert facts.pip_visible == PipVisible.SLEEPING
        assert facts.pip_position_near is True
        assert facts.silence_gap == SilenceGap.LONG
        assert facts.room_change == RoomChange.NONE
        assert isinstance(room_hash, str)

    def test_room_change_detected(self):
        facts, _ = build_runtime_facts(
            thread_id="test",
            room_objects=[{"id": "new"}],
            prev_room_objects=[],
            last_emitted_room_hash=_room_content_hash([], []),
            gap_seconds=0.0,
        )
        assert facts.room_change == RoomChange.OBJECT_ADDED


# ── format_runtime_facts ─────────────────────────────────────


class TestFormatRuntimeFacts:
    def test_minimal(self):
        facts = RuntimeFacts(
            time_of_day=TimeOfDay.NIGHT,
            silence_gap=SilenceGap.NONE,
            pip_visible=PipVisible.SLEEPING,
            pip_position_near=False,
            room_change=RoomChange.NONE,
        )
        text = format_runtime_facts(facts)
        assert "=== 今の場所と時間 ===" in text
        assert "夜。" in text
        assert "Pipは眠っている。" in text
        assert "しばらくぶり" not in text

    def test_with_gap_and_room_change(self):
        facts = RuntimeFacts(
            time_of_day=TimeOfDay.MORNING,
            silence_gap=SilenceGap.VERY_LONG,
            pip_visible=PipVisible.LOOKING,
            pip_position_near=True,
            room_change=RoomChange.ART_HUNG,
        )
        text = format_runtime_facts(facts)
        assert "朝。" in text
        assert "しばらくぶり。" in text
        assert "こちらを見ている" in text
        assert "壁に絵が飾られた" in text

    def test_short_gap_not_shown(self):
        facts = RuntimeFacts(
            time_of_day=TimeOfDay.DAY,
            silence_gap=SilenceGap.SHORT,
            pip_visible=PipVisible.RESTING,
            pip_position_near=False,
            room_change=RoomChange.NONE,
        )
        text = format_runtime_facts(facts)
        assert "間があった" not in text
        assert "しばらくぶり" not in text
