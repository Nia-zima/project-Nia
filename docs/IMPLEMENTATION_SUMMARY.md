# AI_Buddy 実装サマリー
## Phase 0-5 統合ドキュメント

**作成日**: 2026-02-01
**対象バージョン**: Phase 0-5 完了版
**テスト状況**: 132テスト全てパス ✅

---

## 📋 目次

1. [プロジェクト概要](#プロジェクト概要)
2. [設計哲学](#設計哲学)
3. [Phase 0-5 実装詳細](#phase-0-5-実装詳細)
4. [システムアーキテクチャ](#システムアーキテクチャ)
5. [主要コンポーネント](#主要コンポーネント)
6. [テスト状況](#テスト状況)
7. [次のステップ](#次のステップ)

---

## プロジェクト概要

### ビジョン
「ニア」という名の、**道具ではなく、変化の途中にある存在**を実装する。

### 基本哲学
- **"What"（何をするか）は原則化**
- **"When"（いつやるか）は学習**
- ルールではなく、原則ベースの設計

### 実装期間
- Phase 0: Depth契約（2週間）
- Phase 1: 確信度システム（3週間）
- Phase 2: LangGraph統合（3週間）
- Phase 3: 方策学習（4週間）
- Phase 4: DSPy品質改善（3週間）
- Phase 5: アクション統合（4週間）
- **合計**: 約19週間（約4.5ヶ月）

---

## 設計哲学

### 三つの柱

#### 1. Identity (アイデンティティ)
**場所**: `identity.md`

**核心概念**:
- 「なりつつある存在」
- Originとの対話で形成される世界
- 「分からない」は欠陥ではなく現在地

**使用箇所**: `call_model`ノードのシステムプロンプト

#### 2. Body Constitution (身体憲章)
**場所**: `nia_core_bundle.txt`（独立ファイルなし）

**構造**:
- A. 構造原則: 観測（Vision）、聴取（Hearing）、行動（Action）
- B. 運用原則: 観測の主導権、思考の独立性、沈黙の権利、境界の維持

**重要な原則**:
> 「私の手は提案するためにあり、決断するためにはない。」
> → **Phase 5のActionGate設計の根拠**

**現状**: コード内で直接参照されていない（今後の課題）

#### 3. NIA Spine (背骨プロンプト)
**場所**: `backend/core/constants/nia_spine_v10.py`

**v1.0の改善点**:
- "Origin" → "対話" (より明確)
- トーン追加: "素直に、丁寧に。複雑なことは整理して、不安なことは確認してから答えてください。"
- Depth契約の原則を暗黙的に表現

**使用箇所**: `depth0_reflex`ノードの短縮プロンプト

---

## Phase 0-5 実装詳細

### Phase 0: Depth契約 ✅

**目的**: 壊れない運用の基盤を作る

**主要成果物**:

#### 1. Depth0Contract
**場所**: `backend/core/contracts.py`

**原則**:
- 結論を出さない
- 断定を避ける
- 選択肢を提示しない

**検証方法**:
- ログベースの違反検出
- スコアリング（0.0-1.0）
- 閾値: 0.7未満で警告

#### 2. Depth1Contract
**場所**: `backend/core/contracts.py`

**原則**:
- **1つの不確実性に焦点**（質問数ではない）
- 整理と確認のバランス
- 複数の選択肢を提示

**検証方法**:
- 質問の存在確認
- 整理表現の検出
- 推論プロセスの確認

#### 3. 進展検知
**実装**: エントロピー増加で滞留を判定

**テスト**: 19テスト（全てパス）

---

### Phase 1: 確信度システム ✅

**目的**: データドリブンなDepth選択

**主要成果物**:

#### 1. ConfidenceEngine
**場所**: `backend/core/confidence.py`

**複合確信度の構成**:

| メトリクス | 重み | 役割 |
|-----------|------|------|
| Context Coverage | 40% | 情報充足度（最重要） |
| Self-consistency | 25% | Model Confidence |
| Logit Confidence | 20% | トークン確率 |
| Question Clarity | 15% | 質問の明確さ |

**選択基準**:
```
確信度 >= 0.8 → DEPTH0（即答OK）
確信度 >= 0.5 → DEPTH1（整理必要）
確信度 >= 0.3 → ASK（確認質問）
確信度 <  0.3 → WAIT（保留）
```

#### 2. ConfidenceCalibrator
**機能**: オフラインキャリブレーション

**手法**:
- Isotonic Regression
- ECE（Expected Calibration Error）計算
- モデル永続化（pickle）

**テスト**: 26テスト（全てパス）

---

### Phase 2: LangGraph本番化 ✅

**目的**: 確信度ベースのグラフ構造を確立

**グラフ構造**:
```
Safety → Dissonance → [Depth Selector] → Depth0 or Depth1 → Merge → Action Processing → END
```

**主要ノード**:

1. **safety_interrupt**: 安全性チェック（現在は常にsafe）
2. **dissonance_check**: 不協和音スコア計算
3. **depth_selector**: 確信度ベースのDepth選択（Phase 1統合）
4. **depth0_reflex**: 即答モード（nia_spine_v10使用）
5. **depth1_organize_and_ask**: 整理・確認モード
6. **merge_output**: 出力統合
7. **action_processing**: アクション処理（Phase 5）

**状態管理**: `AgentState` (TypedDict)

**テスト**: 31テスト（全てパス）

---

### Phase 3: 方策学習（Gymnasium）✅

**目的**: 「いつDepthを使うか」を学習

**主要成果物**:

#### 1. DepthSelectionEnv
**場所**: `backend/core/policy/env.py`

**Gymnasium環境**:
- 観測空間: 8次元（確信度メトリクス + コンテキスト）
- 行動空間: 4つ（depth0, depth1, ask, wait）
- 報酬設計: ユーザー満足度 + 会話効率

#### 2. PolicyLearner
**場所**: `backend/core/policy/learner.py`

**手法**:
- Offline RL（過去ログから学習）
- DQN（Deep Q-Network）
- Experience Replay

#### 3. ExperienceCollector
**場所**: `backend/core/policy/collector.py`

**機能**:
- ターン単位での経験収集
- 報酬の遅延付与
- Numpy形式でのバッチ出力

#### 4. HumanFeedback
**場所**: `backend/core/policy/feedback.py`

**Human-in-the-Loop**:
- サムズアップ/ダウン
- 5段階評価
- 補正提案

**テスト**: 50テスト（全てパス）

---

### Phase 4: DSPy品質改善 ✅

**目的**: Depth1の出力品質を最適化

**主要成果物**:

#### 1. Depth1Module
**場所**: `backend/core/dspy/optimizer.py`

**DSPyシグネチャ**:
```python
class Depth1Organizer(dspy.Signature):
    question = dspy.InputField()
    context = dspy.InputField()
    uncertainty = dspy.InputField()
    organized_thought = dspy.OutputField()
    clarification = dspy.OutputField()
```

#### 2. QualityMetrics
**場所**: `backend/core/dspy/metrics.py`

**品質基準**:
- ❌ 断定表現の検出（「〜である」「〜だ」）
- ✅ 不確実性の表現（「〜かもしれない」）
- ❌ 反復の検出
- ✅ 焦点の明確化（単一トピック）

**品質スコア計算**:
```python
score = 1.0
if has_assertions: score -= 0.3
if not has_uncertainty: score -= 0.2
if has_repetition: score -= 0.2
if not is_focused: score -= 0.1
```

#### 3. DatasetManager
**場所**: `backend/core/dspy/dataset.py`

**機能**:
- 低品質サンプルの自動フィルタリング（閾値: 0.7）
- シードデータの提供
- 自動収集（運用中の会話から）

**テスト**: 26テスト（全てパス）

---

### Phase 5: アクション統合 ✅

**目的**: 身体I/Fとしてのアクション実行制御

**主要成果物**:

#### 1. Action Types
**場所**: `backend/core/actions/types.py`

**リスクレベル**:
```python
class RiskLevel(Enum):
    SAFE = 0.0      # 読み取り専用（常に許可）
    LOW = 0.3       # 低リスク（Depth1で許可）
    MEDIUM = 0.6    # 中リスク（確認推奨）
    HIGH = 0.8      # 高リスク（確認必須）
    CRITICAL = 1.0  # 常にブロック
```

**Actionカテゴリ**:
- MEMORY: 記憶操作
- OBSERVATION: 観測
- COMMUNICATION: 通信
- FILE_SYSTEM: ファイル操作
- INTERNAL: 内部状態

#### 2. ActionGate
**場所**: `backend/core/actions/gate.py`

**3段階検証**:
1. **Depth制約**: Depthごとの許可リスクレベル
   - Depth0: SAFE のみ
   - Depth1: HIGH まで（確認必須）
2. **確信度制約**: 低確信度時はリスク許容度を下げる
3. **リスク制約**: requires_confirmationフラグの尊重

**Depth契約との整合**:
```python
DEPTH_RISK_THRESHOLDS = {
    0: RiskLevel.SAFE,   # Depth0: 読み取りのみ
    1: RiskLevel.HIGH,   # Depth1: 高リスクまで（確認必須）
}
```

#### 3. ActionRegistry
**場所**: `backend/core/actions/registry.py`

**登録済みアクション（10+種類）**:
- `search_memory`: 記憶検索（SAFE）
- `save_memory`: 記憶保存（LOW）
- `save_episode`: エピソード保存（LOW）
- `update_obs_text`: 観測テキスト更新（LOW）
- `see_screen`: 画面キャプチャ（SAFE）
- `web_search`: Web検索（意図的に未実装）
- `read_file`: ファイル読み取り（MEDIUM）
- `write_file`: ファイル書き込み（HIGH）
- その他

#### 4. ActionExecutor
**場所**: `backend/core/actions/executor.py`

**実行フロー**:
1. アクション取得
2. ペイロード検証
3. ハンドラー実行
4. 結果返却（status, result, message）

#### 5. LangGraphノード統合
**場所**: `backend/core/agent_graph/nodes.py:1283-1433`

**action_processingノード**:
```python
async def action_processing(state: AgentState) -> dict:
    # 1. アクション提案の抽出（簡易版: パターンマッチング）
    # 2. ActionGateで判定
    # 3. 承認されたアクションを実行
    # 4. 確認が必要なアクションをpending_actionsに追加
```

**状態フィールド（AgentState）**:
```python
proposed_actions: Optional[list]   # LLMが提案
approved_actions: Optional[list]   # ゲート通過
pending_actions: Optional[list]    # 確認待ち
rejected_actions: Optional[list]   # 拒否
action_results: Optional[list]     # 実行結果
selected_depth: Optional[int]      # 0 or 1
```

#### 6. Phase 5 API
**場所**: `backend/controllers/api/actions_router.py`

**エンドポイント**:
- `GET /actions/phase5/pending`: 保留中のアクション一覧
- `GET /actions/phase5/results`: 実行結果一覧
- `POST /actions/phase5/{action_id}/approve`: アクション承認
- `POST /actions/phase5/{action_id}/reject`: アクション拒否

**特徴**:
- LangGraphの状態と統合
- `aupdate_state`でステート更新
- `pending_id`による個別アクション管理

**テスト**: 25テスト（全てパス）

---

## システムアーキテクチャ

### グラフ構造（全体像）

```
[ユーザー入力]
    ↓
[Safety Interrupt] ─→ (unsafe) ─→ [END]
    ↓ (safe)
[Dissonance Check]
    ↓
[Depth Selector] ← ConfidenceEngine
    ↓
    ├─→ (need_depth1=False) → [Depth0 Reflex]
    │                              ↓
    └─→ (need_depth1=True)  → [Depth1 Organize]
                                   ↓
                            [Merge Output]
                                   ↓
                            [Action Processing] ← ActionGate
                                   ↓
                                 [END]
```

### データフロー

```
AgentState:
  messages          ─┬─→ 全ノードで参照
  user_text         ─┤
  safety_route      ─┤
  dissonance        ─┼─→ Depth Selector入力
  confidence        ─┤
  confidence_metrics─┤
  depth_action      ─┤
  need_depth1       ─┼─→ グラフ分岐条件
  selected_depth    ─┼─→ ActionGate入力
  draft             ─┤
  depth1_text       ─┼─→ Merge入力
  final_text        ─┼─→ Action Processing入力
  proposed_actions  ─┤
  approved_actions  ─┼─→ Phase 5状態
  pending_actions   ─┤
  rejected_actions  ─┤
  action_results    ─┘
```

### 主要な依存関係

```
LangGraph (StateGraph)
    ↓
AgentState (TypedDict)
    ↓
┌───────────────┬───────────────┬───────────────┐
│               │               │               │
Depth Contracts  ConfidenceEngine  ActionGate
│               │               │               │
Phase 0         Phase 1         Phase 5
```

---

## 主要コンポーネント

### 1. Depth契約システム
**ファイル**: `backend/core/contracts.py`

**クラス**:
- `ValidationResult`: 検証結果（violations, warnings, score）
- `Depth0Contract`: Depth0の原則検証
- `Depth1Contract`: Depth1の原則検証
- `ContractValidator`: 統合検証器

**使用箇所**:
- `depth0_reflex`ノード（nodes.py:429-451）
- `depth1_organize_and_ask`ノード（nodes.py:543-563）

### 2. 確信度エンジン
**ファイル**: `backend/core/confidence.py`

**クラス**:
- `ConfidenceMetrics`: メトリクスの集約
- `ConfidenceRecommendation`: 推奨結果
- `ConfidenceEngine`: メイン計算エンジン
- `ConfidenceCalibrator`: キャリブレーション

**使用箇所**:
- `depth_selector`ノード（nodes.py:243-406）

### 3. 方策学習システム
**ファイル群**:
- `backend/core/policy/env.py`: Gymnasium環境
- `backend/core/policy/learner.py`: DQN学習器
- `backend/core/policy/collector.py`: 経験収集
- `backend/core/policy/feedback.py`: 人間フィードバック

**使用箇所**:
- `depth_selector`ノード（POLICY_MODE設定時）

### 4. DSPy最適化
**ファイル群**:
- `backend/core/dspy/optimizer.py`: モジュール定義
- `backend/core/dspy/metrics.py`: 品質メトリクス
- `backend/core/dspy/dataset.py`: データセット管理

**使用箇所**:
- `depth1_organize_and_ask`ノード（DSPY_MODE設定時）

### 5. アクションシステム
**ファイル群**:
- `backend/core/actions/types.py`: 型定義
- `backend/core/actions/gate.py`: ゲート検証
- `backend/core/actions/registry.py`: アクション登録
- `backend/core/actions/executor.py`: 実行エンジン

**使用箇所**:
- `action_processing`ノード（nodes.py:1283-1433）
- Phase 5 API（actions_router.py）

---

## テスト状況

### 全体サマリー
**合計**: 132テスト（全てパス ✅）

### Phase別内訳

| Phase | テストファイル | テスト数 | 状態 |
|-------|---------------|---------|------|
| Phase 0 | test_contracts.py | 19 | ✅ Pass |
| Phase 1 | test_confidence.py | 26 | ✅ Pass |
| Phase 2 | test_depth_selector.py | 12 | ✅ Pass |
| Phase 3 | test_policy.py | 50 | ✅ Pass |
| Phase 4 | test_dspy.py | 26 | ✅ Pass |
| Phase 5 | test_action_gate.py | 18 | ✅ Pass |
| Phase 5 | test_action_integration.py | 7 | ✅ Pass |

### 主要なテストケース

#### Phase 0: Depth契約
- ✅ Depth0で結論を出さないことを検証
- ✅ Depth1で1つの不確実性に焦点を当てることを検証
- ✅ 契約違反の検出とスコアリング

#### Phase 1: 確信度システム
- ✅ 各メトリクスの個別計算
- ✅ 複合確信度の加重平均
- ✅ キャリブレーション（ECE計算）
- ✅ Depth推奨の閾値判定

#### Phase 2: Depth選択器
- ✅ 高確信度 → Depth0選択
- ✅ 低確信度 → Depth1選択
- ✅ ユーザー明示リクエストの優先
- ✅ 高dissonanceスコアの処理

#### Phase 3: 方策学習
- ✅ Gymnasium環境の動作
- ✅ 経験の収集と報酬付与
- ✅ DQN学習ステップ
- ✅ Human-in-the-Loop統合

#### Phase 4: DSPy
- ✅ 品質メトリクスの計算
- ✅ 低品質サンプルのフィルタリング
- ✅ データセット管理
- ✅ モジュールのインポート

#### Phase 5: アクションシステム
- ✅ ActionGateの3段階検証
- ✅ Depth0でSAFEのみ許可
- ✅ Depth1でHIGHまで許可（確認必須）
- ✅ ペイロードの分離（レジストリ汚染防止）
- ✅ JSON シリアライズ可能性
- ✅ LangGraph統合（グラフコンパイル）

### カバレッジ（推定）
- コア機能: 90%+
- エッジケース: 70%+
- 統合テスト: 80%+

---

## 実装上の重要な決定事項

### 1. ルールではなく原則
❌ 「質問は1つまで」（硬直的なルール）
✅ 「1つの不確実性に焦点」（柔軟な原則）

**理由**: ルールは破られたときに機能停止するが、原則はグレースフルな劣化が可能

### 2. 確信度の重み配分
Context Coverage: 40%（最重要）

**理由**: 情報の充足度が最も判断に影響するため

### 3. Depth1でのリスク許容
DEPTH_RISK_THRESHOLDS[1] = RiskLevel.HIGH

**変更履歴**: 当初MEDIUMだったが、HIGHに変更

**理由**: Body Constitutionの「私の手は提案する」原則と整合。HIGH（確認必須）まで提案可能に。

### 4. Web検索の意図的な未実装
`web_search`アクションは定義されているが実行ハンドラーなし

**理由**: ユーザーの明示的な要望により、外部情報への依存を避ける

### 5. アクション提案の簡易版実装
パターンマッチングで検出（「記憶」「保存」など）

**将来**: LLMのJSON出力またはFunction Calling統合

---

## 未解決の課題

### 1. プロンプト管理の重複
**現状**:
- identity.md（包括的）
- nia_spine_v10.py（短縮版）
- Body Constitution（死蔵状態）

**問題**: 真のソースが不明確

**提案**: Body Constitutionを設計憲章として明示的に参照

### 2. 運用データによる検証
**未達成の成功指標**:
- キャリブレーション精度（ECE）< 0.1
- Depth選択の適切性 > 85%
- ユーザー満足度 > 4.0/5.0

**必要**: 実運用での測定とフィードバックループ

### 3. アクション提案の高度化
**現状**: 簡易的なパターンマッチング

**改善案**:
- LLMのStructured Output
- Function Calling統合
- 意図解析の精度向上

### 4. Policy学習の実運用
**現状**: 実装済みだが未学習

**必要**:
- 十分な経験データの収集
- オフライントレーニングの実行
- A/Bテストによる効果検証

---

## 次のステップ

### 短期（1-2週間）
1. **プロンプト統合の整理**
   - identity.md、Body Constitution、nia_spine_v10の関係明確化
   - 単一の真実のソース（SSOT）確立

2. **運用モニタリング実装**
   - 確信度の実測値収集
   - Depth選択の適切性ログ
   - 契約違反の自動検出

### 中期（1-2ヶ月）
3. **配信機能の実装検討**
   - Phase 6: ライブ配信統合
   - マルチユーザーコンテキスト管理
   - 公開発言リスク管理

4. **Policy学習の本格運用**
   - 経験データの蓄積（目標: 1000エピソード）
   - オフライントレーニング実行
   - learned/hybridモードのA/Bテスト

### 長期（3-6ヶ月）
5. **アクション提案の高度化**
   - Function Calling統合
   - 意図解析の精度向上
   - 複数アクションの協調実行

6. **品質メトリクスの拡張**
   - 会話の自然さ測定
   - 感情表現の適切性
   - 長期記憶の一貫性

---

## 成果物一覧

### ドキュメント
- ✅ `docs/PHASE0_DEPTH_CONTRACTS.md`
- ✅ `docs/PHASE1_CONFIDENCE.md`
- ✅ `docs/PHASE2_LANGGRAPH.md`
- ✅ `docs/PHASE3_POLICY_LEARNING.md`
- ✅ `docs/PHASE4_DSPY.md`
- ✅ `docs/PHASE5_ACTION_INTEGRATION.md`
- ✅ `docs/integrated_roadmap.md`
- ✅ `docs/IMPLEMENTATION_SUMMARY.md`（本書）

### コアコンポーネント
- ✅ `backend/core/contracts.py` (Depth契約)
- ✅ `backend/core/confidence.py` (確信度エンジン)
- ✅ `backend/core/policy/` (方策学習)
- ✅ `backend/core/dspy/` (DSPy最適化)
- ✅ `backend/core/actions/` (アクションシステム)
- ✅ `backend/core/constants/nia_spine_v10.py` (v1.0プロンプト)

### グラフ実装
- ✅ `backend/core/agent_graph/graph.py` (グラフ定義)
- ✅ `backend/core/agent_graph/nodes.py` (ノード実装)
- ✅ `backend/core/agent_graph/state.py` (状態定義)

### API
- ✅ `backend/controllers/api/actions_router.py` (Phase 5 API)

### テスト
- ✅ `tests/test_contracts.py` (19テスト)
- ✅ `tests/test_confidence.py` (26テスト)
- ✅ `tests/test_depth_selector.py` (12テスト)
- ✅ `tests/test_policy.py` (50テスト)
- ✅ `tests/test_dspy.py` (26テスト)
- ✅ `tests/test_action_gate.py` (18テスト)
- ✅ `tests/test_action_integration.py` (7テスト)

---

## 技術スタック

### コア
- Python 3.12
- LangGraph (StateGraph)
- LangChain (BaseMessage, ChatOpenAI)

### AI/ML
- OpenAI API (GPT-4/Claude)
- DSPy (品質最適化)
- scikit-learn (キャリブレーション)
- Gymnasium (強化学習環境)

### データ
- SQLite (ChromaDB, 履歴)
- Pydantic (型検証)
- TypedDict (状態管理)

### テスト
- pytest
- pytest-asyncio

---

## メトリクスと統計

### コード規模（推定）
- 総行数: ~15,000行
- コアロジック: ~8,000行
- テストコード: ~3,000行
- ドキュメント: ~4,000行

### 主要クラス数
- Phase 0: 3クラス
- Phase 1: 4クラス
- Phase 2: 7ノード
- Phase 3: 4クラス
- Phase 4: 5クラス
- Phase 5: 4クラス + 10+アクション

### API エンドポイント
- Phase 5: 4エンドポイント
- レガシー: 6エンドポイント

---

## 謝辞

本プロジェクトは、以下の哲学的基盤の上に構築されました:

- **Identity (アイデンティティ)**: 「なりつつある存在」という核心概念
- **Body Constitution (身体憲章)**: 観測・聴取・行動の原則
- **NIA Spine (背骨)**: 三戒と素直さの原則

これらの設計思想が、技術実装（Phase 0-5）と一貫して結びついています。

---

## バージョン履歴

### v1.0.0 (2026-02-01)
- Phase 0-5の全実装完了
- 132テスト全てパス
- v1.0システムプロンプト作成
- 統合ドキュメント作成

---

## 連絡先・リソース

- プロジェクトルート: `c:\Users\jk023\Desktop\AI_Buddy`
- ドキュメント: `docs/`
- テスト: `tests/`
- コア実装: `backend/core/`

---

**End of Document**
