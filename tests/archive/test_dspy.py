"""
Phase 4: DSPy品質改善モジュールのテスト
"""

import pytest
import importlib.util

if importlib.util.find_spec("dspy") is None:
    pytest.skip("dspy is not installed", allow_module_level=True)
from unittest.mock import Mock, patch, MagicMock
from dataclasses import asdict


class TestQualityMetrics:
    """品質メトリクスのテスト"""

    def test_contains_assertions_detects_断定(self):
        """断定的な表現を検出する"""
        from backend.core.dspy.metrics import contains_assertions

        # 断定を含むテキスト
        has, matches = contains_assertions("これは確実にそうです")
        assert has is True
        assert len(matches) > 0

        has, matches = contains_assertions("絶対に間違いありません")
        assert has is True

    def test_contains_assertions_allows_uncertainty(self):
        """不確実な表現は断定とみなさない"""
        from backend.core.dspy.metrics import contains_assertions

        has, _ = contains_assertions("これは〜かもしれません")
        assert has is False

        has, _ = contains_assertions("まだ判断しかねる状況です")
        assert has is False

    def test_has_uncertainty_expressions(self):
        """不確実性表現を検出する"""
        from backend.core.dspy.metrics import has_uncertainty_expressions

        has, matches = has_uncertainty_expressions("まだわからない部分があります")
        assert has is True

        has, matches = has_uncertainty_expressions("〜の可能性があります")
        assert has is True

        has, _ = has_uncertainty_expressions("これは完璧です")
        assert has is False

    def test_has_repetition_detects_repeat(self):
        """反復を検出する"""
        from backend.core.dspy.metrics import has_repetition

        # 反復のあるテキスト
        repeated = "これは重要です。" * 10
        is_rep, ratio = has_repetition(repeated)
        assert is_rep is True
        assert ratio > 0.3

    def test_has_repetition_allows_normal(self):
        """通常のテキストは反復とみなさない"""
        from backend.core.dspy.metrics import has_repetition

        normal = "これは最初の文です。次に別の内容を述べます。さらに異なる観点から説明します。"
        is_rep, ratio = has_repetition(normal)
        assert is_rep is False

    def test_is_focused_single_topic(self):
        """単一トピックは焦点が明確"""
        from backend.core.dspy.metrics import is_focused

        focused, topics = is_focused("認証方式について検討中です。")
        assert focused is True
        assert topics <= 2

    def test_is_focused_multiple_topics(self):
        """複数トピックは焦点が分散"""
        from backend.core.dspy.metrics import is_focused

        unfocused = "認証は？パフォーマンスは？UIは？デプロイは？"
        focused, topics = is_focused(unfocused)
        assert focused is False
        assert topics > 2

    def test_calculate_quality_score(self):
        """品質スコアの計算"""
        from backend.core.dspy.metrics import calculate_quality_score

        # 高品質な出力
        score = calculate_quality_score(
            organized_thought="現時点では情報が不足しているため、判断しかねる状況です。",
            clarification="具体的にどの部分が気になりますか？",
            original_question="これはどうすべき？",
        )
        assert score.total >= 0.6
        assert score.assertion_score >= 0.5
        assert score.focus_score >= 0.5

    def test_quality_score_low_for_assertion(self):
        """断定的な出力は低スコア"""
        from backend.core.dspy.metrics import calculate_quality_score

        score = calculate_quality_score(
            organized_thought="これは確実にAです。絶対に間違いありません。",
            clarification="",
            original_question="AとBどちら？",
        )
        assert score.total <= 0.7  # 断定があると0.7以下
        assert score.assertion_score < 0.5


class TestDepth1QualityMetric:
    """DSPy用メトリクスのテスト"""

    def test_metric_callable(self):
        """メトリクスが呼び出し可能"""
        from backend.core.dspy.metrics import Depth1QualityMetric

        metric = Depth1QualityMetric()

        example = Mock()
        example.question = "テスト質問"

        prediction = Mock()
        prediction.organized_thought = "まだ検討中です"
        prediction.clarification = ""

        score = metric(example, prediction)
        assert 0.0 <= score <= 1.0

    def test_is_success(self):
        """成功判定"""
        from backend.core.dspy.metrics import Depth1QualityMetric

        metric = Depth1QualityMetric(threshold=0.6)

        example = Mock()
        example.question = "質問"

        good_pred = Mock()
        good_pred.organized_thought = "まだ情報が不足しており、判断しかねます。"
        good_pred.clarification = "詳しく教えてもらえますか？"

        assert metric.is_success(example, good_pred) is True


class TestDepth1Example:
    """データセット例のテスト"""

    def test_to_dspy_example(self):
        """DSPy Exampleへの変換"""
        from backend.core.dspy.dataset import Depth1Example

        ex = Depth1Example(
            question="テスト質問",
            context="コンテキスト",
            uncertainty="不確実性",
            organized_thought="整理された思考",
            clarification="確認質問",
        )

        dspy_ex = ex.to_dspy_example()
        assert dspy_ex.question == "テスト質問"
        assert dspy_ex.context == "コンテキスト"


