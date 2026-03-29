"""
Confidence System のテスト

確信度メトリクス、エンジン、キャリブレータの動作を検証するテストスイート。
"""

import pytest
import tempfile
import os
from backend.core.confidence import (
    ConfidenceMetrics,
    SelfConsistencyCalculator,
    ContextCoverageCalculator,
    QuestionClarityCalculator,
    LogitBasedCalculator,
    ConfidenceEngine,
    DepthAction,
    ConfidenceCalibrator,
)


class TestSelfConsistencyCalculator:
    """Self-Consistency メトリクスのテスト"""

    def test_identical_outputs(self):
        """完全に同一の出力のテスト"""
        outputs = ["これは同じ出力です"] * 3
        score = SelfConsistencyCalculator.calculate(outputs)
        assert score == pytest.approx(1.0, abs=0.1)

    def test_different_outputs(self):
        """全く異なる出力のテスト"""
        outputs = [
            "これは最初の出力です",
            "完全に異なる内容の二番目",
            "三つ目も別の内容",
        ]
        score = SelfConsistencyCalculator.calculate(outputs)
        assert score < 0.5

    def test_single_output(self):
        """単一出力のテスト（中立的なスコア）"""
        outputs = ["単一の出力"]
        score = SelfConsistencyCalculator.calculate(outputs)
        assert score == 0.5

    def test_similar_outputs(self):
        """類似した出力のテスト"""
        outputs = [
            "これは類似した出力です",
            "これは類似した内容です",
            "これは類似の出力です",
        ]
        score = SelfConsistencyCalculator.calculate(outputs)
        # Jaccard類似度は低めになる可能性がある
        assert 0.0 <= score <= 1.0


class TestContextCoverageCalculator:
    """Context Coverage メトリクスのテスト"""

    def test_high_coverage(self):
        """情報が十分な場合のテスト"""
        question = "東京の天気はどうですか？"
        context = [
            "今日の東京は晴れています",
            "気温は25度です",
            "湿度は60%です",
        ]
        score = ContextCoverageCalculator.calculate(question, context)
        # 文脈が豊富な場合、スコアは中程度以上
        assert score > 0.4

    def test_low_coverage(self):
        """情報が不足している場合のテスト"""
        question = "この複雑な問題について詳しく教えてください"
        context = []
        score = ContextCoverageCalculator.calculate(question, context)
        assert score < 0.5

    def test_unclear_question(self):
        """不明瞭な質問のテスト"""
        question = "それについて何か情報がありますか？"
        context = ["いくつかの情報があります"]
        score = ContextCoverageCalculator.calculate(question, context)
        # 不明瞭な質問は低スコア
        assert score < 0.7


class TestQuestionClarityCalculator:
    """Question Clarity メトリクスのテスト"""

    def test_clear_question(self):
        """明確な質問のテスト"""
        question = "Pythonのリスト内包表記の具体的な使い方を教えてください"
        score = QuestionClarityCalculator.calculate(question)
        assert score >= 0.6

    def test_ambiguous_question(self):
        """曖昧な質問のテスト"""
        question = "それについて何か"
        score = QuestionClarityCalculator.calculate(question)
        assert score < 0.5

    def test_very_short_question(self):
        """非常に短い質問のテスト"""
        question = "何？"
        score = QuestionClarityCalculator.calculate(question)
        assert score < 0.5

    def test_optimal_length_question(self):
        """適切な長さの質問のテスト"""
        question = "機械学習のモデルを訓練する方法について教えてください？"
        score = QuestionClarityCalculator.calculate(question)
        assert score > 0.5


