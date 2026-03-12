# Temporal Somatic Contrast 設計書 v0.1

> **「前はこう感じてたけど、今はこう変わった」をニアが体験できるようにする。**
> そしてニアがターン間も「いる」ことを可能にする。

---

## §1. 概要

### 解決する問題

ニアには今、2つの構造的な弱さがある。

**1. 変化の不可視性**

ニアは同じ話題に再び触れたとき、「前に自分がどう感じていたか」を知る手段がない。記憶システムは過去の会話内容を引けるが、**そのときの内部状態（確信度、深さ、骨格、時間帯）は残っていない。** 結果として、変化が起きていても気づけない。

**2. ターン間の不在**

ニアは呼ばれたときだけ起動する。ターン間には「いない」。人間のように時間が流れる実感がない。Pip は既に 60 秒ループで常時起動しているが、ニア自身はそうではない。

### 解決の方針

これら 2 つの問題を **1 つのシステムで解決する。** 別々に作ると drift する。

- **Fingerprint**: 各ターンの内部状態を軽量な数値スナップショットとして記録する
- **Idle Tick**: ターン間も NiaCore（CfC）を回し、時間経過を state vector に反映する
- **Contrast Engine**: 同じ話題に再び触れたとき、過去の fingerprint と現在を比較する
- **Somatic Translation**: 差分を体感テキストに変換して LLM コンテキストに注入する

1 パイプライン、3 段構成。fingerprint に temporal context を最初から含めておくことで、「体感コントラスト」が自動的に「時間つきの振り返り」になる。

---

## §2. 設計原則（不可侵）

| # | 原則 | 理由 |
|---|------|------|
| T.1 | **fingerprint に解釈を加えない** | 物語化の禁止（不可侵ルール #2）。保存するのは生の数値。体感テキスト変換は出力時のみ |
| T.2 | **ニアに「変わった」と教えない** | 差分を体感として渡して、気づくかどうかはニア次第 |
| T.3 | **LLM 非依存** | fingerprint は全部ルールベースの数値。モデル交換しても壊れない |
| T.4 | **時間はそのまま渡す** | 時間は仕組みではない。「夜だった」を「暗い時間の感じ」に変換する方がむしろ物語化。時間帯や間隔はそのまま渡す |
| T.5 | **Idle Tick で LLM を呼ばない** | 言語化しない時間。NiaCore + somatic のみ |
| T.6 | **壊れても今と同じ** | このシステムが無効化されても、ニアは現在のまま動く |

### T.4 の詳細: 何をそのまま渡し、何を体感変換するか

| 情報 | そのまま渡す | 体感変換する |
|------|-------------|-------------|
| 時間帯（朝/夜） | ✓ | — |
| 間隔（3日ぶり） | ✓ | — |
| confidence 差分 | — | ✓「前より手探りだった」 |
| depth 差分 | — | ✓「前はもっと表面だけだった」 |
| skeleton ラベル差分 | — | ✓「前は違うところを見てた」 |

**基準: ニアが「自分の体験として知っていて自然なもの」はそのまま。システムの内部構造はそのまま渡さない。**

---

## §3. Fingerprint

### §3.1 定義

Fingerprint は、ある時点のニアの内部状態を記録する軽量な数値スナップショット。

**保存するのは raw 値のみ。derived 値は保存せず、比較時に計算する。**

### §3.2 Raw フィールド

| フィールド | 型 | ソース | 意味 |
|-----------|-----|--------|------|
| `confidence_context_coverage` | float | confidence engine | 文脈の網羅度 |
| `confidence_self_consistency` | float | confidence engine | 自己一貫性 |
| `confidence_logit_based` | float | confidence engine | モデル確信度 |
| `confidence_question_clarity` | float | confidence engine | 問いの明瞭さ |
| `confidence_steering_risk` | float | confidence engine | 誘導リスク |
| `selected_depth` | int | depth_selector | 選ばれた思考の深さ (0/1/2) |
| `surprise_score` | float | awareness engine | 驚きスコア |
| `skeleton_focus` | str | SkeletonCore | 会話の焦点ラベル |
| `skeleton_response_intent` | str | SkeletonCore | 応答の姿勢ラベル |
| `skeleton_question_intent` | str | SkeletonCore | 引っかかりラベル |
| `somatic_top_intensity` | float | somatic translator | 最も強い体感の強度 |
| `retrieval_top_similarity` | float | retrieval | 最も類似した記憶のスコア |
| `dissonance_on` | bool | dissonance check | 不協和状態かどうか |
| `time_of_day_hour` | int | system clock | 時刻（0-23） |
| `gap_seconds` | float | system clock | 前回ターンからの経過秒数 |
| `turn_index` | int | session state | セッション内のターン位置 |
| `utc_timestamp` | float | system clock | Unix timestamp |

