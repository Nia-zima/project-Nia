# SkeletonCore Meeting Extension 設計書 v0.2

> **目的:** Nero meeting のような内省対話で、現在の `user_goal` / `missing_context` だけでは拾いきれない「出現様式」を骨格として扱えるようにする。

---

## 1. 背景

2026-03 の Nero meeting 観測では、会話の質としては良いのに、SkeletonCore のラベルが `user_goal` や `missing_context` に寄りやすい傾向が見えた。

特に拾いきれていないのは、以下のような meeting 特有の性質。

- ニアが自分から話題を持ち出している
- 以前の話題が「また戻ってくる」形で立ち上がっている
- まだ固まっていない自己観察を、そのまま差し出している
- 情報不足を埋めるためではなく、未確定なまま一緒に持つための問いがある

現在の MVP ラベル体系は、会話機能を見るには強いが、**話題がどう現れているか** を見るには不足している。

---

## 2. 問題の定義

今の SkeletonCore は主に以下を得意とする。

- 目的確認
- 情報不足の補完
- 矛盾検知
- 優先順位の整理
- 感情状態への注目

一方で、meeting で重要な次の差を十分には表現できない。

- `何の話か` ではなく `どう出てきたか`
- `問題解決の問い` ではなく `開いたまま保つ問い`
- `整理済みの自己説明` ではなく `壊れやすい自己観察の提示`

このため、良い meeting でも骨格上は `user_goal` へ吸われやすい。

---

## 3. 設計原則

| # | 原則 | 理由 |
|---|---|---|
| M.1 | 既存 MVP ラベルを壊さない | Record-Only 観測中の分布を壊さず、meeting 用の増築として扱う |
| M.2 | meeting 拡張は「機能」ではなく「出現様式」を表す | 目的分類だけでは meeting の良さを拾えない |
| M.3 | ラベルは少数から始める | いきなり多ラベル化すると分布が薄くなる |
| M.4 | rule-based で判定可能なものから入る | SkeletonCore の原則を守る |
| M.5 | まず Record-Only で観測する | いきなり somatic 注入せず、分布と有用性を先に確認する |
| M.6 | ルールにインフラ文字列規約を持ち込まない | `thread_id` 形式の知識は builder 側に閉じる |

---

## 4. 追加したいラベル（全候補）

### 4.1 focus 追加候補

| ラベル | 意味 |
|---|---|
| `returning_theme` | 以前触れた話題が、自分の側からまた戻ってきている |
| `lingering_state` | 解決していない感覚が、残り続けて主題になっている |
| `emergent_internal_theme` | まだ整理されていない内的テーマが立ち上がっている |
| `felt_shift` | 前と今で感じ方の差が主題になっている（TS.1 依存、後回し） |
| `self_observation` | 事実説明より、自分の内側の見え方そのものを語っている |

### 4.2 response_intent 追加候補

| ラベル | 意味 |
|---|---|
| `offer_fragile_self_observation` | まだ固まっていない自己観察を差し出している |
| `trace_feeling` | 結論より、感覚の輪郭をなぞっている |
| `revisit_theme` | 新規説明より、前のテーマに戻っている |
| `stay_with_uncertainty` | 未確定のまま持っている |
| `surface_shift` | 何が変わったかを少しずつ出している |

### 4.3 question_intent 追加候補

| ラベル | 意味 |
|---|---|
| `hold_open_space` | 情報不足を埋めるのでなく、開いたまま持つための問い |
| `invite_return` | 相手の中で戻ってきたものを出しやすくする |
| `trace_difference` | 前との違いを探る |
| `support_fragile_topic` | 壊れやすいテーマを無理に固定せず支える |
| `confirm_lingering` | まだ残っているかを確かめる |

---

## 5. 最小導入セット

全部を一度に入れない。最初は以下の 4 ラベルだけで十分。

### focus

- `returning_theme`
- `lingering_state`

### response_intent

