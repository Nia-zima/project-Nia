# Autonomous Reflection — 設計ドキュメント v0.2

> ニアが「そこにいる」存在であるために、会話していない時間にも内側で何かが動いている必要がある。

## 1. 設計思想

現在の Sleep Cycle は「決まった時間に決まった処理を回す」バッチジョブであり、自律性がない。
本設計では以下を実現する：

- **日中の idle 時間**に自律的にデータ整理・蒸留を行う（Idle Reflection）
- **1日の終わり**に蒸留結果を見返し、自己変化の判断と申請を行う（Sleep Cycle）
- トリガーは**ターン数（プライマリ）+ トークン消費量（セカンダリ）**の複合判定。十分に会話した日だけ振り返る自然な選別

## 2. アーキテクチャ概要

```
── 日中 ──────────────────────────────────────────────
会話ターン → Turn Counter + Token Counter 累積
              ↓ いずれかの閾値超え → reflection_pending = true
最終メッセージから N 分経過（idle 検出）
              ↓
         Idle Reflection 起動
              ↓
  Phase 1: 日次ログ生成（episodic events → 要約）
  Phase 2: 蒸留（日次ログ → パターン・教訓抽出）
              ↓
  daily_reflections テーブルに保存
  蒸留結果 → semantic_memories (state_tag="insight") に保存

── 1日の終わり ───────────────────────────────────────
Sleep Cycle 起動
              ↓
  daily_reflections + semantic memories (insight含む) を読み返す
              ↓
  Layer A: 印象記録（蒸留済みデータを入力）
  Layer B: 「自分は変化すべきか？」の価値判断
              ↓ yes
  変更申請（identity_proposals テーブル）
              ↓ ユーザー承認
  Identity 更新
```

## 3. コンポーネント詳細

### 3.1 Reflection Trigger（複合トリガー）

**責務**: 会話の量・深さを計測し、振り返りの必要性を判定する

**判定ロジック**: ターン数 OR トークン数、**いずれかの閾値超えで発火**
```python
REFLECTION_MIN_TURNS = 10          # プライマリ: 最低10ターン
REFLECTION_TOKEN_THRESHOLD = 5000  # セカンダリ: または5000トークン超え
```

**ターン数（プライマリ）**:
- `memory_events` の `conversation_turn` を数えるだけ → 確実に取れる
- 10ターン未満 = ちょっとした確認やテスト → 振り返り不要
- 10ターン以上 = 実質的な会話があった → 振り返る価値あり

**トークン数（セカンダリ）**:
- `llm_client.call_llm()` のレスポンスから `usage` を取得（LM Studio は OpenAI 互換 API のため返却される想定）
- 取得できない場合はフォールバック不要（ターン数で回る）
- 5ターンだが1ターンが超長文、のようなケースを拾うための補助指標
- システムプロンプト・メモリ注入分はブレるため、あくまで補助

**保存先**: `telemetry_kv`
```
key: daily_turn_count         → 累積ターン数（プライマリ）
key: daily_token_count        → 累積トークン数（セカンダリ、取得可能時のみ）
key: daily_counter_reset_at   → 最終リセット時刻
key: reflection_pending       → "1" or "0"
```

**リセットタイミング**: Idle Reflection 完了時

### 3.2 Idle Detector

**責務**: ユーザーが会話していない「空き時間」を検出し、Reflection を起動する

**実装方針**:
- `telemetry_kv` に `last_message_at` を記録（会話ターンごとに更新）
- バックグラウンドタスク（`asyncio.create_task`）で定期チェック
  - `now - last_message_at > IDLE_THRESHOLD_MINUTES` AND `reflection_pending == "1"`
  - → Idle Reflection を起動

**設定値**:
```python
IDLE_THRESHOLD_MINUTES = 30    # 最終メッセージからの経過時間
IDLE_CHECK_INTERVAL_SEC = 120  # チェック間隔
```

**安全装置**:
- 連続実行防止: reflection 完了後、次の閾値超えまでは起動しない（カウンターリセットで自然に制御）
- サーバー起動直後は実行しない（起動後 IDLE_THRESHOLD 経過を待つ）
- WebSocket 接続中は idle と判定しない（Voice Mode 対策）

