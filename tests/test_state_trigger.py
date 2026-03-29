"""Tests for State-Driven Reflection Triggers (Phase N.4)."""
from __future__ import annotations

import json
import time
from unittest.mock import patch

import pytest

from backend.core.db import get_conn, init_schema
from backend.services.idle_detector import (
    should_trigger_reflection,
    _check_state_trigger_cooldown,
    _reset_metacog_stats,
    _read_kv,
    _write_kv,
)


@pytest.fixture(autouse=True)
def _setup_db():
    init_schema()
    # Clean telemetry_kv before each test
    conn = get_conn()
    try:
        conn.execute("DELETE FROM telemetry_kv")
    finally:
        conn.close()
    yield


def _set_kv(key: str, value: str) -> None:
    conn = get_conn()
    try:
        _write_kv(conn, key, value)
    finally:
        conn.close()


# ── should_trigger_reflection ──────────────────────────


class TestShouldTriggerReflection:
    def test_no_stats_returns_false(self):
        conn = get_conn()
        try:
            result, reason = should_trigger_reflection(conn)
        finally:
            conn.close()
        assert result is False
        assert reason == ""

    def test_awareness_high_triggers(self):
        _set_kv("awareness_average", "0.3")
        conn = get_conn()
        try:
            result, reason = should_trigger_reflection(conn)
        finally:
            conn.close()
        assert result is True
        assert reason == "awareness_high"

    def test_awareness_low_no_trigger(self):
        _set_kv("awareness_average", "0.1")
        conn = get_conn()
        try:
            result, reason = should_trigger_reflection(conn)
        finally:
            conn.close()
        assert result is False

    def test_confidence_variance_high_triggers(self):
        _set_kv("confidence_variance", "0.1")
        conn = get_conn()
        try:
            result, reason = should_trigger_reflection(conn)
        finally:
            conn.close()
        assert result is True
        assert reason == "confidence_variance_high"

    def test_confidence_variance_low_no_trigger(self):
        _set_kv("confidence_variance", "0.05")
        conn = get_conn()
        try:
            result, reason = should_trigger_reflection(conn)
        finally:
            conn.close()
        assert result is False

    def test_dissonance_streak_triggers(self):
        _set_kv("dissonance_streak", "3")
        conn = get_conn()
        try:
            result, reason = should_trigger_reflection(conn)
        finally:
            conn.close()
        assert result is True
        assert reason == "dissonance_streak"

    def test_dissonance_streak_low_no_trigger(self):
        _set_kv("dissonance_streak", "2")
        conn = get_conn()
        try:
            result, reason = should_trigger_reflection(conn)
        finally:
            conn.close()
        assert result is False

    def test_contradiction_detected_triggers(self):
        _set_kv("contradiction_recent", "1")
        conn = get_conn()
        try:
            result, reason = should_trigger_reflection(conn)
        finally:
            conn.close()
        assert result is True
        assert reason == "contradiction_detected"

    def test_contradiction_zero_no_trigger(self):
        _set_kv("contradiction_recent", "0")
        conn = get_conn()
        try:
            result, reason = should_trigger_reflection(conn)
        finally:
            conn.close()
        assert result is False

    def test_topic_shifts_triggers(self):
        _set_kv("topic_shift_count", "3")
        conn = get_conn()
        try:
            result, reason = should_trigger_reflection(conn)
        finally:
            conn.close()
        assert result is True
        assert reason == "topic_shifts"

    def test_topic_shifts_low_no_trigger(self):
        _set_kv("topic_shift_count", "2")
        conn = get_conn()
        try:
            result, reason = should_trigger_reflection(conn)
        finally:
            conn.close()
        assert result is False

    def test_disabled_returns_false(self):
        _set_kv("awareness_average", "0.9")
        with patch("backend.services.idle_detector.settings") as mock_s:
            mock_s.STATE_TRIGGER_ENABLED = False
            conn = get_conn()
            try:
                result, reason = should_trigger_reflection(conn)
            finally:
                conn.close()
        assert result is False

    def test_priority_order(self):
        """First matching condition wins (awareness checked first)."""
        _set_kv("awareness_average", "0.3")
        _set_kv("dissonance_streak", "5")
        conn = get_conn()
        try:
            result, reason = should_trigger_reflection(conn)
        finally:
            conn.close()
        assert result is True
        assert reason == "awareness_high"


# ── _check_state_trigger_cooldown ──────────────────────


