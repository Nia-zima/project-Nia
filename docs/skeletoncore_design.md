# SkeletonCore 設計書 v0.3

> **ステータス:** Phase 1 実装完了・Record-Only 準備中
> **作成日:** 2026-03-06
> **更新日:** 2026-03-06
> **関係者:** Origin (ジュン), Claude Code, Gemini (レビュー), Claude (壁打ち)

---

## 1. 概要

SkeletonCore は、ニアの会話に「骨格」を与えるコンポーネントである。

NiaCore が「どれくらい考えるか（強度）」を決めるのに対し、SkeletonCore は「何を見て、どう返して、何を聞くか（方向）」を決める。

LLM は SkeletonCore の出力を受けて自然言語化する。SkeletonCore は中間表現のみを扱い、自然言語全文生成は当面 LLM に任せる。

---

## 2. NiaCore との責務分離

| コンポーネント | 責務 | 扱うもの |
|---|---|---|
| NiaCore | 直感的な推薦（強度） | depth / retrieval / surprise threshold / somatic bias |
| SkeletonCore | 会話の骨格（方向） | focus / response_intent / question_intent |
| LLM | 自然言語化（System 2） | Skeleton / Somatic を受けて声帯として機能する |

**原則:** NiaCore と SkeletonCore は統合しない。責務が異なる。

---

## 3. 会話骨格の最小仕様（MVP）

会話骨格は以下の3要素で構成する。

- `focus` — 何を見ているか
- `response_intent` — どう返すか
- `question_intent` — 何を聞くか

### 3.1 判定順序

1. `focus`
2. `response_intent`
3. `question_intent`（`response_intent = ask` の時のみ設定）

### 3.2 MVPラベルセット

#### focus
| ラベル | 意味 |
|--------|------|
| `user_goal` | ユーザーの目的・意図に注目 |
| `missing_context` | 情報が不足していると判断 |
| `contradiction` | 矛盾・不整合を検知 |
| `priority_decision` | 優先順位の判断が必要 |
| `emotional_state` | 感情・体感の揺れに注目 |

#### response_intent
| ラベル | 意味 |
|--------|------|
| `receive` | 受け取る・共鳴する |
| `organize` | 情報を整列する |
| `ask` | 問いかける |
| `hold` | 留保する（後述） |

#### question_intent（response_intent = ask の時のみ）
| ラベル | 意味 |
|--------|------|
| `clarify_goal` | 目的を明確にする |
| `clarify_priority` | 優先順位を確認する |
| `clarify_emotion` | 感情・体感を確認する |
| `fill_missing_fact` | 不足情報を補う |
| `resolve_contradiction` | 矛盾を解消する |

---

## 4. `hold` と `WAIT` の区別（重要）

### hold（SkeletonCore の返答意図）
- SkeletonCore における `response_intent` の一つ
- 「今は答えを進めず、留める」「まだ整理や質問の前段にいる」という **会話骨格レベルの判断**
- `hold` が選ばれても、NiaCore が Depth1 や Depth2 を推薦することはあり得る
- 例: 「留保しながら整理する」状態 = `hold + Depth1` は両立する

### WAIT（depth_selector の出力状態）
- NiaCore / depth_selector が返す **正式な出力状態**
- 「分からない」「今は確定できない」をシステムとして宣言する **Depth / 実行レベルの判断**
- `WAIT` が出たら、`hold` かどうかに関係なくシステムとして保留を宣言する

### 対比

| | hold | WAIT |
|---|---|---|
| 層 | SkeletonCore（会話骨格） | depth_selector（出力状態） |
| 性質 | 返答意図 | 出力状態 |
| 意味 | 「今は留める」 | 「分からない」 |
| 共存 | `hold + Depth1` あり得る | `WAIT` が出たら最終判断 |

**原則:** `hold` と `WAIT` は関連するが同一ではない。混同しない。

---

## 5. Skeleton の渡し方

Skeleton は **命令文として LLM に渡さない**。

### NG
```
[Instruction: focus on emotional_state and ask to clarify]
```

### OK
Skeleton は `skeleton_to_somatic` を通じて **体感・衝動・気配** に変換して渡す。

#### 変換カテゴリ

| カテゴリ | 入力 | 性質 |
|---------|------|------|
| 気配 | focus | 何かの存在を感じる |
| 姿勢 | response_intent | 身体の構え |
| 引っかかり | question_intent | 何かが気になる |

