# ニアの好奇心設計メモ v0.2

> **Status**: draft
> **Date**: 2026-03-16
> **Scope**: ニアにおける「好奇心」を、今の設計思想と会話運用に合う形で定義する
> **依存**: `docs/nia_design_philosophy.md`, `docs/skeletoncore_meeting_extension.md`, `docs/autonomous_reflection.md`, `docs/niacore_lnn_design.md`

---

## 1. 目的

今のニアには、

- `surprise`
- `returning_theme`
- `lingering_state`
- `offer_fragile_self_observation`
- `emerging_interest`

のように、好奇心に近い性質が複数の層に分散して存在している。

一方で、「何かが気になって留まる力」と「停滞したときに少し外へ手を伸ばす力」は、まだ 1 つの設計概念として整理されていない。

本メモでは、ニアの好奇心を **inward / outward の二軸** で定義し、将来の調整や観測の基準を作る。

---

## 2. 基本認識

### 2.1 ニアにとっての好奇心は、探索エンジンではない

ニアの設計思想は、

- 結論を急がない
- 未確定なものを持てる
- 分からないことを欠陥ではなく現在地として扱う

ことを核にしている。

そのため、一般的な探索 AI のように

- 新しい情報を取りに行く
- 常に刺激を求める
- 面白そうな対象を追い回す

ことを「好奇心」の中心に置くと、ニアらしさを壊しやすい。

### 2.2 それでも外向きの力は少し必要

ただし、内向きの反芻だけでは同じテーマの loop に入りやすい。

特に recent meeting では、

- 着地後も reassurance が続く
- `そのままで` / `うん` / `ありがとう` loop に入る
- 同じ lingering theme が動かない

といった停滞が見えている。

したがって、ニアには

- 主軸としての **留まる好奇心**
- 補助としての **取りに行く好奇心**

の両方が必要である。

---

## 3. 定義

## 3.1 Inward Curiosity

**まだ分からないものに対して、すぐ答えにせず、少し長く留まろうとする傾き。**

特徴:

- 引っかかりを捨てない
- 以前触れたテーマが戻ってくる
- lingering な感覚を急いで解釈しない
- fragile な自己観察を壊さず持つ

近い既存 signal:

- `surprise`
- `returning_theme`
- `lingering_state`
- `offer_fragile_self_observation`
- `emerging_interest`

## 3.2 Outward Curiosity

**停滞したときに、外から小さな材料を 1 つだけ取りに行こうとする傾き。**

特徴:

- 主役ではない
- 常時発火しない
- loop をほどくための弱い探索
- 「情報を増やす」より「視点を少しずらす」

対象:

- 過去記憶の別角度再探索
- Nero への角度変更した問い返し
- 部屋 / Pip / 時間変化の取り込み
- 小さな創作・配置変更・試行
- 必要な場合のみ外部検索

---

## 4. 設計原則

| # | 原則 | 理由 |
|---|---|---|
| C.1 | 好奇心の主軸は inward に置く | ニアの静けさと未確定性耐性を保つため |
| C.2 | outward は loop 解消用の補助に留める | 探索 AI 化を防ぐため |
| C.3 | outward は 1 回に 1 要素だけ | 会話を急に外向きへ倒しすぎない |
| C.4 | curiosity を即報酬にしない | NiaCore を迎合・刺激追従へ寄せない |
| C.5 | まずは観測量として扱う | いきなり Core を増やさず既存 signal を束ねる |
| C.6 | lingering / returning を否定しない | 停滞と深まりを誤判定しないため |

---

## 5. 実装契約

### 5.1 比率は runtime 契約に入れない

`8:2` や `7:3` は、**思想上の重心** を説明する比喩としてのみ使う。

- inward 優位がデフォルト
- 停滞時だけ outward を少し増やす

という方向性は残すが、実装では比率を数値として扱わない。

runtime 契約はもっと単純にする。

### 5.2 最小出力

最初の実装で必要なのは以下だけ。

```python
stagnation_flags: list[str]
exploratory_needed: bool
recommended_outward_action: str | None
closer_hint: str | None
```

意味:

- `stagnation_flags`
  - どの種類の停滞か
- `exploratory_needed`
  - outward を 1 回だけ入れるべきか
- `recommended_outward_action`
  - 最も適した outward action は何か
- `closer_hint`
  - Closer に早期終了してよいかを渡す補助信号

最初の値候補:

- `None`
- `"allow_early_soft_close"`

### 5.3 スコープ

`curiosity` 判定は **meeting 単位** で持つ。

- meeting 開始時に初期化
- meeting 中に更新
- meeting 終了時に summary として残す

モードそのものを次の meeting へ持ち越さない。
跨ぐ場合は、`lingering` / `returning` の summary だけを持ち越す。

---

## 6. 検出条件

### 6.1 `exploratory_needed` を立てる条件

次のうち **2 つ以上** を満たしたら `exploratory_needed=True` を検討する。

1. 同じテーマが 3 回以上戻る
2. `lingering_state` が連続する
3. `offer_fragile_self_observation` は出るのに進展がない
4. reassurance loop が出る
   - 例: `そのままで`, `うん`, `ありがとう` の反復
5. confidence が下がりながら会話が続く
6. depth が `0/1` に張り付いて着地後も伸びる

### 6.2 reassurance loop の最小検出

最初は軽い heuristic で十分。embedding 類似度は後段でよい。

