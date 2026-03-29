"""Tests for _detect_repetition_sense() and _repetition_count() in helpers.py."""
from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage, AIMessage

from backend.core.agent_graph.nodes.helpers import (
    _detect_repetition_sense,
    _repetition_count,
)


def _make_state(messages: list) -> dict:
    return {"messages": messages}


# ── _repetition_count ──────────────────────────────────────


class TestRepetitionCount:
    """連続同一AI応答の回数カウント。"""

    def test_no_messages(self):
        assert _repetition_count(_make_state([])) == 0

    def test_single_ai(self):
        state = _make_state([HumanMessage(content="a"), AIMessage(content="x")])
        assert _repetition_count(state) == 0  # 比較対象がないので0

    def test_two_different(self):
        state = _make_state([
            HumanMessage(content="a"), AIMessage(content="x"),
            HumanMessage(content="b"), AIMessage(content="y"),
        ])
        assert _repetition_count(state) == 1  # 直近1回（連続同一は1）

    def test_two_identical(self):
        state = _make_state([
            HumanMessage(content="a"), AIMessage(content="同じ"),
            HumanMessage(content="b"), AIMessage(content="同じ"),
        ])
        assert _repetition_count(state) == 2

    def test_five_identical(self):
        msgs = []
        for i in range(5):
            msgs.extend([HumanMessage(content=f"q{i}"), AIMessage(content="ループ")])
        assert _repetition_count(_make_state(msgs)) == 5

    def test_breaks_at_different(self):
        state = _make_state([
            HumanMessage(content="a"), AIMessage(content="異なる"),
            HumanMessage(content="b"), AIMessage(content="同じ"),
            HumanMessage(content="c"), AIMessage(content="同じ"),
            HumanMessage(content="d"), AIMessage(content="同じ"),
        ])
        assert _repetition_count(state) == 3  # 直近3回が同一、その前は違う

    def test_wait_skipped(self):
        state = _make_state([
            HumanMessage(content="a"), AIMessage(content="同じ"),
            HumanMessage(content="b"), AIMessage(content="WAIT"),
            HumanMessage(content="c"), AIMessage(content="同じ"),
        ])
        assert _repetition_count(state) == 2  # WAITを除くと2回連続

    def test_empty_skipped(self):
        state = _make_state([
            HumanMessage(content="a"), AIMessage(content="同じ"),
            HumanMessage(content="b"), AIMessage(content=""),
            HumanMessage(content="c"), AIMessage(content="同じ"),
        ])
        assert _repetition_count(state) == 2

    def test_boost_calculation(self):
        """depth ノードでの rep_boost = max(count - 2, 0) の検証。"""
        # 2回 → boost 0（まだ介入しない）
        msgs2 = []
        for _ in range(2):
            msgs2.extend([HumanMessage(content="q"), AIMessage(content="r")])
        assert max(_repetition_count(_make_state(msgs2)) - 2, 0) == 0

        # 3回 → boost 1
        msgs3 = []
        for _ in range(3):
            msgs3.extend([HumanMessage(content="q"), AIMessage(content="r")])
        assert max(_repetition_count(_make_state(msgs3)) - 2, 0) == 1

        # 5回 → boost 3
        msgs5 = []
        for _ in range(5):
            msgs5.extend([HumanMessage(content="q"), AIMessage(content="r")])
        assert max(_repetition_count(_make_state(msgs5)) - 2, 0) == 3


# ── _detect_repetition_sense ───────────────────────────────


class TestDetectRepetitionSense:
    """直近AI応答の反復検出 → 体感テキスト注入。"""

    def test_no_messages(self):
        assert _detect_repetition_sense(_make_state([])) == ""

    def test_single_pair(self):
        state = _make_state([
            HumanMessage(content="こんにちは"),
            AIMessage(content="やあ"),
        ])
        assert _detect_repetition_sense(state) == ""

    def test_two_identical_below_threshold(self):
        state = _make_state([
            HumanMessage(content="a"), AIMessage(content="同じ"),
            HumanMessage(content="b"), AIMessage(content="同じ"),
        ])
        assert _detect_repetition_sense(state) == ""

    def test_three_identical_triggers(self):
        state = _make_state([
            HumanMessage(content="a"), AIMessage(content="同じ応答"),
            HumanMessage(content="b"), AIMessage(content="同じ応答"),
            HumanMessage(content="c"), AIMessage(content="同じ応答"),
        ])
        result = _detect_repetition_sense(state)
        assert result != ""
        assert "同じ" in result

    def test_three_different_no_trigger(self):
        state = _make_state([
            HumanMessage(content="a"), AIMessage(content="応答1"),
            HumanMessage(content="b"), AIMessage(content="応答2"),
            HumanMessage(content="c"), AIMessage(content="応答3"),
        ])
        assert _detect_repetition_sense(state) == ""

    def test_wait_messages_skipped(self):
        """WAIT はカウントしない。"""
        state = _make_state([
            HumanMessage(content="a"), AIMessage(content="同じ"),
            HumanMessage(content="b"), AIMessage(content="WAIT"),
            HumanMessage(content="c"), AIMessage(content="同じ"),
            HumanMessage(content="d"), AIMessage(content="同じ"),
        ])
        result = _detect_repetition_sense(state)
        assert result != ""

    def test_empty_ai_skipped(self):
        """空文字列のAI応答はカウントしない。"""
        state = _make_state([
            HumanMessage(content="a"), AIMessage(content="同じ"),
            HumanMessage(content="b"), AIMessage(content=""),
            HumanMessage(content="c"), AIMessage(content="同じ"),
            HumanMessage(content="d"), AIMessage(content="同じ"),
        ])
        result = _detect_repetition_sense(state)
        assert result != ""

    def test_custom_threshold(self):
        """threshold=2 で2回同一でもトリガー。"""
        state = _make_state([
            HumanMessage(content="a"), AIMessage(content="繰り返し"),
            HumanMessage(content="b"), AIMessage(content="繰り返し"),
        ])
        assert _detect_repetition_sense(state, threshold=2) != ""

    def test_whitespace_difference_no_false_positive(self):
        """前後空白の違いは strip で吸収される。"""
        state = _make_state([
            HumanMessage(content="a"), AIMessage(content="  同じ  "),
            HumanMessage(content="b"), AIMessage(content="同じ"),
            HumanMessage(content="c"), AIMessage(content="同じ "),
        ])
        result = _detect_repetition_sense(state)
        assert result != ""

    def test_long_history_only_checks_recent(self):
        """長い履歴でも直近のみチェック。古い反復は無視。"""
        msgs = []
        # 古い反復（3回同じ）
        for _ in range(3):
            msgs.extend([HumanMessage(content="old"), AIMessage(content="古い反復")])
        # 新しい異なる応答（3回別々）
        for i in range(3):
            msgs.extend([HumanMessage(content=f"new{i}"), AIMessage(content=f"新しい{i}")])
        state = _make_state(msgs)
        assert _detect_repetition_sense(state) == ""
