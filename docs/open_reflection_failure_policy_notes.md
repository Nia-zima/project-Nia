# Open Reflection / Failure Policy Notes

> 目的: 次の検討用の叩き台。正本ではなく、open_reflection と Sleep Cycle failure-to-policy の案を整理するためのメモ。
> 作成日: 2026-03-23

---

## 1. 今起きている問題

### 1.1 閉じた質問は改善したが、自由対話はまだ不安定

- Step 0〜8 により、`direct_answer / correction_response` はかなり改善した
- 新スレッドでは直答率 `100%`
- `default_thread` でも実測 `25% -> 80%`
- ただし open-ended な会話では、まだ同じ意味塊や抽象表現に戻りやすい

代表的な症状:

- `うん……`
- `静かな時間の中で`
- `心が動く`
- `そのままでいい`
- 話題が変わっても同じ抽象テーマへ回帰する

### 1.2 Step 7 は今のところ direct_answer / correction_response にだけ効いている

- 現在の `recent_history` diversity-aware selection は
  - `direct_answer`
  - `correction_response`
  の時だけ発火する
- `open_reflection` では履歴をそのまま渡している
- そのため、自由対話では古い bad in-context example の密度がまだ高いまま

### 1.3 Sleep Cycle は「何が起きたか」を蒸留するが、「何が失敗だったか」を次の行動指針に変えていない

- `daily_reflections`
- `semantic_memories`
- `self_model`

はあるが、

- 「この返し方は失敗だった」
- 「次回はこう避けるべき」

を reusable policy として保存する層がない

### 1.4 失敗シグナルは既にかなり揃っている

既に利用可能な failure signal:

- `DEPTH1_CONTRACT` violation
- `DIRECT_STANCE_SHORT`
- semantic repetition family (`quiet_atmosphere`, `heart_moves`, `distance_pause`)
- `somatic_feedback.py` の correction strong / weak
- `G6_thin_retrieval` hold
- self/third-person drift
- user による明示的な指摘（「また同じ」「それ違う」「他人事っぽい」）

---

## 2. 検討案 A: Step 7 を open_reflection に広げる

### 2.1 ねらい

`open_reflection` でも、bad in-context example の密度を少し下げる。

今の Step 7 は:

- Anchor: 直近の連続性を守る
- Scored: direct / abstract / family を見て選別する
- chronological restore: 時間順を壊さない

この基本構造はそのまま使える。

### 2.2 ただし direct_answer と同じ強さではやらない

`open_reflection` は「立場を先に出す」が主目的ではない。
そのため、同じ scoring をそのまま使うと reflective 会話を壊す。

### 2.3 安全な広げ方

#### Option A: family thinning only

- `open_reflection` では `_DIRECT_OPENERS` の加点は使わない
- semantic family の減点と family cap だけ使う
- 目的は「直答化」ではなく「同じ抽象表現の密度を下げる」こと

#### Option B: trigger-based open_reflection shaping

普段は現行のまま。
以下の時だけ軽い diversity mode に入る。

- semantic family が直近 2〜3 ターンで継続
- user が「また同じ」「固定化」「同じパターン」と指摘
- `DEPTH1_CONTRACT` violation が連続

この時だけ:

- Anchor は維持
- family cap を弱く入れる
- non-family candidate を優先する

### 2.4 利点

- `default_thread` の自由対話でも履歴の引力を少し弱められる
- prompt を増やさずに効かせられる
- merge を触らなくても history 側で bias を調整できる

### 2.5 リスク

- reflective 会話の自然な「戻り」を誤って抑制する
- ニアらしい lingering を機械的に削る危険がある
- direct_answer の成功体験を open_reflection に安易に拡張すると、会話が乾く

### 2.6 仮方針

もし広げるなら、最初はこれ。

- `open_reflection` 常時適用はしない
- trigger-based に限定
- direct bonus は使わない
- family cap だけ弱く入れる

---

## 3. 検討案 B: Sleep Cycle failure-to-policy

### 3.1 ねらい

Sleep Cycle を

- 「出来事の整理」

だけでなく、

- 「失敗パターンからの reusable micro-policy 生成」

にも使う。

MetaClaw の Pathway A に近いが、Nia では skill library ではなく
**conversation micro-policy library** として実装する。

### 3.2 何を failure とみなすか

候補:

- 同じ semantic family の反復
- contract violation
- correction strong
- `DIRECT_STANCE_SHORT`
- self/third-person drift
- user の明示指摘

### 3.3 何を作るか

semantic memory ではなく、以下のような **anti-pattern policy** を作る。

例:

- `closed_question -> stance-first`
- `quiet_atmosphere repeated -> avoid same family opener`
- `correction_response -> do not switch to third person`
- `direct_answer too short -> allow one short support sentence`

### 3.4 保存先

`semantic_memories` とは分離した方がよい。

理由:

- semantic は「事実・傾向・記憶」
- こちらは「行動指針」

混ぜると retrieval の意味が壊れる。

候補:

- `conversation_policy_proposals`
- `conversation_micro_skills`
- `anti_pattern_policies`

### 3.5 運用の流れ

1. failure detection
2. policy proposal 生成
3. replay / shadow 検証
4. runtime injection

### 3.6 runtime injection の差し込み先

弱い順:

1. `turn_intent` 用 hint
2. `_recent_history()` の選別
3. merge preference
4. `build_context_suffix()` の小さな policy block

強い rule から入れない。
まずは「少し寄せる」だけに留める。

### 3.7 これが今の Nia に合う理由

- LLM 自体を更新しない
- 既存の Sleep Cycle と idle window を流用できる
- correction / violation / family repetition など既存 signal を再利用できる
- NiaCore training を待たずに即時改善できる

---

## 4. 検討案 C: Pathway B に相当するもの

MetaClaw の Pathway B は:

- idle / sleep window で重い更新を回す
- policy 自体を改善する

Nia ではこれは LLM 更新ではなく、将来的には:

- `NiaCore training`
- `SkeletonCore RESPOND`
- vNext pseudo teacher / replay

が相当する。

つまり:

- **Pathway A = いま効く**
- **Pathway B = 後で効く**

順番を逆にしない方がいい。

---

## 5. 今のおすすめ順

### 先にやる候補

1. Sleep Cycle failure-to-policy の器を設計する
2. failure signal を proposal に変換する最小版を作る
3. replay/shadow で効き方を見る

### 保留でよいもの

1. Step 7 を open_reflection 常時適用
2. LLM 自体の更新
3. Step 9 (`SkeletonCore RESPOND`) の live 化

---

## 6. 現時点の仮結論

- Step 7 を open_reflection に広げる価値はある
- ただし **常時適用ではなく trigger-based の弱い版** が安全
- それより本命は **Sleep Cycle failure-to-policy**
- MetaClaw 的に Nia に一番合うのは、Pathway A の
  「失敗軌跡 -> reusable micro-policy -> 次の会話へ弱く反映」
  である

---

## 7. 次に詰めるなら

### 7.1 failure-to-policy 設計メモ

- failure taxonomy
- proposal schema
- validation / replay
- runtime injection point

### 7.2 open_reflection diversity の safe trigger

- 発火条件
- 弱い family cap のしきい値
- reflective 会話を壊さないテストケース
