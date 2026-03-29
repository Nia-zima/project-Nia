"""NiaCore vNext Shadow — Phase N0 observation pipeline.

v1 shadow と並走する別 shadow。Phase N0 では CfC 推論なし。
擬似教師ルール + StateVectorV2 の記録のみ。

Design doc: docs/niacore_vnext_design.md §11, docs/niacore_lnn_design.md §5.1.1
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from backend.core.logger import logger
from backend.core.niacore.model import StateVector
from backend.core.niacore.vnext.pseudo_teacher import (
    PseudoTeacherResult,
    evaluate_pseudo_teacher,
)
from backend.core.niacore.vnext.state_vector_v2 import (
    STATE_VECTOR_VERSION,
    StateVectorV2,
    build_state_vector_v2,
)


@dataclass
class ShadowVNextResult:
    """Phase N0 shadow result. No CfC inference — pseudo-teacher labels only."""
    state_vector_v2_blob: bytes
    state_vector_version: int = STATE_VECTOR_VERSION
    attention_target: str | None = None
    recommended_action: str | None = None
    pseudo_teacher_rule_trace: list[str] = field(default_factory=list)
    depth2_mode: str | None = None
    model_profile: str | None = None
    model_provider: str | None = None
    model_name: str | None = None
    feature_availability: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state_vector_version": self.state_vector_version,
            "attention_target": self.attention_target,
            "recommended_action": self.recommended_action,
            "pseudo_teacher_rule_trace": self.pseudo_teacher_rule_trace,
            "depth2_mode": self.depth2_mode,
            "model_profile": self.model_profile,
            "model_provider": self.model_provider,
            "model_name": self.model_name,
            "feature_availability": self.feature_availability,
        }


def shadow_vnext_infer(
    *,
    state_vector_v1: StateVector,
    # Spatial signals
    pip_position_near: bool = False,
    room_change: str = "none",
    pip_state: str = "idle",
    room_zone: str = "unknown",
    ambient_state: float = 0.0,
    recent_action: str = "idle",
    # Relational signals
    user_engagement: float = 0.0,
    # Somatic / skeleton
    somatic_senses: list[dict[str, Any]] | None = None,
    skeleton_focus: str | None = None,
    skeleton_response_intent: str | None = None,
    skeleton_question_intent: str | None = None,
    retrieval_top_similarity: float = 0.0,
    confidence: float = 0.5,
    confidence_history: list[float] | None = None,
    # Memory signals
    active_memory_pressure: float = 0.0,
    unresolved_memory_pressure: float = 0.0,
    contradiction_pressure: float = 0.0,
    # Depth2 / model info
    depth2_mode: str | None = None,
    model_profile: str | None = None,
    model_provider: str | None = None,
    model_name: str | None = None,
    feature_availability: dict[str, bool] | None = None,
) -> ShadowVNextResult | None:
    """Run vNext shadow pipeline: StateVectorV2 + pseudo-teacher.

    No CfC inference in Phase N0. Returns None on any failure.
    """
    try:
        # Emotional salience from somatic senses
        emotional_salience = 0.0
        if somatic_senses:
            intensities = [
                float(s.get("intensity", 0.0))
                for s in somatic_senses
                if isinstance(s, dict)
            ]
            emotional_salience = max(intensities) if intensities else 0.0

        # Social pull from skeleton intent
        social_pull = 0.0
        if skeleton_response_intent in ("explore", "deepen", "question_back"):
            social_pull = 0.7
        elif skeleton_response_intent in ("acknowledge", "hold"):
            social_pull = 0.3

        # Build StateVectorV2
        sv2 = build_state_vector_v2(
            v1=state_vector_v1,
            pip_proximity=1.0 if pip_position_near else 0.0,
            pip_state=pip_state,
            room_zone=room_zone,
            ambient_state=ambient_state,
            recent_action=recent_action,
            user_engagement=user_engagement,
            emotional_salience=emotional_salience,
            social_pull=social_pull,
            active_memory_pressure=active_memory_pressure,
            unresolved_memory_pressure=unresolved_memory_pressure,
            contradiction_pressure=contradiction_pressure,
            retrieval_reinforcement=retrieval_top_similarity,
            skeleton_focus=skeleton_focus,
            skeleton_response_intent=skeleton_response_intent,
            skeleton_question_intent=skeleton_question_intent,
        )

        # Run pseudo-teacher rules
        pt_result: PseudoTeacherResult = evaluate_pseudo_teacher(
            pip_position_near=pip_position_near,
            somatic_senses=somatic_senses,
            room_change=room_change,
            skeleton_focus=skeleton_focus,
            skeleton_response_intent=skeleton_response_intent,
            retrieval_top_similarity=retrieval_top_similarity,
            confidence=confidence,
            confidence_history=confidence_history,
        )

        # Track which v2 signal sources were actually available.
        # This is an availability / wiring mask, not an activity mask.
        if feature_availability is None:
            feat_avail = {
                "pip": pip_position_near or pip_state != "idle",
                "room_zone": room_zone != "unknown",
                "room_change": room_change != "none",
                "somatic": somatic_senses is not None,
                "skeleton": skeleton_focus is not None or skeleton_response_intent is not None,
                "memory_pressure": (
                    active_memory_pressure > 0
                    or unresolved_memory_pressure > 0
                    or contradiction_pressure > 0
                ),
                "retrieval": retrieval_top_similarity > 0,
                "confidence_history": bool(confidence_history),
            }
        else:
            feat_avail = dict(feature_availability)

        result = ShadowVNextResult(
            state_vector_v2_blob=sv2.to_blob(),
            state_vector_version=STATE_VECTOR_VERSION,
            attention_target=pt_result.attention_target,
            recommended_action=pt_result.recommended_action,
            pseudo_teacher_rule_trace=pt_result.fired_rules,
            depth2_mode=depth2_mode,
            model_profile=model_profile,
            model_provider=model_provider,
            model_name=model_name,
            feature_availability=feat_avail,
        )

        logger.debug(
            "[NiaCore vNext] shadow: attn=%s action=%s rules=%s",
            pt_result.attention_target,
            pt_result.recommended_action,
            pt_result.fired_rules,
        )
        return result

    except Exception:
        logger.debug("[NiaCore vNext] shadow inference failed", exc_info=True)
        return None
