"""
Confidence Engine - 確信度エンジン

複合確信度の計算、キャリブレーション、Depth選択の推奨を行うモジュール。
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Dict

from .metrics import (
    ConfidenceMetrics,
    SelfConsistencyCalculator,
    ContextCoverageCalculator,
    QuestionClarityCalculator,
    LogitBasedCalculator,
    SteeringRiskCalculator,
)
from .calibrator import ConfidenceCalibrator

logger = logging.getLogger(__name__)


class DepthAction(Enum):
    """Depth選択のアクション"""
    USE_DEPTH0 = "depth0"  # Pre-Thought のみ
    USE_DEPTH1 = "depth1"  # Organize & Ask まで実行
    ASK = "ask"            # ユーザーに質問
    WAIT = "wait"          # 保留（情報不足）


@dataclass
class DepthRecommendation:
    """Depth選択の推奨結果"""
    action: DepthAction
    confidence: float  # 0.0 - 1.0
    reason: str
    metrics: ConfidenceMetrics


class ConfidenceEngine:
    """
    確信度エンジン

    複数のメトリクスを統合して複合確信度を計算し、
    Depth選択の推奨を行います。

    メトリクスの重み（Phase 1 v1）:
    - Context Coverage (40%): 情報充足度 - 最重要
    - Self-Consistency (25%): 複数生成の一貫性
    - Logit-based (20%): トークン確率（簡易実装）
    - Question Clarity (15%): 質問の明瞭度
    """

    # メトリクスの重み
    WEIGHTS = {
        "context_coverage": 0.40,
        "self_consistency": 0.25,
        "logit_based": 0.20,
        "question_clarity": 0.15,
    }

    # Depth選択の閾値
    THRESHOLDS = {
        "depth0": 0.8,   # >= 0.8: DEPTH0で十分
        "depth1": 0.5,   # >= 0.5: DEPTH1が必要
        "ask": 0.3,      # >= 0.3: ユーザーに質問
        # < 0.3: WAIT（情報不足）
    }

    def __init__(
        self,
        calibrator: Optional[ConfidenceCalibrator] = None,
        weights: Optional[Dict[str, float]] = None,
        thresholds: Optional[Dict[str, float]] = None,
    ):
        """
        Args:
            calibrator: キャリブレータ（Noneの場合は未キャリブレーション）
            weights: カスタム重み（Noneの場合はデフォルト）
            thresholds: カスタム閾値（Noneの場合はデフォルト）
        """
        self.calibrator = calibrator
        self.weights = weights or self.WEIGHTS
        self.thresholds = thresholds or self.THRESHOLDS

    def calculate_confidence(
        self,
        question: str,
        context: List[str],
        llm_output: Optional[str] = None,
        alternative_outputs: Optional[List[str]] = None,
    ) -> ConfidenceMetrics:
        """
        確信度メトリクスを計算

        Args:
            question: ユーザーの質問
            context: 文脈（過去のメッセージ等）
            llm_output: LLMの出力（Noneの場合は質問のみで評価）
            alternative_outputs: 複数生成した出力（Self-Consistency用）

        Returns:
            ConfidenceMetrics: 計算結果
        """
        metrics = ConfidenceMetrics()

        # 1. Context Coverage（最重要）
        metrics.context_coverage = ContextCoverageCalculator.calculate(
            question, context
        )

        # 2. Question Clarity
        metrics.question_clarity = QuestionClarityCalculator.calculate(question)

        # 3. Logit-based（LLM出力がある場合のみ）
        if llm_output:
            metrics.logit_based = LogitBasedCalculator.calculate(llm_output)
        else:
            # 出力がない場合は中立的なスコア
            metrics.logit_based = 0.5

        # 4. Self-Consistency（複数出力がある場合のみ）
        if alternative_outputs and len(alternative_outputs) >= 2:
            metrics.self_consistency = SelfConsistencyCalculator.calculate(
                alternative_outputs
            )
        else:
            # 複数出力がない場合は中立的なスコア
            metrics.self_consistency = 0.5

        # 5. Steering Risk（Post-Phase5 新規: Body Constitution B.8）
        metrics.steering_risk = SteeringRiskCalculator.calculate(question, context)

        # 6. 複合確信度の計算（重み付き平均）
        metrics.composite_raw = self._calculate_composite(metrics)

        # 6. キャリブレーション（設定されている場合）
        if self.calibrator:
            metrics.composite_calibrated = self.calibrator.calibrate(
                metrics.composite_raw
            )
        else:
            # キャリブレータがない場合はrawをそのまま使用
            metrics.composite_calibrated = metrics.composite_raw

        # デバッグ情報
        metrics.debug_info = {
            "weights": self.weights,
            "question_length": len(question),
            "context_count": len(context),
            "has_llm_output": llm_output is not None,
            "alternative_count": len(alternative_outputs) if alternative_outputs else 0,
        }

        logger.debug(
            "[CONFIDENCE] composite=%.3f context=%.3f clarity=%.3f logit=%.3f consistency=%.3f steering=%.3f",
            metrics.composite_calibrated,
            metrics.context_coverage,
            metrics.question_clarity,
            metrics.logit_based,
            metrics.self_consistency,
            metrics.steering_risk,
        )

        return metrics

    def get_depth_recommendation(
        self,
        question: str,
        context: List[str],
        llm_output: Optional[str] = None,
        alternative_outputs: Optional[List[str]] = None,
    ) -> DepthRecommendation:
        """
        Depth選択の推奨を取得

        Args:
            question: ユーザーの質問
            context: 文脈
            llm_output: LLM出力
            alternative_outputs: 複数生成した出力

        Returns:
            DepthRecommendation: 推奨結果
        """
        # 確信度を計算
        metrics = self.calculate_confidence(
            question, context, llm_output, alternative_outputs
        )

        # キャリブレーション済みの確信度を使用
        confidence = metrics.composite_calibrated

        # 閾値に基づいてアクションを決定
        if confidence >= self.thresholds["depth0"]:
            action = DepthAction.USE_DEPTH0
            reason = f"高い確信度（{confidence:.2f}）。Depth0で十分です。"
        elif confidence >= self.thresholds["depth1"]:
            action = DepthAction.USE_DEPTH1
            reason = f"中程度の確信度（{confidence:.2f}）。Depth1で詳細な分析が必要です。"
        elif confidence >= self.thresholds["ask"]:
            action = DepthAction.ASK
            reason = f"低い確信度（{confidence:.2f}）。ユーザーに質問して情報を補完すべきです。"
        else:
            action = DepthAction.WAIT
            reason = f"非常に低い確信度（{confidence:.2f}）。情報が不足しています。"

        return DepthRecommendation(
            action=action,
            confidence=confidence,
            reason=reason,
            metrics=metrics,
        )

    def _calculate_composite(self, metrics: ConfidenceMetrics) -> float:
        """
        複合確信度を計算（重み付き平均）

        Args:
            metrics: 個別メトリクス

        Returns:
            float: 複合確信度 (0.0 - 1.0)
        """
        composite = (
            metrics.context_coverage * self.weights["context_coverage"] +
            metrics.self_consistency * self.weights["self_consistency"] +
            metrics.logit_based * self.weights["logit_based"] +
            metrics.question_clarity * self.weights["question_clarity"]
        )

        # 0.0 - 1.0 にクランプ
        return max(0.0, min(1.0, composite))

    def get_depth_recommendation_v2(
        self,
        question: str,
        context: List[str],
        llm_output: Optional[str] = None,
        alternative_outputs: Optional[List[str]] = None,
    ) -> DepthRecommendation:
        """
        Depth選択の推奨を取得（Post-Phase5: 3スカラーロジック）

        Body Constitution に基づく選択ロジック:
        - steering_risk > 0.8 → WAIT（B.6 沈黙の権利）
        - steering_risk > 0.6 → Depth0（B.8 結論圧への抵抗）
        - info_sufficiency < 0.4 → Depth0（B.4 観測の主導権）
        - question_clarity < 0.5 → Depth1（B.5 思考の独立性）
        - それ以外 → Depth1（整理は最小限、結論禁止）

        Args:
            question: ユーザーの質問
            context: 文脈
            llm_output: LLM出力
            alternative_outputs: 複数生成した出力

        Returns:
            DepthRecommendation: 推奨結果
        """
        # 確信度を計算
        metrics = self.calculate_confidence(
            question, context, llm_output, alternative_outputs
        )

        # 3スカラー取得
        steering_risk = metrics.steering_risk
        info_sufficiency = metrics.info_sufficiency  # = context_coverage
        question_clarity = metrics.question_clarity

        # Body Constitution B.6: 沈黙の権利
        # steering_risk > 0.85 → WAIT（緩和: 本当にやばいときだけ）
        if steering_risk > 0.85:
            return DepthRecommendation(
                action=DepthAction.WAIT,
                confidence=metrics.composite_calibrated,
                reason=f"結論圧が非常に高い（steering_risk={steering_risk:.2f}）。沈黙の権利を行使。",
                metrics=metrics,
            )

        # Body Constitution B.8: 結論圧への抵抗
        # steering_risk > 0.7 → Depth0（緩和: 軽い会話は通す）
        if steering_risk > 0.7:
            return DepthRecommendation(
                action=DepthAction.USE_DEPTH0,
                confidence=metrics.composite_calibrated,
                reason=f"結論圧を検出（steering_risk={steering_risk:.2f}）。境界を示す。",
                metrics=metrics,
            )

        # Body Constitution B.4: 観測の主導権
        # info_sufficiency < 0.3 → Depth0（緩和: 本当に情報がないときだけ）
        if info_sufficiency < 0.3:
            return DepthRecommendation(
                action=DepthAction.USE_DEPTH0,
                confidence=metrics.composite_calibrated,
                reason=f"情報不足（info_sufficiency={info_sufficiency:.2f}）。不足を示す。",
                metrics=metrics,
            )

        # Body Constitution B.5: 思考の独立性
        # question_clarity < 0.5 → Depth1（整理して質問1つ）
        if question_clarity < 0.5:
            return DepthRecommendation(
                action=DepthAction.USE_DEPTH1,
                confidence=metrics.composite_calibrated,
                reason=f"質問が不明確（question_clarity={question_clarity:.2f}）。整理して質問1つ。",
                metrics=metrics,
            )

        # 全部OK → Depth1（整理は最小限、結論禁止）
        return DepthRecommendation(
            action=DepthAction.USE_DEPTH1,
            confidence=metrics.composite_calibrated,
            reason="3スカラーOK。整理は最小限、ただし結論は出さない。",
            metrics=metrics,
        )

    def update_weights(self, new_weights: Dict[str, float]):
        """
        重みを更新

        Args:
            new_weights: 新しい重み（合計が1.0になるべき）
        """
        total = sum(new_weights.values())
        if abs(total - 1.0) > 0.01:
            logger.warning(
                "[CONFIDENCE] Weight sum is %.3f, not 1.0. Normalizing...",
                total
            )
            # 正規化
            new_weights = {k: v / total for k, v in new_weights.items()}

        self.weights = new_weights
        logger.info("[CONFIDENCE] Weights updated: %s", new_weights)

    def update_thresholds(self, new_thresholds: Dict[str, float]):
        """
        閾値を更新

        Args:
            new_thresholds: 新しい閾値
        """
        self.thresholds = new_thresholds
        logger.info("[CONFIDENCE] Thresholds updated: %s", new_thresholds)