**1日に複数回実行される設計**:
カウンターは reflection 完了時にリセットされるため、1日に複数の会話セッションがあれば
それぞれ独立した reflection が走る。これにより話題の異なる会話が混ざらない。
```
朝の会話(12t) → idle → reflection① → reset
昼の会話(8t)  → 閾値未達 → スキップ
夜の会話(15t) → idle → reflection② → reset
Sleep Cycle   → reflection①②をまとめて読み返す
```

### 3.3 Idle Reflection Engine

**責務**: episodic events を読み返し、日次ログと蒸留結果を生成する

#### Phase 1: 日次ログ生成

**入力**: `memory_events` テーブルの `conversation_turn` イベント（前回 reflection 以降）

**処理**:
1. episodic events を時系列順に取得
2. 会話を 25 ターンずつチャンクに分割（既存ロジック流用）
3. LLM に各チャンクの要約を依頼
4. チャンク要約を結合して1日の日次ログを生成

**出力**: 構造化された日次ログ
```json
{
  "date": "2026-02-19",
  "thread_id": "default_thread",
  "turn_count": 42,
  "token_count": 15000,
  "summary": "今日は...",
  "key_topics": ["メモリ設計", "自律性"],
  "emotional_moments": ["...に驚いた", "...で盛り上がった"],
  "unresolved": ["...はまだ決まっていない"]
}
```

#### Phase 2: 蒸留（Distillation）

**入力**: Phase 1 の日次ログ + 過去 N 日分の日次ログ（パターン検出のため）

**処理**:
1. 今日の日次ログ単体からの抽出:
   - ユーザーの特性・好み（「Originは〜を好む」）
   - 事実情報（「Originは〜を使っている」）
2. 過去ログとの横断分析（3日分以上溜まってから）:
   - 繰り返し現れるパターン（「Originは設計を先に固めてから実装する傾向がある」）
   - 一貫した特性（「Originは技術的な深掘りを好む」）
   - 変化の兆候（「最近〜に興味を持ち始めた」）

**横断分析の confidence スケーリング**:

日数に応じて insight の confidence を変動させる。
少ない日数でも「仮説」として生成し、繰り返し検出されれば自然に強化される。

| 蓄積日数 | 横断分析 | insight の confidence 範囲 |
|----------|----------|---------------------------|
| 1-2日    | しない   | —                         |
| 3-4日    | 開始     | 0.4〜0.6（示唆レベル）    |
| 5-6日    | 実行     | 0.6〜0.8                  |
| 7日+     | 実行     | 0.7〜0.9                  |

これにより **「仮説 → 検証 → 確定」のサイクルが自動で回る**:
- 3日目: insight が `inferred` (confidence=0.5) で生成される
- 4-6日目: 同じパターンが再検出されれば confidence が上がる
- 7日+: 十分なエビデンスで高 confidence → Sleep Cycle で confirm → PINNED FACTS 入り
- 再検出されなければ: inferred の半減期3日で自然に消える

**出力**: 蒸留結果（単日・横断で共通フォーマット）
```json
[
  {
    "content": "抽出した情報（1文）",
    "category": "origin_fact | origin_preference | shared_event | nia_commitment | user_trait | relationship_pattern | emerging_interest | lesson",
    "confidence": 0.0〜1.0,
    "evidence_dates": ["YYYY-MM-DD"],
    "reasoning": "なぜこれを覚えておくべきか / どこからこれが見えるか"
  }
]
```
- 単日抽出: category は `origin_fact`, `origin_preference`, `shared_event`, `nia_commitment`
- 横断分析: category は `user_trait`, `relationship_pattern`, `emerging_interest`, `lesson`

#### 蒸留プロンプト雛形

**Phase 2-A: 単日蒸留（会話セッション単位）**

