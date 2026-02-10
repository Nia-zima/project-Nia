# Phase 4: 品質改善（DSPy）

## 概要

Phase 4では、DSPyを使用してDepth1の出力品質を最適化します。
**行動ではなく品質**に専念するフェーズです。

## アーキテクチャ

```
┌─────────────────────────────────────────────────────────────┐
│                    DSPy Quality System                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │   Dataset    │    │  Bootstrap   │    │  Optimized   │  │
│  │   Manager    │───▶│   FewShot    │───▶│   Module     │  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
│         ▲                                       │          │
│         │                                       ▼          │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │    Auto      │    │   Quality    │    │   depth1_    │  │
│  │  Collection  │◀───│   Metrics    │◀───│ organize_ask │  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## コンポーネント

### 1. 品質メトリクス (`Depth1QualityMetric`)

出力品質を3つの観点で評価します。

**評価観点:**

| 観点 | 説明 | 重み |
|------|------|------|
| 断定抑制 | 断定的な表現を避けているか | 0.3 |
| 反復抑制 | 不要な反復がないか | 0.3 |
| 焦点明確 | 1つの不確実性に集中しているか | 0.4 |

**断定パターン（検出対象）:**
- `〜と思います$` - 断定的結論
- `確実に`, `絶対に` - 強い断定
- `答えは〜です` - 明確な答え

**不確実性パターン（良いパターン）:**
- `まだわからない`
- `〜かもしれない`
- `情報が足りない`

### 2. DSPy Modules

#### Depth1Organizer (Signature)

```python
from backend.core.dspy.signatures import Depth1Organizer

# 入力
question: str     # ユーザーの質問
context: str      # 会話コンテキスト
uncertainty: str  # 核心的な不確実性

# 出力
organized_thought: str  # 整理された思考
clarification: str      # 確認質問
```

#### Depth1Module

```python
from backend.core.dspy.modules import Depth1Module

module = Depth1Module()
result = module(
    question="この機能はどう実装すべき？",
    context="Webアプリの認証機能について相談中",
    uncertainty="認証方式の選択基準",
)

print(result.organized_thought)
print(result.clarification)
```

### 3. データセット管理 (`Depth1DatasetManager`)

トレーニングデータの収集・管理を行います。

**主要メソッド:**

```python
from backend.core.dspy.dataset import get_dataset_manager

manager = get_dataset_manager()

# 例の追加（自動で品質フィルタリング）
manager.add_example(
    question="質問",
    context="コンテキスト",
    uncertainty="不確実性",
    organized_thought="整理された思考",
    clarification="確認質問",
    thread_id="thread_123",
    source="auto",
)

# トレーニングセット取得
trainset = manager.get_trainset(min_quality=0.7)

# 統計情報
stats = manager.get_statistics()
```

### 4. オプティマイザー (`Depth1Optimizer`)

BootstrapFewShotを使用して最適化します。

```python
from backend.core.dspy.optimizer import get_optimizer, configure_dspy_lm

# LMの設定
configure_dspy_lm(model="openai/gpt-4o-mini")

# 最適化実行
optimizer = get_optimizer()
result = optimizer.optimize(
    max_bootstrapped_demos=8,
    max_labeled_demos=4,
)

print(f"Score: {result.score_before:.2f} → {result.score_after:.2f}")
print(f"Improvement: {result.improvement:.2f}")

# A/Bテスト
ab_result = optimizer.run_ab_test(testset)
print(f"Improvement: {ab_result['improvement_percent']:.1f}%")
```

## 設定

### DSPY_MODE

`.env`または`config.py`で設定:

| モード | 説明 |
|--------|------|
| `disabled` | DSPyを使用しない（デフォルト） |
| `enabled` | DSPyモジュールのみを使用 |
| `hybrid` | DSPy失敗時にLLMにフォールバック |

```python
# config.py
DSPY_MODE = "hybrid"
```

## テスト

### テストファイル

[tests/test_dspy.py](../tests/test_dspy.py)

### 実行方法

```bash
# Phase 4テストのみ
python -m pytest tests/test_dspy.py -v

# 全Phaseテスト
python -m pytest tests/test_contracts.py tests/test_confidence.py tests/test_depth_selector.py tests/test_policy.py tests/test_dspy.py -v
```

## 運用ガイド

### 1. データ収集フェーズ

```python
# 自動収集（DSPY_MODE=hybrid時に自動実行）
# depth1_organize_and_askが自動的にデータを収集

# 手動でシードデータ初期化
from backend.core.dspy.dataset import initialize_seed_data
initialize_seed_data()
```

### 2. 最適化フェーズ

```python
from backend.core.dspy.optimizer import get_optimizer, configure_dspy_lm
from backend.core.dspy.dataset import get_dataset_manager

# 1. LM設定
configure_dspy_lm()

# 2. データ確認
manager = get_dataset_manager()
stats = manager.get_statistics()
print(f"Training examples: {stats['total_examples']}")

# 3. 最適化（100例以上推奨）
if stats['total_examples'] >= 100:
    optimizer = get_optimizer()
    result = optimizer.optimize()

    if result.success:
        print(f"Optimization successful!")
        print(f"Model saved to: {result.model_path}")
```

### 3. デプロイフェーズ

```python
# 1. DSPY_MODE を "enabled" または "hybrid" に設定

# 2. 最適化モデルが自動で読み込まれる
```

### 4. A/Bテスト

```python
optimizer = get_optimizer()
testset = manager.get_devset(ratio=0.2)

ab_result = optimizer.run_ab_test(testset)
print(f"Baseline: {ab_result['baseline_avg_score']:.2f}")
print(f"Optimized: {ab_result['optimized_avg_score']:.2f}")
print(f"Improvement: {ab_result['improvement_percent']:.1f}%")
```

## 成功指標

| 指標 | 目標 |
|------|------|
| 品質スコア | > 0.8 |
| 断定抑制率 | > 90% |
| 反復抑制率 | > 95% |
| 焦点明確率 | > 85% |
| A/Bテスト改善 | > 5% |

## ファイル構成

```
backend/core/dspy/
├── __init__.py         # エクスポート
├── signatures.py       # DSPy Signatures
├── modules.py          # DSPy Modules
├── metrics.py          # 品質メトリクス
├── dataset.py          # データセット管理
└── optimizer.py        # オプティマイザー

data/dspy_training/
└── depth1_examples.jsonl  # トレーニングデータ

models/dspy/
├── depth1_optimized_*.json  # 最適化モデル
└── depth1_latest.json       # 最新モデル参照
```

## 次のステップ（Phase 5）

Phase 5では身体I/F（アクション統合）を実装:

- アクションゲートの実装
- Depth0/1の原則を保ちながら物理的アクションを統合
- リスク評価と確認フロー

詳細は [ROADMAP_INTEGRATED.md](./ROADMAP_INTEGRATED.md) を参照。
