# Memory System Redesign v2 - 設計決定事項

**作成日**: 2026-02-11
**ステータス**: Phase A〜G 完了、Phase R（Autonomous Reflection）完了

## 1. 全体アーキテクチャ

### コンポーネント構成
```
Orchestrator（状態機械: S0→S5）
Context Builder（折らない文脈組み立て）
Memory Store（Episodic / Semantic / Working の3層）
Retriever（引用優先 + provenance 必須）
Guardrail（エアバッグ: 止めるのではなく吸収して確認に戻す）
Generator（LLM: 構造化入力の上でのみ生成）
Commit（最後に1回、1トランザクション）
```

## 2. 1ターンの処理フロー（状態機械）

```
S0. SafetyInterrupt  [ルールベース]  → safe / clarify / block
S1. Pre-Thought      [ルールベース]  → WAIT / short_ack / need_info
    判定: dissonance + surprise スコア + ルール
S2. Organize         [LLM]          → plan = {intent, required_info, ask_one}
    現行 Depth 1 の organize_and_ask を再構成
S3. Retrieve         [ルールベース]  → memory_pack（必要時のみ）
S4. Answer           [LLM]          → 生成（DBに触らない）
S5. Commit           [ルールベース]  → 1トランザクションで保存
```

**LLM 呼び出し: 1〜2回/ターン（現行と同等）**

### 現行 Depth システムとの対応
- S0 = Safety ノード
- S1+S2 = Depth 0 + Depth 1 の再構成
- S3 = memory_context 取得の拡張
- S4 = merge_output の進化版
- S5 = **新規**（一括 Commit）

## 3. Memory Store 3層構成

### 3.1 Episodic（未解釈ログ）
- **テーブル**: 既存の `memory_events` をそのまま再定義
- **内容**: ほぼ生（軽い整形のみ）
- **メタデータ**: topic_tag(optional), turn_id, message_id, timestamp
- **移行コスト**: なし（テーブル変更不要）

### 3.2 Semantic（confirmed 中心 + 撤回・更新・期限）
- **テーブル**: 新規 `semantic_memories`
- **status**: inferred / confirmed / revoked
- **更新チェーン**: supersedes_id + revoked_by_id（双方向）
- **期限**: valid_from / valid_to / staleness_days
- **provenance**: source_turn_ids, source_event_ids

```sql
CREATE TABLE semantic_memories (
    id              TEXT PRIMARY KEY,
    thread_id       TEXT NOT NULL,
    content         TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'inferred',
    confidence      REAL NOT NULL DEFAULT 0.5,
    state_tag       TEXT,
    supersedes_id   TEXT,
    revoked_by_id   TEXT,
    revoke_reason   TEXT,
    valid_from      REAL NOT NULL,
    valid_to        REAL,
    staleness_days  REAL,
    source_turn_ids TEXT NOT NULL DEFAULT '[]',
    source_event_ids TEXT NOT NULL DEFAULT '[]',
    note            TEXT,
    seed_retention  REAL NOT NULL DEFAULT 0.5,
    vector_sync_pending INTEGER NOT NULL DEFAULT 1,
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);
CREATE INDEX idx_sm_thread_status ON semantic_memories(thread_id, status, created_at DESC);
CREATE INDEX idx_sm_status_valid  ON semantic_memories(status, valid_to);
CREATE INDEX idx_sm_supersedes    ON semantic_memories(supersedes_id) WHERE supersedes_id IS NOT NULL;
```

### 3.3 Working（未解決/保留/次の問い）
- **テーブル**: 新規 `working_items`
- **上限**: Context 同梱は最大 3〜7件（DB上は無制限）
- **TTL**: turns または expires_at
- **閉じる条件**: answered / user_revoked / stale / merged

```sql
CREATE TABLE working_items (
    id              TEXT PRIMARY KEY,
    thread_id       TEXT NOT NULL,
    item_type       TEXT NOT NULL,
    content         TEXT NOT NULL,
    priority        INTEGER NOT NULL DEFAULT 3,
    status          TEXT NOT NULL DEFAULT 'open',
    close_reason    TEXT,
    linked_semantic_ids TEXT NOT NULL DEFAULT '[]',
    linked_event_ids    TEXT NOT NULL DEFAULT '[]',
    merged_into_id  TEXT,
    ttl_turns       INTEGER,
    expires_at      REAL,
    created_turn_id TEXT NOT NULL,
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);
CREATE INDEX idx_wi_thread_open ON working_items(thread_id, status, priority) WHERE status = 'open';
```