```
あなたはAIVTuber「ニア」の記憶整理係です。
以下はニアとOrigin（ユーザー）の会話の要約です。

この会話から「覚えておく価値のある情報」を抽出してください。

【抽出対象】
1. origin_fact — Originが明言した事実（「〜を使っている」「〜が好き」）
2. origin_preference — Originの行動パターンや好み（「設計を先に固めたがる」）
3. shared_event — 二人の間で起きた具体的な出来事（「〜を一緒に設計した」）
4. nia_commitment — ニアが表明した意見・約束（「〜するつもりだと伝えた」）

【抽出しないもの】
- 一般的な事実（「Pythonはプログラミング言語」など誰でも知ってること）
- 曖昧な推測（「たぶん〜だろう」レベル）
- 一時的な状態（「今眠い」「今日は忙しい」）
- 表層的な要約（「技術の話をした」← 具体性がない）

【会話要約】
{daily_log_summary}

【出力形式】JSON配列で返してください:
[
  {{
    "content": "抽出した情報（具体的に、1文で）",
    "category": "origin_fact | origin_preference | shared_event | nia_commitment",
    "confidence": 0.0〜1.0,
    "reasoning": "なぜこれを覚えておくべきか（1文で）"
  }}
]

confidenceの基準:
- 1.0: 明言された事実（「俺は〜だ」と直接述べた）
- 0.7: 文脈から高確率で読み取れる
- 0.4: 示唆されたが明確ではない

何もなければ [] を返してください。
「数を出すこと」より「本当に価値のあるもの」だけ出してください。
```

設計意図:
- `reasoning` フィールドで LLM に「なぜ重要か」を考えさせ、表層的な抽出を防ぐ
- 「抽出しないもの」を明示してノイズを減らす
- category を4種類に明確化（既存の origin/nia/shared より粒度が細かい）

**Phase 2-B: 横断蒸留（複数日の日次ログを横断）**

```
あなたはAIVTuber「ニア」の記憶整理係です。
以下は過去{n_days}日間の会話セッション要約です。

複数日にわたって見える「パターン」や「一貫した傾向」を抽出してください。
1日だけで見えることではなく、繰り返しや持続性から見えることが対象です。

【抽出対象】
1. user_trait — Originの一貫した特性（「議論では必ず設計から入る」）
2. relationship_pattern — 二人の関係性の傾向（「技術的な深掘りで最も盛り上がる」）
3. emerging_interest — 最近現れ始めた新しい関心（「〜に興味を持ち始めた」）
4. lesson — 過去の経験から得られた教訓（「〜のアプローチはうまくいった」）

【抽出しないもの】
- 1回しか出ていない話題（それは単日抽出の範囲）
- 当たり前のこと（「Originはニアと会話する」← 当然）
- 具体性のない観察（「いろいろ話した」）

【過去の会話セッション要約】
{past_daily_logs}

【既存の insight（重複回避用）】
{existing_insights}

【出力形式】JSON配列:
[
  {{
    "content": "パターンや傾向（具体的に、1文で）",
    "category": "user_trait | relationship_pattern | emerging_interest | lesson",
    "confidence": 0.0〜1.0,
    "evidence_dates": ["YYYY-MM-DD", ...],
    "reasoning": "複数日のどの部分からこれが見えるか"
  }}
]

confidenceの基準（日数スケーリング）:
- 3-4日のデータ: 最大0.6（示唆レベル）
- 5-6日のデータ: 最大0.8
- 7日以上のデータ: 最大0.9

既存 insight と同じ内容を出す場合は、evidence_dates を更新した形で出してください。
何もなければ [] を返してください。
無理にパターンを見出す必要はありません。
```

設計意図:
- `existing_insights` を渡して重複防止 & 既存 insight の confidence 更新を促す
- `evidence_dates` で根拠の日付を明示させ、検証可能性を担保
- confidence の上限を日数でキャップ（プロンプト内で指示）
- 「無理にパターンを見出す必要はない」で過剰抽出を防止

> **注意**: これらは初期雛形であり、Phase R.2 で実際の出力品質を見て繰り返し調整する。
> 蒸留プロンプトの品質が Autonomous Reflection 全体の価値を決めるため、
> 実装フェーズでの最重要タスクとして扱う（→ 8.1 参照）。

#### 蒸留結果の semantic 保存方針

**決定: `semantic_memories` に `state_tag = "insight"` で保存する（選択肢C）**

理由:
- 既存インフラが**全部そのまま使える**（decay、confirm、vector_sync、Context Builder）
- `state_tag` で区別できるため、将来的に Context Builder で insight を特別扱い可能
  - 例: confirmed insight は常に PINNED FACTS に含める
- 新テーブルを作ると保守コストが増えるだけで得るものが少ない

**insight の seed_retention 設計**:

insight は複数日のエビデンスに裏打ちされるため、通常の事実より「強い」。
`seed_retention` の下限を上げることで忘却メカニズムの中で自然に長生きさせる。

