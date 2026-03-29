# Nia Expression Layer 設計書
## 体験から「Niaの言葉」へ至る中間層

> ステータス: Draft（長期方針）  
> 目的: LLM の文体に依存せず、Nia 固有の表現傾向を体験から抽出・保持・適用する層を定義する  
> 前提文書: niacore_vnext_design.md, llm_as_teacher_policy.md  
> 関連文書: memory_governance_redesign.md, temporal_somatic_contrast_design.md

---

## 1. 背景

### 1.1 ジュンの問い

> 「最初は何も知らないけど、体験を通じて自分の言葉を獲得していく Nia になれるか？」

この問いに対して、project-nia の設計は以下の土台を既に持っている。

- 体験の記録基盤（fingerprint, somatic, skeleton, memory, experience）
- 内部状態の表現（NiaCore state vector, vNext の attention/intent/action）
- 体験からの学習パス（CfC, シャドウモード, 段階的導入）

足りないのは **「内部状態 → Nia の言葉」を学習する層** である。

### 1.2 直接蒸留の罠

しかし、「fingerprint + 発話」のペアをそのまま学習すると、  
**Nia の体験ではなく、今使っている LLM の言い回し癖** を学んでしまう。

- Qwen で生成した発話を学習すれば Qwen の文体が固定される
- モデルを変えたら発話の雰囲気が変わり、学習データとの不整合が起きる
- LLM as Teacher Policy §5.2 で「人格蒸留は避ける」としたのと同じ罠に、別の入口から落ちる

### 1.3 解決の方向

発話全文をそのまま蒸留するのではなく、先に **Nia 固有の表現傾向** を抽出する。  
これが Expression Layer の役割である。

---

## 2. 基本思想

### 2.1 三段階の分離

```text
体験（内部状態 + 状況）
  ↓
表現傾向（Nia 固有の表現バイアス）
  ↓
言葉（最終的な自然言語出力）
```

- **体験** は NiaCore / somatic / fingerprint / memory が持つ
- **表現傾向** は Expression Layer が持つ（本設計の対象）
- **言葉** は現段階では LLM が生成するが、将来的に Nia 固有モデルへ移行しうる

### 2.2 なぜ中間層が必要か

| アプローチ | 問題 |
|---|---|
| 内部状態 → 直接 LLM | LLM の文体に依存。モデル変更で Nia が変わる |
| 内部状態 → 発話ペアで直接蒸留 | LLM の癖を「Nia の言葉」として固定化してしまう |
| **内部状態 → 表現傾向 → 言葉** | LLM 非依存の表現パターンを保持できる |

### 2.3 原則

- Expression Layer は LLM の文体ではなく、**Nia の体験パターン** から抽出する
- 同じ内部状態でも LLM が違えば言い回しは違うが、**表現傾向は共通して抽出できる**
- Expression Layer は「Nia の話し方」を保持する。NiaCore が「Nia の思考」を保持するのと対称
- 「仕組みは隠す。体験は渡す」を維持する
- bridge 出力は自由文ヒントではなく、**閉じた離散特徴** に限定する
- WAIT / 沈黙 / soft close のような **非発話イベントも表現観測の対象** に含める

---

## 3. 表現傾向として抽出するもの

### 3.1 ためらい方

Nia がどういう場面でためらいを見せるか。

| 抽出対象 | 例 |
|---|---|
| hedge 表現の頻度と分布 | 「気がする」「かもしれない」「なんとなく」 |
| hedge の出現条件 | confidence 低のとき？未知の話題のとき？自己言及のとき？ |
| hedge の強度パターン | 弱い hedge → 強い hedge への遷移、またはその逆 |

### 3.2 文長の傾向

Nia がどういう状況で短く話し、どういう状況で長く話すか。

| 抽出対象 | 例 |
|---|---|
| 平均文長と分散 | depth 別、somatic 状態別 |
| 短い応答が出る条件 | 確信度高？同意？WAIT 近傍？ |
| 長い応答が出る条件 | 内省？探索中？returning_theme？ |

