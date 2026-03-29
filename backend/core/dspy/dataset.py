"""
Phase 4: DSPyトレーニングデータセット管理

Depth1の品質最適化のためのデータセット収集・管理機能。
"""

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import dspy

from backend.core.dspy.metrics import calculate_quality_score, QualityScore

logger = logging.getLogger(__name__)


@dataclass
class Depth1Example:
    """Depth1トレーニング例"""

    # 入力
    question: str
    context: str
    uncertainty: str

    # 出力（ラベル）
    organized_thought: str
    clarification: str

    # メタデータ
    thread_id: str = ""
    timestamp: str = ""
    quality_score: float = 0.0
    source: str = "manual"  # "manual", "auto", "human_labeled"

    def to_dspy_example(self) -> dspy.Example:
        """DSPy Exampleに変換"""
        return dspy.Example(
            question=self.question,
            context=self.context,
            uncertainty=self.uncertainty,
            organized_thought=self.organized_thought,
            clarification=self.clarification,
        ).with_inputs("question", "context", "uncertainty")


class Depth1DatasetManager:
    """
    Depth1トレーニングデータセットの管理

    機能:
    - データの収集・追加
    - データの保存・読み込み
    - 品質フィルタリング
    - DSPy形式への変換
    """

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        min_quality_score: float = 0.6,
    ):
        """
        Args:
            data_dir: データ保存ディレクトリ
            min_quality_score: 最小品質スコア（これ以上のデータのみ使用）
        """
        if data_dir is None:
            from backend.core.config import settings
            data_dir = settings.PROJECT_ROOT / "data" / "dspy_training"

        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.min_quality_score = min_quality_score

        self._examples: list[Depth1Example] = []
        self._load_existing()

    def _load_existing(self) -> None:
        """既存のデータを読み込み"""
        data_file = self.data_dir / "depth1_examples.jsonl"
        if not data_file.exists():
            return

        try:
            with open(data_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        data = json.loads(line)
                        self._examples.append(Depth1Example(**data))
            logger.info(f"Loaded {len(self._examples)} examples from {data_file}")
        except Exception as e:
            logger.error(f"Failed to load existing data: {e}")

    def add_example(
        self,
        question: str,
        context: str,
        uncertainty: str,
        organized_thought: str,
        clarification: str,
        thread_id: str = "",
        source: str = "auto",
    ) -> Optional[Depth1Example]:
        """
        新しい例を追加

        Args:
            question: ユーザーの質問
            context: 会話コンテキスト
            uncertainty: 核心的な不確実性
            organized_thought: 整理された思考
            clarification: 確認質問
            thread_id: スレッドID
            source: データソース

        Returns:
            追加された例（品質基準を満たさない場合はNone）
        """
        # 品質スコアを計算
        quality = calculate_quality_score(
            organized_thought=organized_thought,
            clarification=clarification,
            original_question=question,
        )

        # 品質基準を満たさない場合はスキップ
        if quality.total < self.min_quality_score:
            logger.debug(
                f"Example skipped: quality={quality.total:.2f} < {self.min_quality_score}"
            )
            return None

        example = Depth1Example(
            question=question,
            context=context,
            uncertainty=uncertainty,
            organized_thought=organized_thought,
            clarification=clarification,
            thread_id=thread_id,
            timestamp=datetime.now().isoformat(),
            quality_score=quality.total,
            source=source,
        )

        self._examples.append(example)
        self._append_to_file(example)

        logger.info(f"Added example: quality={quality.total:.2f}, source={source}")
        return example

    def _append_to_file(self, example: Depth1Example) -> None:
        """ファイルに追記"""
        data_file = self.data_dir / "depth1_examples.jsonl"
        try:
            with open(data_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(example), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"Failed to append example: {e}")

    def get_trainset(
        self,
        min_quality: Optional[float] = None,
        max_examples: Optional[int] = None,
    ) -> list[dspy.Example]:
        """
        トレーニングセットを取得

        Args:
            min_quality: 最小品質スコア（デフォルトはインスタンス設定）
            max_examples: 最大例数

        Returns:
            DSPy Exampleのリスト
        """
        min_q = min_quality or self.min_quality_score

        filtered = [
            ex for ex in self._examples
            if ex.quality_score >= min_q
        ]

        # スコアの高い順にソート
        filtered.sort(key=lambda x: x.quality_score, reverse=True)

        if max_examples:
            filtered = filtered[:max_examples]

        return [ex.to_dspy_example() for ex in filtered]

    def get_devset(
        self,
        ratio: float = 0.2,
        min_quality: Optional[float] = None,
    ) -> list[dspy.Example]:
        """
        開発セット（検証用）を取得

        Args:
            ratio: 全体に対する割合
            min_quality: 最小品質スコア

        Returns:
            DSPy Exampleのリスト
        """
        all_examples = self.get_trainset(min_quality=min_quality)
        dev_size = max(1, int(len(all_examples) * ratio))
        return all_examples[-dev_size:]  # 最新のものを検証に使用

    def collect_from_logs(
        self,
        db_path: Optional[Path] = None,
        limit: int = 1000,
    ) -> int:
        """
        過去ログからデータを収集

        Args:
            db_path: データベースパス
            limit: 最大収集数

        Returns:
            収集した例の数
        """
        if db_path is None:
            from backend.core.config import settings
            db_path = settings.PROJECT_ROOT / "data" / "nia.sqlite3"

        if not Path(db_path).exists():
            logger.warning(f"Database not found: {db_path}")
            return 0

        # TODO: 実際のログからデータを収集する実装
        # inner_monologue_logテーブルからdepth1関連のログを抽出
        logger.info("Log collection not yet implemented")
        return 0

    def get_statistics(self) -> dict:
        """データセットの統計を取得"""
        if not self._examples:
            return {
                "total_examples": 0,
                "avg_quality_score": 0.0,
                "sources": {},
            }

        sources = {}
        for ex in self._examples:
            sources[ex.source] = sources.get(ex.source, 0) + 1

        return {
            "total_examples": len(self._examples),
            "avg_quality_score": sum(ex.quality_score for ex in self._examples) / len(self._examples),
            "min_quality_score": min(ex.quality_score for ex in self._examples),
            "max_quality_score": max(ex.quality_score for ex in self._examples),
            "sources": sources,
        }

    def export_to_json(self, output_path: Path) -> None:
        """JSON形式でエクスポート"""
        data = [asdict(ex) for ex in self._examples]
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"Exported {len(data)} examples to {output_path}")

    def import_from_json(self, input_path: Path) -> int:
        """JSON形式からインポート"""
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        count = 0
        for item in data:
            example = Depth1Example(**item)
            if example.quality_score >= self.min_quality_score:
                self._examples.append(example)
                self._append_to_file(example)
                count += 1

        logger.info(f"Imported {count} examples from {input_path}")
        return count


