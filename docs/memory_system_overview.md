# ニア 記憶システム全体像

**最終更新**: 2026-02-23
**対象バージョン**: Memory Redesign v2 (Phase A-G, R, M.1 完了)

---

## 1. 全体アーキテクチャ

```
┌───────────────────────────────────────────────────────────────┐
│                     リアルタイム（会話中）                      │
│                                                               │
│  ユーザー入力                                                  │
│      ↓                                                        │
│  S0 SafetyInterrupt [ルール]                                   │
│      ↓                                                        │
│  S1 Pre-Thought [ルール] → dissonance / surprise 判定          │
│      ↓                                                        │
│  S2 Organize / Depth 選択 [LLM]                               │
│      ├── depth0: 反射応答（Pinned Facts のみ参照）              │
│      ├── depth1: 整理応答（フルメモリコンテキスト）              │
│      └── depth2: 結論応答（※ゲート: 100ターン+高confidence）    │
│      ↓                                                        │
│  S3 Retrieve [ルール] → Query-Aware Retrieval (M.1)           │
│      ↓                                                        │
│  S4 Answer [LLM] → 応答生成（DB に触れない）                   │
│      ↓                                                        │
│  S5 Commit [ルール] → episodic保存 + working更新（1トランザク） │
│                                                               │
├───────────────────────────────────────────────────────────────┤
│                     バックグラウンド                            │
│                                                               │
│  Idle Detector (R.1)                                          │
│      └── 3分以上無入力 → Reflection Engine 起動                │
│                                                               │
│  Reflection Engine (R.2)                                      │
│      ├── Phase 1: 会話 → daily_log（日次要約）                 │
│      ├── Phase 2: daily_log → semantic 抽出                   │
│      └── Phase 3 (R.4): 3日分 → cross-day パターン蒸留        │
│                                                               │
├───────────────────────────────────────────────────────────────┤
│                     日次バッチ（Sleep Cycle）                   │
│                                                               │
│  Layer A: 印象記録 → mood / surprise                           │
│  夢の生成 & 保存                                               │
│  日記の生成 & 保存（DIARY_ENABLED）                             │
│  日記 → ツイート提案（TWITTER_AUTO_PROPOSE）                    │
│  Layer B: Identity 提案（proposal or adaptive）                │
│  Semantic 抽出: 常時実行（境界値で Idle Reflection と重複排除） │
│  Semantic 確定: inferred → confirmed（24h経過）                │
│  Episodic 圧縮: 古い memory_events → summaries + archive      │
│  Vector Sync: semantic → ChromaDB 同期                        │
│  Checkpointer クリーンアップ                                   │
└───────────────────────────────────────────────────────────────┘
```

---

## 2. 記憶の3層構成

### 2.1 Episodic（未解釈ログ）

| 項目 | 内容 |
|------|------|
| テーブル | `memory_events` |
| 役割 | 会話の生ログ（append-only、正のデータソース） |
| 内容 | user_text, ai_response, state_tag, emotion 等を payload_json に格納 |
| 寿命 | Sleep Cycle で圧縮 → `episodic_summaries` + `memory_events_archive` |
| 参照 | S5 Commit で毎ターン保存 |

### 2.2 Semantic（事実・知識）

| 項目 | 内容 |
|------|------|
| テーブル | `semantic_memories` |
| 役割 | ユーザーの事実・好み・パターンを構造化して保持 |
| ステータス遷移 | `inferred` → 24h矛盾なし → `confirmed` / 矛盾あり → `revoked` |
| 生成元 | Reflection Engine (R.2) or Sleep Cycle fallback |
| 更新チェーン | `supersedes_id` / `revoked_by_id` で履歴追跡 |
| 検索 | Query-Aware Retrieval (M.1) で意味的検索 |

#### state_tag の種類

| state_tag | 生成元 | 意味 |
|-----------|--------|------|
| `origin` | R.2 (origin_fact, preference) | ユーザーの基本事実・好み |
| `shared` | R.2 (shared_event) | 共有体験 |
| `nia` | R.2 (nia_commitment) | ニアの約束・決意 |
| `insight` | R.4 (cross-day distillation) | 日横断パターン |

#### 忘却システム

| status | 半減期 | 意味 |
|--------|--------|------|
| inferred | 3日 | 未確認 → 早く薄まる |
| confirmed | 30日 | 確定済み → 長く残る |
| revoked | 即アーカイブ | 検索対象外、provenance として保持 |

### 2.3 Working（未解決・保留）

| 項目 | 内容 |
|------|------|
| テーブル | `working_items` |
| 役割 | 会話中の未解決の問い・保留事項を追跡 |
| 上限 | Context に同梱: 最大 3-7件 |
| TTL | `expires_at`（時間）or `ttl_turns`（ターン数） |
| 閉じる条件 | answered / user_revoked / stale / merged |
| 参照 | Context Builder が priority 順で注入 |

