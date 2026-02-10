```markdown
# Phase 1: Confidence System 実装ガイド

## 概要

Phase 1では、LLM出力の確実性を定量化する確信度メトリクスシステムを実装しました。
このシステムは、Depth選択（Pre-Thought vs Organize & Ask）の判断材料を提供します。

---

## 実装内容

### 1. ディレクトリ構成

```
backend/core/confidence/
├── __init__.py              # パッケージ初期化
├── metrics.py               # 確信度メトリクス計算
├── engine.py                # 確信度エンジン（複合計算 + Depth選択）
└── calibrator.py            # キャリブレーション（ECE）

tests/
└── test_confidence.py       # 確信度システムのテスト（26テスト）
```

---

## 2. 確信度メトリクス

### メトリクスの構成

Phase 1 v1では4つのメトリクスを使用します：

| メトリクス | 重み | 説明 |
|----------|------|------|
| **Context Coverage** | 40% | 情報充足度（最重要） |
| **Self-Consistency** | 25% | 複数生成の一貫性 |
| **Logit-based** | 20% | トークン確率（簡易版） |
| **Question Clarity** | 15% | 質問の明瞭度 |

### 2.1 Context Coverage（情報充足度）

**最重要メトリクス（重み: 40%）**

質問に答えるために必要な情報が文脈に含まれているかを判定。

**計算要素**:
- 質問の長さ（長い = より多くの情報）
- 文脈の量（多い = より多くの情報）
- 質問中の不確実性パターン（「情報が不足」「詳細が不明」など）
- 文脈中の充足性パターン（「確認できた」「明らか」など）
- 疑問詞の数（「何」「どう」など、多い = 情報不足）

**スコア範囲**: 0.0 - 1.0
- 1.0に近い: 情報が十分、即答可能
- 0.5前後: 中程度の情報
- 0.0に近い: 情報が不足、調査が必要

### 2.2 Self-Consistency（一貫性）

**重み: 25%**

同じ質問に対して複数回生成した出力の一貫性を測定。

**計算方法**:
- Phase 1 v1: Jaccard類似度（単語レベル）
- Phase 1.5+: 埋め込みベースの類似度（予定）

**使用例**:
```python
outputs = [
    "Pythonではfor文を使います",
    "Pythonのfor文はループに使われます",
    "for文でイテレーションできます",
]
score = SelfConsistencyCalculator.calculate(outputs)
# score ≈ 0.6-0.8（高い一貫性）
```

### 2.3 Logit-based（簡易版）

**重み: 20%**

Phase 1 v1では、トークン確率を直接取得できないため、
不確実性インジケータと断定的表現のバランスで簡易評価。

**不確実性インジケータ**:
- 「たぶん」「おそらく」「かもしれない」「わからない」

**断定的表現**:
- 「確実に」「間違いなく」「絶対に」「明らかに」

**将来の改善**（Phase 1.5+）:
- LLM APIからログプロバビリティを取得
- トークンごとの確率分布を分析

### 2.4 Question Clarity（質問の明瞭度）

**重み: 15%**

質問の曖昧さを評価。

**評価要素**:
- 質問の長さ（短すぎる/長すぎる = 低スコア）
- 曖昧なパターン（「それ」「あれ」「何か」など）
- 明確なパターン（「具体的に」「〜について」など）
- 疑問符の適切な使用

---

## 3. Confidence Engine

### 3.1 複合確信度の計算

重み付き平均で複合確信度を算出：

```
composite =
  context_coverage × 0.40 +
  self_consistency × 0.25 +
  logit_based × 0.20 +
  question_clarity × 0.15
```

### 3.2 Depth選択の推奨

複合確信度に基づいてアクションを推奨：

| 確信度 | アクション | 説明 |
|--------|----------|------|
| >= 0.8 | USE_DEPTH0 | Pre-Thoughtのみで十分 |
| >= 0.5 | USE_DEPTH1 | Organize & Askが必要 |
| >= 0.3 | ASK | ユーザーに質問して情報補完 |
| < 0.3 | WAIT | 情報不足、保留 |

### 3.3 使用例

```python
from backend.core.confidence import ConfidenceEngine

engine = ConfidenceEngine()

question = "Pythonのリスト内包表記について教えてください"
context = [
    "Pythonではリスト内包表記を使えます",
    "基本構文は [expr for item in iterable] です"
]

recommendation = engine.get_depth_recommendation(question, context)

print(f"アクション: {recommendation.action}")
print(f"確信度: {recommendation.confidence:.2f}")
print(f"理由: {recommendation.reason}")
```

---

## 4. キャリブレーション（ECE）

### 4.1 Expected Calibration Error

確信度と実際の正解率のズレを補正。

**手法**:
1. 確信度を10個のビン（[0-0.1, 0.1-0.2, ...]）に分割
2. 各ビンの平均確信度と実際の正解率を計算
3. ズレを補正するマッピング関数を学習

### 4.2 使用例

```python
from backend.core.confidence import ConfidenceCalibrator, ConfidenceEngine