## 4. Episodic → Semantic 昇格ルール

### S5 Commit で inferred 生成する条件（いずれか）
1. ユーザーが明示的に事実を述べた（「俺は〇〇が好き」「〇〇は△△だ」）
2. 複数ターンで同じテーマが繰り返された（Working で tracking 中）
3. CONSENT に該当する発話があった（同意・決定・約束）

### Sleep Cycle で確定
- inferred → 24時間以内に矛盾・撤回なし → **confirmed**
- inferred → 矛盾あり or ユーザー訂正 → **revoked**
- confirmed → 新情報で更新 → 旧を revoked、新を inferred（supersedes チェーン）

## 5. 忘却システム

### status ごとの半減期

| status    | 半減期(prod) | 半減期(fast) | 意味 |
|-----------|-------------|-------------|------|
| inferred  | 3日         | 0.5日       | 未確認 → 早く薄まる |
| confirmed | 30日        | 2日         | 確定済み → 長く残る |
| revoked   | 即アーカイブ | 即時         | 検索対象外、provenance として残る |

### state_tag → 初期 confidence
| state_tag   | confidence | 意味 |
|-------------|-----------|------|
| CONSENT     | 0.8       | Sleep で confirmed されやすい |
| PONDERING   | 0.5       | 中程度 |
| DISSONANCE  | 0.3       | confirmed になりにくい＝揺らぎのまま |
| DEFAULT     | 0.2       | 通常 |

### DISSONANCE の扱い（現行問題の解決）
- inferred のまま低 confidence、短い半減期
- 繰り返し言及されたら confidence 上昇 → Sleep で confirmed の道あり
- 「昇格しても検索に出ない」矛盾が解消

## 6. S5 Commit Plan

```python
commit_plan = {
    "episodic": [...],          # 生ログ（ほぼ毎ターン）
    "semantic_upsert": [...],   # inferred 候補（条件満たした時のみ）
    "semantic_revoke": [...],   # 撤回（矛盾検出時）
    "working_add": [...],       # 新規 Working item
    "working_close": [...],     # クローズ
    "diagnostics": {...}        # read-only、commit 対象外
}
```
- 1トランザクションで実行
- 失敗 → ROLLBACK（データ不整合なし）
- diagnostics は別系統（観測ログ）

## 7. Context 構造（折らない）

```
Context = Pinned + Patterns + Working(少量) + Recent + Retrieved(必要時)

A) Pinned Facts: confirmed高confidenceのsemantic（最優先・最短）
A') Patterns: 日横断パターン（state_tag='insight', R.4で生成）
B) Summary:
   B1: 座標（topic_label, current_goal, open_threads IDs）
   B2: 未解釈（断片、未確定の問い、未解釈メモID）
C) Working: 上位 3〜7件（Q / hold_reason / next_action）
D) Recent Window: 直近Nターン（温度と文脈）
E) Retrieved: Retriever が取得した引用・事実（必要時のみ）
```

人格説明・世界観は Context に入れない（固着防止）

## 8. Guardrail 展開条件

- provenance 無しの主張を出しそう
- semantic 同士が矛盾（revoked/supersedes 未反映含む）
- summary と recent が食い違う
- working が同一テーマで 3ターン停滞
- 引用が必要な場面で要約で済ませようとした
- retrieval 結果が薄いのに断定しそう

**展開後**: 引用提示→確認質問1つ / WAIT / revoke 候補を commit_plan へ

## 9. 実装上の制約と決定事項（レビュー反映 2026-02-11）

### 9.1 参照整合性（supersedes_id / revoked_by_id）
- FK制約は**張らない**（将来の revoked アーカイブ時に CASCADE 設計が重くなるため）
- S5 Commit のアプリケーション層で参照先存在チェックを実施
- Sleep Cycle で孤児参照の定期スキャンを追加（存在しない ID を参照 → ログ警告 + note に記録）

