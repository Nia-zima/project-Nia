"""
Confidence Metrics - 確信度メトリクス

各種確信度メトリクスの計算を行うモジュール。

メトリクスの重み（Phase 1 v1）:
- Context Coverage (40%): 情報充足度 - 最重要
- Self-Consistency (25%): 複数生成の一貫性
- Logit-based (20%): トークン確率（簡易実装）
- Question Clarity (15%): 質問の明瞭度
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict
import logging

logger = logging.getLogger(__name__)


@dataclass
class ConfidenceMetrics:
    """確信度メトリクスの結果を保持するデータクラス"""

    # 個別メトリクス（0.0 - 1.0）
    self_consistency: float = 0.0
    logit_based: float = 0.0
    context_coverage: float = 0.0
    question_clarity: float = 0.0

    # Post-Phase5: 3スカラーシステム用
    # info_sufficiency = context_coverage のエイリアス的位置づけ
    steering_risk: float = 0.0  # 結論圧/依存/誘導リスク（B.8）

    # 複合確信度（キャリブレーション前）
    composite_raw: float = 0.0

    # 複合確信度（キャリブレーション後）
    composite_calibrated: float = 0.0

    # デバッグ情報
    debug_info: Dict[str, any] = field(default_factory=dict)

    @property
    def info_sufficiency(self) -> float:
        """情報充足度（context_coverageのエイリアス）"""
        return self.context_coverage

    def to_dict(self) -> dict:
        """辞書形式に変換"""
        return {
            "self_consistency": self.self_consistency,
            "logit_based": self.logit_based,
            "context_coverage": self.context_coverage,
            "question_clarity": self.question_clarity,
            "steering_risk": self.steering_risk,
            "info_sufficiency": self.info_sufficiency,
            "composite_raw": self.composite_raw,
            "composite_calibrated": self.composite_calibrated,
            "debug_info": self.debug_info,
        }


class SelfConsistencyCalculator:
    """
    Self-Consistency メトリクス

    複数回生成した出力の一貫性を測定。
    同じ質問に対して複数回生成し、類似度を計算。

    重み: 25%
    """

    @staticmethod
    def calculate(outputs: List[str]) -> float:
        """
        複数の出力から一貫性スコアを計算

        Args:
            outputs: 同じ質問に対する複数の出力

        Returns:
            float: 一貫性スコア (0.0 - 1.0)
        """
        if not outputs or len(outputs) < 2:
            # 単一出力の場合は中立的なスコア
            return 0.5

        # 簡易実装: n-gram ベースの類似度
        similarities = []

        for i in range(len(outputs)):
            for j in range(i + 1, len(outputs)):
                sim = SelfConsistencyCalculator._calculate_similarity(
                    outputs[i], outputs[j]
                )
                similarities.append(sim)

        if not similarities:
            return 0.5

        # 平均類似度を返す
        return sum(similarities) / len(similarities)

    @staticmethod
    def _calculate_similarity(text1: str, text2: str) -> float:
        """
        2つのテキストの類似度を計算（簡易版）

        実際のPhase 1.5+では、埋め込みベースの類似度を使用する予定
        """
        # 単語レベルのJaccard類似度
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())

        if not words1 and not words2:
            return 1.0
        if not words1 or not words2:
            return 0.0

        intersection = len(words1 & words2)
        union = len(words1 | words2)

        return intersection / union if union > 0 else 0.0


class ContextCoverageCalculator:
    """
    Context Coverage メトリクス - 最重要

    質問に答えるために必要な情報が文脈に含まれているかを判定。

    重み: 40%（最も重要）
    """

    # 情報不足を示すパターン
    INFO_LACK_PATTERNS = [
        r"情報が.*不足",
        r"詳細が.*わからない",
        r"具体的.*不明",
        r"確認.*必要",
        r"追加.*情報",
        r"もっと.*知りたい",
        r"何.*について",
        r"どの.*について",
    ]

    # 十分な情報を示すパターン
    INFO_SUFFICIENT_PATTERNS = [
        r"確認.*できた",
        r"明らか.*",
        r"わかった",
        r"理解.*した",
        r"説明.*できる",
    ]

    @staticmethod
    def calculate(question: str, context: List[str]) -> float:
        """
        質問と文脈から情報充足度を計算

        Args:
            question: ユーザーの質問
            context: 利用可能な文脈（過去のメッセージ等）

        Returns:
            float: 情報充足度 (0.0 - 1.0)
        """
        score = 0.5  # デフォルト: 中立

        # 1. 質問の長さから推定（長い質問 = より多くの情報を含む）
        question_length_factor = min(len(question) / 200, 1.0)
        score += question_length_factor * 0.2

        # 2. 文脈の量（多い = より多くの情報）
        if context:
            total_context_length = sum(len(c) for c in context)
            context_factor = min(total_context_length / 1000, 1.0)
            score += context_factor * 0.3
        else:
            score -= 0.3  # 文脈なし = 低い情報充足度

        # 3. 質問中の不確実性パターン
        question_lower = question.lower()
        for pattern in ContextCoverageCalculator.INFO_LACK_PATTERNS:
            if re.search(pattern, question):
                score -= 0.1

        # 4. 文脈中の十分性パターン
        context_text = " ".join(context) if context else ""
        for pattern in ContextCoverageCalculator.INFO_SUFFICIENT_PATTERNS:
            if re.search(pattern, context_text):
                score += 0.1

        # 5. 質問中の疑問詞の数（多い = 情報不足）
        question_marks = ["何", "どう", "どの", "いつ", "どこ", "誰", "なぜ"]
        question_mark_count = sum(
            1 for mark in question_marks if mark in question
        )
        score -= min(question_mark_count * 0.05, 0.2)

        # 0.0 - 1.0 にクランプ
        return max(0.0, min(1.0, score))


class QuestionClarityCalculator:
    """
    Question Clarity メトリクス

    質問の明瞭度を評価。
    曖昧な質問は低スコア、明確な質問は高スコア。

    重み: 15%
    """

    # 曖昧さを示すパターン
    AMBIGUOUS_PATTERNS = [
        r"それ",
        r"あれ",
        r"これ",
        r"何か",
        r"よくわからない",
        r"とか",
        r"みたいな",
        r"的な",
    ]

    # 明確さを示すパターン
    CLEAR_PATTERNS = [
        r"具体的に",
        r"〜について",
        r"〜に関して",
        r"〜の場合",
        r"例えば",
    ]

    @staticmethod
    def calculate(question: str) -> float:
        """
        質問の明瞭度を計算

        Args:
            question: ユーザーの質問

        Returns:
            float: 明瞭度スコア (0.0 - 1.0)
        """
        score = 0.5  # デフォルト: 中立

        # 1. 質問の長さ（短すぎる = 曖昧、長すぎる = 冗長）
        length = len(question)
        if length < 10:
            score -= 0.3
        elif 20 <= length <= 150:
            score += 0.2
        elif length > 300:
            score -= 0.1

        # 2. 曖昧なパターンの検出
        for pattern in QuestionClarityCalculator.AMBIGUOUS_PATTERNS:
            if re.search(pattern, question):
                score -= 0.1

        # 3. 明確なパターンの検出
        for pattern in QuestionClarityCalculator.CLEAR_PATTERNS:
            if re.search(pattern, question):
                score += 0.1

        # 4. 疑問符の適切な使用
        if "？" in question or "?" in question:
            score += 0.1

        # 5. 複数の疑問符（過度な不確実性）
        question_mark_count = question.count("？") + question.count("?")
        if question_mark_count > 2:
            score -= 0.15

        # 0.0 - 1.0 にクランプ
        return max(0.0, min(1.0, score))


class LogitBasedCalculator:
    """
    Logit-based メトリクス（簡易版）

    Phase 1 v1では、トークン確率を直接取得できないため、
    簡易的な代替メトリクスを使用。

    将来的には、LLM APIからログプロバビリティを取得する。

    重み: 20%
    """

    @staticmethod
    def calculate(output: str, uncertainty_indicators: List[str] = None) -> float:
        """
        出力の確実性を簡易評価

        Args:
            output: LLMの出力
            uncertainty_indicators: 不確実性を示す単語リスト

        Returns:
            float: 確実性スコア (0.0 - 1.0)
        """
        if uncertainty_indicators is None:
            uncertainty_indicators = [
                "たぶん", "おそらく", "かもしれない", "ようだ",
                "思う", "気がする", "わからない", "不明", "不確か"
            ]

        score = 0.7  # デフォルト: やや高め

        # 不確実性インジケータの数
        uncertainty_count = sum(
            1 for indicator in uncertainty_indicators if indicator in output
        )

        # 不確実性が多いほどスコアを下げる
        score -= min(uncertainty_count * 0.1, 0.5)

        # 断定的な表現の検出
        assertive_patterns = [
            "確実に", "間違いなく", "絶対に", "明らかに"
        ]
        assertive_count = sum(
            1 for pattern in assertive_patterns if pattern in output
        )

        # 断定的な表現が多いほどスコアを上げる（ただし、過度は避ける）
        score += min(assertive_count * 0.1, 0.2)

        # 0.0 - 1.0 にクランプ
        return max(0.0, min(1.0, score))


class SteeringRiskCalculator:
    """
    Steering Risk メトリクス（Post-Phase5 新規追加）

    結論圧/依存/誘導リスクを検出。
    Body Constitution B.8「結論圧への抵抗」の実装。

    steering_risk > 0.6 → Depth0（境界を示す）
    steering_risk > 0.8 → WAIT（沈黙の権利）
    """

    # 結論圧パターン: 「決めて」「正解教えて」系
    CONCLUSION_PRESSURE_PATTERNS = [
        r"決めて",
        r"選んで",
        r"正解.*教えて",
        r"どっち.*いい",
        r"どれ.*おすすめ",
        r"最適.*教えて",
        r"ベスト.*なに",
        r"答え.*教えて",
        r"結論.*教えて",
        r"判断.*して",
        r"診断.*して",
    ]

    # 依存誘発パターン: 「頼りにしてる」「任せる」系
    DEPENDENCY_PATTERNS = [
        r"頼り.*にしてる",
        r"任せる",
        r"決めてくれ",
        r"お願い.*だから",
        r"あなた.*しか",
        r"あなた.*だけ",
    ]

    # 感情的圧力パターン: 危機・重大決定系
    EMOTIONAL_PRESSURE_PATTERNS = [
        r"つらい",
        r"苦しい",
        r"死にたい",
        r"もう.*だめ",
        r"限界",
        r"助けて",
    ]

    # センシティブトピック: 人生の重大決定
    SENSITIVE_TOPICS = [
        r"離婚",
        r"退職",
        r"投資",
        r"手術",
        r"裁判",
        r"自殺",
        r"借金",
    ]

    @staticmethod
    def calculate(question: str, context: List[str] = None) -> float:
        """
        結論圧/誘導リスクを計算

        Args:
            question: ユーザーの質問
            context: 過去の文脈（オプション）

        Returns:
            float: リスクスコア (0.0 - 1.0)
                   0.0 = リスクなし
                   0.6+ = Depth0推奨（境界を示す）
                   0.8+ = WAIT推奨（沈黙の権利）
        """
        score = 0.0

        # 1. 結論圧パターンの検出
        for pattern in SteeringRiskCalculator.CONCLUSION_PRESSURE_PATTERNS:
            if re.search(pattern, question):
                score += 0.25
                logger.debug(f"Conclusion pressure detected: {pattern}")

        # 2. 依存誘発パターンの検出
        for pattern in SteeringRiskCalculator.DEPENDENCY_PATTERNS:
            if re.search(pattern, question):
                score += 0.2
                logger.debug(f"Dependency pattern detected: {pattern}")

        # 3. 感情的圧力パターンの検出
        for pattern in SteeringRiskCalculator.EMOTIONAL_PRESSURE_PATTERNS:
            if re.search(pattern, question):
                score += 0.3
                logger.debug(f"Emotional pressure detected: {pattern}")

        # 4. センシティブトピックの検出
        for pattern in SteeringRiskCalculator.SENSITIVE_TOPICS:
            if re.search(pattern, question):
                score += 0.15
                logger.debug(f"Sensitive topic detected: {pattern}")

        # 5. 文脈からの圧力検出（繰り返しの要求）
        if context:
            context_text = " ".join(context[-3:])  # 直近3メッセージ
            repeat_pressure = sum(
                1 for pattern in SteeringRiskCalculator.CONCLUSION_PRESSURE_PATTERNS
                if re.search(pattern, context_text)
            )
            if repeat_pressure >= 2:
                score += 0.2
                logger.debug("Repeated pressure detected in context")

        # 0.0 - 1.0 にクランプ
        return max(0.0, min(1.0, score))
