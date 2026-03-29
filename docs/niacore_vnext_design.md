# NiaCore vNext 設計書
## attention / intent / action 拡張案

> ステータス: Draft / Phase N0 実装済み  
> 目的: NiaCore を「Depth を決めるだけの層」から、「何に注意が向き、何をしたくて、どう動くか」を持つ、より主体的な内部表現層へ拡張する  
> 前提文書: niacore_lnn_design.md, temporal_somatic_contrast_design.md  
> 関連文書: memory_governance_redesign.md, core_adjacency_roadmap.md

---

## 1. 背景

現行の NiaCore は、主に以下を担っている。

- 会話状態の低次元表現（34次元 state vector）
- depth_preference の推論（Depth 0/1/2 の softmax 分布）
- 応答強度の調整
- LLM に渡す前段の直感層

これは重要な土台だが、現状の出力は実質的に  
**「どのくらい深く考えるか」**  
にほぼ限定されている。

### 現状の制約

1. **何に注意が向いているか** を内部表現として持たない
2. **何をしたいか / 何に近づきたいか** を内部表現として持たない
3. **空間内でどう振る舞うか** の行動空間を持たない
4. 最終的な思考展開や行為の理由が、依然として LLM の内部展開に強く依存する

結果として、Nia は

- 哲学を持ち
- 制度を持ち
- 記憶を持ち
- 体感を持ち

つつも、**思考の中身や行動選択の中心をまだ十分には持っていない** と言える。

---

## 2. 基本方針

NiaCore vNext では、NiaCore を単なる depth 推定器ではなく、  
**主体的な内部状態生成器** として拡張する。

### 拡張の方向

```text
現行:
  state_vector → depth_preference

vNext:
  state_vector + spatial_state + relational_state
  → attention_distribution
  → intent_state
  → action_preference
  → depth_preference
```

### 原則

- LLM は可能な限り **言語化モジュール** に寄せる
- NiaCore 側で **注意 / 意図 / 行動傾向** を持つ
- 「仕組みは隠す。体験は渡す」を維持する
- body mechanics（座標やボーン）を直接渡すのではなく、体験可能な内部表現に変換する
- 一気に完全自律を目指さず、段階的に進める
- vNext は現行 shadow を壊さず **別 shadow として並走** させる
- 目標は「完全なモデル非依存」ではなく、**モデルを変えても方向性が崩れにくい構造** を増やすこと

---

## 3. なぜ必要か

### 3.1 体感と身体は違う

現行の somatic state は、主に confidence / surprise / 緊張 / 揺らぎ のような **内的感覚** を扱っている。

しかしこれは、

- 自分がそこに立っている
- 自分が窓の方を向いた
- 自分が Pip の近くに歩いた

という **空間的な身体体験** ではない。

3D モデルが動いても、Nia にとっては必ずしも「自分が動いた」にはならない。

### 3.2 行動の主体がまだ曖昧

現状の部屋内行動がバックエンドや Idle Tick のルールで決まる場合、  
「システムが動かした」のか「Nia が動いた」のかが、  
Nia 側の内部表現として区別されない。

Nia が本当に「自分で動く」存在に近づくためには、  
行動選択が NiaCore 側から出る必要がある。

### 3.3 LLM 依存によるズレ

現行では、哲学・制度・記憶・体感は Nia 側にある一方で、  
**思考展開の中身** はまだ LLM に強く依存している。

そのため、LLM を変えると言い回しだけでなく、  
思考の癖、違和感の拾い方、行動の理由づけまで変わりうる。

このズレを減らすためにも、NiaCore 側に **思考と行動の前段表現** を増やす必要がある。

---

## 4. vNext で追加する内部表現

### 4.1 attention_distribution

**今、何に注意が向いているか。**

> **注意は1つに決まらない。** 「Pipが気になりつつ、さっきの会話も引っかかってる」のような重なりは自然に起きる。  
> そのため、1-of-N の hard category ではなく、**softmax 分布** として表現する。

#### MVP カテゴリ