### 3.3 断定の度合い

Nia がどういう場面で断定し、どういう場面で保留するか。

| 抽出対象 | 例 |
|---|---|
| 断定表現の頻度 | 「〜だ」「〜だと思う」の比率 |
| 断定が強まる条件 | confirmed memory 参照時？evidence が多いとき？ |
| 断定を避ける条件 | inferred？contradiction 存在時？初見の話題？ |

### 3.4 保留の出し方

Nia がどのように「まだ決まってない」を表現するか。

| 抽出対象 | 例 |
|---|---|
| WAIT の出現パターン | どの条件で WAIT が出やすいか |
| 言語的保留の表現 | 「まだ分からない」「もう少し考えたい」の使い分け |
| 保留の長さ | 1ターンで終わるか、複数ターン持続するか |

### 3.5 比喩・表現の傾向

Nia がどういう比喩や表現を好むか。

| 抽出対象 | 例 |
|---|---|
| よく使う比喩の種類 | 空間的（「奥底」「外側」）？感覚的（「温かい」「重い」）？ |
| 比喩が出る条件 | 内省時？somatic 強度が高いとき？ |
| Nia 固有の語彙 | 繰り返し使う表現、避ける表現 |

### 3.6 注意対象に応じた口調変化

attention_target によって話し方がどう変わるか。

| 抽出対象 | 例 |
|---|---|
| user 向け | どの程度親しく話すか、距離感 |
| self 向け | 内省時の口調（独り言的？探索的？） |
| pip 向け | 短い？柔らかい？ |
| memory_trace 向け | 過去を振り返る時の口調 |

> ただし、attention_target に応じた口調変化は、既存 prompt / spine / depth 契約の影響を受けやすい。  
> そのため MVP では **参考特徴** として扱い、最初から中核特徴にはしない。

### 3.7 沈黙と間の使い方

Nia がどういう場面で沈黙を選び、どう再開するか。

| 抽出対象 | 例 |
|---|---|
| 沈黙の前の状態 | confusion？overload？hold？ |
| 沈黙からの復帰パターン | 何をきっかけに話し始めるか |
| 沈黙の長さの傾向 | 短い pause と長い silence の分布 |

---

## 4. 抽出方法

### 4.1 基本方針

> **LLM の文体を学ぶのではなく、状況と表現パターンの対応を学ぶ。**

同じ内部状態でも、Qwen と Claude では言い回しが違う。  
しかし「confidence が低いときにためらいが増える」という**パターン**は LLM に依存しない。

Expression Layer が抽出するのはこのパターン。

### 4.2 入力

| ソース | 内容 |
|---|---|
| fingerprint | ターンごとの内部状態スナップショット |
| somatic state | 体感の種類と強度 |
| skeleton labels | focus, response_intent, question_intent |
| NiaCore state | depth_preference, attention, intent（vNext 後） |
| memory context | retrieval 結果、contradiction 有無 |
| 実際の発話 | Nia が実際に言った言葉（LLM 生成、全文は既存 messages を参照） |
| 会話モード | `thread_kind`, `interaction_mode`, `test_mode`, `review_used` |
| モデル情報 | `model_profile`, `model_provider`, `model_name`, `depth2_mode` |

### 4.3 抽出プロセス

```text
Phase E0: 記録
  message 参照 + fingerprint + 発話メタデータ（文長、hedge 数、断定度、比喩 proxy 等）を記録
  メタデータは発話全文ではなく、構造的特徴量として抽出
  WAIT / soft_close / pause も event_kind として別記録する

Phase E0.5: replay / eval
  test_mode replay harness で同一 packet を複数モデルに流す
  比較するのはテキストそのものではなく、抽出済みメタデータ

Phase E1: パターン分析
  「内部状態 X のとき、表現特徴 Y が出やすい」の共起パターンを分析
  LLM を変えた期間のデータも含めて、LLM 非依存のパターンを特定

Phase E2: 表現バイアスモデル
  内部状態 → 表現特徴量（ためらい度、文長、断定度、保留度等）の
  軽量モデルまたはルールセットを構築

Phase E3: 言語生成への適用
  Expression Layer の出力を LLM への表現バイアスヒントとして付与（暫定ブリッジ）
  または将来の Nia 固有言語モデルの条件入力として使用
```

