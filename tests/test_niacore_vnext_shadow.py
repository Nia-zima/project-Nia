"""Tests for NiaCore vNext shadow pipeline (Phase N0)."""
import pytest

from backend.core.niacore.model import StateVector
from backend.core.niacore.vnext.shadow_vnext import (
    ShadowVNextResult,
    shadow_vnext_infer,
)
from backend.core.niacore.vnext.state_vector_v2 import STATE_VECTOR_VERSION


class TestShadowVNextInfer:
    def _make_v1(self) -> StateVector:
        return StateVector()

    def test_basic_result(self):
        result = shadow_vnext_infer(state_vector_v1=self._make_v1())
        assert result is not None
        assert isinstance(result, ShadowVNextResult)
        assert result.state_vector_version == STATE_VECTOR_VERSION

    def test_state_vector_v2_blob(self):
        result = shadow_vnext_infer(state_vector_v1=self._make_v1())
        assert result is not None
        assert len(result.state_vector_v2_blob) == 200  # 50 * 4

    def test_with_pseudo_teacher_labels(self):
        result = shadow_vnext_infer(
            state_vector_v1=self._make_v1(),
            pip_position_near=True,
            somatic_senses=[{"text": "温かい気配がそばにある", "intensity": 0.6}],
        )
        assert result is not None
        assert result.attention_target == "pip"
        assert "A1" in result.pseudo_teacher_rule_trace

    def test_no_labels_when_no_rules_fire(self):
        result = shadow_vnext_infer(state_vector_v1=self._make_v1())
        assert result is not None
        assert result.attention_target is None
        assert result.recommended_action is None
        assert result.pseudo_teacher_rule_trace == []

    def test_depth2_mode_recorded(self):
        result = shadow_vnext_infer(
            state_vector_v1=self._make_v1(),
            depth2_mode="reflective",
        )
        assert result is not None
        assert result.depth2_mode == "reflective"

    def test_model_info(self):
        result = shadow_vnext_infer(
            state_vector_v1=self._make_v1(),
            model_profile="depth2_reflective",
            model_provider="anthropic",
            model_name="claude-sonnet-4-6",
        )
        assert result is not None
        assert result.model_profile == "depth2_reflective"
        assert result.model_provider == "anthropic"
        assert result.model_name == "claude-sonnet-4-6"

    def test_to_dict(self):
        result = shadow_vnext_infer(
            state_vector_v1=self._make_v1(),
            room_change="furniture_added",
        )
        assert result is not None
        d = result.to_dict()
        assert d["state_vector_version"] == 2
        assert d["attention_target"] == "environment"
        assert "A2" in d["pseudo_teacher_rule_trace"]
        # _state_vector_v2_blob should NOT be in to_dict (added separately)
        assert "_state_vector_v2_blob" not in d

    def test_emotional_salience_from_somatic(self):
        result = shadow_vnext_infer(
            state_vector_v1=self._make_v1(),
            somatic_senses=[
                {"text": "何か引っかかる", "intensity": 0.8},
                {"text": "静けさを感じる", "intensity": 0.3},
            ],
        )
        assert result is not None
        # emotional_salience should be 0.8 (max)

    def test_social_pull_from_skeleton(self):
        result = shadow_vnext_infer(
            state_vector_v1=self._make_v1(),
            skeleton_response_intent="explore",
        )
        assert result is not None
        # social_pull should be 0.7 for "explore"

    def test_action_rules_via_shadow(self):
        result = shadow_vnext_infer(
            state_vector_v1=self._make_v1(),
            skeleton_focus="lingering_state",
            retrieval_top_similarity=0.1,
        )
        assert result is not None
        assert result.recommended_action == "retrieve_alt_memory"
        assert "C2" in result.pseudo_teacher_rule_trace

    def test_feature_availability_uses_explicit_mask(self):
        result = shadow_vnext_infer(
            state_vector_v1=self._make_v1(),
            pip_position_near=False,
            retrieval_top_similarity=0.0,
            feature_availability={
                "pip": True,
                "room_zone": False,
                "room_change": True,
                "somatic": True,
                "skeleton": False,
                "memory_pressure": False,
                "retrieval": True,
                "confidence_history": False,
            },
        )
        assert result is not None
        assert result.feature_availability["pip"] is True
        assert result.feature_availability["retrieval"] is True
        assert result.feature_availability["room_change"] is True
