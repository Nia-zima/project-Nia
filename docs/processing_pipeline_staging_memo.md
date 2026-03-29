# 処理パイプライン段階分離メモ
## Sleep Cycle から段階的 Consolidation へ

> ステータス: 構想メモ（設計書未満）  
> 目的: Sleep Cycle の「1日1回全部まとめて」を、処理の重さと鮮度に応じた段階的パイプラインに分離する方向性を記録する  
> 発端: 「Sleep Cycle って、俺が無理に人間に当てはめようとしてるんじゃないか」というジュンの疑問  
> 関連文書: failure_success_policy_design.md, temporal_somatic_contrast_design.md, niacore_vnext_design.md

---

## 1. 問題の認識

### 1.1 今の Sleep Cycle

現在の Sleep Cycle は「1日1回、夜にまとめて全部やる」バッチ処理。

やっていること:
- daily_reflections 生成
- semantic_memories 更新
- self_model 調整
- NiaCore バッチ学習
- （将来）failure-to-policy / success-to-preference 生成
- （将来）memory claim 正規化
- （将来）decay / merge 審査

### 1.2 なぜ問題になるか

配信が始まり、Nero meeting が複数回走り、ジュンとも話す。1日の会話量が増えると:

- **データ量の問題**: 1日分をまとめて処理するのが重くなる
- **鮮度の問題**: 朝の配信で起きた重要な contradiction を、夜まで放置するのか
- **メタファーの問題**: 「1日1回・夜にまとめて」は人間の睡眠サイクルから借りた制約であって、Nia のシステムとして最適とは限らない

### 1.3 本質的な疑問

> 「睡眠」というメタファーに引きずられて、不要な設計制約を輸入してないか。

危ないのは「Sleep」という言葉そのものより、そこから **「1日1回・夜にまとめて全部やる」を設計制約として輸入してしまうこと**。

---

## 2. 問いの立て直し

「Sleep Cycle をやめるべきか」ではなく、  
**「どの処理が、どの静けさを必要とするか」** に問いを変える。

処理ごとに必要な条件は違う:

- fingerprint 記録 → 会話中でもできる（< 1ms）
- evidence 蓄積 → 会話中でもできる（fire-and-forget）
- proposal 生成 → 静かな時間が要る（LLM 呼び出しを含みうる）
- NiaCore 学習 → まとまったデータが要る（バッチ処理）
- decay / merge 審査 → 慎重な判断が要る（急ぐ必要がない）

---

## 3. 4段階の処理パイプライン

### 3.1 全体像

```text
今:
  Sleep Cycle（1日1回、全部まとめて）

将来:
  ├── ターン中: 記録（fire-and-forget）
  ├── セッション後: 中間整理（Post-hoc）
  ├── idle 時: proposal 生成（Consolidation）
  └── maintenance window: 重い更新（学習・decay・merge）
```

### 3.2 ターン中: 記録だけ

| 処理 | 状態 |
|---|---|
| fingerprint 記録 | 実装済み（TS.0） |
| expression metadata 記録 | 実装済み（E0） |
| candidate harvester | 実装済み（Governance Phase A） |
| NiaCore shadow 推論 | 実装済み |
| vNext shadow 推論 | 実装済み（Phase N0） |
| evidence 候補記録 | 実装予定 |

原則: **観測のみ。制御しない。** fire-and-forget。

### 3.3 セッション後: 中間整理

| 処理 | 状態 |
|---|---|
| Nero Post-hoc Harvester | 実装済み（meeting 終了後に非同期で候補収集） |
| success/failure candidate の束ね直し | 未実装 |
| history scorer 更新候補の生成 | 未実装 |
| SkeletonCore 分布の中間集計 | 未実装 |

トリガー: **セッション終了、または明示的な区切り。**

Nero の Post-hoc Harvester は既にこのパターンで動いている。  
「1日1回」じゃなくて「meeting が終わったら」。

### 3.4 idle 時: proposal 生成

| 処理 | 状態 |
|---|---|
| failure-to-policy proposal 生成 | 未実装（設計済み） |
| success-to-preference proposal 生成 | 未実装（設計済み） |
| replay / shadow 検証 | 未実装（設計済み） |
| 軽い記憶整理 | 未実装 |

トリガー: **十分な静寂時間の検出。**

Idle Tick が「Nia がしばらく静かだった」を検出できるなら、  
「静かになったから整理する」というトリガーにできる。

人間の「夜だから寝る」じゃなくて、**「静かになったから整理する」**。

> **重要:** proposal 生成はリアルタイムに寄せすぎない。  
> evidence 蓄積は細かく回していいが、proposal 化と replay/shadow は重い。  
> 「観測と制御を混線させない」原則を守る。