### 9.2 source_turn_ids / source_event_ids の格納形式
- **Phase B〜D**: JSON 配列文字列（`json_each()` で展開可能）
- 主な参照方向: semantic → source（provenance 表示）は JSON で十分
- 逆引き（turn_id → semantic）が頻繁に必要になった場合、**Phase E (Guardrail) で中間テーブル追加を再評価**

### 9.3 ベクタストア更新と外部副作用
- SQLite commit を**先に実行**（SQLite が正のデータソース）
- ベクタ更新（ChromaDB）は**ベストエフォート + リトライ**
- `semantic_memories` に `vector_sync_pending` カラム（BOOLEAN DEFAULT 1）を追加
- 未同期レコードは次回 Sleep / boot 時に再同期
- 失敗してもデータ整合は SQLite 側で保証

### 9.4 Sleep Cycle 失敗時の catch-up
- Sleep Cycle はべき等（idempotent）設計にする
- `last_sleep_completed_at` を記録（既存の sleep_outputs/ に追加）
- 次回起動時に前回失敗を検知 → catch-up 実行
- 「24h ルール」の正確な解釈: **次回 Sleep 実行時に `created_at` から24h以上経過していれば確定対象**
- Sleep が48h以上実行されなかった場合でも、同じロジックで一括処理（特別な分岐は不要）

### 9.5 revoked レコードのアクセス経路
- **通常検索（Retriever）**: `WHERE status IN ('confirmed', 'inferred')` → revoked 除外
- **ID 直接取得**: `get_by_id(id)` → status 不問（provenance 参照用）
- **チェーン辿り**: `get_chain(id)` → supersedes/revoked_by を辿って全チェーン返却（revoked 含む）
- **UI 表示**: revoked は取消線 + グレーアウトで視覚的に区別

### 9.6 Working TTL の優先順位
- `expires_at` が設定されていれば**絶対優先**（時間ベース）
- `ttl_turns` は `expires_at` 未設定時のフォールバック
- ターン減算は**ユーザー発話単位**（システムイベントは数えない）
- 両方 null の場合: TTL なし（明示的に閉じるまで残る）
- 評価タイミング: S5 Commit 内で TTL チェック → expired なら `working_close` に追加

### 9.7 移行手順（レガシーテーブル）
- **Phase B**:
  1. `semantic_memories` テーブル作成
  2. `LEGACY_MEMORY_READ_ONLY=True` に設定（新規書き込みは semantic_memories のみ）
  3. バックフィルスクリプト: `long_term_memories` → `semantic_memories` に `status=confirmed` で一括コピー
  4. 整合検証: コピー後のレコード数・内容一致チェック
- **ロールバック条件**: `LEGACY_MEMORY_TABLES_ENABLED=True` に戻せば旧テーブルも使える（既存フラグ）
- **完全廃止**: Phase F 完了後、旧テーブルの DROP は手動判断（自動では行わない）

## 10. 実装フェーズ

```
Phase A: search_memory() バグ修正 + 既存バグ対応                             ← 完了（2026-02-11）
Phase B: semantic_memories テーブル + S5 Commit 一括化 + vector_sync_pending + バックフィル + 孤児スキャン ← 完了
Phase C: working_items テーブル + TTL/close ロジック（TTL 優先順位ルール含む） ← 完了
Phase D: Context Builder 再構成                                              ← 完了
Phase E: Guardrail 展開条件の明文化（source 中間テーブル化を再評価）          ← 完了（2026-02-12）
Phase F.1: S5 Commit ノード + Depth2 ゲート + S1 Pre-Thought                ← 完了（2026-02-12）
Phase G: Semantic extraction → Sleep Cycle 移行 + Context Builder 統合 + 二重パス解消 ← 完了（2026-02-13）
Phase R: Autonomous Reflection（R.1〜R.4）                                     ← 完了（2026-02-19）
Phase F.2: call_model 分解（S3+S4）+ ノード名変更（将来）
```

### Phase R 実装詳細（Autonomous Reflection, 2026-02-19）