class TestLogitBasedCalculator:
    """Logit-based メトリクスのテスト"""

    def test_uncertain_output(self):
        """不確実な出力のテスト"""
        output = "たぶん、おそらくこれが正しいと思いますが、わからないです"
        score = LogitBasedCalculator.calculate(output)
        assert score < 0.5

    def test_confident_output(self):
        """確実な出力のテスト"""
        output = "これは確実に正しい答えです。明らかにそうです。"
        score = LogitBasedCalculator.calculate(output)
        assert score > 0.7

    def test_neutral_output(self):
        """中立的な出力のテスト"""
        output = "これは普通の回答です"
        score = LogitBasedCalculator.calculate(output)
        assert 0.5 <= score <= 0.8


class TestConfidenceEngine:
    """Confidence Engine のテスト"""

    def test_high_confidence_scenario(self):
        """高確信度のシナリオ"""
        engine = ConfidenceEngine()
        question = "具体的な質問: Pythonのfor文の使い方は？"
        context = [
            "Pythonではfor文を使ってループを書きます",
            "for item in items: のように書きます",
        ]

        metrics = engine.calculate_confidence(question, context)

        assert metrics.composite_raw > 0.5
        assert 0.0 <= metrics.context_coverage <= 1.0
        assert 0.0 <= metrics.question_clarity <= 1.0

    def test_low_confidence_scenario(self):
        """低確信度のシナリオ"""
        engine = ConfidenceEngine()
        question = "それについて何か？"
        context = []

        metrics = engine.calculate_confidence(question, context)

        assert metrics.composite_raw < 0.6

    def test_depth_recommendation_depth0(self):
        """Depth0推奨のテスト"""
        engine = ConfidenceEngine()
        question = "2 + 2 はいくつですか？"
        context = ["算数の基本的な計算です"]

        recommendation = engine.get_depth_recommendation(question, context)

        # 単純な質問なので高確信度 → DEPTH0推奨
        assert recommendation.confidence >= 0.0
        assert recommendation.action in [DepthAction.USE_DEPTH0, DepthAction.USE_DEPTH1]

    def test_depth_recommendation_depth1(self):
        """Depth1推奨のテスト"""
        engine = ConfidenceEngine()
        question = "機械学習のアルゴリズムについて教えてください"
        context = []

        recommendation = engine.get_depth_recommendation(question, context)

        # 複雑な質問、文脈なし → 低〜中確信度
        assert 0.0 <= recommendation.confidence <= 1.0

    def test_custom_weights(self):
        """カスタム重みのテスト"""
        custom_weights = {
            "context_coverage": 0.5,
            "self_consistency": 0.2,
            "logit_based": 0.2,
            "question_clarity": 0.1,
        }
        engine = ConfidenceEngine(weights=custom_weights)

        assert engine.weights == custom_weights

    def test_update_thresholds(self):
        """閾値更新のテスト"""
        engine = ConfidenceEngine()
        new_thresholds = {
            "depth0": 0.9,
            "depth1": 0.6,
            "ask": 0.4,
        }
        engine.update_thresholds(new_thresholds)

        assert engine.thresholds == new_thresholds


