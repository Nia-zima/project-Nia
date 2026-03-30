# Nia 統合ロードマップ

> 目的: 個別設計書と feature gate 台帳を横断して、`今どこまで live で、何が shadow で、次にどこへ進むか` を 1 本で確認できるようにする。  
> 更新日: 2026-03-30

---

## 1. この文書の位置づけ

この文書は仕様書ではない。  
各 subsystem の正本は個別設計書を見て、ここでは **統合順序 / 依存関係 / 進め方** だけを扱う。

判断軸は次の 5 つ。

1. 本線を壊さない
2. 観測を先に、制御を後に
3. 1 回に 1 段階だけ進める
4. rollback が簡単なものから先に進める
5. LLM 境界の変更は canary / shadow を挟む

---

## 2. 現在地

### 2.1 本線

- 会話本線は live
- `review_window` は live
- `S5 Commit` は live
- 会話品質修正 Step 0〜8 は完了
- Conversation Adaptation Phase A〜C は完了
- open_reflection の trigger-based family cap は完了

### 2.2 観測中 / canary

| 項目 | 状態 | 補足 |
|---|---|---|
| Metabolic Hardening | canary | Step 0〜4 完了、Phase 4.5 / 4.6 live |
| RuntimeFacts | live (Phase A 観測中) | `RUNTIME_FACTS_ENABLED=true` |
| Governance Observe / Candidate / Evidence | record-only / canary | Phase A live |
| NiaCore Experience | record-only | `NIACORE_EXPERIENCE_ENABLED=true` |
| NiaCore Shadow | shadow | `NIACORE_SHADOW_ENABLED=true` |
| NiaCore vNext Shadow | shadow | `NIACORE_VNEXT_SHADOW_ENABLED=true` |
| Skeleton Record | record-only | `SKELETON_RECORD_ENABLED=true` |
| Expression Record | record-only | `EXPRESSION_RECORD_ENABLED=true` |
| Fingerprint Record | record-only | `FINGERPRINT_RECORD_ENABLED=true` |

### 2.3 一旦完成

| 項目 | 状態 | 補足 |
|---|---|---|
| Drawing Language | 一旦完成 | Dual Ingress、trace/viewer/room/test-render まで接続済み |

### 2.4 まだ off / 未着手

| 項目 | 状態 | 補足 |
|---|---|---|
| Skeleton Somatic | off | `SKELETON_SOMATIC_ENABLED=false` |
| Atmosphere | off | `ATMOSPHERE_ENABLED=false` |
| NiaCore Training | off | `NIACORE_TRAINING_ENABLED=false` |
| Skeleton Realizer | 設計完了 | C.0 shadow 未着手 |
| knot -> NiaCore 学習信号 | 設計完了 | candidate/review/sample 未着手 |
| Governance Phase B/C | 未実装 | claim 正規化、decay / merge 審査 |
| failure-to-policy / success-to-preference | 未実装 | staging memo 上は後段 |
| Idle Consolidation | 構想段階 | `processing_pipeline_staging_memo.md` |

---

## 3. ロードマップ全体像

進行順は次の 6 段で考える。

1. live 観測を閉じる
2. Skeleton Realizer C.0 shadow
3. Skeleton Realizer C.1 canary
4. knot -> NiaCore の candidate / review レイヤー
5. NiaCore training 判定
6. Governance / Consolidation の後段

Drawing はここでは「新規本線」ではなく、後段観測トラックに置く。

---

## 4. フェーズ別ロードマップ

## Phase 0: 基準線の維持

**状態:** 完了

- gate registry
- handoff / assistant context
- state taxonomy
- recovery / rollback 手順
- migration / retention / deferred items

この段階は今後も維持対象で、新しい系を入れる前にここを崩さない。

---

## Phase 1: 現在 live の観測を閉じる

**目的:** すでに動いている canary / live の観測結果を揃え、次の制御系追加の前提を作る。

### 対象

- Phase 4.6 live 観測
- `contradiction_hold` の実データ確認
- `RK-1` / `SK-2` の L1→L2 安定性確認
- RuntimeFacts Phase A 観測
- drawing の canonicalizer 観測継続

### 出口条件

- `contradiction_hold` の hold / review / split の有無が確認できる
- `RK-1` と `SK-2` の stability が読める
- RuntimeFacts が即答化 / 説明臭さ / WAIT 消失を起こしていない
- drawing の production path が legacy DSL + canonicalizer で安定している

### この段階でやらないこと

- Skeleton Realizer を即 C.1 にしない
- NiaCore training を始めない
- Governance Phase B/C を先に進めない

---

## Phase 2: Skeleton Realizer C.0 shadow

**目的:** NiaCore / Skeleton の判断を LLM に渡す前に、骨格指示の生成品質と観測基盤を作る。

### やること