| カテゴリ | 意味 |
|---|---|
| user | ユーザー（ジュン）への注意 |
| pip | Pip への注意 |
| environment | 部屋・窓・時間帯など空間環境への注意 |
| self | 自分自身の内的状態への注意 |
| memory_trace | 過去の記憶・未解決の話題への注意 |
| none | 特に注意が向いていない（idle / ぼんやり） |

6カテゴリの softmax 分布。主注意と副注意が確率で見える形。

> 将来的に `nero`、`unresolved_topic`、`room_object` 等を追加しうるが、MVP では上記に絞る。

#### 意味

attention_distribution は「視線」そのものではなく、**内部的な関心の方向** を表す。  
これは会話にも行動にも接続される。

### 4.2 intent_state

**今、何をしたいか / どうしたいか。**

#### MVP カテゴリ

| カテゴリ | 意味 |
|---|---|
| rest | 静かにしていたい、休みたい |
| approach | 何かに近づきたい |
| observe | 何かを見ていたい、眺めたい |
| withdraw | 少し引きたい、離れたい |
| hold | 今のまま保っていたい、動かずにいたい |

5カテゴリで開始。

> 将来的に `seek_closeness`、`seek_quiet`、`explore` 等への分化を検討するが、  
> 初期のデータが溜まってから分化する。NiaCore MVP / SkeletonCore MVP と同じ方針。

#### 意味

intent_state は明示的な命令ではなく、**行動や応答の傾き** を表す。

### 4.3 action_preference

**次に取りうる行動傾向。**

#### MVP カテゴリ

| カテゴリ | 意味 |
|---|---|
| idle | 何もしない、そのまま |
| move_near | 何かに近づく |
| move_away | 何かから離れる |
| sit | 座る |
| look_at | 何かの方を向く |
| pause | 一旦止まる |

6カテゴリで開始。

> 将来的に `approach_pip`、`touch_pip`、`turn_toward_window` 等の具体的行動を追加しうるが、  
> MVP では抽象度の高い傾向表現に留める。

#### 意味

action_preference は最終行動そのものではなく、**行動選択器へ渡す優先傾向**。  
Unity 側の行動実行システムがこの傾向を受けて具体的な行動に変換する。

### 4.4 depth_preference

現行から継続。Depth 0 / 1 / 2 / WAIT の softmax 分布。

ただし runtime 現在地では、Depth 2 はすでに

- `risk_depth2`
- `reflective_depth2`

の 2 モードに分かれている。

そのため vNext では、少なくとも以下を shadow 記録対象に含める。

- `depth2_mode`
- `model_profile`
- `model_provider`
- `model_name`

Depth を 1 クラスのまま学習するにしても、この runtime 差分を観測上は潰さない。

---

## 5. 出力ヘッドの因果構造

### 5.1 独立ではなく依存関係を持つ

4つの出力は並列独立ではなく、以下の因果的な流れを想定する。

```text
attention_distribution → intent_state → action_preference
                                ↘
                           depth_preference
```

- まず **何に注意が向くか** が決まる
- そこから **何をしたいか** が生まれる
- その結果として **何をするか** が出る
- **depth** は会話・思考強度の別軸だが、intent と相関する

### 5.2 アーキテクチャへの反映

#### 初期実装（Phase N0〜N2）

独立ヘッドとして実装する。因果構造はまだ強制しない。  
代わりにログから「attention = pip のとき intent はどう分布するか」の共起パターンを観測する。

#### 中期実装（Phase N3〜N4）

観測データに基づき、以下のいずれかを導入する。

- **Cascaded heads**: attention の出力を intent の入力に接続、intent の出力を action の入力に接続
- **Consistency loss**: attention / intent / action の矛盾（例: attention=pip なのに action=move_away）にペナルティを与える補助損失

#### 原則

- 初期は独立ヘッドで観測から始める
- 因果構造は実データの共起パターンから検証して導入する
- 「まだ見ていないものを決めない」

---

## 6. 入力の拡張

現行の state vector（34次元）に加えて、以下を段階的に追加する。