# シングルトンインスタンス
_dataset_manager: Optional[Depth1DatasetManager] = None


def get_dataset_manager() -> Depth1DatasetManager:
    """データセットマネージャーのシングルトンを取得"""
    global _dataset_manager
    if _dataset_manager is None:
        _dataset_manager = Depth1DatasetManager()
    return _dataset_manager


# シードデータ（初期トレーニング用）
SEED_EXAMPLES = [
    Depth1Example(
        question="この機能はどう実装すべき？",
        context="ユーザーがWebアプリの認証機能について相談中",
        uncertainty="認証方式（OAuth vs JWT vs セッション）の選択基準",
        organized_thought="認証方式の選択には、アプリケーションの要件によっていくつかの観点があります。まだ判断に必要な情報が揃っていない部分があります。",
        clarification="このアプリはモバイル対応が必要ですか？それによって適切な方式が変わってきます。",
        source="seed",
        quality_score=0.85,
    ),
    Depth1Example(
        question="パフォーマンスが遅い気がする",
        context="ユーザーがReactアプリの速度問題を報告",
        uncertainty="ボトルネックの特定（レンダリング vs API vs バンドルサイズ）",
        organized_thought="パフォーマンス問題の原因は複数の可能性があります。現時点では特定の原因を断言することは難しい状況です。",
        clarification="具体的にどの画面・操作で遅さを感じますか？",
        source="seed",
        quality_score=0.82,
    ),
    Depth1Example(
        question="このエラーが出るんだけど",
        context="ユーザーがTypeScriptのコンパイルエラーを報告",
        uncertainty="エラーの根本原因（型定義 vs ライブラリバージョン vs 設定）",
        organized_thought="このエラーメッセージからは複数の原因が考えられます。もう少し情報があると、より具体的な方向性が見えてくるかもしれません。",
        clarification="エラーが発生するファイルと、最近変更した箇所を教えてもらえますか？",
        source="seed",
        quality_score=0.80,
    ),
]


def initialize_seed_data() -> None:
    """シードデータでデータセットを初期化"""
    manager = get_dataset_manager()

    if manager.get_statistics()["total_examples"] == 0:
        for example in SEED_EXAMPLES:
            manager._examples.append(example)
            manager._append_to_file(example)
        logger.info(f"Initialized with {len(SEED_EXAMPLES)} seed examples")
