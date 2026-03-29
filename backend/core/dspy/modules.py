"""
Phase 4: DSPy Modules

Depth1の出力生成を行うDSPyモジュール。
"""

from typing import Optional
import dspy

from backend.core.dspy.signatures import (
    Depth1Organizer,
    UncertaintyExtractor,
    ResponseQualityChecker,
)


class Depth1Module(dspy.Module):
    """
    Depth1での整理・確認を行うDSPyモジュール

    ChainOfThoughtを使用して、思考過程を明示しながら
    高品質な出力を生成します。
    """

    def __init__(self):
        super().__init__()
        self.organizer = dspy.ChainOfThought(Depth1Organizer)

    def forward(
        self,
        question: str,
        context: str,
        uncertainty: str,
    ) -> dspy.Prediction:
        """
        Depth1の出力を生成

        Args:
            question: ユーザーの質問
            context: 会話コンテキスト
            uncertainty: 核心的な不確実性

        Returns:
            organized_thought と clarification を含む Prediction
        """
        result = self.organizer(
            question=question,
            context=context,
            uncertainty=uncertainty,
        )

        return dspy.Prediction(
            organized_thought=result.organized_thought,
            clarification=result.clarification,
            rationale=getattr(result, "rationale", ""),
        )


class UncertaintyExtractorModule(dspy.Module):
    """
    テキストから不確実性を抽出するモジュール
    """

    def __init__(self):
        super().__init__()
        self.extractor = dspy.ChainOfThought(UncertaintyExtractor)

    def forward(
        self,
        text: str,
        context: str = "",
    ) -> dspy.Prediction:
        """
        テキストから不確実性を抽出

        Args:
            text: 分析対象のテキスト
            context: 会話コンテキスト

        Returns:
            uncertainties と primary_uncertainty を含む Prediction
        """
        result = self.extractor(
            text=text,
            context=context,
        )

        return dspy.Prediction(
            uncertainties=result.uncertainties,
            primary_uncertainty=result.primary_uncertainty,
            rationale=getattr(result, "rationale", ""),
        )


class QualityCheckerModule(dspy.Module):
    """
    レスポンスの品質をチェックするモジュール
    """

    def __init__(self):
        super().__init__()
        self.checker = dspy.Predict(ResponseQualityChecker)

    def forward(
        self,
        response: str,
        original_question: str,
    ) -> dspy.Prediction:
        """
        レスポンスの品質をチェック

        Args:
            response: 評価対象のレスポンス
            original_question: 元の質問

        Returns:
            品質評価の結果を含む Prediction
        """
        result = self.checker(
            response=response,
            original_question=original_question,
        )

        return dspy.Prediction(
            has_assertion=result.has_assertion,
            has_repetition=result.has_repetition,
            is_focused=result.is_focused,
            quality_score=result.quality_score,
        )


class Depth1PipelineModule(dspy.Module):
    """
    Depth1の完全なパイプライン

    1. 不確実性の抽出
    2. Depth1出力の生成
    3. 品質チェック（オプション）
    """

    def __init__(self, check_quality: bool = False):
        super().__init__()
        self.uncertainty_extractor = UncertaintyExtractorModule()
        self.depth1_organizer = Depth1Module()
        self.quality_checker = QualityCheckerModule() if check_quality else None
        self.check_quality = check_quality

    def forward(
        self,
        question: str,
        context: str = "",
    ) -> dspy.Prediction:
        """
        Depth1パイプラインを実行

        Args:
            question: ユーザーの質問
            context: 会話コンテキスト

        Returns:
            完全な Depth1 出力を含む Prediction
        """
        # Step 1: 不確実性を抽出
        uncertainty_result = self.uncertainty_extractor(
            text=question,
            context=context,
        )

        # Step 2: Depth1出力を生成
        depth1_result = self.depth1_organizer(
            question=question,
            context=context,
            uncertainty=uncertainty_result.primary_uncertainty,
        )

        # 基本の出力
        output = dspy.Prediction(
            uncertainties=uncertainty_result.uncertainties,
            primary_uncertainty=uncertainty_result.primary_uncertainty,
            organized_thought=depth1_result.organized_thought,
            clarification=depth1_result.clarification,
        )

        # Step 3: 品質チェック（オプション）
        if self.check_quality and self.quality_checker:
            quality_result = self.quality_checker(
                response=depth1_result.organized_thought,
                original_question=question,
            )
            output.has_assertion = quality_result.has_assertion
            output.has_repetition = quality_result.has_repetition
            output.is_focused = quality_result.is_focused
            output.quality_score = quality_result.quality_score

        return output
