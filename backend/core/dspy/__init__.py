"""
Phase 4: DSPy品質改善モジュール

Depth1の出力品質を最適化するためのDSPyプログラムと
オプティマイザーを提供します。
"""

from backend.core.dspy.signatures import Depth1Organizer
from backend.core.dspy.modules import Depth1Module
from backend.core.dspy.metrics import Depth1QualityMetric
from backend.core.dspy.optimizer import Depth1Optimizer
from backend.core.dspy.dataset import Depth1DatasetManager

__all__ = [
    "Depth1Organizer",
    "Depth1Module",
    "Depth1QualityMetric",
    "Depth1Optimizer",
    "Depth1DatasetManager",
]