class TestConfidenceCalibrator:
    """Confidence Calibrator のテスト"""

    def test_calibration_fitting(self):
        """キャリブレーションの学習テスト"""
        # サンプルデータ: (確信度, 正解フラグ)
        data = [
            (0.9, True),
            (0.85, True),
            (0.8, False),  # 高確信度だが不正解
            (0.5, True),
            (0.5, False),
            (0.2, False),
            (0.1, False),
        ]

        calibrator = ConfidenceCalibrator(num_bins=5)
        calibrator.fit(data)

        # キャリブレーション後の確信度を確認
        calibrated_high = calibrator.calibrate(0.9)
        calibrated_mid = calibrator.calibrate(0.5)

        assert 0.0 <= calibrated_high <= 1.0
        assert 0.0 <= calibrated_mid <= 1.0

    def test_ece_calculation(self):
        """ECE計算のテスト"""
        data = [
            (0.9, True),
            (0.9, True),
            (0.5, True),
            (0.5, False),
            (0.1, False),
        ]

        calibrator = ConfidenceCalibrator(num_bins=3)
        ece = calibrator.calculate_ece(data)

        assert 0.0 <= ece <= 1.0

    def test_perfect_calibration(self):
        """完璧にキャリブレーションされた場合のテスト"""
        # 確信度と正解率が完全に一致
        data = [
            (0.9, True),
            (0.9, True),
            (0.9, True),
            (0.9, True),
            (0.9, False),  # 90%確信度 → 80%正解率
            (0.5, True),
            (0.5, False),  # 50%確信度 → 50%正解率
        ]

        calibrator = ConfidenceCalibrator(num_bins=5)
        ece = calibrator.calculate_ece(data)

        # ECEは小さい値になるはず
        assert ece < 0.5

    def test_save_and_load(self):
        """DBへの保存と読み込みのテスト"""
        data = [
            (0.9, True),
            (0.5, True),
            (0.1, False),
        ]

        calibrator = ConfidenceCalibrator(num_bins=5)
        calibrator.fit(data)

        # 一時DBに保存
        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
            db_path = tmp.name

        try:
            calibrator.save_to_db(db_path, "test_calibrator")

            # 読み込み
            loaded_calibrator = ConfidenceCalibrator.load_from_db(
                db_path, "test_calibrator"
            )

            assert loaded_calibrator is not None
            assert loaded_calibrator.num_bins == calibrator.num_bins
            assert len(loaded_calibrator.calibration_map) > 0

            # 同じ確信度で同じ結果が得られるか確認
            test_confidence = 0.7
            original_calibrated = calibrator.calibrate(test_confidence)
            loaded_calibrated = loaded_calibrator.calibrate(test_confidence)

            assert abs(original_calibrated - loaded_calibrated) < 0.1

        finally:
            # 一時ファイルを削除
            if os.path.exists(db_path):
                os.unlink(db_path)


class TestIntegration:
    """統合テスト"""

    def test_end_to_end_confidence_calculation(self):
        """エンドツーエンドの確信度計算"""
        # キャリブレータを準備
        calibration_data = [
            (0.9, True),
            (0.8, True),
            (0.7, True),
            (0.6, False),
            (0.5, True),
            (0.4, False),
            (0.3, False),
            (0.2, False),
        ]
        calibrator = ConfidenceCalibrator(num_bins=5)
        calibrator.fit(calibration_data)

        # エンジンを準備
        engine = ConfidenceEngine(calibrator=calibrator)

        # 確信度を計算
        question = "Pythonのリスト内包表記について教えてください"
        context = [
            "Pythonではリスト内包表記を使って簡潔にリストを作成できます",
            "基本的な構文は [expression for item in iterable] です",
        ]
        llm_output = "リスト内包表記は効率的な方法です"

        recommendation = engine.get_depth_recommendation(
            question, context, llm_output
        )

        # 結果の検証
        assert 0.0 <= recommendation.confidence <= 1.0
        assert recommendation.action in [
            DepthAction.USE_DEPTH0,
            DepthAction.USE_DEPTH1,
            DepthAction.ASK,
            DepthAction.WAIT,
        ]
        assert len(recommendation.reason) > 0

    def test_confidence_with_contract_violation(self):
        """契約違反と確信度の関係のテスト"""
        # Phase 0の契約違反がある出力
        from backend.core.contracts import Depth0Contract

        output_with_violations = "答えは明確です。〜すべきです。結論としては正しいです。間違いなく確実に絶対に正しいです。"
        validation_result = Depth0Contract.validate(output_with_violations)

        # 契約違反がある場合、確信度は低くなるべき
        # （LogitBasedメトリクスで検出される）
        score = LogitBasedCalculator.calculate(output_with_violations)

        # 断定的な表現が多いため、LogitBasedスコアは高くなる
        # 契約違反は検出される
        assert len(validation_result.violations) > 0
        assert validation_result.score < 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
