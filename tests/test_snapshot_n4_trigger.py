"""Snapshot-driven tests for N.4 State-Driven Reflection Trigger.

Uses SnapshotBuilder to construct specific telemetry_kv states,
then asserts should_trigger_reflection() behavior.
"""
from __future__ import annotations

import json
import pytest

from backend.core.db import init_schema
from harness.snapshot_builder import SnapshotBuilder, clean_all_tables
from harness.assertions import (
    assert_n4_would_trigger,
    assert_telemetry,
    assert_telemetry_range,
    read_telemetry,
)


@pytest.fixture(autouse=True)
def _clean():
    init_schema()
    clean_all_tables()
    yield


# ═══════════════════════════════════════════════════════════════
# Preset: high_awareness
# ═══════════════════════════════════════════════════════════════


class TestHighAwareness:
    def test_triggers_on_high_awareness(self):
        SnapshotBuilder.high_awareness().build()
        assert_n4_would_trigger(True, "awareness_high")

    def test_awareness_value_is_correct(self):
        SnapshotBuilder.high_awareness().build()
        assert_telemetry_range("awareness_average", 0.3, 0.4)


# ═══════════════════════════════════════════════════════════════
# Individual telemetry triggers
# ═══════════════════════════════════════════════════════════════


class TestIndividualTriggers:
    def test_dissonance_streak_triggers(self):
        SnapshotBuilder().with_telemetry("dissonance_streak", "3").build()
        assert_n4_would_trigger(True, "dissonance_streak")

    def test_dissonance_streak_below_threshold(self):
        SnapshotBuilder().with_telemetry("dissonance_streak", "2").build()
        assert_n4_would_trigger(False)

    def test_contradiction_recent_triggers(self):
        SnapshotBuilder().with_telemetry("contradiction_recent", "1").build()
        assert_n4_would_trigger(True, "contradiction_detected")

    def test_contradiction_zero_no_trigger(self):
        SnapshotBuilder().with_telemetry("contradiction_recent", "0").build()
        assert_n4_would_trigger(False)

    def test_topic_shifts_triggers(self):
        SnapshotBuilder().with_telemetry("topic_shift_count", "3").build()
        assert_n4_would_trigger(True, "topic_shifts")

    def test_topic_shifts_below_threshold(self):
        SnapshotBuilder().with_telemetry("topic_shift_count", "2").build()
        assert_n4_would_trigger(False)

    def test_confidence_variance_triggers(self):
        SnapshotBuilder().with_telemetry("confidence_variance", "0.09").build()
        assert_n4_would_trigger(True, "confidence_variance_high")

    def test_confidence_variance_below(self):
        SnapshotBuilder().with_telemetry("confidence_variance", "0.07").build()
        assert_n4_would_trigger(False)


# ═══════════════════════════════════════════════════════════════
# Presets: slump and fresh_start
# ═══════════════════════════════════════════════════════════════


class TestSlumpTrigger:
    def test_slump_triggers(self):
        """Slump preset has confidence_variance=0.12 + dissonance_streak=5 → triggers.

        confidence_variance is checked before dissonance_streak in the check order.
        """
        SnapshotBuilder.slump().build()
        assert_n4_would_trigger(True, "confidence_variance_high")


class TestFreshStart:
    def test_no_trigger_on_empty_db(self):
        SnapshotBuilder.fresh_start().build()
        assert_n4_would_trigger(False)

    def test_empty_telemetry(self):
        SnapshotBuilder.fresh_start().build()
        assert read_telemetry("awareness_average") is None


# ═══════════════════════════════════════════════════════════════
# Priority order (first matching condition wins)
# ═══════════════════════════════════════════════════════════════


class TestPriorityOrder:
    def test_awareness_checked_first(self):
        """awareness_average is checked before confidence_variance."""
        (SnapshotBuilder()
            .with_telemetry("awareness_average", "0.3")
            .with_telemetry("confidence_variance", "0.1")
            .build())
        assert_n4_would_trigger(True, "awareness_high")

    def test_multiple_conditions_first_wins(self):
        """All conditions met → first in check order wins."""
        (SnapshotBuilder()
            .with_telemetry("awareness_average", "0.3")
            .with_telemetry("confidence_variance", "0.1")
            .with_telemetry("dissonance_streak", "5")
            .with_telemetry("contradiction_recent", "1")
            .with_telemetry("topic_shift_count", "5")
            .build())
        # should_trigger_reflection checks awareness first
        assert_n4_would_trigger(True, "awareness_high")