---

## 3. Context Builder（LLM に渡す文脈の組み立て）

```
=== PINNED FACTS ===          ← confirmed 高confidence semantic（常に表示）
- ユーザーは○○が好き
- ユーザーの名前は△△

=== PATTERNS ===              ← state_tag='insight'（R.4 で生成）
- ユーザーは夜型の傾向がある
- 技術的な話題で盛り上がりやすい

=== WORKING ===               ← open な working_items（priority 順）
[Q] ○○について詳しく聞きたい

=== LONG TERM ===             ← Query-Aware Retrieval (M.1) で検索
- (クエリに関連する semantic memories)

=== RECENT ===                ← 直近 N ターンの会話履歴
```

- **depth0**: PINNED FACTS のみ（高速応答のため最小限）
- **depth1/2**: フルコンテキスト（全セクション）

---

## 4. 記憶検索: Query-Aware Retrieval (Phase M.1)

従来の「confidence 順で固定8件」から、クエリの意図に応じた検索に改善。

```
ユーザー入力
    ↓
Step 1: Intent Detection [ルールベース]
    - temporal?  （「昨日」「前に」）→ recency 重視
    - recall?    （「〜だっけ」）→ similarity 重視
    - topic?     （名詞抽出）→ キーワードボーナス
    ↓
Step 2: Candidate Pool [並列実行]
    A) SQL: confidence DESC, limit=30
    B) Vec: cosine_sim(query, memory) ← multilingual embedding
    ↓
Step 3: Hybrid Scoring
    score = 0.45×similarity + 0.25×confidence + 0.15×recency + 0.15×intent_bonus
    （intent により動的調整）
    ↓
Step 4: Select Top-K (8件)
    重複排除 + 最低スコア閾値
```

- 埋め込みモデル: `paraphrase-multilingual-MiniLM-L12-v2`（日本語対応）
- LLM 呼び出し: 0回（検索パスにLLM不使用）
- レイテンシ: ~40ms

---

## 5. Autonomous Reflection（自律振り返り）

ユーザーが離席中に、ニアが自律的に会話を振り返り記憶を整理する。

### 5.1 トリガー（R.1: Idle Detector）

- `backend/services/idle_detector.py`
- 条件: `reflection_pending=1`（ターン閾値超過）AND ユーザー無入力 30分（`IDLE_THRESHOLD_MINUTES`）
- バックグラウンド asyncio ループ（120秒間隔でチェック）

### 5.2 Daily Log（R.2: Reflection Engine Phase 1）

- `backend/services/reflection_engine.py`
- 当日の `memory_events` を LLM で要約
- 保存先: `daily_reflections` テーブル（phase=`daily_log`）

### 5.3 Semantic 抽出（R.2: Reflection Engine Phase 2）

- daily_log から事実・好み・体験・約束を LLM で抽出
- 4カテゴリ: `origin_fact`, `preference`, `shared_event`, `nia_commitment`
- 保存先: `semantic_memories`（status=`inferred`）
- 保存先: `daily_reflections`（phase=`distillation`）

### 5.4 Cross-Day Distillation（R.4）

- 3日以上の daily_reflections から日横断パターンを抽出
- 4カテゴリ: `user_trait`, `relationship_pattern`, `emerging_interest`, `lesson`
- confidence cap: 3-4日→0.6, 5-6日→0.8, 7日+→0.9
- 保存先: `semantic_memories`（state_tag=`insight`）
- Context Builder の `=== PATTERNS ===` セクションに注入

---

## 6. Sleep Cycle（日次バッチ処理）

`backend/scripts/sleep_cycle/` パッケージ。手動実行 or スケジューラ起動。

### 6.1 処理フロー

```
1. 入力ソース選択
   ├── daily_reflections あり → Phase R.3 で前処理済みデータを使用
   └── なし → memory_events から直接取得（フォールバック）

2. Layer A: 印象記録
   └── LLM で mood / surprise / impressions を抽出

3. 夢の生成
   └── mood + surprise → 短い夢テキスト → dreams テーブル

3.5. 日記の生成（DIARY_ENABLED=True）
   ├── identity + memory_block + mood/impressions → LLM で日記生成
   ├── 保存先: daily_reflections（phase='diary'）
   └── TWITTER_AUTO_PROPOSE=True → 日記からツイート提案

4. Layer B: Identity 管理
   ├── proposal モード → identity.md への変更提案を生成 → 人間が承認
   └── adaptive モード → 小変更は自動適用、大変更は提案

5. Semantic 抽出（常時実行）
   ├── max(last_sleep, last_reflection) 以降の memory_events を処理
   └── Idle Reflection 処理済みイベントは境界値で自動スキップ

6. Semantic 確定
   ├── inferred → 24h 経過 → confirmed に昇格
   ├── 孤児参照スキャン（壊れた supersedes/revoked_by チェーン）
   └── Vector Sync（semantic → ChromaDB 同期）

7. Episodic 圧縮
   └── 古い memory_events → episodic_summaries に要約 → archive テーブルに移動

8. クリーンアップ
   ├── Vector Store GC
   └── LangGraph Checkpointer クリーンアップ
```