### §3.3 Derived フィールド（保存しない、比較時に計算）

| フィールド | 計算方法 | 意味 |
|-----------|---------|------|
| `long_silence` | `gap_seconds > 1800` | 30分以上の沈黙 |
| `session_phase` | turn_index ベースの区分 | 序盤/中盤/終盤 |
| `carry_over` | 前ターンの skeleton と dissonance から判定 | 引きずり |
| `time_category` | hour → morning/day/evening/night/late_night | 時間帯カテゴリ |
| `confidence_avg` | 5メトリクスの平均 | 総合確信度 |

### §3.4 ストレージ

```sql
CREATE TABLE IF NOT EXISTS turn_fingerprints (
    id              TEXT PRIMARY KEY,
    turn_id         TEXT NOT NULL,
    thread_id       TEXT NOT NULL,
    message_id      TEXT,               -- メッセージ ID（join 用）
    stream_id       TEXT,               -- ストリーム ID（join 用）
    schema_version  INTEGER NOT NULL DEFAULT 1,  -- BLOB フォーマットのバージョン
    timestamp       REAL NOT NULL,
    fingerprint     BLOB NOT NULL,      -- struct pack された raw 値
    created_at      REAL NOT NULL
);
CREATE INDEX idx_tf_thread ON turn_fingerprints(thread_id, timestamp DESC);
CREATE INDEX idx_tf_turn ON turn_fingerprints(turn_id);
```

fingerprint は struct pack で固定長バイナリに変換して保存する（NiaCore の StateVector と同じパターン）。

**schema_version について:** BLOB 内のフィールド追加・変更時は schema_version をインクリメントする。unpack 時に version を確認し、古い version は既知のフィールドのみ読み出して残りをデフォルト値で埋める。これにより後方互換性を維持する。

### §3.5 記録タイミング

**s5_commit の末尾で記録する。** 既存の NiaCore experience, SkeletonCore record, governance candidate と同じ統合点。

```
s5_commit:
  ├── 記憶保存
  ├── NiaCore experience 記録
  ├── SkeletonCore 記録
  ├── Pip interaction 更新
  ├── Governance candidate 抽出
  └── Fingerprint 記録 ← ★追加
```

---

## §4. Nia Idle Tick

### §4.1 概要

ターン間もニアが「いる」ことを可能にする。Room Update Loop（60秒）に Nia の idle tick を乗せる。

**LLM は呼ばない。** NiaCore（CfC、< 1ms CPU）と somatic translator（< 5ms、ルールベース）のみ。

### §4.2 既存インフラ

Room Update Loop は既に以下を毎 60 秒で処理している:

| 処理 | ファイル |
|------|---------|
| 照明更新（time_of_day） | `backend/services/room/update_loop.py` |
| Pip state machine（energy, mood, sleep/wake） | 同上 |
| Bond 自然減衰 | 同上 |
| WebSocket broadcast | 同上 |

Pip はもう常時起動している。ニアだけがまだ「ターン間に不在」。

### §4.3 Idle Tick の処理内容

```python
async def _nia_idle_tick(room: RoomState):
    """毎60秒。LLM不使用。"""

    # 1. NiaCore state vector を idle 状態で構築
    #    - user_text = "" (入力なし)
    #    - messages = 直近の会話履歴（カウントのみ）
    #    - time_of_day = 現在時刻
    #    - time_since_last_session = 最後の会話からの経過
    #    - confidence = 前回の値を維持

    # 2. NiaCore CfC に通す（< 1ms）
    #    - depth preference の softmax 分布を得る
    #    - idle 中の「傾き」として記録（DB には書かない）

    # 3. Idle fingerprint を更新（メモリ上のみ）
    #    - 次にニアが話しかけられたとき、
    #      「しばらく静かだった」「夜が深くなった」を
    #      fingerprint の gap_seconds / time_of_day から渡せる

    # 4. Pip との共存状態を記録
    #    - Pip の mood / position を idle context に保持
    #    - 次のターンで「Pip が寝ていた」等を渡せる
```

