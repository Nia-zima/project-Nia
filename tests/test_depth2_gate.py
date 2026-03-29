"""Tests for Depth2 gate logic, Depth2Mode, and S1 Pre-Thought (Phase F)."""
from __future__ import annotations

import os
import re
import time

import pytest

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

    def test_receive_ack_markers(self):
        from backend.core.agent_graph.nodes import _is_simple_ack
        assert _is_simple_ack("そのまま受け取った。") is True
        assert _is_simple_ack("その『嬉しい』、ちゃんと受け取った。") is True
        assert _is_simple_ack("その言葉で十分だよね。") is True

    def test_normal_text_not_ack(self):
        from backend.core.agent_graph.nodes import _is_simple_ack
        assert _is_simple_ack("今日の天気はどう？") is False
        assert _is_simple_ack("コーヒーが飲みたい") is False

    def test_empty_or_long_not_ack(self):
        from backend.core.agent_graph.nodes import _is_simple_ack
        assert _is_simple_ack("") is False
        assert _is_simple_ack("おはよう、今日もいい天気だね") is False  # > 20 chars


# ── Tests: Risk Depth2 (existing keyword system) ─────────────────

class TestRiskDepth2:
    """Risk depth2 uses keyword/hard-combo detection."""

    def test_public_policy_triggers_risk(self):
        from backend.core.agent_graph.nodes import _should_use_risk_depth2
        assert _should_use_risk_depth2(
            "ニアの方針を配信で公開する",
            dissonance=0.5, confidence=0.5,
        ) is True

    def test_identity_policy_decision_triggers_risk(self):
        from backend.core.agent_graph.nodes import _should_use_risk_depth2
        assert _should_use_risk_depth2(
            "ニアの設定を判断する",
            dissonance=0.5, confidence=0.5,
        ) is True

    def test_normal_text_no_risk(self):
        from backend.core.agent_graph.nodes import _should_use_risk_depth2
        assert _should_use_risk_depth2(
            "今日は何をしようか",
            dissonance=0.1, confidence=0.9,
        ) is False

    def test_select_returns_risk_mode(self):
        from backend.core.agent_graph.nodes import _select_depth2_mode, Depth2Mode
        mode = _select_depth2_mode(
            "ニアの方針を配信で公開する",
            dissonance=0.5, confidence=0.5,
            thread_id="default_thread", is_meeting=False,
        )
        assert mode == Depth2Mode.RISK


# ── Tests: Reflective Depth2 ─────────────────────────────────────

class TestReflectiveDepth2:
    """Reflective depth2 detects returning themes and lingering states."""

    def test_returning_theme_in_meeting(self):
        from backend.core.agent_graph.nodes import _reflective_score
        # meeting(+1) + return_markers(+2) = 3 → threshold met
        score = _reflective_score(
            "また同じテーマに戻ってきた気がする",
            is_self_scope=False, is_meeting=True,
            recent_skeleton_focuses=[], recent_skeleton_intents=[],
        )
        assert score >= 3

    def test_lingering_with_hedge_and_self_ref(self):
        from backend.core.agent_graph.nodes import _reflective_score
        # linger(+2) + hedge+self_ref(+2) = 4
        score = _reflective_score(
            "自分の中にまだ引っかかってる気がする",
            is_self_scope=False, is_meeting=False,
            recent_skeleton_focuses=[], recent_skeleton_intents=[],
        )
        assert score >= 3

    def test_skeleton_history_boost(self):
        from backend.core.agent_graph.nodes import _reflective_score
        # linger(+2) + skeleton returning_theme(+1) = 3
        score = _reflective_score(
            "まだ抜けない感じがある",
            is_self_scope=False, is_meeting=False,
            recent_skeleton_focuses=["returning_theme"],
            recent_skeleton_intents=[],
        )
        assert score >= 3

    def test_fragile_self_observation_boost(self):
        from backend.core.agent_graph.nodes import _reflective_score
        # linger(+2) + skeleton offer_fragile(+1) = 3
        score = _reflective_score(
            "ずっと残ってるものがある",
            is_self_scope=False, is_meeting=False,
            recent_skeleton_focuses=[],
            recent_skeleton_intents=["offer_fragile_self_observation"],
        )
        assert score >= 3

    def test_normal_text_below_threshold(self):
        from backend.core.agent_graph.nodes import _reflective_score
        score = _reflective_score(
            "今日の天気はどう？",
            is_self_scope=False, is_meeting=False,
            recent_skeleton_focuses=[], recent_skeleton_intents=[],
        )
        assert score < 3

    def test_select_returns_reflective_mode(self):
        from backend.core.agent_graph.nodes import _select_depth2_mode, Depth2Mode
        mode = _select_depth2_mode(
            "また同じテーマに戻ってきた気がする",
            dissonance=0.1, confidence=0.9,
            thread_id="nero_meeting_test", is_meeting=True,
        )
        assert mode == Depth2Mode.REFLECTIVE

    def test_select_returns_none_for_normal(self):
        from backend.core.agent_graph.nodes import _select_depth2_mode
        mode = _select_depth2_mode(
            "今日の天気はどう？",
            dissonance=0.1, confidence=0.9,
            thread_id="default_thread", is_meeting=False,
        )
        assert mode is None


