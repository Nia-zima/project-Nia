"""Tests for NiaCore vNext pseudo-teacher rules (A1-A3, C1-C3)."""
import pytest

from backend.core.niacore.vnext.pseudo_teacher import (
    PseudoTeacherResult,
    evaluate_pseudo_teacher,
    _has_warmth_somatic,
    _confidence_declining,
)


class TestWarmthDetection:
    def test_warmth_keyword_hit(self):
        senses = [{"text": "近くに温かい気配がある", "intensity": 0.6}]
        assert _has_warmth_somatic(senses) is True

    def test_warmth_keyword_variants(self):
        for kw in ["やわらかい", "ぬくもり", "そばに", "warm"]:
            senses = [{"text": f"何か{kw}ものを感じる", "intensity": 0.5}]
            assert _has_warmth_somatic(senses) is True, f"Failed for: {kw}"

    def test_no_warmth(self):
        senses = [{"text": "静かな時間の中にいる", "intensity": 0.3}]
        assert _has_warmth_somatic(senses) is False

    def test_empty_somatic(self):
        assert _has_warmth_somatic(None) is False
        assert _has_warmth_somatic([]) is False

    def test_non_dict_somatic_ignored(self):
        assert _has_warmth_somatic(["invalid"]) is False


class TestConfidenceDeclining:
    def test_declining(self):
        assert _confidence_declining([0.8, 0.6, 0.4]) is True

    def test_not_declining(self):
        assert _confidence_declining([0.4, 0.6, 0.8]) is False

    def test_flat(self):
        assert _confidence_declining([0.5, 0.5, 0.5]) is False

    def test_too_few(self):
        assert _confidence_declining([0.8, 0.6]) is False
        assert _confidence_declining(None) is False

    def test_uses_last_three(self):
        assert _confidence_declining([0.1, 0.2, 0.9, 0.7, 0.5]) is True


class TestAttentionRules:
    def test_a1_pip_near_with_warmth(self):
        result = evaluate_pseudo_teacher(
            pip_position_near=True,
            somatic_senses=[{"text": "近くに温かい気配", "intensity": 0.5}],
        )
        assert result.attention_target == "pip"
        assert "A1" in result.fired_rules

    def test_a1_pip_near_without_warmth(self):
        result = evaluate_pseudo_teacher(
            pip_position_near=True,
            somatic_senses=[{"text": "静かな感じ", "intensity": 0.3}],
        )
        assert result.attention_target is None
        assert "A1" not in result.fired_rules

    def test_a1_pip_not_near(self):
        result = evaluate_pseudo_teacher(
            pip_position_near=False,
            somatic_senses=[{"text": "温かい気配", "intensity": 0.5}],
        )
        assert result.attention_target is None

    def test_a2_room_change(self):
        result = evaluate_pseudo_teacher(room_change="furniture_added")
        assert result.attention_target == "environment"
        assert "A2" in result.fired_rules

    def test_a2_no_room_change(self):
        result = evaluate_pseudo_teacher(room_change="none")
        assert result.attention_target is None

    def test_a3_returning_theme_with_retrieval(self):
        result = evaluate_pseudo_teacher(
            skeleton_focus="returning_theme",
            retrieval_top_similarity=0.7,
        )
        assert result.attention_target == "memory_trace"
        assert "A3" in result.fired_rules

    def test_a3_returning_theme_low_retrieval(self):
        result = evaluate_pseudo_teacher(
            skeleton_focus="returning_theme",
            retrieval_top_similarity=0.3,
        )
        assert result.attention_target is None

    def test_a_rules_priority_first_match(self):
        """A1 wins over A2 when both conditions are met."""
        result = evaluate_pseudo_teacher(
            pip_position_near=True,
            somatic_senses=[{"text": "温かい気配", "intensity": 0.5}],
            room_change="furniture_added",
        )
        assert result.attention_target == "pip"
        assert result.fired_rules == ["A1"]


class TestActionRules:
    def test_c1_lingering_confidence_down(self):
        result = evaluate_pseudo_teacher(
            skeleton_focus="lingering_state",
            confidence_history=[0.8, 0.6, 0.4],
        )
        assert result.recommended_action == "soft_close"
        assert "C1" in result.fired_rules

    def test_c1_no_confidence_down(self):
        result = evaluate_pseudo_teacher(
            skeleton_focus="lingering_state",
            confidence_history=[0.4, 0.6, 0.8],
        )
        # C1 doesn't fire, but C2 might fire if retrieval is low
        assert "C1" not in result.fired_rules

    def test_c2_lingering_no_progress(self):
        result = evaluate_pseudo_teacher(
            skeleton_focus="lingering_state",
            retrieval_top_similarity=0.1,
        )
        assert result.recommended_action == "retrieve_alt_memory"
        assert "C2" in result.fired_rules

    def test_c2_lingering_with_progress(self):
        result = evaluate_pseudo_teacher(
            skeleton_focus="lingering_state",
            retrieval_top_similarity=0.6,
        )
        # C2 doesn't fire
        assert result.recommended_action is None

    def test_c3_fragile_self_observation(self):
        result = evaluate_pseudo_teacher(
            skeleton_response_intent="offer_fragile_self_observation",
        )
        assert result.recommended_action == "hold_support"
        assert "C3" in result.fired_rules

    def test_c1_beats_c2(self):
        """C1 wins over C2 when both could fire."""
        result = evaluate_pseudo_teacher(
            skeleton_focus="lingering_state",
            confidence_history=[0.8, 0.6, 0.4],
            retrieval_top_similarity=0.1,
        )
        assert result.recommended_action == "soft_close"
        assert "C1" in result.fired_rules
        assert "C2" not in result.fired_rules


class TestCombined:
    def test_a_and_c_independent(self):
        """Attention and action rules fire independently."""
        result = evaluate_pseudo_teacher(
            pip_position_near=True,
            somatic_senses=[{"text": "温かい気配", "intensity": 0.5}],
            skeleton_response_intent="offer_fragile_self_observation",
        )
        assert result.attention_target == "pip"
        assert result.recommended_action == "hold_support"
        assert "A1" in result.fired_rules
        assert "C3" in result.fired_rules

    def test_no_rules_fire(self):
        result = evaluate_pseudo_teacher()
        assert result.attention_target is None
        assert result.recommended_action is None
        assert result.fired_rules == []

    def test_null_inputs_safe(self):
        result = evaluate_pseudo_teacher(
            pip_position_near=False,
            somatic_senses=None,
            room_change="none",
            skeleton_focus=None,
            skeleton_response_intent=None,
            retrieval_top_similarity=0.0,
            confidence=0.5,
            confidence_history=None,
        )
        assert isinstance(result, PseudoTeacherResult)
        assert result.fired_rules == []

    def test_rule_trace_format(self):
        result = evaluate_pseudo_teacher(room_change="time_change")
        assert isinstance(result.fired_rules, list)
        assert all(isinstance(r, str) for r in result.fired_rules)