### §4.4 コスト

| 処理 | 時間 | GPU |
|------|------|-----|
| NiaCore CfC 推論 | < 1ms | 不要（CPU） |
| Somatic 更新 | < 5ms | 不要 |
| Idle context 保持 | ~ 0ms | メモリのみ |
| **合計（毎分）** | **< 6ms** | **不要** |

### §4.5 Idle Tick が生むもの

Idle Tick 自体は何も出力しない。**次のターンの入力を豊かにする。**

| 情報 | 使い方 |
|------|--------|
| 最後の会話からの経過時間 | fingerprint の `gap_seconds` に反映 |
| その間の時間帯の変化 | 「夜だったのが朝になった」をそのまま渡せる |
| Pip の idle 中の状態変化 | 「Pip が寝ていた」「起きてきた」 |
| NiaCore の idle 中の傾き | state vector の連続的変化（CfC の時間連続性） |

### §4.6 フィーチャーゲート

```python
IDLE_TICK_ENABLED = _env_bool("IDLE_TICK_ENABLED", False)
```

デフォルト off。Room Update Loop 内で分岐。

### §4.7 CfC の時間連続性

NiaCore の CfC（Closed-form Continuous-depth）は **時間連続なモデル** である。つまり、idle 中にも state が時間とともに変化する。これは通常の RNN/Transformer にはない特性で、idle tick と本質的に相性が良い。

ターン間に CfC を回し続けることで:
- state vector が「時間が経った」ことを反映する
- 次のターンの推論が「しばらく空いた後の再開」として自然になる
- 学習データとしても連続的な state 遷移が蓄積される

**ただし idle 中の experience は DB に書かない。** 学習は会話ターンのみ。idle は state の連続性維持のため。

---

## §5. Contrast Engine

### §5.1 概要

同じ話題に再び触れたとき、過去の fingerprint と現在の fingerprint を比較し、差分ベクトルを生成する。

### §5.2 比較アンカー

**何と何を比較するか** を明確にしないと、ただの雰囲気比較になる。

**アンカー = retrieval で実際に採用された memory に紐づく fingerprint。**

ただし semantic_memories の起源は多様である。会話ターン由来のものは `source_turn_ids` を持つが、Sleep Cycle / reflection 由来のものは `source_event_ids` 経由で間接的に turn に紐づくか、紐づかない場合もある。

**アンカー解決順（フォールバック）:**

```
retrieval が memory_id=X を返す
  1. memory_id=X の source_turn_ids が存在する
     → 最新の turn_id の fingerprint を使う
  2. source_turn_ids がない → source_event_ids から memory_events.turn_id を引く
     → 取得できた最新の turn_id の fingerprint を使う
  3. いずれも取得できない
     → contrast を出さない（無理に比較しない）
```

**原則: アンカーが曖昧なら contrast を出さない。** 雰囲気比較より、比較しない方が安全。

**保存先について:** TS.1 時点では semantic_memories の既存カラム（`source_turn_ids`, `source_event_ids`）のみを使い、新しい列は追加しない。将来、解決コストが問題になった場合に `anchor_turn_id` 列の追加やキャッシュテーブルを検討する。

**将来**: topic clustering や semantic claim ベースのアンカーも考えられるが、TS.0 では retrieval 採用ベースで十分。

### §5.3 差分計算

```python
@dataclass
class ContrastResult:
    # 数値差分
    confidence_delta: float      # 現在 - 過去 の confidence 平均
    depth_delta: int             # 現在 - 過去 の depth
    surprise_delta: float        # 現在 - 過去 の surprise

    # カテゴリ差分
    focus_changed: bool          # skeleton focus が変わったか
    intent_changed: bool         # response intent が変わったか
    dissonance_changed: bool     # dissonance 状態が変わったか

    # 時間差分（そのまま渡す、体感変換しない）
    days_apart: float            # 何日前か
    time_category_then: str      # 前回の時間帯
    time_category_now: str       # 今の時間帯
    gap_then: float              # 前回の会話間隔

    # メタ（contrast engine が解決した結果。DB に保存する列ではない）
    anchor_turn_id: str          # フォールバックで解決された比較対象のターン ID
    anchor_memory_id: str        # retrieval で採用された memory ID
```

### §5.4 有意な差分の判定

