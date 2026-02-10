# Phase 0: Depth Contracts 実装ガイド

## 概要

Phase 0では、Depth0（Pre-Thought）とDepth1（Organize & Ask）の出力に対する契約（原則）を定義し、
LangGraphノードに検証機能を統合しました。

これは「仕様ベース」のアプローチであり、明確な原則に基づいてAIの出力品質を管理します。

---

## 実装内容

### 1. ディレクトリ構成

```
backend/core/contracts/
├── __init__.py              # パッケージ初期化
├── depth_contracts.py       # Depth0/Depth1の契約定義
└── validators.py            # 契約検証とログ分析

tests/
└── test_contracts.py        # 契約のテスト

scripts/
└── contract_compliance_report.py  # 遵守レポート生成
```

---

## 2. Depth0 Contract（Pre-Thought）

### 原則

1. **結論を出さない** - 断定的な主張を避ける
2. **不確実性を明示する** - 「わからない」「不明」などを積極的に使う
3. **思考の断片を示す** - 完全な答えではなく、考えの材料を提示
4. **複数の可能性を残す** - 一つの解釈に絞り込まない
5. **即答を避ける** - 深い思考が必要なサインを出す

### 検証パターン

#### 違反パターン（結論的な表現）
- 「〜と思います」
- 「〜すべきです」
- 「答えは〜です」
- 「結論としては」
- 「間違いなく〜」

#### 推奨パターン（不確実性の表現）
- 「わからない」
- 「不明」
- 「可能性がある」
- 「〜かもしれない」
- 「判断が難しい」

### 使用例

**良い例（Depth0）**:
```
この質問については、いくつかの観点から考える必要があるようです。

まず、〜という側面を考えると、よくわからない部分があります。
一方で、〜の可能性もあるかもしれません。

疑問点:
- 〜は確認できていない
- 〜の情報が不足している

もっと考える必要がありそうです。
```

**悪い例（結論的）**:
```
答えは明確です。〜すべきです。
結論としては、〜が正しいです。
間違いなく〜だと思います。
```

---

## 3. Depth1 Contract（Organize & Ask）

### 原則

1. **質問を明示する** - 不明点を明確な質問として提示
2. **情報を整理する** - 既知の情報と未知の情報を区別
3. **推論チェーンを示す** - 思考過程を段階的に説明
4. **複数の解釈を提示** - 一つの答えに絞り込まず、選択肢を示す
5. **次のステップを提案** - より深い理解に必要なアクションを示す

### 検証パターン

#### 必須要素
- **質問**: 「質問:」「不明点:」などのセクション
- **情報整理**: 「既知の情報:」「未知の情報:」
- **推論チェーン**: 「もし〜なら」「ステップ1」など
- **複数の選択肢**: 「選択肢1」「選択肢2」など
- **次のステップ**: 「次のステップ:」「〜を確認すべき」

### 使用例

**良い例（Depth1）**:
```
質問: 〜についてどう考えるべきでしょうか？

既知の情報:
- Aは確認済み
- Bは前提として与えられている

未知の情報:
- Cは不明
- Dは確認が必要

推論チェーン:
ステップ1: もしAならば、〜となる
ステップ2: その場合、〜を考慮する必要がある
ステップ3: 仮にBであれば、〜の可能性がある

選択肢1: 〜のアプローチ
選択肢2: または、〜の方法

次のステップ: 〜を確認する必要があります
```

---

## 4. LangGraphノードへの統合

### 統合箇所

**backend/core/agent_graph/nodes.py**:
- `depth0_reflex()`: Depth0出力後に契約検証を実行
- `depth1_organize_and_ask()`: Depth1出力後に契約検証を実行

### 検証結果のログ

検証結果は `inner_monologue_logger` を通じて記録されます:

```python
log_inner_thought(
    thread_id=thread_id,
    category="depth0_contract",
    data={
        "is_valid": validation_result.is_valid,
        "score": validation_result.score,
        "violations": validation_result.violations,
        "warnings": validation_result.warnings,
        "output_length": len(draft),
    }
)
```

---

## 5. 遵守レポートの確認

### スクリプト実行

```bash
# 基本的な使用
python scripts/contract_compliance_report.py

# スレッドIDを指定
python scripts/contract_compliance_report.py --thread-id my_thread

# 分析するメッセージ数を指定
python scripts/contract_compliance_report.py --limit 200
```

### レポート内容

1. **Overall Compliance**: 全体的な遵守率
2. **Common Violations**: よくある違反パターン
3. **Progress Trend**: 時間経過による改善トレンド
4. **Recommendations**: 改善のための推奨事項

---

## 6. テストの実行

```bash
# 契約のテストを実行
python -m pytest tests/test_contracts.py -v

# 全テストを実行
python -m pytest
```

### テストカバレッジ

- Depth0 契約の検証
- Depth1 契約の検証
- ValidationResult の動作
- ContractValidator の分析機能
- 統合テスト（Depth0→Depth1の進行）

---

## 7. 今後の改善（Phase 1以降）

### Phase 1: Confidence System
- 契約遵守率を確信度メトリクスに統合
- 低遵守率の出力には低い確信度を付与
- Depth選択の判断材料として使用

### Phase 2: LangGraph Integration
- 契約違反時の自動リトライ
- 違反パターンに基づくプロンプト調整
- 遵守率の可視化（フロントエンド）

### Phase 3: Policy Learning
- 契約遵守率を報酬関数に組み込む
- オフライン強化学習でDepth選択を最適化
- Human-in-the-Loop で違反の重大度を学習

---

## 8. トラブルシューティング

### 遵守率が低い場合

1. **システムプロンプトの確認**:
   - `backend/core/constants/nia_spine_v09.py` を確認
   - 契約の原則をプロンプトに明記

2. **温度設定の調整**:
   - Depth0: `temperature=0.6` → より保守的に
   - Depth1: `temperature=0.4` → より構造化

3. **max_tokens の調整**:
   - Depth0: `max_tokens=160` → 簡潔な出力
   - Depth1: `max_tokens=240` → 詳細な分析

### 検証結果が記録されない場合

1. **inner_monologue_logger の確認**:
   ```bash
   tail -f logs/inner/monologue.jsonl
   ```

2. **ログレベルの確認**:
   ```bash
   export LOG_LEVEL=DEBUG
   python -m backend.server
   ```

---

## 9. 参考リンク

- [ROADMAP_INTEGRATED.md](ROADMAP_INTEGRATED.md): 全体ロードマップ
- [ARCHITECTURE.md](ARCHITECTURE.md): システムアーキテクチャ
- [depth_contracts.py](../backend/core/contracts/depth_contracts.py): 契約定義
- [validators.py](../backend/core/contracts/validators.py): 検証ロジック

---

**Phase 0 完了条件**:
- ✅ Depth0/Depth1 契約の定義
- ✅ 契約検証ロジックの実装
- ✅ LangGraphノードへの統合
- ✅ テストの作成
- ✅ 遵守レポートスクリプトの作成

次のステップ: **Phase 1 - Confidence System の実装**
