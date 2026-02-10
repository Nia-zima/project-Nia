"""
Phase 4: DSPyオプティマイザー

BootstrapFewShotを使用してDepth1の出力品質を最適化。
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import dspy

from backend.core.dspy.modules import Depth1Module
from backend.core.dspy.metrics import Depth1QualityMetric, QualityScore
from backend.core.dspy.dataset import Depth1DatasetManager, get_dataset_manager

logger = logging.getLogger(__name__)


@dataclass
class OptimizationResult:
    """最適化結果"""

    success: bool
    score_before: float
    score_after: float
    improvement: float
    n_examples: int
    n_bootstrapped: int
    duration_seconds: float
    model_path: Optional[str] = None
    error: Optional[str] = None


class Depth1Optimizer:
    """
    Depth1モジュールの最適化器

    BootstrapFewShotを使用して、少数の例から
    高品質な出力を生成するためのプロンプトを学習します。
    """

    def __init__(
        self,
        model_dir: Optional[Path] = None,
        metric: Optional[Depth1QualityMetric] = None,
    ):
        """
        Args:
            model_dir: モデル保存ディレクトリ
            metric: 品質メトリクス
        """
        if model_dir is None:
            from backend.core.config import settings
            model_dir = settings.PROJECT_ROOT / "models" / "dspy"

        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)

        self.metric = metric or Depth1QualityMetric()
        self._optimized_module: Optional[Depth1Module] = None

    def optimize(
        self,
        trainset: Optional[list[dspy.Example]] = None,
        max_bootstrapped_demos: int = 8,
        max_labeled_demos: int = 4,
        num_candidate_programs: int = 10,
    ) -> OptimizationResult:
        """
        Depth1モジュールを最適化

        Args:
            trainset: トレーニングセット（Noneの場合はデータセットマネージャーから取得）
            max_bootstrapped_demos: 最大ブートストラップデモ数
            max_labeled_demos: 最大ラベル付きデモ数
            num_candidate_programs: 候補プログラム数

        Returns:
            OptimizationResult
        """
        import time
        start_time = time.time()

        try:
            # データセットの取得
            if trainset is None:
                dataset_manager = get_dataset_manager()
                trainset = dataset_manager.get_trainset()

            if len(trainset) < 3:
                return OptimizationResult(
                    success=False,
                    score_before=0.0,
                    score_after=0.0,
                    improvement=0.0,
                    n_examples=len(trainset),
                    n_bootstrapped=0,
                    duration_seconds=time.time() - start_time,
                    error="Not enough training examples (minimum 3 required)",
                )

            # ベースラインモジュール
            base_module = Depth1Module()

            # ベースラインスコアの計算
            score_before = self._evaluate_module(base_module, trainset)
            logger.info(f"Baseline score: {score_before:.4f}")

            # オプティマイザーの設定
            optimizer = dspy.BootstrapFewShot(
                metric=self.metric,
                max_bootstrapped_demos=max_bootstrapped_demos,
                max_labeled_demos=max_labeled_demos,
            )

            # 最適化実行
            optimized_module = optimizer.compile(
                base_module,
                trainset=trainset,
            )

            # 最適化後のスコア
            score_after = self._evaluate_module(optimized_module, trainset)
            logger.info(f"Optimized score: {score_after:.4f}")

            # モジュールを保存
            model_path = self._save_module(optimized_module)
            self._optimized_module = optimized_module

            improvement = score_after - score_before
            duration = time.time() - start_time

            return OptimizationResult(
                success=True,
                score_before=score_before,
                score_after=score_after,
                improvement=improvement,
                n_examples=len(trainset),
                n_bootstrapped=max_bootstrapped_demos,
                duration_seconds=duration,
                model_path=str(model_path),
            )

        except Exception as e:
            logger.error(f"Optimization failed: {e}")
            return OptimizationResult(
                success=False,
                score_before=0.0,
                score_after=0.0,
                improvement=0.0,
                n_examples=len(trainset) if trainset else 0,
                n_bootstrapped=0,
                duration_seconds=time.time() - start_time,
                error=str(e),
            )

    def _evaluate_module(
        self,
        module: Depth1Module,
        examples: list[dspy.Example],
    ) -> float:
        """モジュールを評価"""
        if not examples:
            return 0.0

        scores = []
        for example in examples:
            try:
                prediction = module(
                    question=example.question,
                    context=example.context,
                    uncertainty=example.uncertainty,
                )
                score = self.metric(example, prediction)
                scores.append(score)
            except Exception as e:
                logger.warning(f"Evaluation failed for example: {e}")
                scores.append(0.0)

        return sum(scores) / len(scores) if scores else 0.0

    def _save_module(self, module: Depth1Module) -> Path:
        """モジュールを保存"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        model_path = self.model_dir / f"depth1_optimized_{timestamp}.json"

        module.save(str(model_path))
        logger.info(f"Saved optimized module to {model_path}")

        # 最新モデルへのシンボリックリンク的な参照を保存
        latest_path = self.model_dir / "depth1_latest.json"
        with open(latest_path, "w") as f:
            json.dump({"path": str(model_path), "timestamp": timestamp}, f)

        return model_path

    def load_optimized(
        self,
        model_path: Optional[Path] = None,
    ) -> Optional[Depth1Module]:
        """
        最適化されたモジュールを読み込み

        Args:
            model_path: モデルパス（Noneの場合は最新を使用）

        Returns:
            最適化されたモジュール
        """
        if model_path is None:
            latest_path = self.model_dir / "depth1_latest.json"
            if not latest_path.exists():
                logger.warning("No optimized model found")
                return None

            with open(latest_path, "r") as f:
                data = json.load(f)
                model_path = Path(data["path"])

        if not model_path.exists():
            logger.warning(f"Model not found: {model_path}")
            return None

        try:
            module = Depth1Module()
            module.load(str(model_path))
            self._optimized_module = module
            logger.info(f"Loaded optimized module from {model_path}")
            return module
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            return None

    def get_module(self) -> Depth1Module:
        """
        使用するモジュールを取得

        最適化されたモジュールがあればそれを、なければベースラインを返す。
        """
        if self._optimized_module is not None:
            return self._optimized_module

        # 最適化モジュールの読み込みを試みる
        optimized = self.load_optimized()
        if optimized is not None:
            return optimized

        # ベースラインを返す
        return Depth1Module()

    def run_ab_test(
        self,
        testset: list[dspy.Example],
        baseline: Optional[Depth1Module] = None,
    ) -> dict:
        """
        A/Bテストを実行

        Args:
            testset: テストセット
            baseline: ベースラインモジュール（Noneの場合は新規作成）

        Returns:
            テスト結果
        """
        if baseline is None:
            baseline = Depth1Module()

        optimized = self.get_module()

        # ベースラインの評価
        baseline_scores = []
        for example in testset:
            try:
                pred = baseline(
                    question=example.question,
                    context=example.context,
                    uncertainty=example.uncertainty,
                )
                score = self.metric(example, pred)
                baseline_scores.append(score)
            except Exception:
                baseline_scores.append(0.0)

        # 最適化版の評価
        optimized_scores = []
        for example in testset:
            try:
                pred = optimized(
                    question=example.question,
                    context=example.context,
                    uncertainty=example.uncertainty,
                )
                score = self.metric(example, pred)
                optimized_scores.append(score)
            except Exception:
                optimized_scores.append(0.0)

        baseline_avg = sum(baseline_scores) / len(baseline_scores) if baseline_scores else 0.0
        optimized_avg = sum(optimized_scores) / len(optimized_scores) if optimized_scores else 0.0

        return {
            "n_examples": len(testset),
            "baseline_avg_score": baseline_avg,
            "optimized_avg_score": optimized_avg,
            "improvement": optimized_avg - baseline_avg,
            "improvement_percent": ((optimized_avg - baseline_avg) / baseline_avg * 100)
                if baseline_avg > 0 else 0.0,
            "baseline_scores": baseline_scores,
            "optimized_scores": optimized_scores,
        }


# シングルトンインスタンス
_optimizer: Optional[Depth1Optimizer] = None


def get_optimizer() -> Depth1Optimizer:
    """オプティマイザーのシングルトンを取得"""
    global _optimizer
    if _optimizer is None:
        _optimizer = Depth1Optimizer()
    return _optimizer


def configure_dspy_lm(
    model: str = "openai/gpt-4o-mini",
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
) -> None:
    """
    DSPyの言語モデルを設定

    Args:
        model: モデル名
        api_key: APIキー
        api_base: APIベースURL
    """
    from backend.core.config import settings

    if api_key is None:
        api_key = settings.OPENAI_API_KEY
    if api_base is None:
        api_base = settings.OPENAI_BASE_URL

    # DSPyのLM設定
    lm = dspy.LM(
        model=model,
        api_key=api_key,
        api_base=api_base,
    )
    dspy.configure(lm=lm)
    logger.info(f"Configured DSPy LM: {model}")
