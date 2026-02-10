"""
Phase 4: DSPy Signatures

Depth1の出力品質を最適化するためのSignature定義。
DSPy 3.x API対応。
"""

import dspy


class Depth1Organizer(dspy.Signature):
    """
    Depth1での整理・確認の品質を最適化

    入力:
    - question: ユーザーの質問
    - context: 会話コンテキスト
    - uncertainty: 核心的な不確実性

    出力:
    - organized_thought: 整理された思考（断定を避ける）
    - clarification: 確認質問（1つの不確実性に焦点）
    """

    # 入力フィールド
    question = dspy.InputField(
        desc="ユーザーの質問または発話"
    )
    context = dspy.InputField(
        desc="会話コンテキスト（過去のやり取り）"
    )
    uncertainty = dspy.InputField(
        desc="核心的な不確実性（何が明確でないか）"
    )

    # 出力フィールド
    organized_thought = dspy.OutputField(
        desc="整理された思考（断定を避け、不確実性を明示）"
    )
    clarification = dspy.OutputField(
        desc="確認質問（1つの不確実性に焦点を当てる、不要なら空文字）"
    )


class UncertaintyExtractor(dspy.Signature):
    """
    テキストから核心的な不確実性を抽出

    例:
    「AとBのどちらを優先すべきか、まだ決めかねています。」
    → 「A vs B の優先順位」
    """

    text = dspy.InputField(
        desc="分析対象のテキスト"
    )
    context = dspy.InputField(
        desc="会話コンテキスト",
        default=""
    )

    uncertainties = dspy.OutputField(
        desc="抽出された不確実性のリスト（最大3つ）"
    )
    primary_uncertainty = dspy.OutputField(
        desc="最も重要な不確実性（1つ）"
    )


class ResponseQualityChecker(dspy.Signature):
    """
    レスポンスの品質をチェック

    以下の観点で評価:
    - 断定の有無
    - 反復の有無
    - 焦点の明確さ
    """

    response = dspy.InputField(
        desc="評価対象のレスポンス"
    )
    original_question = dspy.InputField(
        desc="元の質問"
    )

    has_assertion = dspy.OutputField(
        desc="断定的な表現が含まれているか（true/false）"
    )
    has_repetition = dspy.OutputField(
        desc="不要な反復があるか（true/false）"
    )
    is_focused = dspy.OutputField(
        desc="焦点が明確か（true/false）"
    )
    quality_score = dspy.OutputField(
        desc="品質スコア（0.0-1.0の数値）"
    )
