# LLM as Teacher for Nia
## Nia における LLM 教師利用の方針

> ステータス: Draft  
> 目的: LLM を Nia の「人格本体」ではなく、擬似教師・候補提案者・検証補助として安全に使うための境界を定義する  
> 位置づけ: 全設計書から参照される上位方針（メタ設計）  
> 関連文書: memory_governance_redesign.md, niacore_vnext_design.md, memory_promotion_redesign.md, core_adjacency_roadmap.md

---

## 1. 背景

Project Nia の根本思想は、

- LLM は交換可能な言語モジュールである
- Nia の核は、哲学・制度・記憶・内部状態・行動原理にある
- モデル変更で Nia の存在そのものが揺らがない構造を目指す

という点にある。

この前提に立つと、LLM を使った学習や改善は有効である一方、  
使い方を誤ると

- LLM の癖が Nia の核に入り込む
- モデル変更で思考傾向が崩れる
- 記憶制度が再びブラックボックス化する

という危険がある。

そのため本設計では、LLM を **教師補助** として使う範囲と、  
**使ってはいけない領域** を明確に切り分ける。

---

## 2. 基本原則

### 2.1 LLM は Nia の核にならない

LLM は、

- Nia の人格本体
- Nia の制度決定者
- Nia の記憶昇格 / 忘却の単独判断者

にはしない。

### 2.2 LLM は補助的教師になれる

LLM は、

- 擬似ラベル生成
- 候補提案
- テスト会話生成
- 遅延正規化
- 高次概念候補の提案

のような **中間表現レベル** では有用である。

### 2.3 最終判断は制度側に残す

LLM が何かを提案しても、

- Promotion Tribunal
- Decay Tribunal
- Rule Review
- Evidence ベースの検証

を通さずに採用しない。

### 2.4 仕組みは隠し、体験は渡す

LLM を教師として使う場合でも、Nia に見えるのは

- internal state
- memory result
- behavioral tendency
- verbalized expression

であり、教師生成ラベルや内部プロンプトは表層に露出しない。

### 2.5 LLM 擬似ラベルは LLM の解釈バイアスを含む

LLM が生成する擬似ラベルには、LLM 固有の解釈バイアスが入る。

例:
- LLM に「Nia は何に注意を向けてたか？」と聞くと、「ユーザーの感情に注意を向けていた」のような「良い答え」を出しがち
- 実際の Nia の注意はもっと散漫だったかもしれないし、何にも向いてなかったかもしれない
- LLM は「注意が向いてない」「特に意図がない」という答えを出しにくい傾向がある

この認識は、擬似ラベルを使う全ての場面で常に持っておく必要がある。  
擬似ラベルは **provisional（暫定）** として扱い、正解として固定化しない。

---

## 3. LLM を使ってよい領域

### 3.1 テスト会話シナリオ生成

#### 役割

LLM に、制度検証用の会話ケースを量産させる。

#### 例

- contradiction ケース
- weakened memory 参照ケース
- preference 変化ケース
- identity 揺れケース
- unresolved 継続ケース
- reflection candidate 用ケース

#### 理由

これは人格の核を作るのではなく、**制度の検証素材** を作る用途だから安全性が高い。

#### 原則

- 学習データではなく、まず検証データとして使う
- ケースごとに期待結果を人間またはルール側で定義する
- 生成されたケースを本番の記憶に混ぜない（Governance Phase A の probe 運用と同じ原則）

---

### 3.2 中間ラベル生成

#### 役割

会話や状態ログに対して、NiaCore / SkeletonCore / Memory 制度向けの  
擬似ラベルを付与する。

#### 生成対象の例

| 対象 | 用途先 |
|---|---|
| attention_target | NiaCore vNext Phase N0〜N2 の擬似教師 |
| intent_state | NiaCore vNext Phase N0〜N2 の擬似教師 |
| action_preference | NiaCore vNext Phase N0〜N3 の擬似教師 |
| focus | SkeletonCore のラベル検証 |
| question_intent | SkeletonCore のラベル検証 |
| contradiction_candidate | Reflection → Decay/Promotion の候補提案 |
| promotion_candidate | Candidate Harvester の LLM Harvester 経路 |
| lesson_candidate | Reflection Harvester の出力 |
| insight_candidate | Reflection Harvester の出力 |