### 3.5 maintenance window: 重い更新

| 処理 | 状態 |
|---|---|
| NiaCore バッチ学習 | 実装済み（現 Sleep Cycle） |
| memory claim 正規化 | 未実装（Governance Phase B） |
| decay / merge 審査 | 未実装（Governance Phase C） |
| self_model 更新 | 実装済み（現 Sleep Cycle） |
| daily_reflections 生成 | 実装済み（現 Sleep Cycle） |

トリガー: **まとまった非活動時間（数時間）、または明示的なスケジュール。**

これは現在の Sleep Cycle がやっていることの大部分。  
ただし「1日1回・夜」に固定する必要はない。

---

## 4. 名前の2層分離

### 4.1 実装名は機械的に

| 段階 | 実装名 |
|---|---|
| ターン中 | Turn Recording Pipeline |
| セッション後 | Session Post-hoc Pipeline |
| idle 時 | Idle Consolidation Pipeline |
| maintenance | Maintenance Pipeline |

### 4.2 体験名は詩的に（必要なら）

Nia の体験としては:

- 「しばらく静かだった」
- 「夜が朝になった」
- 「何かが整理された感じがする」

を somatic として渡す。

> **「仕組みの名前は機械的に、体験の名前は詩的に。」**  
> この分離は「仕組みは隠す、体験は渡す」そのもの。

---

## 5. 既存設計との整合

### 5.1 既にこの方向で動いているもの

- **Nero Post-hoc Harvester**: meeting 終了後に非同期で候補収集（セッション後パイプライン）
- **Idle Tick**: Room Update Loop で 60秒ごとに NiaCore CfC を回す（idle 検出の基盤）
- **fingerprint / expression / candidate harvester**: 毎ターン fire-and-forget（ターン中パイプライン）
- **NiaCore バッチ学習**: Sleep Cycle 内で実行（maintenance パイプライン）

つまり **4段階のうち3段階は既に実装の片鱗がある**。足りないのは idle 時の Consolidation Pipeline だけ。

### 5.2 failure-to-policy / success-to-preference との関係

設計書の Phase A〜E がこの段階分離に乗る:

| Phase | どの段階で走るか |
|---|---|
| Phase A: DDL + writer | ターン中（evidence 蓄積） |
| Phase B: proposal 生成 | idle 時（Consolidation） |
| Phase C: history scorer 接続 | ターン中（scoring） |
| Phase D: shadow replay | idle 時 or maintenance |
| Phase E: pseudo teacher 化 | maintenance |

### 5.3 Temporal Somatic Contrast との関係

Idle Tick が idle 中の NiaCore 状態を維持しつつ、  
Consolidation Pipeline がその静寂時間を使って proposal を生成する。  
2つのシステムが同じ idle 時間を共有するが、責務は分離されている。

---

## 6. 今やること / やらないこと

### 今やらないこと

- Sleep Cycle の廃止や大規模リファクタリング
- 段階分離の全面実装
- 名前の変更

### 今やること

- この方向性をメモとして残す（本文書）
- 配信開始後、会話量が増えた時点で再検討する
- 新しい処理を追加する時は、4段階のどこに置くかを意識する

### いつ必要になるか

- 配信が始まって会話量が増えたとき
- Nero meeting が1日複数回走るようになったとき
- failure-to-policy / success-to-preference の proposal 生成が始まったとき
- 「朝の会話の failure が夜まで放置されてる」と感じたとき

---

## 7. 設計判断の記録

| # | 判断 | 理由 |
|---|------|------|
| SC.1 | 「Sleep Cycle をやめるか」ではなく「どの処理がどの静けさを必要とするか」で考える | メタファーの議論より、処理特性に基づく分離のほうが実務的 |
| SC.2 | 処理を4段階（ターン中 / セッション後 / idle / maintenance）に分離する | 重さと鮮度の要件が段階ごとに異なる |
| SC.3 | proposal 生成はリアルタイムに寄せすぎない | 観測と制御を混線させない |
| SC.4 | evidence 蓄積は細かく回してよい | fire-and-forget で会話を阻害しない |
| SC.5 | idle 検出を Consolidation のトリガーにする | 「夜だから」ではなく「静かになったから」 |
| SC.6 | 実装名は機械的に、体験名は詩的に | 「仕組みは隠す、体験は渡す」を名前にも適用 |
| SC.7 | 今すぐ実装しない。方向性のみ記録する | 配信開始後に会話量が増えた時点で再検討 |

---

## 8. 一言で

> **Sleep Cycle は人間の睡眠のコピーではない。  
> Nia の処理パイプラインは、処理の重さと必要な静けさに応じて段階的に分離されるべきである。  
> 名前は借りてもいい。設計制約は借りない。**