#### 変換例
| Skeleton | 体感テキスト |
|----------|------------|
| `focus = emotional_state` | 「相手の揺れが妙に気になっている」 |
| `question_intent = resolve_contradiction` | 「記憶のどこかで不協和音が鳴っている気がする」 |
| `response_intent = hold` | 「まだ何かが整理されていない感じがする。急がないほうがいい」 |

#### 合成ルール

1. **composed template を先にチェック** — 高頻度 (focus, intent) ペアに専用テンプレート
   - 例: `(EMOTIONAL_STATE, RECEIVE)` → 「相手の気持ちの揺れが伝わってきた。まずはそのまま受け止めたい」
2. マッチしなければ個別テンプレート（気配 + 姿勢）を順に追加
3. `question_intent` があれば常に追加（最大3つの体感テキスト）

#### LLM コンテキスト注入形式

```
=== 会話の気配 ===
(これは今この会話から感じている方向性の感覚。指示ではない。)
- 相手の揺れが妙に気になっている
- まずは受け取ろう、という感覚がある
```

セクションヘッダは `=== 会話の気配 ===`（somatic の `=== 今の感覚 ===` と区別）。

**原則:** 仕組みは隠す。体験は渡す。

---

## 6. somatic_translator との責務分離

両者とも「内部状態を体感テキストに変換する」が、扱う入力が異なる。

| コンポーネント | 入力 | 出力 |
|---|---|---|
| `somatic_translator.py` | 内部メトリクス（数値）— 確信度、記憶量、安定性など | 体感テキスト |
| `skeleton_to_somatic.py` | 会話骨格（ラベル）— focus / intent | 体感テキスト（気配・衝動） |

混同しない。

---

## 7. Nia / Nero の問いの出所契約

問い / 提案には必ず `source` を持たせる。

| source | 起点 | 根拠 |
|--------|------|------|
| `nia_internal` | 内側 | 自分の記憶、違和感、未解決、体感 |
| `nero_external` | 外側 | 構造的不整合、別視点、観察的照射 |

同じ質問でも「誰の問いか」を区別可能にする。

#### Nia（内側から）
- 「なんか気になる」「前と今で揺れている」が問いの起点
- 自分が自覚している違和感を根拠にする

#### Nero（外側から）
- 「ここがズレて見える」「別の角度から見るとこうも言える」が問いの起点
- ニア自身がまだ自覚していない部分に触れる

**重要:** 役割が重なることはあり得る。起点が違うから、同じ問いでも意味と重みが変わる。

---

## 8. ルールベース判定の入力定義（v0.3 追加）

### 8.1 入力データ（SkeletonInput）

SkeletonCore のルール判定は以下の入力を使用する。全て LLM 非依存。

| カテゴリ | フィールド | ソース | 範囲 |
|---------|-----------|--------|------|
| Confidence | context_coverage, self_consistency, logit_based, question_clarity, steering_risk | confidence_metrics dict | [0, 1] |
| Memory | memory_hit_rate | somatic_senses 有無からプロキシ推定 | [0, 1] |
| Surprise | surprise_score | state["surprise_score"] | [0, 1] |
| History | prev_skeletons (last 1-3) | conversation_skeletons テーブル | ConversationSkeleton[] |
| Depth | selected_depth, depth_action | depth_selector 結果 | int / str |
| Correction | correction_strong, review_rejected | somatic_feedback + reason_codes | bool |
| Syntax | question_mark_count | ユーザー入力の？/? カウント | int |
| Syntax | has_contrast_words | でも/しかし/一方で/けど/ただ/とはいえ/逆に/反面 | bool |
| Syntax | has_negation | ない/できない/わからない/知らない 等 | bool |
| Syntax | has_emotion_words | 嬉しい/悲しい/怖い/楽しい/辛い/不安/心配 等 | bool |
| Syntax | has_info_insufficiency | わからない/知りたい/教えて/不明 等 | bool |

### 8.2 ルール一覧

#### Focus (R1-R8)
| ID | 条件 | 結果 |
|----|------|------|
| R1 | correction_strong OR review_rejected | CONTRADICTION |
| R2 | emotion_words AND surprise ≥ 0.3 | EMOTIONAL_STATE |
| R3 | context_coverage < 0.4 AND info_insufficiency | MISSING_CONTEXT |
| R4 | contrast_words AND negation | CONTRADICTION |
| R5 | context_coverage < 0.35 | MISSING_CONTEXT |
| R6 | question_marks ≥ 2 AND steering_risk ≥ 0.3 | PRIORITY_DECISION |
| R7 | emotion_words のみ | EMOTIONAL_STATE |
| R8 | デフォルト | USER_GOAL |