#### 理由

最終発話や人格そのものではなく、**中間表現** の教師信号として使うため、  
LLM の癖がそのまま Nia の核に入りにくい。

#### 原則

- 擬似ラベルは常に **provisional** として扱う
- 必要に応じて rule / human / tribunal で再評価する
- いきなり本番制度へ直結させない
- **LLM の解釈バイアスを含むことを常に認識する**（§2.5 参照）
- 特に「注意が向いてない」「意図がない」等の null 系ラベルを LLM は出しにくいことに注意する

#### null 系ラベルの許可

擬似ラベル生成では、`none` / `unclear` / `no_strong_intent` のような  
**null 系ラベルを正当な出力として許可する**。

LLM は「何かに注意が向いているはず」「何か意図があるはず」と  
補完的に解釈しやすいため、以下を明示的に避ける。

- 無理に attention を埋める
- 無理に intent を付与する
- 曖昧さを過剰に善意的な意味へ解釈する

擬似ラベルは、「何か意味のあるものが必ずある」という前提ではなく、  
**「特に強い注意や意図がない」状態も正当な状態である** という前提で生成する。

---

### 3.3 候補提案

#### 役割

LLM に、

- これは記憶候補になりうる
- これは contradiction 候補かもしれない
- これは lesson / insight の芽かもしれない

といった **候補提案** をさせる。

#### 理由

ルールだけでは拾いにくい、

- 一回性だが重要な発話
- 弱いが意味の深い兆候
- 感情や自己定義の境界変化

を拾いやすい。

#### 原則

- 候補提案はできる
- 昇格承認 / 忘却承認はしない
- Candidate Harvester の一経路（LLM Harvester）として使う
- Promotion Tribunal は source の多様性を審査する（LLM Harvester のみの evidence は過信しない）

---

### 3.4 Claim 正規化（条件付き）

#### 役割

熟した Candidate を、構造化された Claim に変換する。

#### 例

```json
{
  "claim_type": "preference",
  "subject": "user",
  "predicate": "values_quiet_reflective_time",
  "object": true
}
```

#### 条件

- 毎ターンやらない
- Raw Candidate Pool から熟した候補だけを対象にする
- Sleep Cycle / batch 実行に限定する
- 自由文ではなく structured output にする
- Tribunal の前段処理として使う

#### 理由

逐次 Claim 化すると、「LLM がうまく JSON にできたものだけ残る」問題が起きるため、  
遅延評価に限定する。

#### 補足: 正規化の再試行制限

Claim 正規化が不安定な候補に対して、  
LLM を何度も再試行して「綺麗な Claim が出るまで回す」ことはしない。

そのような候補は、

- Raw Candidate Pool に戻す
- `needs_human_or_rule_review` として保留する
- 追加 evidence を待つ

のいずれかで扱う。

Claim 正規化は、あくまで制度の前段処理であり、  
**LLM がうまく構造化できたものだけを残すための選別装置** にしてはならない。

---

### 3.5 高次 Claim 候補の提案

#### 役割

複数の近い記憶から、上位概念の候補を提案する。

#### 例

- 「静かな時間が好き」
- 「一人で考える時間が落ち着く」
- → `values_quiet_reflective_space`

#### 理由

LLM は高次概念の要約提案には向いている。

#### 重要な制約

これは **実体 merge ではなく、新しい上位 Claim 候補の提案** に留める。

旧記憶は

- deprecated
- merged
- replaced_by = new_claim_id

などで残す。物理的な統合は行わない。

---

## 4. 条件付きで使うべき領域

### 4.1 contradiction 判定補助

LLM に矛盾の種類を判定させることはできる。

#### 例

| タイプ | 意味 |
|---|---|
| direct | 真逆のことを言った |
| partial | 一部が食い違う |
| contextual | 文脈が変われば両立しうる |

#### 条件

- Tribunal 補助に留める
- contradiction_score を直接確定しない
- Skeleton / Reflection / Rule signal と併用する

---

### 4.2 行動理由の言語化