### 6.2 モジュール構成

| ファイル | 責務 |
|----------|------|
| `orchestrator.py` | メインフロー制御 |
| `helpers.py` | 共通定数、セクション管理、フィルタリング、夢生成 |
| `layers.py` | Layer A（印象）、Layer B（Identity 提案）、日記生成 |
| `extraction.py` | Episodic → Semantic 抽出（LLM バッチ） |
| `compression.py` | Episodic 圧縮 & アーカイブ |

---

## 7. データベーステーブル一覧

### 記憶系（コア）

| テーブル | 役割 | 書き込み元 |
|----------|------|-----------|
| `memory_events` | Episodic ログ（正のデータソース） | S5 Commit |
| `memory_events_archive` | 圧縮済み episodic の原本保存 | Sleep Cycle |
| `episodic_summaries` | 圧縮後の日次要約 | Sleep Cycle |
| `semantic_memories` | 事実・知識・パターン | Reflection Engine / Sleep Cycle |
| `working_items` | 未解決の問い・保留 | S5 Commit |
| `daily_reflections` | 日次振り返りログ + 日記 | Reflection Engine / Sleep Cycle (diary) |

### 記憶系（補助）

| テーブル | 役割 |
|----------|------|
| `memory_index` | 派生検索インデックス |
| `memory_judgments` | 記憶判定の監査ログ |
| `pending_actions` | 保留中アクション |
| `vector_sync_queue` | ベクトル同期キュー |

### その他

| テーブル | 役割 |
|----------|------|
| `messages` | チャット履歴 |
| `dreams` | 生成された夢 |
| `identity_proposals` | Identity 変更提案 |
| `telemetry_kv` | システム状態 KV |

---

## 8. 記憶のライフサイクル

```
会話ターン
    │
    ├── S5 Commit ──→ memory_events（episodic）
    │                  working_items（更新/クローズ）
    │
    ├── [30分後] Idle Detector トリガー
    │       │
    │       └── Reflection Engine
    │              ├── Phase 1: memory_events → daily_reflections (daily_log)
    │              ├── Phase 2: daily_log → semantic_memories (inferred)
    │              └── Phase 3 (R.4): 3日分 daily_reflections → semantic (insight)
    │
    └── [日次] Sleep Cycle
            ├── daily_reflections → Layer A → 夢 → 日記 → Layer B
            ├── memory_events → semantic 抽出（境界値で R.2 と重複排除）
            ├── inferred → confirmed（24h 確定ルール）
            ├── memory_events → episodic_summaries + archive（圧縮）
            └── semantic → ChromaDB（ベクトル同期）
```

---

## 9. 設定値一覧（.env）

| 設定 | デフォルト | 意味 |
|------|-----------|------|
| `ORCHESTRATOR_S5_ENABLED` | `True` | S5 Commit ノード有効化 |
| `DEPTH2_MIN_TURNS` | `100` | Depth2 発動に必要な累計ターン数 |
| `RETRIEVAL_ENABLED` | `True` | Query-Aware Retrieval 有効化 |
| `IDLE_DETECTION_ENABLED` | `True` | Idle Detector 有効化 |
| `IDLE_THRESHOLD_MINUTES` | `30` | 振り返りトリガーまでの無入力時間 |
| `IDLE_CHECK_INTERVAL_SEC` | `120` | Idle チェック間隔 |
| `EPISODIC_SUMMARY_ENABLED` | `True` | Episodic 圧縮有効化 |
| `LAYER_B_MODE` | `proposal` | `proposal`（人間承認）/ `adaptive`（小変更自動） |
| `DIARY_ENABLED` | `True` | Sleep Cycle 日記生成 |
| `TWITTER_AUTO_PROPOSE` | `False` | 日記/振り返りからツイート自動提案 |
| `EXPERIMENT_MODE` | `False` | Body Constitution チェックスキップ |

---

## 10. 将来計画

| 項目 | 状態 | 依存 |
|------|------|------|
| Phase F.2: call_model 分解（S3+S4 独立ノード化） | 未着手 | 安定運用後 |
| Phase M.2: Pinned Facts のクエリ連動並べ替え | 未着手 | M.1 安定後 |
| Phase M.3: Embedding Cache（encode 結果の DB 保存） | 未着手 | semantic 数百件超 |
| Phase M.4: 検索 Observability（スコア可視化） | 未着手 | M.2/M.3 後 |
| Depth2 有効化 + Context Builder キャッシュ層 | 未着手 | 累計100ターン + データ蓄積 |
| Legacy テーブル完全廃止 | 観察中 | ログ確認後 |