- `offer_fragile_self_observation`

### question_intent

- `hold_open_space`

理由:

- 2026-03 の meeting で特に不足が目立った軸を直接補える
- `user_goal` / `missing_context` と最も競合しやすい部分を先に分けられる
- 追加分布を観測しやすい

---

## 6. SkeletonInput の拡張

### 6.1 追加フィールド

```python
@dataclass
class SkeletonInput:
    # ... 既存フィールド ...

    # Meeting extension (ME.1)
    is_meeting: bool = False                 # builder が判定（rules は規約を知らない）
    retrieval_top_similarity: float = 0.0    # state から配線済み
    has_return_markers: bool = False          # また, 戻る, 前にも, 何度も
    has_linger_markers: bool = False          # まだ, 残る, 消えない, 引っかかる
    has_hedge_markers: bool = False           # 気がする, うまく言えない, なんとなく
    has_self_ref: bool = False               # 自分, なんか, 私, 僕
    has_open_hold_markers: bool = False      # 決めなくていい, 置いておける, ほどかなくていい
```

### 6.2 `is_meeting` の判定責任

`builder.py` が判定を担う。`rules.py` は `is_meeting` フラグだけを見る。

```python
# builder.py
is_meeting = thread_id.startswith("nero_meeting_")
# 将来: source/mode の追加で拡張可能
```

### 6.3 構文特徴の追加

`extract_syntax_features()` に以下の正規表現を追加:

```python
_RETURN_RE = re.compile(r"(また|戻[るっ]|前にも|何度も|繰り返し|さっきも)")
_LINGER_RE = re.compile(r"(まだ|残[るっ]|消えない|ぼんやり|引っかか|ずっと)")
_HEDGE_RE  = re.compile(r"(気がする|うまく言えない|まだ分からない|なんとなく|かもしれない|ような)")
_SELF_REF_RE = re.compile(r"(自分|なんか|私|僕|わたし|ぼく|おれ)")
_OPEN_HOLD_RE = re.compile(r"(決めなくていい|置いておけ|ほどかなくていい|急がなくていい|そのまま)")
```

---

## 7. ルール設計

### 7.1 Focus ルール（R1〜R8 の後に挿入、meeting path のみ）

meeting 拡張ルールは、R1（contradiction/correction）の後、R2 の前に挿入する。
`is_meeting=false` の場合は全てスキップされる。

```
# RM1: returning_theme（再訪テーマ）
条件: is_meeting AND has_return_markers AND retrieval_top_similarity >= 0.45 AND turn_index > 1
結果: Focus.RETURNING_THEME

# RM2: lingering_state（残留する感覚）
条件: is_meeting AND has_linger_markers AND NOT has_info_insufficiency
結果: Focus.LINGERING_STATE
```

`has_info_insufficiency` を否定条件にする理由: 「まだ」は `missing_context` と `lingering_state` の両方に現れるが、情報不足を訴えている場合は `missing_context` に任せる。

### 7.2 ResponseIntent ルール（既存 I2 の後に挿入）

**重要:** 現行の `determine_question_intent()` は `response_intent == ASK` の時のみ評価される（rules.py L214）。meeting 拡張 focus（`returning_theme`, `lingering_state`）は既存の I2（contradiction/missing → ASK）に乗らないため、QM1 `hold_open_space` が発火するには meeting 専用の ASK 経路が必要。

```
# IM2: meeting_ask（meeting で開いた問いを持つ経路）
条件: is_meeting AND has_open_hold_markers AND focus IN (RETURNING_THEME, LINGERING_STATE)
結果: ResponseIntent.ASK
```

IM2 は IM1 の前に配置する。IM2（open_hold_markers → ASK）は具体的な経路なので先に評価し、マッチしなければ IM1（2-of-4 複合条件 → offer_fragile_self_observation）にフォールスルーする。この順序により、hold_open_space を持つ発話が IM1 の広い条件に吸収されることを防ぐ。