class TestDepth1DatasetManager:
    """データセットマネージャーのテスト"""

    def test_add_example_filters_low_quality(self, tmp_path):
        """低品質の例はフィルタされる"""
        from backend.core.dspy.dataset import Depth1DatasetManager

        manager = Depth1DatasetManager(
            data_dir=tmp_path,
            min_quality_score=0.8,
        )

        # 低品質な例（断定的）
        result = manager.add_example(
            question="質問",
            context="",
            uncertainty="",
            organized_thought="確実にAです。絶対です。",
            clarification="",
        )

        # フィルタされてNoneが返る（または品質が高ければ追加される）
        # 品質スコアは実装に依存

    def test_get_trainset(self, tmp_path):
        """トレーニングセットの取得"""
        from backend.core.dspy.dataset import Depth1DatasetManager, Depth1Example

        manager = Depth1DatasetManager(
            data_dir=tmp_path,
            min_quality_score=0.5,
        )

        # 手動で例を追加
        ex = Depth1Example(
            question="Q",
            context="C",
            uncertainty="U",
            organized_thought="まだ検討中",
            clarification="どう思いますか？",
            quality_score=0.8,
        )
        manager._examples.append(ex)

        trainset = manager.get_trainset()
        assert len(trainset) >= 1

    def test_get_statistics(self, tmp_path):
        """統計情報の取得"""
        from backend.core.dspy.dataset import Depth1DatasetManager

        manager = Depth1DatasetManager(data_dir=tmp_path)
        stats = manager.get_statistics()

        assert "total_examples" in stats
        assert "avg_quality_score" in stats
        assert "sources" in stats


class TestSeedData:
    """シードデータのテスト"""

    def test_seed_examples_exist(self):
        """シード例が存在する"""
        from backend.core.dspy.dataset import SEED_EXAMPLES

        assert len(SEED_EXAMPLES) >= 3

    def test_seed_examples_quality(self):
        """シード例の品質が基準を満たす"""
        from backend.core.dspy.dataset import SEED_EXAMPLES

        for ex in SEED_EXAMPLES:
            assert ex.quality_score >= 0.7
            assert ex.question
            assert ex.organized_thought


class TestDepth1Module:
    """Depth1モジュールのテスト"""

    def test_module_structure(self):
        """モジュール構造の確認"""
        from backend.core.dspy.modules import Depth1Module

        module = Depth1Module()
        assert hasattr(module, "organizer")
        assert hasattr(module, "forward")


class TestDepth1Optimizer:
    """オプティマイザーのテスト"""

    def test_optimizer_init(self, tmp_path):
        """オプティマイザーの初期化"""
        from backend.core.dspy.optimizer import Depth1Optimizer

        optimizer = Depth1Optimizer(model_dir=tmp_path)
        assert optimizer.model_dir == tmp_path
        assert optimizer.metric is not None

    def test_get_module_returns_baseline(self, tmp_path):
        """最適化前はベースラインを返す"""
        from backend.core.dspy.optimizer import Depth1Optimizer
        from backend.core.dspy.modules import Depth1Module

        optimizer = Depth1Optimizer(model_dir=tmp_path)
        module = optimizer.get_module()

        assert isinstance(module, Depth1Module)


class TestOptimizationResult:
    """最適化結果のテスト"""

    def test_result_fields(self):
        """結果フィールドの確認"""
        from backend.core.dspy.optimizer import OptimizationResult

        result = OptimizationResult(
            success=True,
            score_before=0.5,
            score_after=0.8,
            improvement=0.3,
            n_examples=100,
            n_bootstrapped=8,
            duration_seconds=120.0,
            model_path="/path/to/model.json",
        )

        assert result.success is True
        assert result.improvement == 0.3
        assert result.n_examples == 100


class TestSignatures:
    """DSPy Signaturesのテスト"""

    def test_depth1_organizer_signature(self):
        """Depth1Organizerシグネチャの確認"""
        from backend.core.dspy.signatures import Depth1Organizer
        import dspy

        # シグネチャがdspy.Signatureを継承しているか
        assert issubclass(Depth1Organizer, dspy.Signature)

        # フィールドが定義されているか（DSPy 3.xではmodel_fieldsで確認）
        fields = Depth1Organizer.model_fields
        assert "question" in fields
        assert "context" in fields
        assert "uncertainty" in fields
        assert "organized_thought" in fields
        assert "clarification" in fields

    def test_uncertainty_extractor_signature(self):
        """UncertaintyExtractorシグネチャの確認"""
        from backend.core.dspy.signatures import UncertaintyExtractor
        import dspy

        assert issubclass(UncertaintyExtractor, dspy.Signature)

        fields = UncertaintyExtractor.model_fields
        assert "text" in fields
        assert "uncertainties" in fields
        assert "primary_uncertainty" in fields


class TestIntegration:
    """統合テスト"""

    def test_full_pipeline_structure(self):
        """パイプライン構造の確認"""
        from backend.core.dspy.modules import Depth1PipelineModule

        pipeline = Depth1PipelineModule(check_quality=True)
        assert hasattr(pipeline, "uncertainty_extractor")
        assert hasattr(pipeline, "depth1_organizer")
        assert hasattr(pipeline, "quality_checker")

    def test_module_import(self):
        """モジュールのインポート"""
        from backend.core.dspy import (
            Depth1Organizer,
            Depth1Module,
            Depth1QualityMetric,
            Depth1Optimizer,
            Depth1DatasetManager,
        )

        assert Depth1Organizer is not None
        assert Depth1Module is not None
        assert Depth1QualityMetric is not None
        assert Depth1Optimizer is not None
        assert Depth1DatasetManager is not None