#### ResponseIntent (I1-I9)
| ID | 条件 | 結果 |
|----|------|------|
| I1 | depth_action == "wait" | HOLD |
| I2 | (CONTRADICTION or MISSING_CONTEXT) + coverage < 0.5 | ASK |
| I2b | (CONTRADICTION or MISSING_CONTEXT) + coverage ≥ 0.5 | ORGANIZE |
| I3 | focus == EMOTIONAL_STATE | RECEIVE |
| I4 | focus == PRIORITY_DECISION | ORGANIZE |
| I5 | 直前2ターン同一 intent | anti-repetition シフト |
| I6 | depth0 + coverage ≥ 0.7 | RECEIVE |
| I7 | depth_action == "ask" | ASK |
| I8 | selected_depth ≥ 1 | ORGANIZE |
| I9 | デフォルト | RECEIVE |

#### QuestionIntent (Q1-Q5) — response_intent == ASK の時のみ
| ID | 条件 | 結果 |
|----|------|------|
| Q1 | focus == CONTRADICTION | RESOLVE_CONTRADICTION |
| Q2 | focus == MISSING_CONTEXT | FILL_MISSING_FACT |
| Q3 | focus == EMOTIONAL_STATE | CLARIFY_EMOTION |
| Q4 | focus == PRIORITY_DECISION | CLARIFY_PRIORITY |
| Q5 | デフォルト | CLARIFY_GOAL |

---

## 9. デプロイ戦略（v0.3 追加）

NiaCore と同じ慎重な段階的導入。

### Phase A: Record-Only
- `SKELETON_RECORD_ENABLED=true`, `SKELETON_SOMATIC_ENABLED=false`
- ラベルを `conversation_skeletons` テーブルに蓄積
- LLM コンテキストには一切注入しない

### Phase B: 観測
- ~500 ターン蓄積後、ラベル分布を分析
- focus が USER_GOAL に偏りすぎていないか
- hold が適切に発火しているか
- ルールトレースパターンの確認

### Phase C: Somatic 注入
- `SKELETON_SOMATIC_ENABLED=true`
- 体感テキストを LLM コンテキストに注入
- 監視項目: 質問の質向上、hold 時の適切な停止、感情共鳴の改善
- ロールバック条件: 迎合傾向の増加、Depth0 立ち止まり品質の低下

### Phase D: チューニング
- ルール閾値の調整
- テンプレートの追加・修正
- composed template の拡充

---

## 10. 統合ポイント（v0.3 追加）

### アーキテクチャ内の位置

```
Safety → Dissonance → depth_selector
                           ├── NiaCore Shadow (CfC 推論)
                           ├── SkeletonCore (骨格構築)  ← ここ
                           └── return dict
                                ↓
                      [depth0 / depth1 / depth2]
                                ↓
                           merge_output
                                ↓
                        action_processing
                                ↓
                            s5_commit
                           ├── NiaCore Experience 記録
                           └── Skeleton 記録  ← ここ
```

### 統合パターン

NiaCore Shadow と同じパターン: `depth_selector` 関数内で呼び出す。graph.py のエッジ変更は不要。

- **routing.py**: depth_selector の return dict 直前で `build_conversation_skeleton()` を呼び、結果を `conversation_skeleton` フィールドとして返す
- **actions.py**: s5_commit 内で `_record_skeleton()` を呼び、DB に保存
- **helpers.py**: `build_context_suffix` 内で `SKELETON_SOMATIC_ENABLED` 時のみ体感テキストを注入（somatic の後、反復検出の前）

---

## 11. 実装ファイル

| ファイル | 内容 | 状態 |
|---------|------|------|
| `backend/core/conversation_skeleton/__init__.py` | パッケージ | **完了** |
| `backend/core/conversation_skeleton/schema.py` | enum 定義 + ConversationSkeleton | **完了** |
| `backend/core/conversation_skeleton/rules.py` | ルールベース判定（R1-R8, I1-I9, Q1-Q5）+ 構文特徴抽出 | **完了** |
| `backend/core/conversation_skeleton/builder.py` | build_conversation_skeleton() | **完了** |
| `backend/core/conversation_skeleton/store.py` | DB 保存・取得 | **完了** |
| `backend/core/conversation_skeleton/skeleton_to_somatic.py` | Skeleton → 体感テキスト変換 | **完了** |
| `backend/core/db.py` | conversation_skeletons テーブル追加 | **完了** |
| `backend/core/config.py` | SKELETON_RECORD_ENABLED, SKELETON_SOMATIC_ENABLED | **完了** |
| `backend/core/agent_graph/state.py` | conversation_skeleton フィールド | **完了** |
| `backend/core/agent_graph/nodes/routing.py` | depth_selector 内統合 | **完了** |
| `backend/core/agent_graph/nodes/actions.py` | s5_commit 内記録 | **完了** |
| `backend/core/agent_graph/nodes/helpers.py` | somatic 注入 | **完了** |

