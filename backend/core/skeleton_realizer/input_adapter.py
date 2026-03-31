"""Skeleton Realizer — input adapter for C.0 shadow.

C.0 では NiaCore multi-head はまだ live ではないため、
SkeletonCore + NiaCore vNext + confidence から RealizerInput を推定する。

これは暫定的な adapter。Phase C.2+ では NiaCore が直接 head 値を出す。
"""
from __future__ import annotations

from typing import Any, Optional

from backend.core.skeleton_realizer.schema import (
    AttentionTarget,
    RealizerInput,
    RelationPosture,
    RespondMode,
    Structure,
    ToneBias,
)


def build_realizer_input(
    *,
    selected_depth: int,
    confidence: float,
    conversation_skeleton: Optional[dict[str, Any]],
    niacore_vnext_shadow: Optional[dict[str, Any]],
    turn_role: Optional[str],
    somatic_senses: Optional[list[dict[str, Any]]],
) -> RealizerInput:
    """SkeletonCore + NiaCore vNext + confidence → RealizerInput.

    C.0 shadow adapter: ルールベースで head 値を推定。
    NiaCore が成長したらこの adapter は不要になる。
    """
    skeleton = conversation_skeleton or {}
    vnext = niacore_vnext_shadow or {}

    focus = skeleton.get("focus", "")
    response_intent = skeleton.get("response_intent", "")
    question_intent = skeleton.get("question_intent", "")
    rule_trace = skeleton.get("rule_trace", [])

    # ── respond_mode ──
    respond_mode = _infer_respond_mode(
        response_intent, turn_role, confidence, rule_trace,
    )

    # ── attention_target ──
    attention_target = _infer_attention_target(
        focus, question_intent, vnext.get("recommended_action"),
    )

    # ── tone_bias ──
    tone_bias = _infer_tone_bias(somatic_senses, confidence)

    # ── relation_posture ──
    relation_posture = _infer_relation_posture(turn_role, response_intent)

    # ── structure ──
    structure = _infer_structure(selected_depth, respond_mode, confidence)

    # ── hesitation ──
    hesitation = _infer_hesitation(confidence, response_intent)

    return RealizerInput(
        depth=selected_depth,
        respond_mode=respond_mode,
        tone_bias=tone_bias,
        structure=structure,
        relation_posture=relation_posture,
        hesitation=hesitation,
        attention_target=attention_target,
    )


# ── Private inference functions ──────────────────────────────────────


def _infer_respond_mode(
    response_intent: str,
    turn_role: Optional[str],
    confidence: float,
    rule_trace: list[str] | None = None,
) -> RespondMode:
    """SkeletonCore response_intent → respond_mode.

    I5_anti_repetition 経由の ask は「開いたまま返す」意味であり、
    「質問文を出す」意味ではない。RespondMode.REFLECT に寄せる。
    I2_low_coverage_ask だけが真の ASK。
    """
    trace = rule_trace or []

    if response_intent == "ask":
        # I2_low_coverage_ask → 真の質問意図
        if "I2_low_coverage_ask" in trace:
            return RespondMode.ASK
        # I5_anti_repetition → 繰り返し回避で開いたまま返す = reflect
        if "I5_anti_repetition" in trace:
            return RespondMode.REFLECT
        # その他の ask → デフォルトは ASK
        return RespondMode.ASK

    intent_map: dict[str, RespondMode] = {
        "receive": RespondMode.HOLD,
        "organize": RespondMode.REFLECT,
        "hold": RespondMode.HOLD,
        "offer_fragile_self_observation": RespondMode.REFLECT,
    }
    mode = intent_map.get(response_intent, RespondMode.HOLD)

    # turn_role override
    if turn_role == "answer" or (turn_role == "deepen" and confidence > 0.7):
        mode = RespondMode.ANSWER

    return mode


def _infer_attention_target(
    focus: str,
    question_intent: str,
    recommended_action: Optional[str],
) -> AttentionTarget:
    """SkeletonCore focus + question_intent → attention_target."""
    # vNext recommended_action overrides
    if recommended_action == "soft_close":
        return AttentionTarget.DEFER
    if recommended_action == "retrieve_alt_memory":
        return AttentionTarget.EXPLORE

    # question_intent mapping
    q_map: dict[str, AttentionTarget] = {
        "clarify_goal": AttentionTarget.CLARIFY,
        "clarify_priority": AttentionTarget.CLARIFY,
        "clarify_emotion": AttentionTarget.EXPLORE,
        "fill_missing_fact": AttentionTarget.CLARIFY,
        "resolve_contradiction": AttentionTarget.CLARIFY,
        "hold_open_space": AttentionTarget.DEFER,
    }
    if question_intent in q_map:
        return q_map[question_intent]

    # focus fallback
    focus_map: dict[str, AttentionTarget] = {
        "missing_context": AttentionTarget.CLARIFY,
        "contradiction": AttentionTarget.CLARIFY,
        "user_goal": AttentionTarget.CONFIRM,
        "returning_theme": AttentionTarget.EXPLORE,
        "lingering_state": AttentionTarget.DEFER,
        "emotional_state": AttentionTarget.EXPLORE,
        "priority_decision": AttentionTarget.CONFIRM,
    }
    return focus_map.get(focus, AttentionTarget.CLARIFY)


def _infer_tone_bias(
    somatic_senses: Optional[list[dict[str, Any]]],
    confidence: float,
) -> ToneBias:
    """Somatic senses + confidence → tone_bias."""
    if not somatic_senses:
        return ToneBias.QUIET

    # 高強度の体感があれば warm 寄り
    max_intensity = max((s.get("intensity", 0) for s in somatic_senses), default=0)
    if max_intensity >= 0.8:
        return ToneBias.WARM

    # 高確信度は direct 寄り
    if confidence >= 0.75:
        return ToneBias.DIRECT

    return ToneBias.QUIET


def _infer_relation_posture(
    turn_role: Optional[str],
    response_intent: str,
) -> RelationPosture:
    """turn_role + response_intent → relation_posture."""
    if turn_role == "mirror" or response_intent == "offer_fragile_self_observation":
        return RelationPosture.APPROACH
    if turn_role == "close":
        return RelationPosture.KEEP_DISTANCE
    return RelationPosture.STAY


def _infer_structure(
    depth: int,
    respond_mode: RespondMode,
    confidence: float,
) -> Structure:
    """depth + respond_mode + confidence → structure."""
    if depth == 0:
        return Structure.ONE_LINE
    if respond_mode == RespondMode.ASK:
        return Structure.SUMMARY_THEN_QUESTION
    if confidence < 0.5:
        return Structure.CONTRASTIVE
    return Structure.ONE_LINE


def _infer_hesitation(confidence: float, response_intent: str) -> float:
    """confidence + response_intent → hesitation.

    低確信度 → 高躊躇。hold/receive intent → 躊躇を上げる。
    """
    base = max(0.0, min(1.0, 1.0 - confidence))

    if response_intent in ("hold", "receive"):
        base = min(1.0, base + 0.15)
    elif response_intent == "offer_fragile_self_observation":
        base = min(1.0, base + 0.1)

    return round(base, 2)