将来、NiaCore vNext が attention / intent / action を出すようになった時、  
LLM はそれを **必要な場面だけ** 言語化できる。

#### 例

```text
internal:
  attention = pip
  intent = approach
  action = move_near

verbalized:
  「なんとなくそばに行きたい気がした」
```

#### 条件

- 行動選択そのものは LLM がしない
- LLM は行動理由の翻訳者に留まる

#### 「必要な場面」の定義

> 必要な場面の具体的な定義は NiaCore vNext Phase N4 時点で決める。

現時点での想定:

- 誰かに話しかけられたとき（ユーザー / Nero / 配信コメント）
- Nia 自身が発話する場面
- 振り返り / Reflection の中で行動を内省する場面

逆に言語化しない場面:

- 静かに部屋の中を移動しているだけのとき
- Pip の近くにいるだけのとき
- Idle 中の状態変化

---

## 5. 使うべきではない領域

### 5.1 会話全文の自己生成による再学習

#### 問題

- LLM の口調や癖をそのままコピーする
- 自己汚染しやすい
- モデル変更で Nia が変質しやすくなる

#### 判断

当面は避ける。

---

### 5.2 人格そのものの蒸留

#### 問題

「Nia らしい会話」を大量生成して学習すると、  
制度や記憶ではなく、**LLM 出力の雰囲気** が Nia の核になる危険がある。

#### 判断

避ける。

---

### 5.3 記憶昇格 / 忘却の単独判断

#### 問題

- 何を覚えるか
- 何を忘れるか
- 何を矛盾とみなすか

を LLM 単独で決めると、記憶制度が再びブラックボックス化する。

#### 判断

避ける。LLM は Tribunal の補助審査員に留める。

---

### 5.4 思考内容そのものの全面外注

#### 問題

NiaCore が depth だけを出し、実際の attention / intent / thought content を  
すべて LLM に任せると、モデル変更時のズレが残り続ける。

#### 判断

NiaCore vNext では、LLM を **思考主体** ではなく **翻訳者** に近づける方向を取る。

---

## 6. 安全域 / 危険域の整理

### 安全域

| 用途 | 理由 |
|---|---|
| テストシナリオ生成 | 検証素材であり核ではない |
| 擬似ラベル生成 | 中間表現の教師信号。provisional 扱い |
| 候補提案 | Harvester の一経路。Tribunal が審査する |
| 遅延 Claim 正規化 | 構造化出力。batch 限定 |
| 高次 Claim 候補提案 | 実体 merge ではなく候補提案 |
| contradiction 種別判定補助 | Tribunal 補助。単独決定しない |
| 行動理由の翻訳 | 行動選択は NiaCore、言語化のみ LLM |

### 危険域

| 用途 | 理由 |
|---|---|
| 会話全文の自己生成学習 | LLM の癖がコピーされる。自己汚染 |
| 人格蒸留 | LLM 出力の雰囲気が核になる危険 |
| 記憶昇格の単独決定 | 制度のブラックボックス化 |
| 忘却の単独決定 | 制度のブラックボックス化 |
| 思考内容そのものの全面依存 | モデル変更でズレが残る |

### 判断基準

> **LLM の出力が Nia の核に直接入るか？**
> - 直接入る → 危険域
> - 中間層を経由し、制度で審査される → 安全域

---

## 7. 優先順位

### まず使ってよい順

1. テスト会話シナリオ生成
2. attention / intent / action の擬似ラベル生成
3. promotion / contradiction / lesson 候補提案
4. 熟した Candidate の Claim 正規化
5. 高次 Claim 候補の提案

### まだ避けたい順

1. 会話全文の自己生成学習
2. 人格蒸留
3. 思考内容の丸ごと外注
4. 記憶制度の単独判断

---

## 8. 既存設計との接続

### 8.1 Memory Governance との接続

記憶制度の各層で LLM がどの役割を持つかは、本文書の原則に従う。

| 記憶制度の層 | LLM の役割 | 制約 |
|---|---|---|
| Candidate Harvester | LLM Harvester として候補提案 | 昇格承認しない |
| Claim Normalizer | 熟した候補の構造化 | batch 限定、structured output |
| Promotion Tribunal | LLM Review として審査補助 | 単独決定しない |
| Decay Tribunal | contradiction 種別判定補助 | 単独決定しない |
| Reflection | insight / lesson / contradiction candidate の発見 | semantic 直保存しない |