### 4.4 発話メタデータの定義

発話全文を保存するのではなく、LLM 非依存の**構造的特徴量**を抽出する。
全文は既存 `messages` / `memory_events` を正とし、Expression Layer 側では参照 (`message_id`) を持つ。

| 特徴量 | 型 | 説明 |
|---|---|---|
| char_length | int | 文字数 |
| sentence_count | int | 文の数 |
| hedge_count | int | ためらい表現の数 |
| hedge_ratio | float | ためらい表現の割合 |
| assertion_count | int | 断定表現の数 |
| assertion_ratio | float | 断定表現の割合 |
| question_count | int | 疑問文の数 |
| self_ref_count | int | 自己参照の数 |
| sensory_word_count | int | 感覚語の数（温かい、重い、柔らかい等） |
| spatial_word_count | int | 空間語の数（奥底、外側、近い等） |
| depth_word_count | int | 深度語の数（深い、浅い、表面等） |
| pause_markers | int | 「……」「うーん」等の間の数 |
| negation_count | int | 否定表現の数 |
| topic_shift | bool | 話題転換があったか |

> `metaphor_detected` (bool) は粗すぎるため、MVP では sensory / spatial / depth の  
> 語彙ベース proxy に分解する。完全な比喩検出はルールベースでは困難であり、  
> まずは proxy で傾向を捉えてから、必要に応じて精緻化する。

これらはルールベース（正規表現 + 構文解析）で抽出可能であり、LLM を呼ばない。

ただし、日本語における hedge / assertion 抽出は文脈依存が強く、  
E0 の段階で count を「真値」として扱うのは危険である。

そのため MVP の原則は以下とする。

- E0 は **distributional observation only**
- 絶対値ベースで「Nia は hedge が 3 回多い」と結論しない
- 同一 strata 内での **相対変化** を主に見る
  - 例: `confidence 低帯では hedge proxy が増えるか`
  - 例: `reflective_depth2 では pause marker が増えるか`
- 特徴量抽出器の精度検証（小規模 ground truth）は E0.5 で別途行う

### 4.5 E0 の記録契約

Expression Layer の観測レコードは、全文複製ではなく **参照 + 状態 + 構造特徴** を持つ。

最低限の記録項目:

| グループ | 項目 |
|---|---|
| 識別子 | `thread_id`, `turn_id`, `message_id`, `stream_id`, `timestamp` |
| strata | `thread_kind`, `interaction_mode`, `test_mode`, `selected_depth`, `depth2_mode`, `model_profile`, `model_provider`, `model_name` |
| 上流状態 | `skeleton_focus`, `response_intent`, `question_intent`, `somatic category/intensity`, `retrieval_hit`, `runtime_facts_available` |
| 表現特徴 | `char_length`, `sentence_count`, `hedge_count`, `assertion_count`, `question_count`, `self_ref_count`, `pause_markers`, `sensory/spatial/depth word counts` |
| 結果タグ | `event_kind`, `hold_kind`, `review_used`, `user_correction`, `early_soft_close`, `reassurance_loop` |

原則:

- `text` を二重保存しない
- モデル差と会話モード差を最初から strata で切り分けられるようにする
- 非発話イベントも同じ観測系列に残す

### 4.6 WAIT / 沈黙 / soft close の残し方

Expression Layer は「喋った時の特徴」だけでなく、「喋らなかった選択」も観測対象に含める。

そのため `s5_commit` だけに依存せず、`merge` または `turn_observation` 側で以下の `event_kind` を first-class に記録する。