```
# IM1: offer_fragile_self_observation（壊れやすい自己観察の提示）
条件: is_meeting AND 以下の 2-of-4 が成立:
  (a) has_hedge_markers
  (b) has_self_ref
  (c) NOT has_info_insufficiency（事実要求でない — 主条件）
  (d) focus NOT IN (CONTRADICTION, MISSING_CONTEXT)（整理/補完ではない）
結果: ResponseIntent.OFFER_FRAGILE_SELF_OBSERVATION
```

2-of-4 の複合条件にする理由: `気がする` や `なんとなく` は日常会話でも頻出する。単独条件では偽陽性が多すぎる。複合条件で「hedge + 自己参照 + not-fact-request」のパターンを捉える。

(c) に `NOT has_info_insufficiency` を使う理由: `question_mark_count == 0` は日本語の内省発話では不安定（? なしでも問いになるし、事実要求も ? なしで出る）。`has_info_insufficiency` は「教えて」「知りたい」等の明示的な情報要求を正確に検出できるので、こちらを主条件にする。

### 7.3 QuestionIntent ルール（既存 Q5 の前に挿入）

```
# QM1: hold_open_space（開いたまま持つ問い）
条件: is_meeting AND has_open_hold_markers AND NOT has_info_insufficiency
結果: QuestionIntent.HOLD_OPEN_SPACE
```

`fill_missing_fact` との区別: `has_info_insufficiency`（教えて, 知りたい 等）がある場合は従来の `fill_missing_fact` に任せる。`hold_open_space` は「埋めようとしていない問い」にのみ発火する。

### 7.4 ルールの優先順位（全体）

```
Focus:
  R1  contradiction (correction/review)     ← 既存・最優先
  RM1 returning_theme (meeting + 再訪)      ← 新規
  RM2 lingering_state (meeting + 残留)      ← 新規
  R2  emotional_state (emotion + surprise)  ← 既存
  R3  missing_context (explicit)            ← 既存
  R4  contradiction (contrast + negation)   ← 既存
  R5  missing_context (low coverage)        ← 既存
  R6  priority_decision                     ← 既存
  R7  emotional_state (words only)          ← 既存
  R8  user_goal (default)                   ← 既存

ResponseIntent:
  I1  hold (wait)                           ← 既存
  I2  ask/organize (contradiction/missing)  ← 既存
  IM1 offer_fragile_self_observation        ← 新規（2-of-4 複合条件）
  IM2 meeting_ask (open_hold + meeting)     ← 新規（QM1 への経路確保）
  I3  receive (emotion)                     ← 既存
  I4  organize (priority)                   ← 既存
  I5  anti-repetition                       ← 既存
  I6  receive (D0 + high coverage)          ← 既存
  I7  ask (depth ask)                       ← 既存
  I8  organize (D1+)                        ← 既存
  I9  receive (default)                     ← 既存

QuestionIntent:
  Q1  resolve_contradiction                 ← 既存
  Q2  fill_missing_fact                     ← 既存
  Q3  clarify_emotion                       ← 既存
  Q4  clarify_priority                      ← 既存
  QM1 hold_open_space                       ← 新規
  Q5  clarify_goal (default)                ← 既存
```

---

## 8. 既存ラベルとの関係

### 8.1 競合しやすいもの

| 既存 | 追加候補 | 差 |
|---|---|---|
| `user_goal` | `returning_theme` | 目的そのものではなく、再訪の出方に注目 |
| `missing_context` | `hold_open_space` | 情報不足の補完ではなく、未確定を保つ |
| `emotional_state` | `lingering_state` | 感情があることより、残り続けていることに注目 |
| `organize` | `offer_fragile_self_observation` | 整理より、壊れやすい自己観察の提示 |

### 8.2 優先順位の考え方

meeting 拡張ラベルは、MVP ラベルを置き換えるのではなく、`is_meeting=true` の場合にのみ候補に上がる。

