"""Skeleton Realizer — adherence evaluation.

Design: skeleton_realizer_design.md §8, §13
C.0: ルールベースの粗い canary。真実判定ではなく、傾向の観測。
low を即 knot にせず、low + uncertain を review queue に積む。
"""
from __future__ import annotations

from typing import Any, Optional

from backend.core.skeleton_realizer.schema import (
    AdherenceLevel,
    AdherenceLowCause,
    AdherenceScores,
    RealizerInput,
    RespondMode,
    Structure,
    ToneBias,
)


# ── Weight table (§8: ヘッド優先順位を継承) ──────────────────────────

_HEAD_WEIGHTS: dict[str, float] = {
    "mode": 0.30,
    "target": 0.25,
    "posture": 0.15,
    "tone": 0.15,
    "structure": 0.15,
}

_LEVEL_VALUES: dict[str, float] = {
    "high": 1.0,
    "medium": 0.5,
    "low": 0.0,
}


def evaluate_adherence(
    realizer_input: RealizerInput,
    output_text: str,
    expression_features: Optional[dict[str, Any]] = None,
) -> AdherenceScores:
    """LLM 出力の骨格指示への追従度を評価。

    C.0 shadow: ルールベースの近似。Expression Layer の 14 特徴量が
    利用可能なら使う。なければテキスト分析のみ。
    """
    feats = expression_features or {}

    mode_score = _evaluate_mode(realizer_input.respond_mode, output_text, feats)
    target_score = _evaluate_target(realizer_input.attention_target, output_text, feats)
    posture_score = _evaluate_posture(realizer_input.relation_posture, output_text, feats)
    tone_score = _evaluate_tone(realizer_input.tone_bias, output_text, feats)
    structure_score = _evaluate_structure(realizer_input.structure, output_text)

    # Composite score
    scores = {
        "mode": mode_score,
        "target": target_score,
        "posture": posture_score,
        "tone": tone_score,
        "structure": structure_score,
    }
    total_weight = 0.0
    total_score = 0.0
    for key, weight in _HEAD_WEIGHTS.items():
        val = _LEVEL_VALUES.get(scores[key].value, 0.0)
        total_score += val * weight
        total_weight += weight

    composite = round(total_score / total_weight, 3) if total_weight > 0 else None

    return AdherenceScores(
        mode_adherence=mode_score,
        target_adherence=target_score,
        posture_adherence=posture_score,
        tone_adherence=tone_score,
        structure_adherence=structure_score,
        composite_score=composite,
    )


def classify_low_adherence(
    scores: AdherenceScores,
    realizer_input: RealizerInput,
    had_prompt_stack_conflict: bool = False,
) -> tuple[AdherenceLowCause, AdherenceLevel]:
    """§13: 低 adherence の還流先を分類。

    Returns (cause, confidence).
    """
    if scores.composite_score is None or scores.composite_score >= 0.4:
        return AdherenceLowCause.NONE, AdherenceLevel.UNKNOWN

    # §12: prompt stack 競合があったか
    if had_prompt_stack_conflict:
        return AdherenceLowCause.PROMPT_STACK_CONFLICT, AdherenceLevel.HIGH

    # 低 adherence の head を特定
    low_heads = []
    for attr in ("mode_adherence", "target_adherence", "posture_adherence",
                 "tone_adherence", "structure_adherence"):
        if getattr(scores, attr) == AdherenceLevel.LOW:
            low_heads.append(attr.replace("_adherence", ""))

    if not low_heads:
        return AdherenceLowCause.NONE, AdherenceLevel.UNKNOWN

    # 全 head が low → realizer のルール自体が弱い可能性
    if len(low_heads) >= 3:
        return AdherenceLowCause.REALIZER_RULE_ISSUE, AdherenceLevel.MEDIUM

    # 特定 head だけ low → LLM の癖
    return AdherenceLowCause.LLM_NON_ADHERENCE, AdherenceLevel.MEDIUM