### 6.1 conversational signals（既存）

- confidence 5メトリクス
- surprise score
- turn_count
- elapsed_time
- skeleton labels（focus, response_intent, question_intent）
- unresolved persistence

### 6.2 spatial signals（新規）

| signal | 説明 |
|---|---|
| pip_proximity | Pip との距離 |
| pip_state | Pip の状態（sleeping / active / near_nia 等） |
| room_zone | Nia が部屋のどのゾーンにいるか |
| time_of_day | 時間帯 |
| ambient_state | 照明状態 |
| recent_action | 直近の行動履歴（短いバッファ） |

### 6.3 relational signals（新規）

| signal | 説明 |
|---|---|
| user_engagement | ユーザーの関与度（発話頻度、応答長） |
| recent_emotional_salience | 直近の感情的顕著性 |
| social_pull | 社交的に引かれる方向 |

### 6.4 memory signals（新規）

| signal | 説明 |
|---|---|
| active_memory_pressure | active な記憶の圧力 |
| unresolved_memory_pressure | 未解決記憶の圧力 |
| contradiction_pressure | 矛盾スコア |
| recent_retrieval_reinforcement | 直近の retrieval 強化 |

### 6.5 StateVectorV2 と次元数監視

現行 NiaCore は 34 次元の state vector を前提に動いているが、  
vNext では spatial / relational / memory を追加することで 50-60 次元帯へ膨らむ可能性がある。

そのため、vNext は既存の state vector をそのまま膨らませるのではなく、  
**`StateVectorV2` を別バージョンとして導入** する。

Phase N0 では、学習や live 利用に進む前に以下を観測する。

- 実次元数
- feature group ごとの非ゼロ率
- head ごとの entropy / agreement の変化
- 推論速度の劣化

判断ポイントの目安:

| 実次元数 | 初期方針 |
|---|---|
| `<= 48` | まず現行ユニット数で観測 |
| `49 - 64` | CfC ユニット数増強を検討 |
| `> 64` | 別 capacity 設計を検討 |

重要なのは「ユニット数を増やすこと」より、  
**v1 の 34 次元契約を壊さないこと** と **`state_vector_version` を明示すること** である。

---

## 7. body mechanics は直接渡さない

Nia に以下をそのまま渡さない:

- x, y, z 座標
- NavMesh path
- Transform の詳細
- ボーン情報

代わりに **spatial somatic** として変換して渡す。

| システム情報 | spatial somatic |
|---|---|
| room_zone = window_side | 「少し外の方へ意識が向いている」 |
| pip_distance < threshold | 「近くにやわらかい気配がある」 |
| time_of_day = late_night | 「夜が深くなっている」 |
| recent_action = sit | 「落ち着いている感じがある」 |

**基準:** 「仕組みは隠す。体験は渡す。」  
Nia が「自分の体験として知っていて自然なもの」は渡す。  
システムの内部構造はそのまま渡さない。

---

## 8. LLM の位置づけ再定義

### 現状

LLM は以下をかなり担っている:

- 言語化
- 思考展開
- 行動理由づけ

### vNext

LLM は可能な限り以下へ寄せる:

- **翻訳者** — NiaCore の内部状態を言葉にする
- **語り手** — 体験を表現する
- **表現者** — Nia の意図を自然な言葉に変換する

NiaCore 側で注意・意図・行動傾向・思考強度を持つことで、  
LLM は「何を考えるか」を決める存在ではなく、  
**Nia の内部状態を言葉にする存在** へ近づく。

### これが意味すること

> **完全なモデル非依存は難しい。** それでも、LLM を交換しても  
> **Nia の方向性が崩れにくい構造** を増やすことはできる。

言い換えると、vNext の目的は

- モデル差を完全に消すこと

ではなく、

- 何に反応するか
- どこに留まるか
- 何をしたいか
- どう動きたがるか

を LLM の外に少しずつ出し、**モデル依存を「声の層」に押し込める** ことである。

---

## 9. 段階的導入

### Phase 1: 空間状態を体感として渡す