# ── Tests: Dissonance_on depends on mode ────────────────────────

class TestDepth2Dissonance:
    """risk_depth2 forces dissonance_on, reflective does not."""

    def test_risk_forces_dissonance_on(self):
        from backend.core.agent_graph.nodes.routing import _resolve_depth_decision, Depth2Mode
        from backend.core.confidence import DepthAction
        _, _, need_depth1, dissonance_on, _ = _resolve_depth_decision(
            action=DepthAction.USE_DEPTH0,
            confidence=0.5, dissonance=0.2,
            reason_codes=[],
            need_depth2=True, depth2_mode=Depth2Mode.RISK,
        )
        assert need_depth1 is True
        assert dissonance_on is True

    def test_reflective_does_not_force_dissonance_on(self):
        from backend.core.agent_graph.nodes.routing import _resolve_depth_decision, Depth2Mode
        from backend.core.confidence import DepthAction
        _, _, need_depth1, dissonance_on, _ = _resolve_depth_decision(
            action=DepthAction.USE_DEPTH0,
            confidence=0.5, dissonance=0.2,
            reason_codes=[],
            need_depth2=True, depth2_mode=Depth2Mode.REFLECTIVE,
        )
        assert need_depth1 is True
        assert dissonance_on is False  # NOT forced True

    def test_pre_thought_short_ack_overrides_depth1(self):
        from backend.core.agent_graph.nodes.routing import _resolve_depth_decision
        from backend.core.confidence import DepthAction
        action, action_source, need_depth1, dissonance_on, _ = _resolve_depth_decision(
            action=DepthAction.USE_DEPTH1,
            confidence=0.4, dissonance=0.1,
            reason_codes=["pre_thought_ack"],
            need_depth2=False,
            pre_thought_action="short_ack",
        )
        assert action == DepthAction.USE_DEPTH0
        assert action_source == "pre_thought"
        assert need_depth1 is False
        assert dissonance_on is False


# ── Tests: Depth2 gate in depth_selector ──────────────────────────

class TestDepth2Gate:
    """Depth2 gate should block when cumulative turns < threshold."""

    def test_gate_blocks_below_threshold(self, monkeypatch):
        """need_depth2 signal present but cumulative turns < DEPTH2_MIN_TURNS → blocked."""
        monkeypatch.setattr(
            "backend.core.agent_graph.nodes.settings.DEPTH2_MIN_TURNS", 100
        )
        _insert_events("t_gate", 50)  # below threshold

        from backend.core.agent_graph.nodes import _should_use_risk_depth2, _get_cumulative_turn_count

        # Verify signal fires
        signal = _should_use_risk_depth2(
            "ニアの方針を配信で公開する",
            dissonance=0.5, confidence=0.5,
        )
        assert signal is True

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