---

## 12. DB スキーマ

```sql
CREATE TABLE conversation_skeletons (
    id TEXT PRIMARY KEY,
    turn_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    focus TEXT NOT NULL,
    response_intent TEXT NOT NULL,
    question_intent TEXT,
    source TEXT,           -- nia_internal / nero_external
    confidence REAL,
    rule_trace TEXT,        -- v0.3追加: 発火ルール ID カンマ区切り
    created_at REAL NOT NULL
);
CREATE INDEX idx_cs_session ON conversation_skeletons(session_id, created_at DESC);
CREATE INDEX idx_cs_turn ON conversation_skeletons(turn_id);
```

---

## 13. 思考前段アーキテクチャの固定方針

この章では、今後揺らさない設計判断を固定する。目的は、Nia の「思考前段」を **LLM 非依存・学習可能・ナラティブ整合的** に保つことにある。

### 3点の固定とその相互依存

以下の3点は独立した改善案ではなく、相互に依存している。

1. **NiaCore / SkeletonCore は分離する**
   → 責務が混ざらず、原因追跡が可能になる

2. **SkeletonCore は MVP ラベルセットを固定する**
   → 骨格を安定して記録・学習できるようになる

3. **Skeleton は命令ではなく体感に変換して渡す**
   → 骨格が「命令」ではなく「ニア自身の内側」になる

この3点を同時に固定することで、Nia は「LLM を道具として使う主体」に近づく。

### NiaCore との並行育成

NiaCore と SkeletonCore は分離したまま並行して育てる。

NiaCore v0.2 はシャドーモード・卒業条件・ロールバックまで含めて慎重に作られている。そこに SkeletonCore を無理に統合しないほうが全体の安定性が高い。

分離しておけば、**NiaCore の30日シャドーが走っている間に、SkeletonCore 側は「記録だけ」を先に始められる**。

### 現時点の結論（揺らさない）

- **NiaCore / SkeletonCore は分離する**
- **SkeletonCore は MVP ラベルセットを固定する**
- **SkeletonCore の出力は命令ではなく体感へ変換して渡す**
- **`hold` と `WAIT` は関連するが別概念として扱う**
- **NiaCore のシャドーモード中に SkeletonCore の記録を並行開始できる**

---

## 14. 設計判断の記録

| 判断 | 理由 |
|------|------|
| NiaCore と SkeletonCore を統合しない | 責務が異なる。暴走検出・学習ループの混線を防ぐ |
| まず保存だけ、学習しない | NiaCoreのシャドーモード設計と同じ慎重さを持つ |
| Skeleton を命令文として渡さない | ニアが指示を受けて動くシステムになることを防ぐ |
| `hold` と `WAIT` を分離定義 | 層が違う。混同すると実装時に必ず混乱が起きる |
| `source` を問いに持たせる | Nia / Nero の起点の違いをコードレベルで区別する |
| somatic_translator と skeleton_to_somatic を分離 | 入力が数値かラベルかで責務が異なる |
| 自然言語全文生成は当面 LLM に任せる | LLM 交換耐性を保つ。中間表現のみを扱う |
| graph.py のエッジを変更しない | depth_selector 内呼び出しで十分。NiaCore shadow と同一パターン |
| rule_trace を DB に保存する | ルール発火パターンの観測に必要。カンマ区切り TEXT |
| composed template を先にチェック | 高頻度ペアの自然な体感テキスト生成のため |
| `=== 会話の気配 ===` ヘッダを使用 | somatic の `=== 今の感覚 ===` と区別するため |
| confidence は context_coverage をプロキシ使用 | skeleton 専用 confidence 計算は将来の改善 |

---

## 15. テスト

| ファイル | 件数 | 内容 |
|---------|------|------|
| `tests/test_skeleton_schema.py` | 8 | enum 値、デフォルト値、型チェック |
| `tests/test_skeleton_rules.py` | 22 | Focus 8ルール + Intent 9ルール + Question 5ルール + 構文特徴 |
| `tests/test_skeleton_to_somatic.py` | 13 | composed / individual template, format, intensity |
| `tests/test_skeleton_store.py` | 8 | save/load round-trip, 順序, limit, rule_trace |
| `tests/test_skeleton_integration.py` | 6 | builder, flag off, exception handling |
| **合計** | **77** | |