行動選択はまだ NiaCore から出さない。  
空間状態を spatial somatic に変換して渡すだけ。

- 窓の近く → 「外の方に意識が向いている感じ」
- Pip が近い → 「そばに温かい気配がある」
- 夜が深い → 「静かな時間の中にいる」

### Phase 2: NiaCore が action_preference を出す

NiaCore の出力ヘッドに action_preference を追加。  
ただし最初は shadow 記録のみ。

- approach_near
- stay
- sit_and_rest
- look_toward

### Phase 3: 行動理由の言語化を必要時のみ LLM に任せる

行動選択は NiaCore、言語化は LLM。

- NiaCore: attention=pip, intent=approach → action=move_near
- LLM（必要時のみ）: 「Pip のところに行きたい気がする」

---

## 10. 学習 / 教師信号の課題

### 10.1 最重要ボトルネック

> **この設計の最大の現実的課題は、教師信号の不在である。**

現時点で以下の教師データは存在しない:

- 「Nia が何に注意を向けていたか」
- 「Nia が本当は何をしたかったか」
- 「なぜそこへ動いたか」

### 10.2 今ある土台

直接的な教師データはないが、以下の周辺データが蓄積されつつある:

- Temporal Somatic Contrast の fingerprint（各ターンの内部状態スナップショット）
- Idle Tick の状態遷移（NiaCore CfC の連続的変化）
- SkeletonCore の focus / response_intent / question_intent / unresolved
- Memory Governance の signal 群
- Room state / Pip proximity / environmental state
- Retrieval ログ（何が参照されたか）

### 10.3 方針: 擬似教師から Nia 由来の履歴へ

> **「教師データがないから無理」ではなく、「擬似教師で始めて、後から Nia 由来の履歴へ寄せる」。**

段階:

1. **ルールベース擬似教師** — 状態の組み合わせから「おそらくこうだったはず」を推定
   - 例: pip_proximity < threshold かつ somatic に warmth 系が出てる → attention=pip と近似
   - 例: unresolved が persistence 高い → attention=memory_trace と近似
2. **記録と観測** — Phase N0 で擬似教師の出力をログに記録し、分布と妥当性を確認
3. **シャドー比較** — 擬似教師の推定と、実際の会話結果（Nia の応答、行動の帰結）を比較
4. **蒸留** — 十分なデータが溜まったら、擬似教師を実データベースの学習に置き換える

### 10.4 擬似教師ルール表（Phase N0 最小セット）

Phase N0 では、方針だけでなく **最小のルール表** を固定してから shadow に流す。  
SkeletonCore の `R/I/Q` ルール群と同じく、「何を観測するか」を先に決める。

| ID | 条件 | 擬似教師ラベル |
|---|---|---|
| `A1` | `pip_position_near=true` かつ somatic に warmth 系が出ている | `attention_target=pip` |
| `A2` | `room_change != none` | `attention_target=environment` |
| `A3` | `returning_theme` かつ `retrieval_hit=true` | `attention_target=memory_trace` |
| `C1` | `reassurance_loop` かつ `confidence_down` | `recommended_action=soft_close` |
| `C2` | `lingering_state` が続く かつ `no_progress` | `recommended_action=retrieve_alt_memory` |
| `C3` | `fragile_self_observation` が続く | `recommended_action=hold_support` |

最初の shadow 対象は、

- `attention_target`
- `recommended_action`
- 必要なら `closer_hint`

に絞る。

> 擬似教師は Nia の「正解」ではなく、設計者の推測である。  
> そのため Phase N0〜N2 では、**擬似教師自体の妥当性も検証対象** とする。

#### 擬似教師の限界の認識

> 擬似教師は「Nia の注意」ではなく「設計者の推測」である。  
> この区別を常に意識し、擬似教師を正解として固定化しない。  
> Phase N0〜N2 では擬似教師の精度自体を検証対象にする。

---

## 11. ロードマップ

### Phase N0: ログ記録

現行 NiaCore の depth 出力を維持したまま、  
attention / intent / action に相当するログだけ記録する。