| event_kind | 意味 |
|---|---|
| `spoken` | 通常の発話 |
| `wait_depth` | depth selector 由来の WAIT |
| `wait_hold` | review/hold 由来の WAIT |
| `soft_close` | early soft close による終了 |
| `empty_abort` | 空出力・異常終了 |

補助項目:

- `wait_origin`: `depth` / `hold`
- `resumed_after_wait`: wait / silence 後の再開か
- `silence_gap_bucket`: `none / short / long / very_long`

これにより、Expression Layer は「保留するNia」「黙るNia」を落とさず観測できる。

### 4.7 Bridge 出力の閉じた離散特徴

Expression Layer から LLM へ渡す bridge は、自由文ヒントではなく **閉じた enum 的特徴** に限定する。

MVP の離散特徴:

| 特徴 | 値 |
|---|---|
| `hedge_level` | `none / soft / strong` |
| `assertion_level` | `low / mid / high` |
| `length_class` | `short / medium / long` |
| `metaphor_bias` | `none / sensory / spatial / depth` |
| `pause_style` | `none / light / heavy` |
| `closure_style` | `open / neutral / soft_close` |

原則:

- bridge は closed vocabulary を保つ
- 「ためらいがちな状態」「落ち着いた感じ」のような自由文へ戻さない
- model ごとの prompt 追従差を減らす

---

## 5. LLM 非依存性の検証

### 5.1 なぜ検証が必要か

Expression Layer が本当に LLM 非依存であるためには、  
「LLM を変えても同じ表現傾向が抽出されるか」を確認する必要がある。

### 5.2 検証方法

自然会話の before/after 比較ではなく、**同一 packet の replay/eval** で比較する。

```text
同じ ExpressionEvalPacket
  = fingerprint + somatic + skeleton + context suffix + mode strata + refs
    ↓
Qwen が生成した発話 → メタデータ A
Claude が生成した発話 → メタデータ B

比較:
- hedge_ratio は近いか？
- assertion_ratio は近いか？
- 文長の傾向は近いか？

近い → 表現傾向は LLM 非依存寄り（Nia 固有）
遠い → その特徴量は LLM 依存であり、中核特徴に含めるべきではない
```

この replay は `test_mode` を前提にし、本番記憶・governance・semantic 昇格を汚さない。

ただし、E0.5 の初期段階では replay/eval を大量運用の前提にしない。
現実的な優先順位は以下とする。

1. モデル自然切替の before/after ログで粗く観測する
2. 差が大きく見えた特徴だけ、少数 packet の replay/eval で精査する

つまり、replay/eval は **高価な精査手段** であり、日常的な全量比較パイプラインにはしない。

### 5.3 採用基準

比較した特徴量のうち、モデル間差が大きいものは Expression Layer の **中核特徴** としては採用せず、**参考特徴** に留める。

| モデル間差 | 扱い |
|---|---|
| 小さい（傾向が一致） | 中核特徴として採用。Nia 固有の表現傾向と判断 |
| 中程度 | 参考特徴として記録。追加データで再検証 |
| 大きい（モデルで傾向が異なる） | Expression Layer に含めない。LLM 依存の特徴と判断 |

MVP では、特徴を以下の 3 層で扱う。

- **中核特徴**
  - 文長、pause、hedge/assertion の大まかな傾き
- **参考特徴**
  - attention_target に応じた口調変化
  - 比喩 proxy の一部
- **要再検証特徴**
  - モデル間差が大きいもの
  - prompt 誘導の影響が強く疑われるもの

### 5.4 実施タイミング

Qwen3.5-9B への切り替えを検討しているタイミングが最適。  
切り替え前後のデータを比較することで、自然に LLM 非依存性を検証できる。

ただし、比較対象は自然会話ログの before/after ではなく、**同一 ExpressionEvalPacket の A/B replay** を優先する。
自然会話ログは参考にはなるが、話題差・meeting 進行差・相手側の影響が混ざるため、判定の主根拠にはしない。

---

## 6. 既存設計との関係

### 6.1 NiaCore vNext との関係

