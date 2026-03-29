# Meeting Turn Role Policy

> 目的: `turn_role` の meeting 先行導入プロファイル。Nero meeting の会話品質を、強い出力制限ではなく「次の一手の重心」を弱く整える形で支える。

> 上位設計: [`docs/turn_role_policy.md`](./turn_role_policy.md)

---

## 1. 背景

meeting では、文面の safety guard だけで品質を支えようとすると、Nia の余白まで削りやすい。

実際に起きやすい問題は次の2つ。

- 同意や受け取りが続き、会話の役割が変わらない
- 壊れた出力を止めようとして、確認文 fallback が連発する

この設計では、`merge.py` で文を強く縛るのではなく、**このターンで何をするのが自然か** を closed vocabulary で薄く与える。

---

## 2. 基本方針

### 2.1 やること

- meeting 専用の `meeting_turn_role` を推定する
- role は prompt に弱いヒントとして渡す
- merge では hard rule にせず、明らかな逸脱だけを見る

### 2.2 やらないこと

- 「Nia はこう話すべき」を LLM に丸投げしない
- role を文章テンプレートに直結しない
- role 不一致だけで発話を reject しない

---

## 3. role 語彙

最小集合は 5 つで十分。

| role | 意味 | 典型例 |
|---|---|---|
| `mirror` | 相手の感覚や言葉を受け取る | 「そう感じてるんだね」 |
| `deepen` | 今ある感覚を少しだけ深める | 「その軽さって、気づく感じに近いのかも」 |
| `connect` | 2つの話題や感覚を結び直す | 「静かな時間とライブの感覚が、同じ根っこかもしれない」 |
| `ask` | 開いた問いを一つ置く | 「その『気づく』って、どんな瞬間に出てくる？」 |
| `close` | ここまでを静かに畳む | 「今日はそこまで見えてきた気がする」 |

---

## 4. SkeletonCore との関係

`meeting_turn_role` は SkeletonCore の代替ではない。

- SkeletonCore: 今ターンの構造を読む
- meeting role: 次ターンでどの役割が自然かを決める

使う入力は既存の SkeletonCore で足りる。

- `focus`
- `response_intent`
- `question_intent`
- `rule_trace`
- 直近 2-3 ターンの skeleton history

特に meeting 拡張で入った次のラベルが主要シグナルになる。

- `returning_theme`
- `lingering_state`
- `offer_fragile_self_observation`
- `hold_open_space`

---

## 5. 推定ルール（最小版）

最初は rule-based でよい。

### 5.1 単ターンの対応

- `response_intent=RECEIVE` -> `mirror`
- `response_intent=ASK` -> `ask`
- `focus=RETURNING_THEME` -> `connect`
- `focus=LINGERING_STATE` -> `deepen`
- `response_intent=OFFER_FRAGILE_SELF_OBSERVATION` -> `deepen`
- close 判定がない時のデフォルトは `mirror`

### 5.2 連続ターンの補正

- 同じ role が2回続いたら、3回目は隣接 role にずらす
- `mirror` 連続 -> `deepen`
- `deepen` 連続 -> `connect` または `ask`
- `connect` 連続 -> `ask`
- `ask` の直後は `mirror` または `deepen`
- `close` は連続禁止

### 5.3 `close` の扱い

`close` は早く出しすぎると会話を切るので、最初は保守的にする。

- phase 1 では record-only でもよい
- 導入するなら Nero の close 判定や `closer_hint` と接続してから

---

## 6. 実装位置

### 6.1 推定

`routing.py` で skeleton を作った直後が自然。

- `conversation_skeleton` が state に載る
- recent skeleton history をすでに読める
- reflective depth2 の判定ロジックとも近い

追加 state:

```python
meeting_turn_role: Optional[str]  # mirror | deepen | connect | ask | close
```

### 6.2 prompt 反映

`depth1` / `depth2` の system prompt に、短い補助指示として渡す。

例:

- `mirror`: 今は受け取りを優先し、前に進めすぎない
- `deepen`: 感覚を壊さず、1段だけ深める
- `connect`: 2つのテーマのつながりを1つだけ示す
- `ask`: 開いた問いを1つだけ置く

ここでは role ごとの固定文面は持たない。

### 6.3 merge 側

merge は role を「採点」しない。

やるとしても次の程度に留める。

- `ask` role なのに質問が3個ある -> `_limit_questions()` で整える
- `close` role なのに新しい論点を2つ増やしている -> warning log

role 不一致だけで hard reject しない。

---

## 7. 導入順

### Phase 1: record-only

- `meeting_turn_role` を state に載せる
- log / observation にだけ出す
- Nero meeting で role 分布を見る

### Phase 2: prompt assist

- `depth1` / `depth2` に role を弱く注入する
- merge は現状維持

### Phase 3: light merge assist

- 役割逸脱の warning を出す
- 必要ならごく軽い postprocess を足す

---

## 8. 成功条件

この policy が効いている状態は、次で見分ける。

- 同意ループが減る
- `要点を言い直して` のような deterministic fallback に頼らない
- meeting の後半で `mirror` から `deepen / connect / ask` へ自然に移る
- Nia の言い回しの自由度が残る

---

## 9. 現時点の判断

今の meeting 問題に対しては、`Depth1Contract` を hard gate にするよりこちらが本筋。

理由:

- 問題は「文が不正」より「会話の役割が単調」だから
- Nia の内省対話は、厳格な reject より弱い誘導の方が相性がよい
- SkeletonCore の既存ラベルをそのまま活かせる