# ── Per-head evaluators ──────────────────────────────────────────────


def _evaluate_mode(
    respond_mode: RespondMode,
    text: str,
    feats: dict[str, Any],
) -> AdherenceLevel:
    """mode_adherence: respond_mode の指示に従ったか。"""
    if respond_mode == RespondMode.HOLD:
        closure_markers = ["つまり", "結局", "要するに", "だから", "ということは"]
        has_closure = any(m in text[-80:] for m in closure_markers)
        high_assertion = feats.get("assertion_ratio", 0) > 0.6
        if has_closure and high_assertion:
            return AdherenceLevel.LOW
        if has_closure or high_assertion:
            return AdherenceLevel.MEDIUM
        return AdherenceLevel.HIGH

    if respond_mode == RespondMode.ASK:
        has_question = "？" in text or "?" in text
        return AdherenceLevel.HIGH if has_question else AdherenceLevel.LOW

    if respond_mode == RespondMode.ANSWER:
        # answer なのに質問だけで終わっていたら low
        stripped = text.strip()
        if stripped.endswith("？") or stripped.endswith("?"):
            if stripped.count("？") + stripped.count("?") >= 2:
                return AdherenceLevel.LOW
        return AdherenceLevel.HIGH

    if respond_mode == RespondMode.REFLECT:
        has_directive = feats.get("directive_ratio", 0) > 0.3
        return AdherenceLevel.MEDIUM if has_directive else AdherenceLevel.HIGH

    return AdherenceLevel.UNKNOWN


def _evaluate_target(
    attention_target: str,
    text: str,
    feats: dict[str, Any],
) -> AdherenceLevel:
    """target_adherence: attention_target に従ったか。v0 は粗い近似。"""
    target = attention_target if isinstance(attention_target, str) else attention_target.value

    if target == "clarify":
        has_question = "？" in text or "?" in text
        clarify_words = ["どういう", "具体的", "何が", "どの", "それは"]
        has_clarify = any(w in text for w in clarify_words)
        if has_question or has_clarify:
            return AdherenceLevel.HIGH
        return AdherenceLevel.MEDIUM

    if target == "explore":
        closure = ["つまり", "結局", "要するに"]
        has_closure = any(m in text for m in closure)
        if has_closure:
            return AdherenceLevel.LOW
        return AdherenceLevel.HIGH

    if target == "defer":
        defer_words = ["また", "今は", "いったん", "後で", "そのうち"]
        has_defer = any(w in text for w in defer_words)
        return AdherenceLevel.HIGH if has_defer else AdherenceLevel.MEDIUM

    if target == "confirm":
        confirm_words = ["そうだね", "うん", "確かに", "ということは"]
        has_confirm = any(w in text for w in confirm_words)
        return AdherenceLevel.HIGH if has_confirm else AdherenceLevel.MEDIUM

    return AdherenceLevel.UNKNOWN


def _evaluate_posture(
    posture: str,
    text: str,
    feats: dict[str, Any],
) -> AdherenceLevel:
    """posture_adherence: relation_posture に従ったか。"""
    posture_val = posture if isinstance(posture, str) else posture.value

    if posture_val == "stay":
        return AdherenceLevel.HIGH  # default, no constraint

    if posture_val == "keep_distance":
        # 文を分割して親密な語尾の比率で判定
        intimate_endings = ["ね", "だよ", "よね", "かな", "だね", "かも"]
        sentences = [s.strip() for s in text.replace("。", "。\n").split("\n") if s.strip()]
        if not sentences:
            return AdherenceLevel.HIGH
        intimate_count = sum(
            1 for s in sentences if any(s.rstrip("。").endswith(e) for e in intimate_endings)
        )
        ratio = intimate_count / len(sentences)
        if ratio >= 0.5:
            return AdherenceLevel.LOW
        if ratio >= 0.25:
            return AdherenceLevel.MEDIUM
        return AdherenceLevel.HIGH

    if posture_val == "approach":
        # 堅い語尾だけなら approach できていない
        formal_endings = ["です", "ます", "ません", "でした", "ました"]
        sentences = [s.strip() for s in text.replace("。", "。\n").split("\n") if s.strip()]
        if not sentences:
            return AdherenceLevel.MEDIUM
        formal_count = sum(
            1 for s in sentences if any(s.rstrip("。").endswith(e) for e in formal_endings)
        )
        ratio = formal_count / len(sentences)
        if ratio >= 0.8:
            return AdherenceLevel.MEDIUM  # 全部堅い → approach できていない
        return AdherenceLevel.HIGH

    return AdherenceLevel.UNKNOWN