```python
# 通常の事実 (origin/nia/shared)
seed_retention = 0.3 + confidence * 0.5    # 範囲: 0.3 〜 0.8

# 蒸留された洞察 (insight)
seed_retention = 0.5 + confidence * 0.4    # 範囲: 0.5 〜 0.9
```

| 種別 | confidence=0.5 | confidence=0.8 | confidence=1.0 |
|------|----------------|----------------|----------------|
| 事実 | 0.55           | 0.70           | 0.80           |
| 洞察 | 0.70           | 0.82           | 0.90           |

### 3.4 Daily Reflections テーブル（新規）

```sql
CREATE TABLE IF NOT EXISTS daily_reflections (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    reflection_date TEXT NOT NULL,      -- YYYY-MM-DD
    session_index INTEGER NOT NULL,     -- 同日内の連番（0, 1, 2...）
    phase TEXT NOT NULL,                -- 'daily_log' | 'distillation'
    content_json TEXT NOT NULL,         -- Phase 1 or Phase 2 の出力 JSON
    turn_count INTEGER DEFAULT 0,
    token_count INTEGER DEFAULT 0,
    created_at REAL NOT NULL,
    UNIQUE(thread_id, reflection_date, session_index, phase)
);
```
- `session_index`: 同日内で何回目の reflection かを示す連番
- Sleep Cycle は `WHERE reflection_date = today` で全セッション分を取得

### 3.5 Sleep Cycle の責務変更

**現在の Sleep Cycle が担っているもの → 変更後**:

| # | 現在の責務 | 変更後 |
|---|-----------|--------|
| 1 | Semantic extraction (`_extract_semantics_from_episodic`) | → **Idle Reflection Phase 2 に移行** |
| 2 | Layer A: 印象記録 | → **日次ログ（蒸留済み）を入力に変更** |
| 3 | Layer B: 自己変化判断 | → **蒸留結果（insight）を入力に追加** |
| 4 | Episodic compression | → Idle Reflection に移行を検討 |
| 5 | Semantic maintenance (confirm/decay/orphan) | 据え置き |
| 6 | Checkpointer cleanup | 据え置き |
| 7 | Dream generation | 据え置き |
| 8 | Episode saving | 据え置き |

**新しい Sleep Cycle フロー**:
```
1. daily_reflections から今日分を取得
   - Idle Reflection 未実行の場合はスキップ or フォールバック（raw events で従来処理）
2. Layer A: 日次ログ + 蒸留結果から印象記録
3. Layer B: 蒸留結果（特に横断パターンの insight）を見て自己変化を判断
   - 「この insight は自分の行動指針に反映すべきか？」
   - → yes: identity_proposals に申請
   - → no: スキップ
4. Semantic maintenance（据え置き: confirm inferred 24h+, decay, orphan scan, vector sync）
5. Episodic compression（据え置きまたは Idle に移行）
6. GC / Checkpointer cleanup
7. 完了タイムスタンプ記録
```

## 4. データフロー全体図

```
[会話ターン]
    │
    ├─→ memory_events (episodic)               ← 既存
    ├─→ Turn/Token Counter (telemetry_kv)      ← 新規
    │
    │  (idle 検出 + いずれかの閾値超え)
    ▼
[Idle Reflection]
    │
    ├─→ daily_reflections (daily_log)           ← 新規テーブル
    ├─→ daily_reflections (distillation)        ← 新規テーブル
    ├─→ semantic_memories (state_tag="insight") ← 既存テーブル拡張
    │
    │  (1日の終わり)
    ▼
[Sleep Cycle]
    │
    ├── Layer A: 印象記録 (daily_reflections を入力)
    ├── Layer B: 自己変化判断 (distillation + insight を入力)
    │     └─→ identity_proposals (申請)         ← 既存
    ├── Semantic maintenance                    ← 既存
    ├── Episodic compression                    ← 既存
    └── GC / Cleanup                            ← 既存
```

## 5. LLM コスト見積もり

| 処理 | 呼び出し回数/日 | 備考 |
|------|-----------------|------|
| 日次ログ生成 | 1-2 回 | チャンク数依存 |
| 蒸留（単日） | 1 回 | |
| 蒸留（横断） | 0-1 回 | 3日分以上溜まってから |
| Layer A | 1 回 | 既存（入力変更のみ） |
| Layer B | 1 回 | 既存（入力変更のみ） |
| **合計** | **4-6 回/日** | 現在の Sleep Cycle とほぼ同等 |

