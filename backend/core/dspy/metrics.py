"""
Phase 4: DSPy品質メトリクス

Depth1出力の品質を評価するためのメトリクス関数。

品質評価の観点:
1. 断定抑制: 断定的な表現を避けているか
2. 反復抑制: 不要な反復がないか
3. 焦点の明確さ: 1つの不確実性に集中しているか
"""

import re
from dataclasses import dataclass
from typing import Optional

import dspy


@dataclass
class QualityScore:
    """品質スコアの詳細"""

    total: float  # 総合スコア (0.0-1.0)
    assertion_score: float  # 断定抑制スコア (0.0-1.0)
    repetition_score: float  # 反復抑制スコア (0.0-1.0)
    focus_score: float  # 焦点明確さスコア (0.0-1.0)
    detail: dict  # 詳細情報


# 断定パターン（日本語）
ASSERTION_PATTERNS = [
    r"〜と思います$",
    r"〜すべきです$",
    r"答えは〜です",
    r"結論としては",
    r"確実に",
    r"絶対に",
    r"間違いなく",
    r"必ず",
    r"〜に違いない",
    r"〜はずです",
    r"断言できる",
    r"〜でしょう。$",  # 推量だが断定的に使われることがある
]

# 不確実性表現パターン（良いパターン）
UNCERTAINTY_PATTERNS = [
    r"まだわからない",
    r"不確か",
    r"〜かもしれない",
    r"〜の観点では",
    r"〜と思われる",
    r"〜の可能性",
    r"〜とは限らない",
    r"検討中",
    r"判断しかねる",
    r"情報が足りない",
]

# 反復検出用
MIN_REPETITION_LENGTH = 10  # 最小反復長
MAX_REPETITION_RATIO = 0.3  # 許容反復率


def contains_assertions(text: str) -> tuple[bool, list[str]]:
    """
    断定的な表現が含まれているかチェック

    Args:
        text: チェック対象のテキスト

    Returns:
        (断定があるか, マッチしたパターンのリスト)
    """
    if not text:
        return False, []

    matches = []
    for pattern in ASSERTION_PATTERNS:
        if re.search(pattern, text):
            matches.append(pattern)

    return len(matches) > 0, matches


def has_uncertainty_expressions(text: str) -> tuple[bool, list[str]]:
    """
    不確実性を示す表現が含まれているかチェック

    Args:
        text: チェック対象のテキスト

    Returns:
        (不確実性表現があるか, マッチしたパターンのリスト)
    """
    if not text:
        return False, []

    matches = []
    for pattern in UNCERTAINTY_PATTERNS:
        if re.search(pattern, text):
            matches.append(pattern)

    return len(matches) > 0, matches


def has_repetition(text: str) -> tuple[bool, float]:
    """
    不要な反復があるかチェック

    Args:
        text: チェック対象のテキスト

    Returns:
        (反復があるか, 反復率)
    """
    if not text or len(text) < MIN_REPETITION_LENGTH * 2:
        return False, 0.0

    # N-gramベースの反復検出
    n = MIN_REPETITION_LENGTH
    ngrams = [text[i : i + n] for i in range(len(text) - n + 1)]

    if not ngrams:
        return False, 0.0

    # 重複するN-gramの割合を計算
    unique_ngrams = set(ngrams)
    repetition_ratio = 1 - (len(unique_ngrams) / len(ngrams))

    return repetition_ratio > MAX_REPETITION_RATIO, repetition_ratio