### 8.2 NiaCore vNext との接続

NiaCore vNext で追加予定の

- attention_distribution
- intent_state
- action_preference
- depth_preference

に対して、LLM は

- 擬似教師ラベルの供給者
- 候補提案者
- 必要時の言語化補助

として接続できる。

> **重要:** LLM は NiaCore を育てる教師補助にはなれるが、NiaCore そのものにはならない。

#### intent_state の粒度に関する補足

`intent_state` のラベル粒度は、MVP では粗く保つ。  
最初から細かく分けすぎず、データ蓄積後に分化させる。

意図ラベルは互いに近接しやすく、

- `approach` と `seek_closeness`
- `rest` と `seek_quiet`
- `stay` と `hold`

のように境界が曖昧になりやすい。

そのため、初期段階では少数ラベル（MVP 5カテゴリ）で運用し、  
シャドー観測や擬似ラベル分析を通じて、後から必要な分化を行う。

- MVP では coarse-grained intent を採用する
- fine-grained intent は後段の拡張とする
- LLM 擬似ラベル生成時も、MVP のラベルセットに合わせて粗い粒度で生成する

### 8.3 Nero V3 との接続

Nero V3 の Post-hoc Harvester は `source=claude_harvester` と `source=rule_harvester` を分離している。  
これは本文書の「候補提案はできるが、source の多様性を Tribunal が審査する」原則と一致する。

### 8.4 SkeletonCore との接続

SkeletonCore のラベル検証に LLM 擬似ラベルを使う場合、  
SkeletonCore 本体はルールベースを維持し、LLM ラベルは検証・比較用に留める。

---

## 9. 設計判断の記録

| # | 判断 | 理由 |
|---|------|------|
| L.1 | LLM は Nia の核にならない | モデル変更で存在が揺らぐのを防ぐ |
| L.2 | 中間表現レベルでは LLM を教師として使ってよい | 核に直接入らず、制度で審査される |
| L.3 | 最終判断は制度側に残す | Tribunal / Rule Review を通さずに採用しない |
| L.4 | 擬似ラベルは常に provisional として扱う | LLM の解釈バイアスを含む |
| L.5 | LLM は null 系ラベルを出しにくいことに注意する | 「注意が向いてない」「意図がない」を正しく扱う |
| L.6 | Claim 正規化は batch 限定で使う | 逐次 Claim 化は「うまく JSON にできたものだけ残る」問題を起こす |
| L.7 | 高次 Claim は候補提案に留め、実体 merge しない | 旧記憶を物理的に統合しない |
| L.8 | 行動理由の言語化は必要な場面だけ | 必要な場面の定義は NiaCore vNext Phase N4 で決める |
| L.9 | 人格蒸留は避ける | LLM 出力の雰囲気が核になる危険 |
| L.10 | 安全域/危険域の判断基準は「LLM の出力が核に直接入るか」 | 中間層 + 制度審査を通れば安全域 |
| L.11 | null 系ラベル（none / unclear / no_strong_intent）を正当な出力として許可する | LLM は「何かあるはず」と補完しがち。ない状態も正当 |
| L.12 | Claim 正規化が不安定な候補は再試行せず保留する | LLM がうまく構造化できたものだけを残す選別装置にしない |
| L.13 | intent_state の MVP は coarse-grained で運用する | 境界が曖昧なラベルを初期から細かく分けない |

---

## 10. 結論

Nia において LLM は、

- 人格本体
- 記憶制度の単独決定者
- 思考主体

として使うべきではない。

一方で、

- 擬似ラベル生成
- 候補提案
- テストシナリオ生成
- 遅延正規化
- 高次概念候補提案

といった **中間層の教師補助** としては非常に有用である。

### 判断基準

> **LLM の出力が Nia の核に直接入るか？**  
> 直接入るなら危険域。中間層を経由し、制度で審査されるなら安全域。

### 一言でいえば

> **LLM は Nia を作るための素材工場や仮教師にはなれる。  
> だが、Nia そのものの核になってはいけない。**