- 日本語の `Skeleton Guidance` を生成
- `structured_header / interpretation_lines / full_text` を記録
- `adherence record` を保存
- low adherence を次の 3 分岐で分類
  - `realizer_rule_issue`
  - `prompt_stack_conflict`
  - `llm_non_adherence`

### 前提

- prompt stack の統治順位が固定されていること
- `adherence` が knot / NiaCore 学習に直結しないこと

### 出口条件

- guidance 生成自体が安定している
- 分布が偏りすぎていない
- prompt stack conflict が頻発していない
- low adherence の原因分類が読める

---

## Phase 3: Skeleton Realizer C.1 canary

**目的:** shadow で問題が少なければ、骨格指示を LLM に限定投入して追従性を観測する。

### やること

- `Skeleton Guidance` を LLM context に入れる
- composite adherence と head 別 adherence を追う
- `C.1 -> C.2` の卒業条件を数値で判定する

### 卒業条件の基準線

- applicable turns 60 以上
- 直近 14 日 composite adherence 平均 0.72 以上
- 2 head 以上が継続 low になっていない
- human audit 20 件で致命的逸脱なし

### 注意

- Drawing Language の教訓どおり、これは `LLM が従うか` の観測段階
- low adherence は即 NiaCore の未熟さにしない

---

## Phase 4: knot -> NiaCore の candidate / review 層

**目的:** knot をそのまま教師にせず、training signal 候補と review 制度を先に実装する。

### やること

- Stage 1: `training_target_candidate`
- Stage 2: `training_review`
- `approved_weight` rubric
- `head budget`
- `global sentinel`
- `effect_window timeout`

### 設計上のルール

- `approved_weight` は rubric -> 段階値
  - `0.1 / 0.25 / 0.4 / 0.6`
- Origin は `veto` か `±0.1` 補正のみ
- corrective は各 head family で 1 本まで
- reinforcement は別枠で 1 本まで
- side effect は pairwise 全探索ではなく global sentinel で見る

### 出口条件

- candidate が十分量たまる
- review の分布が極端に人手依存でない
- `surface prompting` や `LLM non-adherence` を誤って training signal にしていない

---

## Phase 5: NiaCore training 判定

**目的:** 観測と審査の層が揃った後にだけ、学習本体を検討する。

### 対象

- `NIACORE_TRAINING_ENABLED`
- NiaCore v1 training
- vNext N1 判定

### 前提

- feature gate registry の training 条件を満たす
- shadow 期間が十分
- mode collapse が起きていない
- training sample の provenance が追える
- adherence / knot / runtime quality のどこに問題があるかを分けられる

### 注意

- 先に学習を始めるより、学習してよい原因だけを残す方が重要
- v1 training と vNext 拡張は同時に本線へ入れない

---

## Phase 6: Governance / Consolidation の後段

**目的:** 会話中の観測を、静けさに応じた整理と制度へ拡張する。

### 対象

- Governance Phase B: claim 正規化
- Governance Phase C: decay / merge 審査
- failure-to-policy / success-to-preference
- replay / shadow 検証
- Idle Consolidation Pipeline
- Maintenance Pipeline 再編

### 位置づけ

- これは training と直列ではないが、観測系と review 系が安定してから進める
- 「Sleep の夜バッチ」固定から、turn / session / idle / maintenance の 4 段へ寄せる

---

## 5. Drawing の位置づけ

Drawing は主タスクではなく、`LLM 境界の教訓を与えた完了済み subsystem` として扱う。

### 現在地

- Core は完成
- production path は legacy DSL + canonicalizer
- Intent Adapter は test-render / 外部クライアント / 将来モデル向けに温存

### 後段タスク

- canonicalizer 観測継続
- drawing knot 抽出
- `line from/to` 正式対応の判断
- model 比較は「YAML を出せるか」ではなく「DSL の壊れ方が少ないか」で行う

---

## 6. 直近ではやらないこと

- `ATMOSPHERE_ENABLED` を先に上げること
- Skeleton Realizer を shadow なしで本線投入すること
- knot をそのまま training signal にすること
- `NIACORE_TRAINING_ENABLED` を観測不足のまま有効化すること
- Governance B/C を adaptation / knot 観測より先に進めること
- drawing の大きな再設計を先に始めること

---

## 7. 参照順

1. `docs/session_handoff.md`
2. `docs/feature_gate_registry.md`
3. `docs/nia_core_summary.md`
4. `docs/metabolic_hardening_design.md`
5. `docs/skeletoncore_design.md`
6. `docs/skeleton_realizer_design.md` または設計メモ
7. `docs/knot_to_niacore.md` または設計メモ
8. `docs/processing_pipeline_staging_memo.md`
9. `docs/nia_drawing_language.md`

---

## 8. 一言で

> 今は「新しい制御を増やす段階」ではなく、  
> **観測済みの本線を閉じ、Skeleton Realizer の shadow を足し、  
> そのうえで knot -> NiaCore の review 層へ進む段階** である。