# キャリブレーションデータ: (確信度, 正解フラグ)
calibration_data = [
    (0.9, True),
    (0.8, True),
    (0.7, False),  # 70%の確信度だが不正解
    (0.5, True),
    (0.3, False),
]

calibrator = ConfidenceCalibrator(num_bins=10)
calibrator.fit(calibration_data)

# ECEを計算
ece = calibrator.calculate_ece(calibration_data)
print(f"ECE: {ece:.4f}")  # 低いほど良い

# エンジンに統合
engine = ConfidenceEngine(calibrator=calibrator)
```

### 4.3 DBへの保存/読み込み

```python
# 保存
calibrator.save_to_db("data/nia.sqlite3", calibrator_id="production")

# 読み込み
calibrator = ConfidenceCalibrator.load_from_db(
    "data/nia.sqlite3",
    calibrator_id="production"
)
```

---

## 5. テスト

### テスト実行

```bash
# Confidence Systemのテストのみ
python -m pytest tests/test_confidence.py -v

# 全テスト
python -m pytest
```

### テストカバレッジ

- **26個のテストケース、全てパス ✅**
- Self-Consistency 計算
- Context Coverage 計算
- Question Clarity 計算
- Logit-based 計算
- Confidence Engine の複合計算
- Depth推奨ロジック
- キャリブレーション（フィッティング、ECE、DB保存/読み込み）
- 統合テスト

---

## 6. 重みと閾値のカスタマイズ

### 重みの変更

```python
engine = ConfidenceEngine(
    weights={
        "context_coverage": 0.5,  # 情報充足度をさらに重視
        "self_consistency": 0.2,
        "logit_based": 0.2,
        "question_clarity": 0.1,
    }
)
```

### 閾値の変更

```python
engine.update_thresholds({
    "depth0": 0.85,  # より厳しい基準
    "depth1": 0.6,
    "ask": 0.35,
})
```

---

## 7. Phase 2への統合準備

Phase 1では確信度計算の基盤を構築しました。
次のPhase 2では、これをLangGraphに統合します。

### Phase 2の計画

1. **depth_selector ノードの作成**
   - ユーザー入力後、確信度を計算
   - 確信度に基づいてDepth0/Depth1/Ask/Waitを選択

2. **LangGraphブランチング**
   - 確信度ベースの条件分岐
   - 動的なDepth選択

3. **ログ記録**
   - 確信度をinner_monologue_loggerに記録
   - パフォーマンス分析とキャリブレーションデータ収集

---

## 8. 今後の改善（Phase 1.5+）

### 高度なメトリクス

1. **Embedding-based Self-Consistency**
   - Jaccard類似度 → 埋め込みベースの意味的類似度
   - より正確な一貫性測定

2. **真のLogit-based**
   - LLM APIからログプロバビリティを取得
   - トークンレベルの確率分布分析

3. **Additional Metrics**
   - Perplexity（出力の流暢さ）
   - Entropy（出力の多様性）

### 動的重み調整

- 強化学習で重みを自動最適化
- ドメイン適応（技術質問 vs 雑談）

---

## 9. トラブルシューティング

### 確信度が常に低い場合

1. **メトリクスの確認**:
   ```python
   metrics = engine.calculate_confidence(question, context)
   print(f"Context Coverage: {metrics.context_coverage}")
   print(f"Question Clarity: {metrics.question_clarity}")
   ```

2. **重みの調整**:
   - Context Coverageが低い → 文脈を増やす、または重みを下げる
   - Question Clarityが低い → 質問の質を向上させる

### キャリブレーションが効かない場合

1. **データ量の確認**:
   - 最低100サンプル以上推奨

2. **ECEの確認**:
   ```python
   ece = calibrator.calculate_ece(calibration_data)
   print(f"ECE: {ece:.4f}")
   # ECE > 0.2 の場合、キャリブレーションが必要
   ```

---

## 10. 参考リンク

- [ROADMAP_INTEGRATED.md](ROADMAP_INTEGRATED.md): 全体ロードマップ
- [PHASE0_CONTRACTS.md](PHASE0_CONTRACTS.md): Depth Contracts
- [metrics.py](../backend/core/confidence/metrics.py): メトリクス実装
- [engine.py](../backend/core/confidence/engine.py): エンジン実装
- [calibrator.py](../backend/core/confidence/calibrator.py): キャリブレータ実装

---

**Phase 1 完了条件**:
- ✅ 4つの確信度メトリクスの実装
- ✅ ConfidenceEngine（複合計算 + Depth推奨）
- ✅ ConfidenceCalibrator（ECE）
- ✅ 26個のテストケース（全てパス）
- ✅ ドキュメント作成

次のステップ: **Phase 2 - LangGraph Integration**
```