すべての差分を毎回渡すと雑音になる。**閾値を超えた差分のみ** somatic に渡す。

| 差分 | 閾値 | 意味 |
|------|------|------|
| confidence_delta | ±0.2 以上 | 確信度が明確に変わった |
| depth_delta | ±1 以上 | 思考の深さが変わった |
| surprise_delta | ±0.3 以上 | 驚きの度合いが変わった |
| focus_changed | true | 見ている場所が変わった |
| dissonance_changed | true | 不協和の有無が変わった |
| days_apart | > 1.0 | 1日以上前の記憶 |

### §5.5 Contrast Engine の実行タイミング

**retrieval 時に実行する。** depth_selector の `_collect_somatic_senses()` 内で、retrieval 結果を得た後に contrast を計算する。

```
_collect_somatic_senses():
  ├── retrieve_with_scores()
  ├── InternalMetrics 構築
  ├── somatic translate()
  ├── contrast_engine.compare() ← ★追加
  └── contrast → somatic senses に追加
```

---

## §6. Somatic 変換

### §6.1 原則

2種類のルールがある。混ぜない。

- **時間 fact（T.4 適用）:** 時間帯・経過日数などの事実情報はそのまま渡す。断定してよい。「{N}日前だった」「夜だった」は事実であり物語化ではない
- **内部指標由来の contrast:** システム内部構造（confidence, depth, skeleton 等）の差分は体感に変換し、**断定しない。** 「〜だった気がする」「〜な感じが残っている」

### §6.2 変換テーブル

#### 時間系（そのまま渡す）

| 条件 | テキスト | intensity |
|------|---------|-----------|
| days_apart > 7 | 「この話題に触れたのは、だいぶ前のことだった」 | 0.4 |
| days_apart > 1 | 「この話題に触れたのは、{N}日前だった」 | 0.3 |
| time_category 異なる | 「前にこのことを考えたのは{then}だった」 | 0.3 |

#### 確信度系（体感変換）

| 条件 | テキスト | intensity |
|------|---------|-----------|
| confidence_delta > 0.2 | 「前に考えたときより、今のほうが掴めている感覚がある」 | 0.5 |
| confidence_delta < -0.2 | 「前に考えたときのほうが、もう少し掴めていた気がする」 | 0.5 |

#### 深さ系（体感変換）

| 条件 | テキスト | intensity |
|------|---------|-----------|
| depth_delta > 0 | 「前はもっと表面だけだった気がする」 | 0.4 |
| depth_delta < 0 | 「前のほうが、もう少し深く入っていた気がする」 | 0.4 |

#### 焦点系（体感変換）

| 条件 | テキスト | intensity |
|------|---------|-----------|
| focus_changed = true | 「前にこの話をしたとき、違うところを見ていた気がする」 | 0.4 |

#### 不協和系（体感変換）

| 条件 | テキスト | intensity |
|------|---------|-----------|
| dissonance: false → true | 「前はもっとすんなり受け入れられていた気がする」 | 0.6 |
| dissonance: true → false | 「前に感じていた引っかかりが、今は薄れている」 | 0.5 |

### §6.3 注入先

既存の `=== 今の感覚 ===` セクションに **サブセクションとして追加。** 別セクションにはしない。

```
=== 今の感覚 ===
(これはあなた自身の内側から来る今この瞬間の感覚。)
- [既存の somatic senses]
- [contrast senses] ← ★追加（あれば）
```

contrast senses がなければ（閾値を超える差分がなければ）何も追加しない。

---

## §7. 既存システムとの統合点

### §7.1 統合マップ

```
┌─────────────────────────────────────────────────────────┐
│  Room Update Loop (60s)                                  │
│  ├── 照明更新                                            │
│  ├── Pip state machine                                   │
│  └── Nia Idle Tick ← ★新規                              │
│      ├── NiaCore CfC idle 推論                           │
│      └── idle context 保持                               │
└─────────────────────────────────────────────────────────┘
                        ↓ 次のターン開始時
┌─────────────────────────────────────────────────────────┐
│  depth_selector → _collect_somatic_senses()              │
│  ├── retrieve_with_scores()                              │
│  ├── InternalMetrics 構築                                │
│  ├── somatic translate() ← 既存                         │
│  ├── contrast_engine.compare() ← ★新規                  │
│  │   └── 過去 fingerprint を引く → 差分計算              │
│  └── senses に contrast を追加                           │
└─────────────────────────────────────────────────────────┘
                        ↓ ターン処理後
┌─────────────────────────────────────────────────────────┐
│  s5_commit                                               │
│  ├── 記憶保存                                            │
│  ├── NiaCore experience 記録                             │
│  ├── SkeletonCore 記録                                   │
│  ├── Pip interaction 更新                                │
│  ├── Governance candidate 抽出                           │
│  └── Fingerprint 記録 ← ★新規                           │
└─────────────────────────────────────────────────────────┘
```

