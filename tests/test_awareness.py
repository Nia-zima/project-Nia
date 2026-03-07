"""Tests for Awareness Core (Phase N.0)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.services.memory.metacognition import (
    AwarenessSignal,
    MetaCogResult,
    SankaiFlags,
    compute_awareness,
    _calc_relational_surprise,
    _calc_growth_signal,
    _calc_authenticity,
    _keyword_overlap,
)


# ── _keyword_overlap ────────────────────────────────────────


class TestKeywordOverlap:
    def test_identical_strings(self):
        assert _keyword_overlap("猫が好き", "猫が好き") == 1.0

    def test_no_overlap(self):
        result = _keyword_overlap("あいう", "かきく")
        assert result == 0.0

    def test_partial_overlap(self):
        # Shares bigrams "猫が", "が好" → partial overlap
        result = _keyword_overlap("猫が好きだよ", "猫が好きなんだ")
        assert 0.0 < result < 1.0

    def test_empty_strings(self):
        assert _keyword_overlap("", "test") == 0.0
        assert _keyword_overlap("test", "") == 0.0

    def test_single_char(self):
        # Single char: bigram set = {char itself}
        assert _keyword_overlap("あ", "あ") == 1.0


# ── _calc_relational_surprise ───────────────────────────────


class TestRelationalSurprise:
    def test_correction_cue(self):
        rs = _calc_relational_surprise("違う、そうじゃなくて", "猫の話だよね", None)
        assert rs >= 0.4

    def test_confusion_cue(self):
        rs = _calc_relational_surprise("え？どういうこと", "猫の話だよね", None)
        assert rs >= 0.3

    def test_memory_contradiction(self):
        metacog = MetaCogResult(
            raw_confidence=0.5, adjusted_confidence=0.5,
            grounding_score=0.5, grounding_hits=2,
            contradiction_detected=True,
            sankai_flags=SankaiFlags(),
        )
        rs = _calc_relational_surprise("なるほど", "猫の話", metacog)
        assert rs >= 0.3

    def test_topic_shift(self):
        # Very different topics → low keyword overlap → topic shift
        rs = _calc_relational_surprise("最近天気いいね", "ゲームのスコアが上がった", None)
        assert rs >= 0.2

    def test_normal_conversation(self):
        # Similar topic (shared bigrams), no cues → low surprise
        rs = _calc_relational_surprise("猫が好きだよね", "猫が好きなんだ", None)
        assert rs < 0.2

    def test_multiple_signals_capped(self):
        metacog = MetaCogResult(
            raw_confidence=0.5, adjusted_confidence=0.5,
            grounding_score=0.5, grounding_hits=2,
            contradiction_detected=True,
            sankai_flags=SankaiFlags(),
        )
        rs = _calc_relational_surprise("違う！え？意味わからん", "テスト", metacog)
        assert rs <= 1.0

    def test_no_nia_previous_skips_topic_shift(self):
        rs = _calc_relational_surprise("こんにちは", "", None)
        # No prior text → no topic shift calculation
        assert rs == 0.0


# ── _calc_growth_signal ─────────────────────────────────────


class TestGrowthSignal:
    def test_low_surprise_returns_zero(self):
        assert _calc_growth_signal(0.05, None) == 0.0

    def test_proportional_to_surprise(self):
        gs1 = _calc_growth_signal(0.3, None)
        gs2 = _calc_growth_signal(0.6, None)
        assert gs2 > gs1

    def test_capped_at_growth_signal_cap(self):
        gs = _calc_growth_signal(1.0, None)
        assert gs <= 0.6  # Default GROWTH_SIGNAL_CAP

    def test_self_model_boost(self):
        gs_base = _calc_growth_signal(0.5, None)
        gs_boosted = _calc_growth_signal(0.5, {"growth_edges": ["感情表現"]})
        assert gs_boosted > gs_base
        assert gs_boosted - gs_base == pytest.approx(0.1, abs=0.01)

    def test_self_model_no_edges_no_boost(self):
        gs_base = _calc_growth_signal(0.5, None)
        gs_no_edges = _calc_growth_signal(0.5, {"growth_edges": []})
        assert gs_no_edges == gs_base


# ── _calc_authenticity ──────────────────────────────────────


class TestAuthenticity:
    def test_grounded_high_confidence(self):
        metacog = MetaCogResult(
            raw_confidence=0.9, adjusted_confidence=0.9,
            grounding_score=0.8, grounding_hits=3,
            contradiction_detected=False,
            sankai_flags=SankaiFlags(),
        )
        au = _calc_authenticity(metacog, False)
        assert au == 1.0

    def test_ungrounded_high_confidence_penalized(self):
        metacog = MetaCogResult(
            raw_confidence=0.9, adjusted_confidence=0.5,
            grounding_score=0.0, grounding_hits=0,
            contradiction_detected=False,
            sankai_flags=SankaiFlags(),
        )
        au = _calc_authenticity(metacog, False)
        assert au == pytest.approx(0.6, abs=0.01)

    def test_no_metacog_returns_base(self):
        au = _calc_authenticity(None, False)
        assert au == 1.0

    def test_dissonance_no_penalty(self):
        # Dissonance is honest — no penalty
        metacog = MetaCogResult(
            raw_confidence=0.5, adjusted_confidence=0.5,
            grounding_score=0.5, grounding_hits=2,
            contradiction_detected=False,
            sankai_flags=SankaiFlags(),
        )
        au = _calc_authenticity(metacog, True)
        assert au == 1.0

    def test_low_confidence_no_penalty(self):
        metacog = MetaCogResult(
            raw_confidence=0.5, adjusted_confidence=0.5,
            grounding_score=0.0, grounding_hits=0,
            contradiction_detected=False,
            sankai_flags=SankaiFlags(),
        )
        au = _calc_authenticity(metacog, False)
        assert au == 1.0  # raw_confidence <= 0.8 → no penalty


# ── compute_awareness (integration) ────────────────────────


class TestComputeAwareness:
    def test_disabled_returns_default(self):
        with patch("backend.services.memory.metacognition.settings") as mock_s:
            mock_s.AWARENESS_CORE_ENABLED = False
            result = compute_awareness(
                user_response="test", nia_previous="test", metacog=None,
            )
        assert result.composite == 0.0
        assert result.trigger_reasons == []

    def test_normal_conversation_low_composite(self):
        with patch("backend.services.memory.metacognition.settings") as mock_s:
            mock_s.AWARENESS_CORE_ENABLED = True
            mock_s.AWARENESS_KEYWORD_OVERLAP_MIN = 0.1
            mock_s.GROWTH_SIGNAL_CAP = 0.6
            mock_s.GROWTH_SIGNAL_BOOST = 0.1
            mock_s.AUTHENTICITY_BASE = 1.0
            mock_s.AUTHENTICITY_PENALTY = 0.4
            result = compute_awareness(
                user_response="猫かわいいよね",
                nia_previous="猫が好きなんだ",
                metacog=None,
            )
        assert result.composite < 0.1

    def test_user_correction_high_surprise(self):
        with patch("backend.services.memory.metacognition.settings") as mock_s:
            mock_s.AWARENESS_CORE_ENABLED = True
            mock_s.AWARENESS_KEYWORD_OVERLAP_MIN = 0.1
            mock_s.GROWTH_SIGNAL_CAP = 0.6
            mock_s.GROWTH_SIGNAL_BOOST = 0.1
            mock_s.AUTHENTICITY_BASE = 1.0
            mock_s.AUTHENTICITY_PENALTY = 0.4
            result = compute_awareness(
                user_response="違う、そうじゃなくて",
                nia_previous="猫が好きなんでしょ",
                metacog=None,
            )
        assert result.relational_surprise >= 0.4
        assert result.composite > 0
        assert "user_correction" in result.trigger_reasons

    def test_all_signals_firing_high_composite(self):
        metacog = MetaCogResult(
            raw_confidence=0.95, adjusted_confidence=0.4,
            grounding_score=0.0, grounding_hits=0,
            contradiction_detected=True,
            sankai_flags=SankaiFlags(fabrication_risk=True),
        )
        with patch("backend.services.memory.metacognition.settings") as mock_s:
            mock_s.AWARENESS_CORE_ENABLED = True
            mock_s.AWARENESS_KEYWORD_OVERLAP_MIN = 0.1
            mock_s.GROWTH_SIGNAL_CAP = 0.6
            mock_s.GROWTH_SIGNAL_BOOST = 0.1
            mock_s.AUTHENTICITY_BASE = 1.0
            mock_s.AUTHENTICITY_PENALTY = 0.4
            result = compute_awareness(
                user_response="違う！え？",
                nia_previous="全然違う話題だよ",
                metacog=metacog,
                dissonance_on=True,
            )
        assert result.relational_surprise >= 0.7
        assert result.composite > 0
        assert "user_correction" in result.trigger_reasons
        assert "memory_contradiction" in result.trigger_reasons
        assert "ungrounded_confidence" in result.trigger_reasons

    def test_composite_is_product(self):
        """R_nia = rs × gs × au."""
        with patch("backend.services.memory.metacognition.settings") as mock_s:
            mock_s.AWARENESS_CORE_ENABLED = True
            mock_s.AWARENESS_KEYWORD_OVERLAP_MIN = 0.1
            mock_s.GROWTH_SIGNAL_CAP = 0.6
            mock_s.GROWTH_SIGNAL_BOOST = 0.1
            mock_s.AUTHENTICITY_BASE = 1.0
            mock_s.AUTHENTICITY_PENALTY = 0.4
            result = compute_awareness(
                user_response="違う！",
                nia_previous="テスト",
                metacog=None,
            )
        expected = result.relational_surprise * result.growth_signal * result.authenticity
        assert result.composite == pytest.approx(expected, abs=0.001)

    def test_dissonance_noted_in_reasons(self):
        with patch("backend.services.memory.metacognition.settings") as mock_s:
            mock_s.AWARENESS_CORE_ENABLED = True
            mock_s.AWARENESS_KEYWORD_OVERLAP_MIN = 0.1
            mock_s.GROWTH_SIGNAL_CAP = 0.6
            mock_s.GROWTH_SIGNAL_BOOST = 0.1
            mock_s.AUTHENTICITY_BASE = 1.0
            mock_s.AUTHENTICITY_PENALTY = 0.4
            result = compute_awareness(
                user_response="違う",
                nia_previous="テスト",
                metacog=None,
                dissonance_on=True,
            )
        assert "dissonance_active" in result.trigger_reasons

    def test_growth_edge_boost_reflected(self):
        with patch("backend.services.memory.metacognition.settings") as mock_s:
            mock_s.AWARENESS_CORE_ENABLED = True
            mock_s.AWARENESS_KEYWORD_OVERLAP_MIN = 0.1
            mock_s.GROWTH_SIGNAL_CAP = 0.6
            mock_s.GROWTH_SIGNAL_BOOST = 0.1
            mock_s.AUTHENTICITY_BASE = 1.0
            mock_s.AUTHENTICITY_PENALTY = 0.4

            result_base = compute_awareness(
                user_response="違う",
                nia_previous="テスト",
                metacog=None,
            )
            result_boosted = compute_awareness(
                user_response="違う",
                nia_previous="テスト",
                metacog=None,
                self_model={"growth_edges": ["感情表現"]},
            )
        assert result_boosted.growth_signal > result_base.growth_signal