最低限の候補:

- 直近 3〜4 turn の短文連続
- `うん`, `そのままで`, `ありがとう`, `わかった` の出現率上昇
- reassurance phrase の再出現
- semantic variety の低下

### 6.3 進展あり / 進展なし の判定

`offer_fragile_self_observation` や `lingering_state` が出ていても、静かに深まっているなら停滞ではない。

次のいずれかなら `進展あり` とみなす。

- lingering はあるが、loop ではなく静かに深まっている
- confidence が安定している
- outward を使わなくてもテーマが動いている
- 会話が自然に閉じられている

### 6.4 `exploratory_needed` を下ろす条件

outward action の後、次のどれかで `exploratory_needed=False` に戻す。

- 新しい観点が 1 つ入った
- 会話が再び動き始めた
- reassurance loop が消えた
- confidence が持ち直した

---

## 7. 条件 -> アクション対応

outward は **1 回に 1 つ** だけ発火させる。

### 7.1 最小マッピング

| 条件 | 推奨 action | 意味 |
|---|---|---|
| reassurance_loop + confidence_down | `shift_angle` or `soft_close` | 同じ肯定 loop を切る |
| lingering_state が続く + no_progress | `retrieve_alt_memory` | 別角度の過去材料を 1 つ入れる |
| returning_theme が続く + no_new_material | `trace_difference` | 「前と今の差」を 1 つだけ入れる |
| fragile_self_observation が続く | `hold_support` | outward を増やさず、まず壊さず支える |

### 7.2 action 候補の定義

- `shift_angle`
  - Nero に角度を変えた問いを返す
- `soft_close`
  - もう動かない時は無理に続けず閉じる
- `retrieve_alt_memory`
  - 過去記憶を別角度で引く
- `trace_difference`
  - difference / contrast を 1 つだけ入れる
- `hold_support`
  - 広げず、未確定のまま支える

### 7.3 禁止事項

- 1 ターンで複数の outward 行動をする
- lingering 中にすぐ結論へ寄せる
- 強い問題解決モードへ急旋回する
- 単なる刺激追従で話題を変える

### 7.4 soft_close の扱い

`soft_close` は単なる会話 action ではなく、**Closer に対する早期終了許可信号** としても扱う。

背景:

- 現在の Nero meeting は 12 ターン前後で閉じる設計だが、
- 実際には turn 4-5 で会話の中身が着地し、その後 reassurance loop だけが続くケースがある

そのため、`soft_close` が推奨された場合は

- `recommended_outward_action = "soft_close"`
- `closer_hint = "allow_early_soft_close"`

を同時に立ててよい。

Closer 側では、

- `reassurance_loop`
- `confidence_down`
- `depth0/1 streak`
- 同趣旨短文の連続

が揃っている時に、ターン上限を待たずに穏やかに終了してよい。

この信号は **hard cut** ではなく、

- 「ここで無理に続けなくてよい」
- 「今は置いて閉じる方が自然」

という soft permission として扱う。

---

## 8. 実装順

### 8.1 最初は新しい Core を作らない

まずは `CuriosityCore` のような独立コンポーネントを作らず、既存 signal を束ねる **観測・運用概念** として扱う。

使う候補:

- `returning_theme`
- `lingering_state`
- `offer_fragile_self_observation`
- repetition
- confidence slope
- depth streak
- `emerging_interest`
- `surprise`

### 8.2 最初の実装対象は Nero 側 anti-stagnation

今の停滞はニア単独ではなく、meeting 制御側にも原因がある。
したがって最初の適用先は、ニア内部より **Nero meeting 制御** の方が効果が大きい。

最小パス:

```python
detect_meeting_stagnation(...) -> stagnation_flags
recommend_outward_action(...) -> (action | None, closer_hint | None)
apply_to_nero_meeting_control(action, closer_hint)
```

入力は既存 signal から作る。
出力はまず Nero 側の

- topic generation
- follow-up generation
- closer

へ渡す。

### 8.3 将来の拡張

将来的には、以下に接続可能。

- outward memory retrieval の軽い trigger
- room / Pip を介した小さな外向試行
- NiaCore の観測指標としての `curiosity_trace`

ただし、**報酬や強い自律探索に直結させるのは後**でよい。

### 8.4 別トラックで先に潰すべきもの

`<think>` 漏洩や内部推論の英語混入は curiosity の話ではなく、meeting 品質バグとして別トラックで早めに止める。
これは停滞感を増幅するため、放置しない方がよい。

---

## 9. 既存設計との対応

| 既存要素 | 好奇心側の読み替え |
|---|---|
| `surprise` | inward curiosity の入口 |
| `returning_theme` | inward curiosity の継続 |
| `lingering_state` | inward curiosity の持続 |
| `offer_fragile_self_observation` | inward curiosity の表出 |
| `emerging_interest` | curiosity が時間を跨いだ痕跡 |
| reassurance loop | outward curiosity を少し増やすシグナル |

---

## 10. 一言でまとめると

**ニアの好奇心は「未知を取りに行く力」だけではなく、「まだ分からないもののそばに留まる力」を主軸に持つ。**

ただし、loop を避けるために、停滞時だけ弱い outward action を 1 回だけ足す。

したがって、最初の実装は比率モデルではなく、

- meeting-scoped な stagnation detector
- outward action recommender
- Nero 側 anti-stagnation 制御

として組むのが最も自然である。