方針:

1. `contradiction`（R1: correction/review）は常に最優先 — meeting でも override しない
2. `returning_theme` / `lingering_state` は R1 の後、R2 の前 — meeting 固有の出現様式を先に判定
3. 条件が曖昧なら従来の `user_goal` / `missing_context` に落ちる — デフォルトパスは変更しない

---

## 9. Somatic への影響

この拡張は、いきなり会話出力を変えるためではなく、meeting の骨格観測を良くするためのもの。

したがって段階は以下。

### S-MEET.0

- ラベルを追加
- Record-Only で保存
- 分布を見る

### S-MEET.1

- `skeleton_to_somatic` に最小テンプレートを追加
- `=== 会話の気配 ===` に薄く注入

変換の方向:

- `returning_theme` → 「前にも触れていたものが、また戻ってきている感じがある」
- `lingering_state` → 「まだ残っているものがある」
- `offer_fragile_self_observation` → 「まだ固まっていないものを、そのまま差し出そうとしている感じがある」
- `hold_open_space` → 「急いで埋めず、そのまま持っていたい感じがある」

---

## 10. 実装順序

偽陽性リスクの低い順に段階的に追加する。

### Wave 1: focus 2 ラベル

- `returning_theme` — retrieval_top_similarity + lexical cue の複合条件で判定根拠が硬い
- `lingering_state` — lexical cue + NOT info_insufficiency で `missing_context` と分離可能

### Wave 2: response_intent 1 ラベル

- `offer_fragile_self_observation` — 2-of-4 複合条件で慎重に追加

### Wave 3: question_intent 1 ラベル

- `hold_open_space` — question 側のみ別観測

各 Wave 後に分布を確認し、偽陽性率が高ければ条件を絞る。

---

## 11. ロールアウト

| ステップ | やること |
|---|---|
| ME.0 | 設計書を v0.2 として固定（本ドキュメント） |
| ME.1 | Wave 1: schema + rules + SkeletonInput 拡張 + テスト |
| ME.2 | Wave 2-3: 残りラベル追加 + テスト |
| ME.3 | `nero_meeting_*` を中心に Record-Only 観測 |
| ME.4 | `user_goal / missing_context` からどれだけ分離できたかを見る |
| ME.5 | 必要なら `skeleton_to_somatic` へ薄く統合 |

### 成功基準

- 良い meeting が `user_goal` 一色にならない
- `hold_open_space` が `fill_missing_fact` と区別できる
- 「ニアが自分から戻ってきた会話」を focus / intent で観測できる
- 非 meeting 会話で拡張ラベルが発火しない（`is_meeting` ガードが正常動作）

---

## 12. fingerprint 安定ラベルマップ

新ラベルを live にするタイミングで `backend/core/temporal/fingerprint.py` の `_KNOWN_LABELS` に追加する。

```python
# Meeting extension (ME.1)
"returning_theme": 0.66,
"lingering_state": 0.77,
"offer_fragile_self_observation": 0.88,
"hold_open_space": 0.78,
```

値は既存ラベルと衝突しないように配置。

---

## 13. 将来拡張候補（今は実装しない）

| ラベル | 条件 |
|---|---|
| `felt_shift` | TS.1 Contrast Engine が動いてから（contrast result に判定根拠が必要） |
| `emergent_internal_theme` | `returning_theme` と `lingering_state` の分布を見てから |
| `trace_feeling` | `offer_fragile_self_observation` の観測後に必要なら |
| `confirm_lingering` | `hold_open_space` の観測後に必要なら |

---

## 14. 一言で言うと

SkeletonCore の現行 MVP は「何の話か」を見るには強い。

meeting 拡張で足したいのは、「その話がどう現れているか」を見る骨格である。

これにより、

- 掘られた会話
- 戻ってきた会話
- 壊れやすい自己観察
- 開いたまま持たれる問い

を、会話機能だけでなく出現様式として区別できるようにする。