class TestCooldown:
    def test_no_previous_trigger(self):
        conn = get_conn()
        try:
            assert _check_state_trigger_cooldown(conn) is False
        finally:
            conn.close()

    def test_recent_trigger_in_cooldown(self):
        _set_kv("last_state_trigger_at", str(time.time()))
        conn = get_conn()
        try:
            assert _check_state_trigger_cooldown(conn) is True
        finally:
            conn.close()

    def test_old_trigger_not_in_cooldown(self):
        _set_kv("last_state_trigger_at", str(time.time() - 3700))  # >60min ago
        conn = get_conn()
        try:
            assert _check_state_trigger_cooldown(conn) is False
        finally:
            conn.close()

    def test_custom_cooldown_period(self):
        _set_kv("last_state_trigger_at", str(time.time() - 1200))  # 20min ago
        with patch("backend.services.idle_detector.settings") as mock_s:
            mock_s.STATE_TRIGGER_COOLDOWN_MINUTES = 30
            conn = get_conn()
            try:
                assert _check_state_trigger_cooldown(conn) is True
            finally:
                conn.close()


# ── _reset_metacog_stats ──────────────────────────────


class TestResetMetacogStats:
    def test_resets_all_stats(self):
        _set_kv("confidence_history", json.dumps([0.5, 0.6, 0.7]))
        _set_kv("confidence_variance", "0.1")
        _set_kv("dissonance_streak", "5")
        _set_kv("contradiction_recent", "1")
        _set_kv("topic_shift_count", "4")

        conn = get_conn()
        try:
            _reset_metacog_stats(conn)

            assert _read_kv(conn, "confidence_history") == "[]"
            assert _read_kv(conn, "confidence_variance") == "0"
            assert _read_kv(conn, "dissonance_streak") == "0"
            assert _read_kv(conn, "contradiction_recent") == "0"
            assert _read_kv(conn, "topic_shift_count") == "0"
        finally:
            conn.close()


# ── _update_metacog_stats (from actions.py) ────────────


class TestUpdateMetacogStats:
    def test_accumulates_confidence(self):
        from backend.core.agent_graph.nodes.actions import _update_metacog_stats

        now = time.time()
        state = {"confidence": 0.8}
        _update_metacog_stats(state, now)

        conn = get_conn()
        try:
            history = json.loads(_read_kv(conn, "confidence_history"))
            assert len(history) == 1
            assert history[0] == 0.8
        finally:
            conn.close()

    def test_ring_buffer_caps_at_5(self):
        from backend.core.agent_graph.nodes.actions import _update_metacog_stats

        now = time.time()
        for i in range(7):
            _update_metacog_stats({"confidence": 0.1 * (i + 1)}, now)

        conn = get_conn()
        try:
            history = json.loads(_read_kv(conn, "confidence_history"))
            assert len(history) == 5
        finally:
            conn.close()

    def test_variance_computed(self):
        from backend.core.agent_graph.nodes.actions import _update_metacog_stats

        now = time.time()
        # Insert varying confidences
        for c in [0.2, 0.8, 0.2, 0.8, 0.2]:
            _update_metacog_stats({"confidence": c}, now)

        conn = get_conn()
        try:
            var_str = _read_kv(conn, "confidence_variance")
            assert float(var_str) > 0.05  # High variance
        finally:
            conn.close()

    def test_dissonance_streak_increments(self):
        from backend.core.agent_graph.nodes.actions import _update_metacog_stats

        now = time.time()
        _update_metacog_stats({"dissonance_on": True}, now)
        _update_metacog_stats({"dissonance_on": True}, now)

        conn = get_conn()
        try:
            assert _read_kv(conn, "dissonance_streak") == "2"
        finally:
            conn.close()

    def test_dissonance_streak_resets_on_false(self):
        from backend.core.agent_graph.nodes.actions import _update_metacog_stats

        now = time.time()
        _update_metacog_stats({"dissonance_on": True}, now)
        _update_metacog_stats({"dissonance_on": True}, now)
        _update_metacog_stats({"dissonance_on": False}, now)

        conn = get_conn()
        try:
            assert _read_kv(conn, "dissonance_streak") == "0"
        finally:
            conn.close()

    def test_contradiction_flag(self):
        from backend.core.agent_graph.nodes.actions import _update_metacog_stats

        now = time.time()
        _update_metacog_stats(
            {"metacog_result": {"contradiction_detected": True}}, now
        )

        conn = get_conn()
        try:
            assert _read_kv(conn, "contradiction_recent") == "1"
        finally:
            conn.close()

    def test_topic_shift_increments(self):
        from backend.core.agent_graph.nodes.actions import _update_metacog_stats

        now = time.time()
        _update_metacog_stats(
            {"awareness_signal": {"trigger_reasons": ["topic_shift"]}}, now
        )

        conn = get_conn()
        try:
            assert _read_kv(conn, "topic_shift_count") == "1"
        finally:
            conn.close()

    def test_thread_scoped_confidence_keeps_global_aggregate(self):
        from backend.core.agent_graph.nodes.actions import _update_metacog_stats

        now = time.time()
        _update_metacog_stats({"confidence": 0.8}, now, thread_id="thread_a")

        conn = get_conn()
        try:
            global_history = json.loads(_read_kv(conn, "confidence_history"))
            thread_history = json.loads(_read_kv(conn, "confidence_history:thread_a"))
            assert global_history == [0.8]
            assert thread_history == [0.8]
        finally:
            conn.close()
