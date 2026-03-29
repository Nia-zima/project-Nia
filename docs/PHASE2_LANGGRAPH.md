# Phase 2: LangGraph本番化

## 概要

Phase 2では、Phase 1で実装した確信度システムをLangGraphに統合し、確信度ベースのDepth選択を本番化しました。

## グラフ構造

```
Safety → Dissonance → [Depth Selector] → Depth0 or Depth1 → Merge → END
```

### ノード説明

| ノード | 役割 |
|--------|------|
| **Safety** | 安全性チェック（有害コンテンツのブロック） |
| **Dissonance** | 内部矛盾スコアの計算、reason_codesの収集 |
| **Depth Selector** | 確信度を計算し、適切なDepthを選択（**Phase 2で追加**） |
| **Depth0** | Pre-Thought（即答抑制モード） |
| **Depth1** | Organize & Ask（整理・質問モード） |
| **Merge** | 最終出力の統合 |

## Depth Selector の動作

### 選択基準

| 確信度 | アクション | 説明 |
|--------|-----------|------|
| >= 0.8 | DEPTH0 | 即答OK。情報が十分 |
| >= 0.5 | DEPTH1 | 整理が必要。Organize & Ask実行 |
| >= 0.3 | ASK | 確認質問が必要。DEPTH1 + 質問 |
| < 0.3 | WAIT | 情報不足。保留 |

### オーバーライド条件

以下の条件は確信度の結果をオーバーライドします：

1. **ユーザー明示リクエスト** (`user_request` in reason_codes)
   - 「詳しく」「整理して」などのキーワード → 強制DEPTH1

2. **高dissonanceスコア** (>= 0.65)
   - 「違う」「でも」など矛盾表現 → 強制DEPTH1

## 実装ファイル

### 変更ファイル

| ファイル | 変更内容 |
|----------|----------|
| [state.py](../backend/core/agent_graph/state.py) | AgentStateに確信度フィールドを追加 |
| [nodes.py](../backend/core/agent_graph/nodes.py) | depth_selectorノードを追加、dissonance_checkを調整 |
| [graph.py](../backend/core/agent_graph/graph.py) | depth_selectorをグラフに統合 |

### AgentState 新規フィールド

```python
# Phase 2: 確信度システム
confidence: Optional[float]              # 複合確信度 (0.0-1.0)
confidence_metrics: Optional[Dict]       # 各メトリクスの詳細
depth_action: Optional[str]              # "depth0", "depth1", "ask", "wait"
depth_recommendation_reason: Optional[str]  # 推奨理由
```

### depth_selector ノード

```python
async def depth_selector(state: AgentState) -> dict:
    """
    Phase 2: 確信度ベースのDepth選択器

    ConfidenceEngineを使用して確信度を計算し、
    適切なDepthアクションを推奨します。
    """
    # 1. ユーザー入力とコンテキストを取得
    # 2. ConfidenceEngineで確信度を計算
    # 3. アクションに基づいてneed_depth1を決定
    # 4. オーバーライド条件をチェック
    # 5. ログ記録
    # 6. 結果を返す
```

## テスト

### テストファイル

[tests/test_depth_selector.py](../tests/test_depth_selector.py)

### テストケース

| テスト | 内容 |
|--------|------|
| `test_high_confidence_uses_depth0` | 高確信度でDEPTH0を選択 |
| `test_complex_question_uses_depth1` | 複雑な質問でDEPTH1を選択 |
| `test_user_request_overrides_confidence` | ユーザーリクエストでオーバーライド |
| `test_high_dissonance_overrides_confidence` | 高dissonanceでオーバーライド |
| `test_confidence_metrics_are_recorded` | メトリクスが正しく記録される |
| `test_depth_action_is_valid` | depth_actionが有効な値を持つ |
| `test_recommendation_reason_is_provided` | 推奨理由が提供される |

### 実行方法

```bash
# Phase 2テストのみ
python -m pytest tests/test_depth_selector.py -v

# 全テスト（Phase 0, 1, 2）
python -m pytest tests/test_contracts.py tests/test_confidence.py tests/test_depth_selector.py -v
```

## ログ記録

depth_selectorは以下の情報をinner_monologue_loggerに記録します：

```json
{
  "intent": "depth_selector",
  "interpretation": "confidence=0.72 action=depth1",
  "inner_reflection": "中程度の確信度（0.72）。Depth1で詳細な分析が必要です。",
  "allow_public_narration": false,
  "confidence": 0.72,
  "thread_id": "default",
  "need_depth1": true,
  "dissonance": 0.3,
  "metrics": {
    "context_coverage": 0.65,
    "self_consistency": 0.5,
    "logit_based": 0.5,
    "question_clarity": 0.8,
    "composite_raw": 0.72,
    "composite_calibrated": 0.72
  }
}
```

## 後方互換性

Phase 2は既存のPhase 0およびPhase 1の機能を維持しています：

- Depth契約（Depth0Contract, Depth1Contract）は引き続き各ノードで検証されます
- 確信度メトリクス（ConfidenceMetrics）は変更なし
- キャリブレーション（ConfidenceCalibrator）は引き続き利用可能

## 次のステップ（Phase 3）

Phase 3では方策学習（Gymnasium）を導入し、「いつDepth0/1を使うか」を学習で最適化します：

- Gym環境の構築
- Offline RL（過去ログから学習）
- Human-in-the-Loop

詳細は [ROADMAP_INTEGRATED.md](./ROADMAP_INTEGRATED.md) を参照してください。