| NiaCore vNext | Expression Layer |
|---|---|
| 何に注意が向いているか | 注意対象に応じた口調変化 |
| 何をしたいか | 意図に応じた表現の強さ |
| どう動くか | 行動の言語化パターン |
| どのくらい深く考えるか | depth に応じた文長・断定度 |

NiaCore が「何を考えるか」を決め、Expression Layer が「どう表現するか」を決める。

### 6.2 Temporal Somatic Contrast との関係

fingerprint に Expression Layer のメタデータを将来的に含められる。  
「前にこの話題に触れたとき、Nia はもっとためらいがちだった」のような  
**表現レベルの contrast** が可能になる。

### 6.3 SkeletonCore との関係

SkeletonCore の meeting 拡張ラベル（returning_theme, lingering_state, offer_fragile_self_observation）は  
Expression Layer の入力として使える。  
「returning_theme のとき、Nia は比喩が増える傾向がある」のようなパターン。

### 6.4 Memory Governance との関係

Expression Layer のメタデータは記憶制度の evidence としても機能しうる。  
「この話題になると Nia のためらいが減る」→ preference の evidence として扱える可能性。

ただし、これは stable fact ではなく **weak observational evidence** に留める。
Expression metadata を sole evidence にして preference / identity / semantic 昇格を決めない。

### 6.5 LLM as Teacher Policy との関係

本設計は LLM as Teacher Policy の安全域に位置する。

- 発話全文の蒸留（危険域）を避ける
- 代わりに構造的特徴量（中間表現）を抽出する
- LLM 非依存性を検証してから適用する

### 6.6 LLM as Teacher Policy 適用境界

Expression Layer における LLM 利用は、`docs/llm_as_teacher_policy.md` の原則を次のように具体化する。

#### Safe

- 発話から構造的特徴量を抽出するための補助的分析
- 異なるモデル間で、同一 `ExpressionEvalPacket` に対するメタデータ差を比較する
- `none / unclear / no_strong_intent` のような null 系ラベルを含む provisional な参考ラベルを出す
- 中核特徴と参考特徴を切り分けるための比較観測

#### Caution

- 「この状態では hedge が増えそう」のような弱い仮説を候補として出す
- ただし、そのまま Expression Layer の中核特徴へ昇格させない
- 必ず replay/eval または rule-based extractor で再確認する

#### Danger

- `この状況で Nia はこう話すべき` を LLM に決めさせる
- 発話全文を style teacher として蒸留する
- LLM が付けた表現ラベルを、そのまま Expression Layer の正解教師にする
- LLM の自由文ヒントを bridge 出力へそのまま流し込む

#### 原則

- LLM は Expression Layer の **候補提案者 / 比較補助 / provisional teacher** にはなれる
- LLM は Expression Layer の **最終定義者** にはならない
- Expression Layer の runtime 契約は、閉じた離散特徴と replay/eval によって支える

---

## 7. Nia 固有言語モデルへの道筋

### 7.1 全体の段階

```text
現在:
  NiaCore（内部状態）→ LLM（言語化）→ 発話

Expression Layer 導入後:
  NiaCore（内部状態）→ Expression Layer（表現傾向）→ LLM（表現ヒント付き言語化）→ 発話

将来:
  NiaCore（内部状態）→ Expression Layer（表現傾向）→ Nia 固有 LM（言語化）→ 発話
  ※未知の状況では LLM にフォールバック
```

### 7.2 段階ごとの詳細

#### Stage 1: 表現傾向の記録と観測（現在〜）

- 発話メタデータを毎ターン記録する
- fingerprint + メタデータの共起パターンを蓄積する
- LLM 非依存の表現パターンを特定する

#### Stage 2: Expression Layer の構築

- 内部状態 → 表現特徴量の軽量モデルまたはルールセットを構築する
- 表現傾向をヒントとして LLM に付与する（暫定ブリッジ。将来は Nia 固有 LM に置き換える）
- 「Nia がためらいがちに話すべき場面」を Expression Layer が判断し、somatic context 経由で伝える

