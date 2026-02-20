# Phase 3: 方策学習（Gymnasium）

## 概要

Phase 3では、Gymnasium環境と方策学習システムを実装し、「いつDepth0/1を使うか」を学習で最適化します。

## アーキテクチャ

```
┌─────────────────────────────────────────────────────────────┐
│                    Policy Learning System                    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │ Gymnasium    │    │  Experience  │    │   Policy     │  │
│  │ Environment  │───▶│  Collector   │───▶│   Learner    │  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
│         ▲                   │                   │          │
│         │                   ▼                   ▼          │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │    Human     │    │   Offline    │    │   depth_     │  │
│  │   Feedback   │───▶│   Storage    │◀───│   selector   │  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## コンポーネント

### 1. Gymnasium環境 (`DepthSelectionEnv`)

Depth選択の学習環境を提供します。

**状態空間（8次元）:**

| 次元 | 説明 | 範囲 |
|------|------|------|
| context_coverage | 情報充足度 | 0.0-1.0 |
| self_consistency | 一貫性 | 0.0-1.0 |
| logit_based | トークン確率 | 0.0-1.0 |
| question_clarity | 質問明瞭度 | 0.0-1.0 |
| dissonance | 矛盾スコア | 0.0-1.0 |
| has_user_request | ユーザーリクエスト | 0 or 1 |
| has_contrast | 対比表現 | 0 or 1 |
| turn_count | ターン数（正規化） | 0.0-1.0 |

**行動空間（4つ）:**

| ID | アクション | 説明 |
|----|-----------|------|
| 0 | DEPTH0 | 即答モード |
| 1 | DEPTH1 | 整理・質問モード |
| 2 | ASK | 確認質問 |
| 3 | WAIT | 保留 |

**報酬設計:**

| 条件 | 報酬 |
|------|------|
| 適切なDepth選択 | +1.0 |
| ユーザー満足（高） | +0.5 × satisfaction |
| 会話効率（3-5ターン） | +0.3 |
| 不適切な選択 | -0.5 |
| ユーザー不満 | -0.3 |

### 2. 経験収集 (`ExperienceCollector`)

Offline RL用の経験データを収集・管理します。

**主要メソッド:**

```python
from backend.core.policy import ExperienceCollector

collector = ExperienceCollector(buffer_size=10000)

# 経験を収集
exp = collector.collect(
    confidence_metrics={"context_coverage": 0.7, ...},
    dissonance=0.3,
    reason_codes=["user_request"],
    action=1,
    action_name="depth1",
    thread_id="thread_123",
    turn_count=2,
)

# 報酬を付与
collector.assign_reward(0.8, user_satisfaction=0.9)

# エピソード終了
collector.end_episode(final_reward=0.3)

# 保存・読み込み
collector.save("experiences_20260201.jsonl")
collector.load("experiences_20260201.jsonl")
```

### 3. 方策学習 (`PolicyLearner`)

Q-learningベースの方策学習を実装。

**学習フロー:**

```python
from backend.core.policy import PolicyLearner, PolicyConfig

config = PolicyConfig(
    learning_rate=0.01,
    discount_factor=0.95,
    epsilon=0.1,
    batch_size=32,
    n_epochs=100,
)

learner = PolicyLearner(config)

# 学習
result = learner.train(collector, n_epochs=100)
print(f"Final TD Error: {result['final_td_error']:.4f}")

# 評価
eval_result = learner.evaluate(collector)
print(f"Accuracy: {eval_result['accuracy']:.2%}")

# 保存・読み込み
learner.save("policy_20260201.json")
learner.load("policy_20260201.json")
```

### 4. Human-in-the-Loop (`HumanFeedback`)

ユーザーフィードバックを収集・管理します。

**フィードバックタイプ:**

| タイプ | 報酬への変換 |
|--------|-------------|
| thumbs_up | +1.0 |
| thumbs_down | -1.0 |
| rating (1-5) | (rating - 3) / 2 |
| correction | -0.5 |

**使用例:**

```python
from backend.core.policy import HumanFeedback, FeedbackType

feedback = HumanFeedback()

# フィードバックをリクエスト
token = feedback.request_feedback(
    thread_id="thread_123",
    turn_id=1,
    context={"action": "depth1", "confidence": 0.65},
)

# ユーザーからフィードバックを受け取る
feedback.submit_thumbs_up("thread_123", 1)
# または
feedback.submit_rating("thread_123", 1, rating=4)
# または
feedback.submit_correction("thread_123", 1, "depth0", "もっとシンプルでよかった")

# 満足度スコアを計算
score = feedback.get_satisfaction_score("thread_123")
```

## depth_selectorとの統合

### 方策モード

`POLICY_MODE`設定で動作を切り替え:

| モード | 説明 |
|--------|------|
| `confidence` | 確信度ベースの選択（デフォルト） |
| `learned` | 学習した方策のみを使用 |
| `hybrid` | 確信度が不明確な場合のみ学習方策を使用 |

設定方法:

```python
# backend/core/config.py または .env
POLICY_MODE = "hybrid"
```

### 経験の自動収集

`depth_selector`は自動的に経験を収集します:

```python
# nodes.py内で自動実行
experience_collector.collect(
    confidence_metrics=confidence_metrics,
    dissonance=dissonance,
    reason_codes=reason_codes,
    action=action_int,
    action_name=action.value,
    thread_id=thread_id,
    turn_count=turn_count,
)
```

## テスト

### テストファイル

[tests/test_policy.py](../tests/test_policy.py) - 25テストケース

### 実行方法

```bash
# Phase 3テストのみ
python -m pytest tests/test_policy.py -v

# 全Phaseテスト
python -m pytest tests/test_contracts.py tests/test_confidence.py tests/test_depth_selector.py tests/test_policy.py -v
```

## 運用ガイド

### 1. データ収集フェーズ

```python
# 1. 通常運用で経験を収集（自動）
# depth_selectorが自動的にexperience_collectorに経験を追加

# 2. 定期的に保存
from backend.core.policy import experience_collector
experience_collector.save()
```

### 2. 学習フェーズ

```python
from backend.core.policy import experience_collector, policy_learner

# 1. 過去の経験を読み込み
experience_collector.load_all()

# 2. 学習
result = policy_learner.train(experience_collector, n_epochs=100)

# 3. 評価
eval_result = policy_learner.evaluate(experience_collector)

# 4. 保存
policy_learner.save("policy_production.json")
```

### 3. デプロイフェーズ

```python
# 1. 方策を読み込み
policy_learner.load("policy_production.json")

# 2. 方策モードを変更
# .envまたはconfig.pyで POLICY_MODE = "hybrid"
```

### 4. Human-in-the-Loop

```python
from backend.core.policy import human_feedback

# 1. フィードバックを収集（UIから）
feedback.submit_rating(thread_id, turn_id, rating=4)

# 2. 統計を確認
stats = feedback.get_statistics()

# 3. 学習に反映
# フィードバックの報酬を経験に追加
```

## 成功指標

| 指標 | 目標 |
|------|------|
| Depth選択の適切性 | > 85% |
| ユーザー満足度 | > 4.0/5.0 |
| 会話効率（ターン数） | 3-5ターン |

## 次のステップ（Phase 4）

Phase 4ではDSPyによる品質改善を実装:

- Depth1の出力品質最適化
- 断定抑制・反復抑制
- 焦点の明確化

詳細は [ROADMAP_INTEGRATED.md](./ROADMAP_INTEGRATED.md) を参照。