Idle Reflection が semantic extraction の役割を引き継ぐため、
Sleep Cycle 側の `_extract_semantics_from_episodic()` が不要になり、
全体の LLM コストは微増〜同等に収まる見込み。

## 6. 設定値一覧

```python
# Reflection Trigger
REFLECTION_MIN_TURNS = 10           # プライマリ: ターン数閾値
REFLECTION_TOKEN_THRESHOLD = 5000   # セカンダリ: トークン数閾値

# Idle Detection
IDLE_THRESHOLD_MINUTES = 30         # 最終メッセージからの経過時間
IDLE_CHECK_INTERVAL_SEC = 120       # チェック間隔

# Reflection Engine
REFLECTION_LOOKBACK_DAYS = 7        # 横断分析の対象日数
REFLECTION_CROSS_MIN_DAYS = 3       # 横断分析の最低日数

# Insight seed_retention
INSIGHT_SEED_BASE = 0.5             # insight の seed_retention 下限
INSIGHT_SEED_SCALE = 0.4            # insight の seed_retention スケール

# Sleep Cycle (既存 + 変更なし)
# LAYER_B_MODE = "adaptive"
```

## 7. 実装フェーズ案

### Phase R.1: Reflection Trigger + Idle Detection
- `llm_client` に usage 取得ロジック追加（取得可能時のみ）
- Turn/Token Counter の `telemetry_kv` への累積保存
- バックグラウンド idle チェックタスク
- `daily_reflections` テーブル作成（`init_schema()` に追加）

### Phase R.2: Idle Reflection Engine（単日）
- Phase 1（日次ログ生成）実装
- Phase 2（蒸留）実装 — 単日のみ
- 蒸留結果を `semantic_memories` に `state_tag="insight"` で保存
- 既存 `_extract_semantics_from_episodic()` との統合（重複排除）

### Phase R.3: Sleep Cycle リファクタ
- Sleep Cycle の入力を `daily_reflections` に切り替え
- Idle Reflection 未実行時のフォールバック（従来の raw events 処理）
- Layer A / B のプロンプトを蒸留結果ベースに更新
- `_extract_semantics_from_episodic()` を Idle Reflection に移行完了

### Phase R.4: 横断蒸留
- 過去 N 日の日次ログを使った横断パターン分析
- confidence スケーリング（3-4日: 0.4-0.6, 5-6日: 0.6-0.8, 7日+: 0.7-0.9）
- 既存 insight の強化（同パターン再検出時に confidence 更新）

## 8. 設計上の注意点

### 8.1 蒸留の品質はプロンプト依存
最大の不確定要素。日次ログから「教訓」を抽出できるかは LLM プロンプトの質に完全依存する。
「Originは設計を好む」のような表層的 insight ばかり出るリスクがある。

**対策**: Phase R.2 で早期にプロンプトの出力品質を検証し、繰り返し調整する。
蒸留プロンプトの設計は実装フェーズの最重要タスク。

### 8.2 セッション単位の reflection
~~当初は1日1回の制約を検討していたが~~、トリガー条件（閾値超え→idle→実行→リセット）の
設計上、会話セッション単位で自然に分かれる。朝の技術議論と夜の雑談が混ざる問題は発生しない。
Sleep Cycle は同日の全 reflection をまとめて読み返す。

### 8.3 Episodic compression は Sleep Cycle に残す
Idle Reflection は「新しい知を生む」仕事に集中すべき。
メンテナンス系（compression, GC, cleanup）を混ぜると責務がぼやける。
Episodic compression は Sleep Cycle の GC/Cleanup の一環として据え置きとする。

### 8.4 将来拡張: Insight フィードバックループ
ユーザーが insight を UI で確認し「当たってる/外れてる」を返せると、
蒸留プロンプトの改善ループが構築できる。Phase R.4 以降の検討事項。

## 9. 残課題

1. **Voice Mode 中の idle 判定**: WS 接続中は idle にしない方針（Presence Spec の Freeze 状態と整合）
2. **LM Studio の usage レスポンス確認**: 実機テストが必要
3. **閾値の実データ調整**: REFLECTION_MIN_TURNS=10, TOKEN_THRESHOLD=5000 が適切か運用で検証