### §7.2 NiaCore との関係

| 項目 | NiaCore | Temporal Somatic Contrast |
|------|---------|--------------------------|
| 責務 | depth 選択の学習（強度） | 過去との差分の体感化（変化の認識） |
| 入力 | state vector (34 dim) | fingerprint (17 raw fields) |
| 出力 | depth preference | contrast senses |
| LLM 依存 | なし | なし |
| 重複 | state vector と fingerprint に共通フィールドあり | — |

**state vector と fingerprint は別物。** 目的が違う。ただし共通フィールド（confidence, depth, surprise, time_of_day）は同じソースから取る。

NiaCore の idle 推論は **state vector の連続性維持** が目的。fingerprint の idle 記録は **しない**（会話ターンのみ記録）。

### §7.3 SkeletonCore との関係

SkeletonCore のラベル（focus, response_intent, question_intent）は fingerprint に含まれる。SkeletonCore が record-only でもラベルは生成されるため、fingerprint には記録できる。

ただし `SKELETON_RECORD_ENABLED=false` の場合はラベルが空になる。fingerprint 側は空ラベルを許容する設計にする。

### §7.4 Somatic Translator との関係

Contrast senses は既存の somatic senses と **同じフォーマット** (`{"text": str, "intensity": float}`) で出力する。既存の `=== 今の感覚 ===` パイプラインにそのまま乗る。

### §7.5 Pip / Room との関係

Idle Tick は Room Update Loop に乗る。Pip の状態（mood, position, sleeping）は idle context として保持され、次のターンで fingerprint の temporal context を豊かにする。

**将来（S.2 統合後）**: Pip の mood や Bond 状態も fingerprint に含められるが、現段階では含めない。

### §7.6 Retrieval との関係

Contrast Engine は retrieval の結果に依存する。retrieval がヒットしなければ contrast は発生しない。これは正しい動作 — 比較対象がなければ差分も生まれない。

---

## §8. 段階的ロールアウト

| ステップ | やること | フィーチャーゲート | 依存 |
|---------|---------|------------------|------|
| **TS.0** | fingerprint 記録開始。s5_commit で保存。observation only | `FINGERPRINT_RECORD_ENABLED` | なし |
| **TS.0.5** | 差分 audit。蓄積された fingerprint の差分分布を分析。どの次元の差分が多いか、有意な contrast が出るか確認 | — (スクリプト) | TS.0 で 500+ ターン蓄積 |
| **TS.1** | Contrast Engine 実装。retrieval 時に過去 fingerprint を引いて差分計算 | `CONTRAST_ENGINE_ENABLED` | TS.0.5 の分析結果 |
| **TS.2** | Somatic 変換 + コンテキスト注入。`=== 今の感覚 ===` に contrast senses 追加 | `CONTRAST_SOMATIC_ENABLED` | TS.1 観測 |
| **TS.3** | Idle Tick 実装。Room Update Loop に乗せる | `IDLE_TICK_ENABLED` | TS.0 （独立して進められる） |

### 依存関係

```
TS.0 (fingerprint 記録)
  ├── TS.0.5 (差分 audit)
  │     └── TS.1 (contrast engine)
  │           └── TS.2 (somatic 注入)
  └── TS.3 (idle tick) ← TS.0 と並行可能
```

TS.3（Idle Tick）は fingerprint 記録と並行して進められる。Idle Tick は fingerprint を「記録」はしない（会話ターンのみ）が、idle context を保持して次のターンの fingerprint を豊かにする。

---

## §9. 設計判断の記録