4段階の自律振り返りパイプライン:

| Phase | 名前 | ファイル | 内容 |
|-------|------|---------|------|
| **R.1** | Idle Detection | `services/idle_detector.py` | 3分以上の無入力を検出、振り返りトリガー |
| **R.2** | Daily Log | `services/reflection_engine.py` | セッション中の会話を LLM で振り返り → `daily_reflections` テーブル |
| **R.3** | Sleep Cycle 連携 | `scripts/sleep_cycle.py` | daily_reflections → memory_block 変換。利用可能時は memory_events フォールバック不要。semantic extraction もスキップ |
| **R.4** | Cross-Day Distillation | `services/reflection_engine.py` | 3日以上の daily_reflections を分析、日横断パターンを抽出 |

#### R.4 パターンカテゴリ
- `user_trait`: ユーザーの一貫した特性
- `relationship_pattern`: ニアとユーザーの関係パターン
- `emerging_interest`: 新しく浮上した関心テーマ
- `lesson`: 繰り返し現れた教訓

#### R.4 Confidence Cap
| データ日数 | cap |
|-----------|-----|
| 3-4日 | 0.6 |
| 5-6日 | 0.8 |
| 7日+ | 0.9 |

保存先: `semantic_memories` (`state_tag='insight'`)
注入先: Context Builder の `=== PATTERNS ===` セクション（Depth1/2 で自動表示）

### クリーンアップ（2026-02-19）
- **P2**: Context Builder に `=== PATTERNS ===` セクション追加（`_build_patterns()` 関数）
- **P4**: `_extract_legacy_fragments()` + `long_mem` パラメータを削除（デッドコード除去）

### Depth2 と Phase F の関係（決定事項 2026-02-12）
- Phase F の S2 (Organize) に Depth2（結論層）の**分岐枠**を設計に含める
- S2 内で `if depth2_conditions_met: conclude else: organize` の型を入れる
- 発動条件: `confidence >= 0.85 AND context_coverage >= 0.7 AND 累計100ターン以上`
- 実際の発動はゲート（累計ターン閾値）で封じたまま。記憶データが十分溜まってから有効化
- Depth2 の実装自体は Phase F の型に後から追加する形で行う

### Phase F.1 実装詳細（2026-02-12）
- **S5 Commit ノード**: `s5_commit()` を graph に追加（action_processing → s5_commit → END）
  - `ORCHESTRATOR_S5_ENABLED` フラグ制御（デフォルト OFF）
  - episodic event 保存のみ（semantic 生成は Sleep Cycle に移行済み）
- **Depth2 ゲート**: depth_selector 内で `_get_cumulative_turn_count()` + `DEPTH2_MIN_TURNS`(100) + context_coverage >= 0.7 のAND条件
- **S1 Pre-Thought**: dissonance_check に `pre_thought_action` 追加（WAIT / short_ack）

### Phase G 実装詳細（2026-02-13）
- **Semantic extraction → Sleep Cycle 移行**: S5 から regex ベースの事実抽出を削除。Sleep Cycle に `_extract_semantics_from_episodic()` を追加（LLM バッチ抽出）
- **Context Builder 統合**: depth0/1/2 にメモリコンテキストを注入
  - `safety_interrupt` で config → state に thread_id 伝播
  - `depth_selector` で `build_memory_context()` → state.memory_context に格納
  - depth0: PINNED FACTS のみ、depth1/2: フルコンテキスト
- **二重パス解消**: `ORCHESTRATOR_S5_ENABLED=True` 時に `analyze_and_save_memory` をスキップ（S5 に一本化）

## 11. 既存システムとの関係

| 既存 | 新設計 | 移行 |
|------|--------|------|
| memory_events | Episodic（そのまま） | 変更なし |
| episodic_captures | 廃止候補 | semantic_memories に吸収 |
| long_term_memories | 廃止候補 | confirmed semantic に対応 |
| retention_sweeper | status ベース半減期に改修 | Phase B で対応 |
| pending_actions | Working items に統合 | Phase C で対応 |
| Depth 0/1 | S0-S5 状態機械 | Phase F で対応 |