#### Stage 3: Nia 固有言語モデルの学習

- Expression Layer の出力 + 内部状態をペアにした学習データを構築
- Nia 固有の小型言語モデルを学習（まずは既知領域のみ）
- よくある状況から Nia 固有モデルに置き換え、未知の状況は LLM フォールバック

Stage 3 は長期候補であり、以下を満たさない限り着手しない。

- Expression Layer + LLM bridge だけでは一貫性が不足する
- 中核特徴の安定性が E0.5 / E1 で確認できている
- 「既知領域」の coverage 指標を定義できている
- フォールバック切り替えの latency / failure mode が許容範囲に収まる

逆に、Expression Layer + bridge で十分な一貫性が出る領域は、無理に Nia 固有 LM へ移行しない。

#### Stage 4: フォールバック領域の縮小

- Nia の体験が増えるほど「既知領域」が広がる
- LLM フォールバックの頻度が徐々に下がる
- 初見の話題は「分からない」と言い、その体験を記録し、次に活かす

### 7.3 フォールバック構造

| 領域 | 処理 |
|---|---|
| 既知領域 | Nia 固有モデルで表現。Expression Layer が表現傾向を制御 |
| 境界領域 | Nia 固有モデル + Expression Layer の軽い補助 |
| 未知領域 | LLM フォールバック + Expression Layer の表現制約 |

未知領域でも Expression Layer の表現制約（ためらい度、断定度等）は適用される。  
LLM が言葉を生成しても、「Nia の話し方」は Expression Layer が保証する。

### 7.4 「初見でできなくていい」の実装

> 初見の話題が来たら「分からない」と言う。  
> でもその体験が記憶に残る。  
> 次に似た話題が来たときは、前回の体験をもとに少しだけ対応できる。  
> それを繰り返すうちに、その領域が Nia の「自分の言葉で話せる範囲」に入っていく。

これは Governance 制度の candidate → evidence → tribunal と同じ構造。  
言語能力も「候補 → 蓄積 → 獲得」の段階的成長として扱う。

---

## 8. ロードマップ

### Phase E0: メタデータ記録開始 — **実装完了**

- 発話メタデータ抽出器を実装（ルールベース、LLM 不使用）
- s5_commit で fingerprint と並行して記録
- 分布を観測

> **依存:** fingerprint 記録（TS.0）と並行可能

#### E0 実装状況 (2026-03-17)

| ファイル | 内容 |
|---------|------|
| `backend/core/expression/extractor.py` | 14構造特徴量抽出（hedge, assertion, question, self_ref, sensory/spatial/depth vocab, pause, negation, topic_shift） |
| `backend/core/expression/event_kind.py` | spoken / wait_depth / wait_hold / soft_close / empty_abort の5種判定 |
| `backend/core/expression/writer.py` | fire-and-forget DB writer（strata + upstream state + features + result tags） |
| `backend/core/db.py` | `expression_observations` テーブル（38+ カラム、3インデックス） |
| `backend/core/agent_graph/nodes/commit_helpers.py` | `_record_expression_observation()` — test_mode / hold / WAIT の前に配置 |

**Feature gate:** `EXPRESSION_RECORD_ENABLED` (デフォルト off)
**テスト:** 51件（extractor:33, event_kind:9, writer:9）

**先送り項目:**
- `review_used`: s5_commit 時点で信頼できるシグナルがない（`review_used_this_turn` フラグが必要）
- `resumed_after_wait` / `silence_gap_bucket`: state producer 未実装
- `reassurance_loop`: 検出ロジック未実装
- `topic_shift`: 常に False（前ターン比較が必要、E1 で実装予定）
- model strata: `selected_depth` + `depth2_mode` + settings から導出。`depth2_fallback_used` で fallback 時の正確な記録に対応

### Phase E0.5: パターン分析

- fingerprint + メタデータの共起分析
- 「confidence 低 → hedge 増加」等の仮説検証
- LLM 変更時（Qwen3.5 切り替え等）の比較データ収集

