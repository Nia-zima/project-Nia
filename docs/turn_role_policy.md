# Turn Role Policy

> 目的: 会話の各ターンに「この一手が何をしているか」を弱く与え、Nia の流れを整える。文そのものを強く縛るのではなく、会話の重心だけを支える。

---

## 1. 背景

今の問題は、単語や語尾の反復そのものより、**会話上の役割が固定化すること**にある。

典型例:

- ずっと受け取り続けて、会話が前に進まない
- 深めるべき場面で整理に寄りすぎる
- connect すべき場面で mirror が続く
- 壊れた出力を止めようとして、最終ガードが強くなりすぎる

この設計は、`merge.py` の hard guard を増やす代わりに、turn ごとの役割を closed vocabulary で持つ。

---

## 2. 基本概念

`turn_role` は SkeletonCore の代替ではない。

- SkeletonCore: 今ターンの構造を読む
- turn_role: 次の一手の重心を決める

最初の語彙は 5 つで十分。

| role | 意味 | 典型例 |
|---|---|---|
| `mirror` | 相手の感覚や言葉を受け取る | 「そう感じてるんだね」 |
| `deepen` | 今ある感覚を一段だけ深める | 「その軽さは、気づく感じに近いのかも」 |
| `connect` | 2つの話題や感覚をつなぐ | 「静かな時間とライブの感覚が、同じ根っこかもしれない」 |
| `ask` | 開いた問いを1つ置く | 「その『気づく』って、どんな瞬間に出てくる？」 |
| `close` | 今回はここまででよさそう、と柔らかく畳む | 「今日はそこまで見えてきた気がする」 |

---

## 3. どこで使うか

### 3.1 先に効く場所

- `depth1` prompt
- `depth2` prompt
- anti-repetition の補助
- meeting / companion 系の flow 制御

### 3.2 後から効く場所

- `soft_close` の質調整
- curiosity / stagnation 制御
- NiaCore の action head / pseudo teacher 特徴量

---

## 4. 推定入力

推定は既存 state と SkeletonCore でかなり足りる。

- `conversation_skeleton.focus`
- `conversation_skeleton.response_intent`
- `conversation_skeleton.question_intent`
- `conversation_skeleton.rule_trace`
- `selected_depth`
- `depth_action`
- recent skeleton history
- thread mode (`meeting`, `default`, 将来は `livestream` など)

meeting では、既存の meeting 拡張ラベルが特に効く。

- `returning_theme`
- `lingering_state`
- `offer_fragile_self_observation`
- `hold_open_space`

---

## 5. 最小ルール

### 5.1 単ターン対応

- `response_intent=RECEIVE` -> `mirror`
- `response_intent=ASK` -> `ask`
- `focus=RETURNING_THEME` -> `connect`
- `focus=LINGERING_STATE` -> `deepen`
- `response_intent=OFFER_FRAGILE_SELF_OBSERVATION` -> `deepen`
- 明示条件が弱い時の default は `mirror`

### 5.2 連続ターン補正

- 同じ role が 2 回続いたら、3 回目は隣接 role にずらす
- `mirror -> deepen`
- `deepen -> connect` または `ask`
- `connect -> ask`
- `ask -> mirror` または `deepen`
- `close` は連続禁止

### 5.3 mode 別プロファイル

いきなり全会話共通にはしない。

- `meeting`: `deepen / connect / ask` を厚く使う
- `default`: `mirror / organize寄りの deepen / ask` を基本にする
- `close` は mode ごとに閾値を変える

---

## 6. 実装位置

### 6.1 推定

`routing.py` で `conversation_skeleton` を作った直後が自然。

追加 state:

```python
turn_role: Optional[str]  # mirror | deepen | connect | ask | close
turn_role_source: Optional[str]  # skeleton_rule | role_transition | manual | None
```

### 6.2 prompt 反映

`depth1` / `depth2` の system prompt に短い補助として渡す。

例:

- `mirror`: 今は受け取りを優先し、進めすぎない
- `deepen`: 感覚を壊さず、一段だけ深める
- `connect`: 二つの流れのつながりを一つだけ示す
- `ask`: 開いた問いを一つだけ置く
- `close`: 締めすぎず、今回はここまででもよいと扱う

role を文面テンプレートにはしない。

### 6.3 merge 側

merge は role を採点しない。

やるとしても次だけ:

- `ask` role なのに質問が多すぎる -> `_limit_questions()`
- `close` role なのに論点を増やしすぎる -> warning log

role 不一致だけで hard reject しない。

---

## 7. core 系への影響

はい。かなり良い影響があります。

### 7.1 SkeletonCore

一番相性が良い。

- 既存の `focus / response_intent / question_intent` をそのまま使える
- Skeleton を「構造認識」に専念させ、turn_role は「次の手」に分離できる
- anti-repetition を intent 単位から role 単位に上げられる

### 7.2 NiaCore / NiaCore vNext

かなり効く。

- state vector に `turn_role` を入れると、「何をしようとしたターンか」が明確になる
- pseudo teacher や shadow 観測で、同じ text でも role が違うケースを分けて見られる
- future action head で `explore / deepen / question_back` と接続しやすい

特に vNext は、今でも `skeleton_response_intent` を特徴量に使っているので、そこに role を足すと意味の粒度が上がる。

### 7.3 Expression Layer

相性が良い。

- 表現特徴と `turn_role` を並べると、「どの role で hedge が増えるか」「どの role で close しがちか」を見られる
- text そのものではなく、役割ごとの表現傾向を分析できる
- 将来 bridge を作る時も、「Nia はこの場面で何をしているか」を閉じた語彙で渡せる

### 7.4 Governance / Review

補助的に効く。

- 反復や停滞を「悪い text」ではなく「role が回っていない状態」として観測できる
- review で「この発話は不自然」だけでなく、「role が mirror に偏った」が言える

### 7.5 Curiosity / anti-stagnation

かなり自然につながる。

- stagnation を text 類似ではなく role 停滞として見られる
- `offer_fragile_self_observation` が出ていても `deepen` に進んでいれば停滞ではない、と言いやすい
- `close` や `ask` の出しどころも curiosity 側と接続しやすい

---

## 8. 導入順

### Phase 1: 共通概念として追加

- `turn_role` を state に追加
- 推定だけする
- record-only で log / observation に出す

### Phase 2: meeting を先行導入

- `meeting` profile だけ prompt assist を有効化
- role 分布と会話後半の推移を見る

### Phase 3: default 会話へ拡張

- `default` profile を追加
- 相談 / 雑談 / 自己観察で role 遷移を調整

### Phase 4: core 系へ接続

- NiaCore shadow / pseudo teacher に role を配線
- Expression observation に role を載せる
- curiosity / stagnation 系に role 停滞を渡す

---

## 9. 成功条件

- 同意ループが減る
- hard fallback に頼らず会話が進む
- meeting だけでなく通常会話でも role の偏りが減る
- NiaCore / Expression の観測粒度が上がる
- Nia の話し方の自由度が残る

---

## 10. 現時点の判断

`turn_role` は meeting 専用の小手先に留めるのはもったいない。

一方で、いきなり全会話で live 制御するのは雑。

いちばん自然なのは、

1. 共通概念として `turn_role` を作る  
2. meeting を先行導入トラックにする  
3. 効いたら core 系へ配線する

この順です。