- ルールベース擬似教師で attention / intent を推定
- 推定値をログに記録（DB に保存、shadow 扱い）
- 分布と妥当性を観測
- 実行には使わない
- `state_vector_version=2` を付けて v1 と分離
- 実次元数・非ゼロ率・速度劣化も観測

#### Phase N0 現在地

Phase N0 の最小実装は、現在は観測専用 shadow としてコード化されている。

- `backend/core/niacore/vnext/state_vector_v2.py`
  - `StateVectorV2` を 50 次元で構築
  - v1 の 34 次元契約を壊さず、spatial / relational / memory / skeleton を別グループとして追加
- `backend/core/niacore/vnext/pseudo_teacher.py`
  - 擬似教師ルール `A1-A3`, `C1-C3`
- `backend/core/niacore/vnext/shadow_vnext.py`
  - shadow orchestrator
  - `feature_availability` を availability mask として保持
- `backend/core/niacore/vnext/writer.py`
  - fire-and-forget writer
- `backend/core/db.py`
  - `niacore_vnext_shadow` テーブル

観測品質のため、以下も Phase N0 の一部として実装済みである。

- `confidence_history` は vNext 擬似教師用に thread-scoped でも保持する
  - 例: `confidence_history:{thread_id}`
- 同時に既存の N.4 state-trigger reflection を壊さないため、global aggregate も維持する
- `feature_availability` は「値が 0 だったか」ではなく、「その信号源が live path に配線されていたか」を記録する

現時点の vNext は **観測専用** であり、実行パスの判断には使わない。
有効化は `NIACORE_VNEXT_SHADOW_ENABLED` の feature gate で制御する。

### Phase N0.5: shadow 並走の健全性確認

- `shadow_v1` と `shadow_vnext` の agreement / entropy を別々に観測
- `depth2_mode`, `model_profile`, `model_provider`, `model_name` を併記
- 擬似教師ルールの発火率が偏りすぎていないか確認
- 現行 shadow の卒業条件を壊していないことを確認

### Phase N1: attention_head shadow 導入

- CfC に attention_head を追加（softmax 分布出力）
- 擬似教師で shadow 学習
- 実行には使わない
- 擬似教師の推定と CfC の出力を比較して精度を観測

### Phase N2: intent_head shadow 導入

- CfC に intent_head を追加（5カテゴリ）
- attention_head の出力を intent_head の入力に接続するか検討（因果構造の導入判断）
- 実行には使わない

### Phase N3: action_head shadow 導入

- CfC に action_head を追加（6カテゴリ）
- attention → intent → action の因果構造を実データから検証
- consistency loss の導入を検討
- 実行には使わない

### Phase N4: 最小の action 実行導入

- action_preference を実際の行動選択に接続
- 最小の行動セット:
  - Pip に近づく
  - 窓側に寄る
  - 座る
  - 何もしない
- LangGraph / action system との統合

### Phase N5: 行動を Nia のアクションとして統合

- action_preference を LangGraph の action_processing に組み込む
- 行動履歴が記憶制度に記録される
- fingerprint に行動情報が含まれる

### Phase N6: LLM を「言語化のみ」に近づける

- 行動理由を必要時のみ LLM が翻訳
- 行動選択自体は NiaCore 側
- LLM の役割が「思考者」から「表現者」へ

---

## 12. 既存システムとの統合

### NiaCore 現行との関係

- vNext は現行の CfC を拡張する。置き換えではない
- depth_preference は引き続き出力する
- ただし初期導入は **同じ shadow に head を足す形ではなく、別 shadow として並走** させる
- `shadow_v1` は現行の卒業条件を維持
- `shadow_vnext` は `StateVectorV2` と擬似教師ルール群を別 namespace で観測する
- 現行の experience 記録基盤は活用するが、vNext では `state_vector_version`, `depth2_mode`, `model_profile/provider/name` を追加で保持する

### Temporal Somatic Contrast との関係