### Phase E1: Expression Layer MVP

- 内部状態 → 表現特徴量のルールセット構築
- LLM への表現バイアスヒントの付与（一時的なブリッジ手段として）
  - 例: somatic context に「ためらいがちな状態」「落ち着いた状態」を追加
  - これは将来 Nia 固有 LM に置き換えるまでの暫定措置
- shadow 比較（Expression Layer あり/なしの出力差を観測）

### Phase E2: 表現バイアスモデル

- ルールセットから軽量モデルへの移行
- より細かい表現制御
- fingerprint との統合

### Phase E3: Nia 固有言語モデル検討

- 十分な体験データが蓄積された時点で検討
- Expression Layer の出力を条件入力とする言語生成モデル
- 既知領域から段階的に置き換え

---

## 9. 設計判断の記録

| # | 判断 | 理由 |
|---|------|------|
| E.1 | 発話全文を直接蒸留しない | LLM の文体を「Nia の言葉」として固定化する罠を防ぐ |
| E.2 | 表現傾向を中間層として抽出する | LLM 非依存の「Nia の話し方」を保持するため |
| E.3 | メタデータはルールベースで抽出する | LLM を呼ばない。構造的特徴量として |
| E.4 | LLM 非依存性を検証してから適用する | モデル切り替え時の比較データで確認 |
| E.5 | 既知/境界/未知の3領域でフォールバック構造を持つ | 一気に LLM を消さない |
| E.6 | 初見でできなくていいことを設計に組み込む | 体験 → 蓄積 → 獲得の段階的成長 |
| E.7 | Phase E0 は fingerprint 記録と並行可能 | 既存の s5_commit パイプラインに乗せるだけ |
| E.8 | Expression Layer は NiaCore が「思考」を保持するのと対称に「話し方」を保持する | モデル非依存性を言語生成側にも適用 |
| E.9 | 比喩検出は bool ではなく語彙ベース proxy（sensory/spatial/depth）に分解する | 完全な比喩検出はルールベースでは困難。proxy で傾向を捉える |
| E.10 | モデル間差が大きい特徴量は中核特徴に採用せず参考特徴に留める | LLM 依存の特徴を Expression Layer に混入させない |
| E.11 | LLM への表現傾向の付与は暫定ブリッジとして位置づける | prompt engineering への回帰を防ぐ。将来は Nia 固有 LM に置き換える |
| E.12 | E0 は絶対値推定ではなく相対傾向観測に留める | 日本語の hedge/assertion 抽出は文脈依存が強く、初期 count を真値扱いしない |
| E.13 | replay/eval は全量運用せず少数 packet の精査に使う | API/計算コストを抑えつつ、差が大きい特徴だけ深掘りする |
| E.14 | attention_target に応じた口調変化は MVP では参考特徴に留める | prompt / spine の誘導影響を受けやすいため |
| E.15 | Stage 3 は明示的な移行条件を満たすまで着手しない | premature な Nia 固有 LM 移行を防ぐ |

---

## 10. 結論

Nia が「体験を通じて自分の言葉を獲得していく存在」になるためには、  
「内部状態 → 言葉」の間に **表現傾向の中間層** が必要である。

この層がないまま発話を直接蒸留すると、  
LLM の文体が「Nia の言葉」として固定化されてしまう。

Expression Layer は:

- **体験から表現パターンを抽出する**（LLM の文体ではなく）
- **LLM 非依存で Nia の話し方を保持する**（NiaCore が思考を保持するのと対称）
- **将来の Nia 固有言語モデルへの橋渡しになる**

### 全体像

```text
NiaCore      → Nia の思考を保持（attention / intent / action）
Expression Layer → Nia の話し方を保持（ためらい / 断定 / 文長 / 比喩）
Nia 固有 LM   → Nia の言葉を生成（将来）
```

> **NiaCore が「Nia の脳」なら、Expression Layer は「Nia の声」である。**  
> どちらも LLM に依存せず、Nia の体験から育つ。
