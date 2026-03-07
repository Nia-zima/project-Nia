"""SkeletonCore ルールベース判定.

全ルールベース・LLM なし。優先順で評価し、最初にマッチしたルールで確定。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .schema import (
    ConversationSkeleton,
    Focus,
    QuestionIntent,
    ResponseIntent,
)

# ---------------------------------------------------------------------------
# SkeletonInput — rules が参照する入力データ
# ---------------------------------------------------------------------------


@dataclass
class SkeletonInput:
    """骨格判定に使う全入力。LLM 出力の特徴量は含めない。"""

    # Confidence 5 metrics
    context_coverage: float = 0.5
    self_consistency: float = 0.5
    logit_based: float = 0.5
    question_clarity: float = 0.5
    steering_risk: float = 0.0

    # Memory retrieval
    memory_hit_rate: float = 0.0

    # Surprise
    surprise_score: float = 0.0

    # Skeleton history (last 1-3 turns, oldest first)
    prev_skeletons: list[ConversationSkeleton] = field(default_factory=list)

    # Depth selector result
    selected_depth: int = 0
    depth_action: str = "depth0"  # "depth0" | "depth1" | "ask" | "wait"

    # Correction / review flags
    correction_strong: bool = False
    review_rejected: bool = False

    # User input syntax features
    question_mark_count: int = 0
    has_contrast_words: bool = False
    has_negation: bool = False
    has_emotion_words: bool = False
    has_info_insufficiency: bool = False


# ---------------------------------------------------------------------------
# 日本語構文特徴抽出
# ---------------------------------------------------------------------------

_CONTRAST_RE = re.compile(
    r"(でも|しかし|一方で|けど|ただ|とはいえ|逆に|反面|だけど|けれど)"
)
_NEGATION_RE = re.compile(
    r"(ない|できない|わからない|知らない|ありません|いません|なかった|しない)"
)
_EMOTION_RE = re.compile(
    r"(嬉しい|悲しい|怖い|楽しい|辛い|寂しい|不安|心配|イライラ|ムカ|困っ|焦っ|驚い|つらい|苦しい)"
)
_INFO_INSUF_RE = re.compile(
    r"(わからない|知りたい|教えて|何が|どう|どういう|不明|未知|よくわからない)"
)


def extract_syntax_features(text: str) -> dict[str, int | bool]:
    """ユーザー入力から構文特徴を抽出。"""
    t = (text or "").strip()
    return {
        "question_mark_count": t.count("?") + t.count("？"),
        "has_contrast_words": bool(_CONTRAST_RE.search(t)),
        "has_negation": bool(_NEGATION_RE.search(t)),
        "has_emotion_words": bool(_EMOTION_RE.search(t)),
        "has_info_insufficiency": bool(_INFO_INSUF_RE.search(t)),
    }


# ---------------------------------------------------------------------------
# Focus 判定 (R1〜R8)
# ---------------------------------------------------------------------------


def determine_focus(inp: SkeletonInput) -> tuple[Focus, list[str]]:
    """何を見ているかを判定。優先順で最初にマッチしたルールで確定。"""
    trace: list[str] = []

    # R1: 矛盾検知（correction strong or review rejected）
    if inp.correction_strong or inp.review_rejected:
        trace.append("R1_contradiction_correction")
        return Focus.CONTRADICTION, trace

    # R2: 感情 + サプライズ（揺れが大きい）
    if inp.has_emotion_words and inp.surprise_score >= 0.3:
        trace.append("R2_emotion_surprise")
        return Focus.EMOTIONAL_STATE, trace

    # R3: 情報不足（明示的マーカー + 低カバレッジ）
    if inp.context_coverage < 0.4 and inp.has_info_insufficiency:
        trace.append("R3_missing_context_explicit")
        return Focus.MISSING_CONTEXT, trace

    # R4: 対比語 + 否定 → 矛盾の兆候
    if inp.has_contrast_words and inp.has_negation:
        trace.append("R4_contrast_negation")
        return Focus.CONTRADICTION, trace

    # R5: 低カバレッジ単独
    if inp.context_coverage < 0.35:
        trace.append("R5_low_coverage")
        return Focus.MISSING_CONTEXT, trace

    # R6: 複数質問 + ステアリングリスク → 優先順位判断
    if inp.question_mark_count >= 2 and inp.steering_risk >= 0.3:
        trace.append("R6_multi_q_steering")
        return Focus.PRIORITY_DECISION, trace

    # R7: 感情語のみ（サプライズなし）
    if inp.has_emotion_words:
        trace.append("R7_emotion_words")
        return Focus.EMOTIONAL_STATE, trace

    # R8: デフォルト
    trace.append("R8_default_user_goal")
    return Focus.USER_GOAL, trace


# ---------------------------------------------------------------------------
# ResponseIntent 判定 (I1〜I9)
# ---------------------------------------------------------------------------


def determine_response_intent(
    focus: Focus,
    inp: SkeletonInput,
) -> tuple[ResponseIntent, list[str]]:
    """どう返すかを判定。"""
    trace: list[str] = []

    # I1: WAIT → hold（depth_selector が保留を宣言）
    if inp.depth_action == "wait":
        trace.append("I1_depth_wait")
        return ResponseIntent.HOLD, trace

    # I2: 矛盾 or 情報不足
    if focus in (Focus.CONTRADICTION, Focus.MISSING_CONTEXT):
        if inp.context_coverage < 0.5:
            trace.append("I2_low_coverage_ask")
            return ResponseIntent.ASK, trace
        trace.append("I2_organize_contradiction")
        return ResponseIntent.ORGANIZE, trace

    # I3: 感情 → まず受け取る
    if focus == Focus.EMOTIONAL_STATE:
        trace.append("I3_emotion_receive")
        return ResponseIntent.RECEIVE, trace

    # I4: 優先順位判断 → 整理
    if focus == Focus.PRIORITY_DECISION:
        trace.append("I4_priority_organize")
        return ResponseIntent.ORGANIZE, trace

    # I5: 反復防止（直前2ターン同一 intent → シフト）
    if len(inp.prev_skeletons) >= 2:
        last_two = [s.response_intent for s in inp.prev_skeletons[-2:]]
        if last_two[0] == last_two[1]:
            trace.append("I5_anti_repetition")
            if last_two[0] == ResponseIntent.RECEIVE:
                return ResponseIntent.ORGANIZE, trace
            if last_two[0] == ResponseIntent.ORGANIZE:
                return ResponseIntent.ASK, trace

    # I6: Depth0 + 高カバレッジ → 受け取り
    if inp.selected_depth == 0 and inp.context_coverage >= 0.7:
        trace.append("I6_depth0_receive")
        return ResponseIntent.RECEIVE, trace

    # I7: depth_action == ask
    if inp.depth_action == "ask":
        trace.append("I7_depth_ask")
        return ResponseIntent.ASK, trace

    # I8: Depth1+ デフォルト → 整理
    if inp.selected_depth >= 1:
        trace.append("I8_depth1_organize")
        return ResponseIntent.ORGANIZE, trace

    # I9: デフォルト → 受け取り
    trace.append("I9_default_receive")
    return ResponseIntent.RECEIVE, trace


# ---------------------------------------------------------------------------
# QuestionIntent 判定 (Q1〜Q5)
# ---------------------------------------------------------------------------


def determine_question_intent(
    focus: Focus,
    response_intent: ResponseIntent,
    inp: SkeletonInput,
) -> tuple[QuestionIntent | None, list[str]]:
    """何を聞くかを判定。response_intent == ASK の時のみ。"""
    if response_intent != ResponseIntent.ASK:
        return None, []

    trace: list[str] = []

    # Q1: 矛盾 → 矛盾解消
    if focus == Focus.CONTRADICTION:
        trace.append("Q1_resolve_contradiction")
        return QuestionIntent.RESOLVE_CONTRADICTION, trace

    # Q2: 情報不足 → 事実補充
    if focus == Focus.MISSING_CONTEXT:
        trace.append("Q2_fill_missing_fact")
        return QuestionIntent.FILL_MISSING_FACT, trace

    # Q3: 感情 → 感情確認
    if focus == Focus.EMOTIONAL_STATE:
        trace.append("Q3_clarify_emotion")
        return QuestionIntent.CLARIFY_EMOTION, trace

    # Q4: 優先順位 → 優先順位確認
    if focus == Focus.PRIORITY_DECISION:
        trace.append("Q4_clarify_priority")
        return QuestionIntent.CLARIFY_PRIORITY, trace

    # Q5: デフォルト → 目的確認
    trace.append("Q5_clarify_goal")
    return QuestionIntent.CLARIFY_GOAL, trace


# ---------------------------------------------------------------------------
# オーケストレータ
# ---------------------------------------------------------------------------


def evaluate_skeleton(inp: SkeletonInput) -> ConversationSkeleton:
    """全ルールチェーンを実行し ConversationSkeleton を返す。"""
    focus, f_trace = determine_focus(inp)
    response_intent, r_trace = determine_response_intent(focus, inp)
    question_intent, q_trace = determine_question_intent(
        focus, response_intent, inp,
    )

    return ConversationSkeleton(
        focus=focus,
        response_intent=response_intent,
        question_intent=question_intent,
        source="nia_internal",
        confidence=inp.context_coverage,
        rule_trace=f_trace + r_trace + q_trace,
    )