def is_focused(text: str, max_topics: int = 2) -> tuple[bool, int]:
    """
    焦点が明確か（複数のトピックに分散していないか）チェック

    Args:
        text: チェック対象のテキスト
        max_topics: 許容する最大トピック数

    Returns:
        (焦点が明確か, 検出されたトピック数)
    """
    if not text:
        return True, 0

    # 質問の数をカウント（複数の質問 = 焦点が分散）
    question_count = text.count("?") + text.count("？")

    # 段落・箇条書きの数をカウント
    paragraph_count = len([p for p in text.split("\n") if p.strip()])

    # トピック数を推定
    estimated_topics = max(question_count, (paragraph_count + 1) // 2)

    return estimated_topics <= max_topics, estimated_topics


def calculate_quality_score(
    organized_thought: str,
    clarification: str,
    original_question: str = "",
) -> QualityScore:
    """
    Depth1出力の品質スコアを計算

    Args:
        organized_thought: 整理された思考
        clarification: 確認質問
        original_question: 元の質問（オプション）

    Returns:
        QualityScore オブジェクト
    """
    combined_text = f"{organized_thought}\n{clarification}".strip()

    # 1. 断定抑制スコア
    has_assertion, assertion_matches = contains_assertions(combined_text)
    has_uncertainty, _ = has_uncertainty_expressions(combined_text)

    if has_assertion:
        assertion_score = 0.3 if has_uncertainty else 0.0
    else:
        assertion_score = 1.0 if has_uncertainty else 0.7

    # 2. 反復抑制スコア
    is_repetitive, repetition_ratio = has_repetition(combined_text)
    repetition_score = max(0.0, 1.0 - repetition_ratio * 2)

    # 3. 焦点明確さスコア
    focused, topic_count = is_focused(combined_text)
    if focused:
        focus_score = 1.0
    elif topic_count <= 3:
        focus_score = 0.6
    else:
        focus_score = 0.3

    # 総合スコア（重み付け平均）
    weights = {
        "assertion": 0.3,
        "repetition": 0.3,
        "focus": 0.4,
    }
    total = (
        weights["assertion"] * assertion_score
        + weights["repetition"] * repetition_score
        + weights["focus"] * focus_score
    )

    return QualityScore(
        total=total,
        assertion_score=assertion_score,
        repetition_score=repetition_score,
        focus_score=focus_score,
        detail={
            "has_assertion": has_assertion,
            "assertion_matches": assertion_matches,
            "has_uncertainty": has_uncertainty,
            "is_repetitive": is_repetitive,
            "repetition_ratio": repetition_ratio,
            "is_focused": focused,
            "topic_count": topic_count,
        },
    )


class Depth1QualityMetric:
    """
    DSPy用のDepth1品質メトリクス

    BootstrapFewShotオプティマイザーで使用するメトリクス関数を提供。
    """

    def __init__(
        self,
        assertion_weight: float = 0.3,
        repetition_weight: float = 0.3,
        focus_weight: float = 0.4,
        threshold: float = 0.7,
    ):
        """
        Args:
            assertion_weight: 断定抑制の重み
            repetition_weight: 反復抑制の重み
            focus_weight: 焦点明確さの重み
            threshold: 成功とみなす閾値
        """
        self.assertion_weight = assertion_weight
        self.repetition_weight = repetition_weight
        self.focus_weight = focus_weight
        self.threshold = threshold

    def __call__(
        self,
        example: dspy.Example,
        prediction: dspy.Prediction,
        trace: Optional[object] = None,
    ) -> float:
        """
        品質スコアを計算

        Args:
            example: 入力例
            prediction: モデルの予測
            trace: トレース情報（オプション）

        Returns:
            品質スコア (0.0-1.0)
        """
        organized_thought = getattr(prediction, "organized_thought", "")
        clarification = getattr(prediction, "clarification", "")
        original_question = getattr(example, "question", "")

        score = calculate_quality_score(
            organized_thought=organized_thought,
            clarification=clarification,
            original_question=original_question,
        )

        return score.total

    def is_success(
        self,
        example: dspy.Example,
        prediction: dspy.Prediction,
    ) -> bool:
        """
        成功/失敗を判定

        Args:
            example: 入力例
            prediction: モデルの予測

        Returns:
            成功したかどうか
        """
        score = self(example, prediction)
        return score >= self.threshold

    def detailed_score(
        self,
        example: dspy.Example,
        prediction: dspy.Prediction,
    ) -> QualityScore:
        """
        詳細なスコアを取得

        Args:
            example: 入力例
            prediction: モデルの予測

        Returns:
            QualityScore オブジェクト
        """
        organized_thought = getattr(prediction, "organized_thought", "")
        clarification = getattr(prediction, "clarification", "")
        original_question = getattr(example, "question", "")

        return calculate_quality_score(
            organized_thought=organized_thought,
            clarification=clarification,
            original_question=original_question,
        )


# シングルトンインスタンス
depth1_quality_metric = Depth1QualityMetric()