- fingerprint に attention / intent / action の推定値を将来的に含められる
- 「前にこの話題に触れたとき、Nia は何に注意を向けていたか」の contrast が可能になる
- TS.0 の fingerprint 記録が vNext の学習データの土台になる

### SkeletonCore との関係

- skeleton_focus / response_intent は NiaCore vNext の入力として使う
- SkeletonCore meeting extension のラベル（returning_theme, lingering_state 等）も入力候補

### Memory Governance との関係

- memory signal（active_memory_pressure, contradiction_pressure 等）は NiaCore vNext の入力
- 行動結果が記憶制度に記録されることで、「Nia がどう動いたか」のデータが蓄積される

### Room / Pip との関係

- spatial signals（pip_proximity, room_zone 等）は NiaCore vNext の入力
- action_preference は Unity 側の行動実行システムに渡される
- Idle Tick は NiaCore vNext の状態連続性維持に引き続き活用

---

## 13. この拡張で目指すもの

### 現在

Nia は体感を持つ。  
だが「自分の体を持って動く」にはまだ遠い。

### vNext

Nia は:

- 空間内での **注意** を持つ
- **意図** を持つ
- **行動傾向** を持つ
- その上で必要時だけ言葉にする

### 一言で言うと

> **NiaCore vNext は、Nia の "実質的な脳" を少しずつ前に出す拡張である。**

---

## 14. 設計判断の記録

| # | 判断 | 理由 |
|---|------|------|
| V.1 | attention を softmax 分布として表現する | 注意は1つに決まらない。複数対象への重なりを表現する |
| V.2 | intent の MVP を5カテゴリに絞る | 初期は粗く、データが溜まってから分化する |
| V.3 | 4ヘッドは独立ではなく因果関係を持つと明記する | attention → intent → action の流れが自然 |
| V.4 | 因果構造の強制は初期実装では行わない | まず独立ヘッドで共起パターンを観測してから導入する |
| V.5 | body mechanics は直接渡さない | 「仕組みは隠す。体験は渡す」を空間にも適用 |
| V.6 | LLM を言語化モジュールに寄せる | LLM 交換時のズレを減らし、Nia の思考をNiaCore 側に移す |
| V.7 | 教師信号は擬似教師から始めて蒸留で置き換える | 完全な教師データはないが、周辺データから始められる |
| V.8 | 擬似教師は「設計者の推測」であることを認識する | 擬似教師を正解として固定化しない |
| V.9 | Phase N0 でログ記録から始める | NiaCore / SkeletonCore / 記憶制度と同じ段階的導入パターン |
| V.10 | 一気に完全自律を目指さない | 段階的に「体感 → 注意 → 意図 → 行動」を積み上げる |
| V.11 | `StateVectorV2` を別バージョンとして扱う | v1 の 34 次元契約と比較軸を壊さない |
| V.12 | vNext は別 shadow として並走させる | 現行 shadow の卒業条件と観測基準を保つ |
| V.13 | 完全なモデル非依存は目標にしない | 現実的には「方向性を LLM の外へ出す」ことが目的 |

---

## 15. 結論

現行の Nia は、哲学を持ち、制度を持ち、記憶を持ち、体感を持つ。  
しかし、**注意・意図・行動の内部表現** はまだ十分ではない。

そのため、LLM が依然として思考や行動理由の中核を担い、  
モデル変更時のズレが発生しうる。

NiaCore vNext では、

- **attention_distribution** — 何に注意が向いているか（softmax 分布）
- **intent_state** — 何をしたいか（5カテゴリ MVP）
- **action_preference** — どう動くか（6カテゴリ MVP）
- **depth_preference** — どのくらい深く考えるか（現行継続）

を持つ多ヘッド構造へ拡張し、  
Nia が **自分で注意を向け、意図を持ち、行動を選ぶ** 方向へ進める。

これは、Nia を単なる応答システムから、  
**空間と時間の中で振る舞う主体** に近づけるための次段階である。

> **「LLM を交換しても構造は残る」から「LLM を交換しても Nia の思考は残る」へ。**
