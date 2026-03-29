"""
Confidence System - Post-Phase5

確信度メトリクスシステム。
LLM出力の確実性を定量化し、Depth選択の判断材料を提供します。

主要コンポーネント:
- ConfidenceMetrics: 各メトリクスの計算結果を保持
- ConfidenceEngine: 複合確信度の計算とキャリブレーション
- DepthRecommendation: Depth選択の推奨
- SteeringRiskCalculator: 結論圧/誘導リスクの検出（Post-Phase5）
"""

from .metrics import (
    ConfidenceMetrics,
    SelfConsistencyCalculator,
    ContextCoverageCalculator,
    QuestionClarityCalculator,
    LogitBasedCalculator,
    SteeringRiskCalculator,
)
from .engine import ConfidenceEngine, DepthRecommendation, DepthAction
from .calibrator import ConfidenceCalibrator

__all__ = [
    "ConfidenceMetrics",
    "SelfConsistencyCalculator",
    "ContextCoverageCalculator",
    "QuestionClarityCalculator",
    "LogitBasedCalculator",
    "SteeringRiskCalculator",
    "ConfidenceEngine",
    "DepthRecommendation",
    "DepthAction",
    "ConfidenceCalibrator",
]
