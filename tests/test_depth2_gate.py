"""Tests for Depth2 gate logic and S1 Pre-Thought (Phase F)."""
from __future__ import annotations

import os
import re
import time

import pytest

os.environ.setdefault("RETENTION_PROFILE", "fast")

from backend.core.db import get_conn, init_schema


@pytest.fixture(autouse=True)
def _setup_db():
    """Ensure schema exists and clean memory_events."""
    init_schema()
    conn = get_conn()
    try:
        conn.execute("DELETE FROM memory_index")
        conn.execute("DELETE FROM memory_events")
        conn.commit()
    finally:
        conn.close()
    yield


# ── Helpers ───────────────────────────────────────────────────────

def _insert_events(thread_id: str, count: int):
    """Insert `count` dummy memory_events for a thread."""
    import uuid
    conn = get_conn()
    try:
        for _ in range(count):
            conn.execute(
                """INSERT INTO memory_events
                   (event_id, thread_id, event_type, payload_json, created_at, schema_version)
                   VALUES (?, ?, 'test', '{}', ?, 1)""",
                (uuid.uuid4().hex, thread_id, time.time()),
            )
        conn.commit()
    finally:
        conn.close()


# ── Tests: _get_cumulative_turn_count ─────────────────────────────

class TestGetCumulativeTurnCount:

    def test_zero_for_empty_thread(self):
        from backend.core.agent_graph.nodes import _get_cumulative_turn_count
        assert _get_cumulative_turn_count("nonexistent") == 0

    def test_counts_events(self):
        from backend.core.agent_graph.nodes import _get_cumulative_turn_count
        _insert_events("t_count", 42)
        assert _get_cumulative_turn_count("t_count") == 42

    def test_counts_only_target_thread(self):
        from backend.core.agent_graph.nodes import _get_cumulative_turn_count
        _insert_events("t_a", 10)
        _insert_events("t_b", 20)
        assert _get_cumulative_turn_count("t_a") == 10
        assert _get_cumulative_turn_count("t_b") == 20


# ── Tests: _is_simple_ack ────────────────────────────────────────

class TestIsSimpleAck:

    def test_greeting(self):
        from backend.core.agent_graph.nodes import _is_simple_ack
        assert _is_simple_ack("おはよう") is True
        assert _is_simple_ack("こんにちは") is True
        assert _is_simple_ack("こんばんは！") is True

    def test_short_acks(self):
        from backend.core.agent_graph.nodes import _is_simple_ack
        assert _is_simple_ack("うん") is True
        assert _is_simple_ack("なるほど") is True
        assert _is_simple_ack("了解") is True

    def test_normal_text_not_ack(self):
        from backend.core.agent_graph.nodes import _is_simple_ack
        assert _is_simple_ack("今日の天気はどう？") is False
        assert _is_simple_ack("コーヒーが飲みたい") is False

    def test_empty_or_long_not_ack(self):
        from backend.core.agent_graph.nodes import _is_simple_ack
        assert _is_simple_ack("") is False
        assert _is_simple_ack("おはよう、今日もいい天気だね") is False  # > 20 chars


# ── Tests: Depth2 gate in depth_selector ──────────────────────────

class TestDepth2Gate:
    """Depth2 gate should block when cumulative turns < threshold."""

    def test_gate_blocks_below_threshold(self, monkeypatch):
        """need_depth2 signal present but cumulative turns < DEPTH2_MIN_TURNS → blocked."""
        monkeypatch.setattr(
            "backend.core.agent_graph.nodes.settings.DEPTH2_MIN_TURNS", 100
        )
        _insert_events("t_gate", 50)  # below threshold

        from backend.core.agent_graph.nodes import _should_use_depth2, _get_cumulative_turn_count

        # Verify _should_use_depth2 would trigger
        signal = _should_use_depth2(
            "ニアの方針を配信で公開する",
            dissonance=0.5, confidence=0.5,
        )
        assert signal is True  # signal fires

        # But cumulative count is below gate
        count = _get_cumulative_turn_count("t_gate")
        assert count < 100

    def test_gate_passes_above_threshold(self, monkeypatch):
        """cumulative turns >= DEPTH2_MIN_TURNS → gate passes."""
        monkeypatch.setattr(
            "backend.core.agent_graph.nodes.settings.DEPTH2_MIN_TURNS", 100
        )
        _insert_events("t_gate_pass", 150)

        from backend.core.agent_graph.nodes import _get_cumulative_turn_count
        count = _get_cumulative_turn_count("t_gate_pass")
        assert count >= 100

    def test_custom_min_turns_setting(self, monkeypatch):
        """DEPTH2_MIN_TURNS env override works."""
        monkeypatch.setattr(
            "backend.core.agent_graph.nodes.settings.DEPTH2_MIN_TURNS", 10
        )
        _insert_events("t_custom", 15)

        from backend.core.agent_graph.nodes import _get_cumulative_turn_count
        count = _get_cumulative_turn_count("t_custom")
        assert count >= 10


# ── Tests: S1 Pre-Thought in dissonance_check ────────────────────

class TestPreThought:
    """S1 Pre-Thought should set pre_thought_action in state."""

    @pytest.mark.asyncio
    async def test_simple_ack_sets_short_ack(self):
        from backend.core.agent_graph.nodes import dissonance_check

        state = {
            "messages": [],
            "user_text": "うん",
            "has_user_text": True,
        }
        result = await dissonance_check(state)
        assert result["pre_thought_action"] == "short_ack"
        assert "pre_thought_ack" in result["reason_codes"]

    @pytest.mark.asyncio
    async def test_normal_text_no_pre_thought(self):
        from backend.core.agent_graph.nodes import dissonance_check

        state = {
            "messages": [],
            "user_text": "今日は何をしようか",
            "has_user_text": True,
        }
        result = await dissonance_check(state)
        assert result["pre_thought_action"] is None

    @pytest.mark.asyncio
    async def test_greeting_sets_short_ack(self):
        from backend.core.agent_graph.nodes import dissonance_check

        state = {
            "messages": [],
            "user_text": "おはよう",
            "has_user_text": True,
        }
        result = await dissonance_check(state)
        assert result["pre_thought_action"] == "short_ack"