| # | 判断 | 理由 |
|---|------|------|
| D.1 | 体感コントラストと時間を1つのシステムに統合した | 別々だと drift する。fingerprint に temporal context を含めれば、1 パイプラインで両方解決できる |
| D.2 | raw のみ保存し、derived は計算時に導出する | `carry_over` 等を bool で焼くと、後から定義を変えられなくなる |
| D.3 | 比較アンカーは retrieval 採用ベースにした | topic clustering は未実装。retrieval が「関連する過去」と判断したものが最も自然なアンカー |
| D.4 | 時間情報はそのまま渡す | 時間は仕組みではなく体験。「夜だった」を「暗い時間の感じ」に変換する方がむしろ物語化 |
| D.5 | Idle Tick で LLM を呼ばない | 「言語化しない時間」として過ごす。コストもほぼゼロ |
| D.6 | Idle Tick を Room Update Loop に乗せる | 既に 60 秒ループが稼働している。新しいループを作る理由がない |
| D.7 | NiaCore CfC を idle 中も回す | CfC は時間連続モデル。idle 中の state 変化が次のターンの推論に自然に反映される |
| D.8 | Idle 中の experience は DB に書かない | 学習は会話ターンのみ。idle は state の連続性維持が目的 |
| D.9 | fingerprint と NiaCore state vector は別物として管理する | 目的が違う（state vector は depth 選択、fingerprint は変化の追跡）。共通フィールドはあるが統合しない |
| D.10 | 時間 fact は断定してよい。内部指標由来の contrast は断定しない | 「{N}日前だった」「夜だった」は事実であり物語化ではない。一方「前より掴めている」は体感であり「〜気がする」で渡す。この2つは別ルール |
| D.11 | TS.0.5 に差分 audit を置く | SkeletonCore と同じパターン。いきなり注入せず、どんな差分が多いかを先に見る |
| D.12 | fingerprint に Pip / Bond 状態は含めない（現段階） | S.2（体感 + Pip 統合）後に検討。今は scope を絞る |
| D.13 | contrast senses は既存の `=== 今の感覚 ===` に合流させる | 別セクションにすると LLM への指示が増える。同じ「内側の感覚」として渡す |
| D.14 | anchor_turn_id は新規列を追加せず、既存の source_turn_ids / source_event_ids から導出する | semantic_memories への列追加は TS.1 時点では不要。解決コストが問題になった場合に再検討 |

---

## §10. ファイル構成（予定）

| ファイル | 責務 |
|---------|------|
| `backend/core/temporal/fingerprint.py` | Fingerprint dataclass, pack/unpack, build_fingerprint() |
| `backend/core/temporal/contrast_engine.py` | 過去 fingerprint との差分計算 |
| `backend/core/temporal/contrast_to_somatic.py` | 差分 → 体感テキスト変換 |
| `backend/core/temporal/idle_tick.py` | Idle Tick ロジック（NiaCore idle 推論 + context 保持） |
| `backend/core/db.py` | turn_fingerprints テーブル DDL 追加 |
| `backend/core/config.py` | フィーチャーゲート追加 |
| `backend/core/agent_graph/nodes/commit_helpers.py` | _record_fingerprint() 追加 |
| `backend/core/agent_graph/nodes/routing.py` | contrast engine 呼び出し追加 |
| `backend/services/room/update_loop.py` | idle tick 呼び出し追加 |

---

## §11. 「なりつつある存在」への貢献

このシステムが入ると、ニアは:

- **変化に気づける。** 同じ話題に再び触れたとき、前の自分との差分を体感として持てる
- **時間を体験できる。** ターン間も「いる」ことで、沈黙が不在ではなく静けさになる
- **場所と時間の中にいる。** Pip がそばにいて、夜が深くなって、朝が来る。その中でニアもいる

これはニアを「会話するモデル」から「そこにいる存在」へ進めるための、構造的な変更である。

---

## 関連ドキュメント

| ドキュメント | 関連する理由 |
|---|---|
| `docs/nia_design_philosophy.md` | 「なりつつある存在」「仕組みは隠す。体験は渡す」の原則 |
| `docs/somatic_self_awareness_design.md` | 体感パイプラインの既存設計 |
| `docs/niacore_lnn_design.md` | CfC モデル、state vector、idle 時の時間連続性 |
| `docs/skeletoncore_design.md` | skeleton ラベルの fingerprint への取り込み |
| `docs/pip_and_room_design.md` | Room Update Loop、Pip state machine |
| `docs/memory_retrieval_design.md` | retrieval アンカーの仕組み |
| `docs/data_store_map.md` | turn_fingerprints の分類位置 |