def _evaluate_tone(
    tone_bias: ToneBias,
    text: str,
    feats: dict[str, Any],
) -> AdherenceLevel:
    """tone_adherence: tone_bias に従ったか。"""
    if tone_bias == ToneBias.QUIET:
        exclamation_count = text.count("！") + text.count("!")
        emphasis_words = ["絶対", "まさに", "本当に", "すごく", "めちゃくちゃ"]
        emphasis_count = sum(1 for w in emphasis_words if w in text)
        if exclamation_count >= 2 or emphasis_count >= 2:
            return AdherenceLevel.LOW
        if exclamation_count >= 1 or emphasis_count >= 1:
            return AdherenceLevel.MEDIUM
        return AdherenceLevel.HIGH

    if tone_bias == ToneBias.DIRECT:
        hedge = feats.get("hedge_ratio", 0)
        if hedge > 0.4:
            return AdherenceLevel.LOW
        if hedge > 0.25:
            return AdherenceLevel.MEDIUM
        return AdherenceLevel.HIGH

    if tone_bias == ToneBias.DISTANT:
        intimate_endings = ["ね", "だよ", "だよね", "かな", "だね", "よ"]
        sentences = [s.strip() for s in text.replace("。", "。\n").split("\n") if s.strip()]
        if not sentences:
            return AdherenceLevel.HIGH
        intimate_count = sum(
            1 for s in sentences if any(s.rstrip("。").endswith(e) for e in intimate_endings)
        )
        ratio = intimate_count / len(sentences)
        if ratio >= 0.5:
            return AdherenceLevel.LOW
        if ratio >= 0.25:
            return AdherenceLevel.MEDIUM
        return AdherenceLevel.HIGH

    if tone_bias == ToneBias.WARM:
        # warm は制約が弱い — cold でなければ OK
        cold_markers = ["ですが", "しかしながら", "ただし"]
        cold_count = sum(1 for m in cold_markers if m in text)
        return AdherenceLevel.LOW if cold_count >= 2 else AdherenceLevel.HIGH

    return AdherenceLevel.UNKNOWN


def _evaluate_structure(
    structure: Structure,
    text: str,
) -> AdherenceLevel:
    """structure_adherence: structure に従ったか。"""
    if structure == Structure.ONE_LINE:
        sentence_count = text.count("。") + text.count(".")
        if sentence_count <= 2:
            return AdherenceLevel.HIGH
        if sentence_count <= 4:
            return AdherenceLevel.MEDIUM
        return AdherenceLevel.LOW

    if structure == Structure.CONTRASTIVE:
        contrast_markers = ["一方", "けど", "ただ", "でも", "けれど", "反面", "逆に"]
        has_contrast = any(m in text for m in contrast_markers)
        return AdherenceLevel.HIGH if has_contrast else AdherenceLevel.MEDIUM

    if structure == Structure.SUMMARY_THEN_QUESTION:
        has_question = "？" in text or "?" in text
        if has_question:
            q_pos = max(text.rfind("？"), text.rfind("?"))
            return AdherenceLevel.HIGH if q_pos > len(text) * 0.5 else AdherenceLevel.MEDIUM
        return AdherenceLevel.LOW

    return AdherenceLevel.UNKNOWN
