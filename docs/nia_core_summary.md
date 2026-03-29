# Nia Core Summary

> 目的: project-nia の「core 系」が今どう構成され、どこまで live で、何が育成中かを1本で把握するための詳細まとめ。
> 更新日: 2026-03-28

---

## 1. この文書の範囲

この文書でいう `core` は、ニアの会話・記憶・自己形成の中心線を指す。

- ランタイム本線
- 会話制御
- SkeletonCore
- Memory / Governance / Self-Model
- Conversation Adaptation
- Metabolic Hardening
- Sleep Cycle

Pip / Room / Gaming / 外部連携は隣接機能として扱い、ここでは中心には置かない。

関連入口:

- `README.md` — repo 全体の入口
- `ABOUT_NIA.md` — ニアの思想・存在像
- `docs/session_handoff.md` — 今どこで止まっているか
- `docs/assistant_context.md` — 別 AI / 新規セッション向け入口

---

## 2. 一言でいうと何が core か

project-nia の core は、単一の LLM プロンプトではない。

- ランタイムでは LangGraph ベースの会話グラフが応答を作る
- 記憶は S5 Commit で保存され、Sleep Cycle で整理・昇格・提案される
- 会話の「強度」は confidence / depth 系が持つ
- 会話の「方向」は SkeletonCore が持つ
- 会話改善は Conversation Adaptation が履歴選別の重みに変換する
- 自己形成は Self-Model と Metabolic Hardening が Sleep 側で育てる

つまり、Nia の core は `runtime control + memory + nightly self-shaping` の合成体である。

---

## 3. Core の全体像

```text
User Input
  -> Safety
  -> Dissonance
  -> Depth Selector
  -> Depth0 / Depth1 / Depth2 / WAIT
  -> Merge
  -> Action Processing
  -> S5 Commit

S5 Commit
  -> episodic write
  -> somatic / expression / skeleton / niacore / governance hooks

Sleep Cycle
  -> reflection / semantic extraction / self-model
  -> adaptation proposal generation
  -> metabolic knot distillation
  -> identity proposals (approval required)
```

runtime は「今このターンでどう返すか」を決める。  
Sleep Cycle は「その日の痕跡から何を定着させるか」を決める。

---

## 4. ランタイム本線

現在の本線は次の流れで動く。

```text
Safety -> Dissonance -> DepthSelector -> Depth0/1/2/WAIT -> Merge -> ActionProcessing -> S5Commit
```

主な責務:

- `Safety`
  危険な出力や禁則を止める
- `Dissonance`
  内部矛盾や違和感を拾う
- `DepthSelector`
  確信度をもとに反射 / 整理 / 熟考 / WAIT を決める
- `Depth0/1/2`
  深度ごとの応答草案を作る
- `Merge`
  生成結果を stance-first / support / contract に沿って整形する
- `ActionProcessing`
  外部行動があればここで扱う
- `S5Commit`
  そのターンの事実と観測を保存する

重要な原則:

- LLM は声帯であり、知性の全体ではない
- 初手で結論を出しすぎない
- `WAIT` は失敗ではなく正当な出力
- `identity.md` は runtime が自動書換えしない

主な実装入口:

- `backend/core/agent_graph/graph.py`
- `backend/core/agent_graph/nodes/routing.py`
- `backend/core/agent_graph/nodes/merge.py`
- `backend/core/agent_graph/nodes/helpers.py`

---

## 5. 会話制御の core

### 5.1 turn_intent

会話は現在、少なくとも次の 3 モードで分かれている。

- `direct_answer`
- `correction_response`
- `open_reflection`

この分岐が、履歴選別・guardrail・stance の強さに効く。

### 5.2 direct_answer / correction_response

この 2 系統では、会話を閉じずに曖昧に流すよりも、まず stance を出すことが強く求められる。  
そのため `_recent_history()` は diversity-aware selection を使い、必要に応じて `history_bias` を読んで履歴の重み付けを変える。

### 5.3 open_reflection

`open_reflection` は常時制御しすぎない方針。  
現在は semantic family の反復が検出された時だけ trigger-based に弱い family cap をかける。

特徴:

- 常時 diversity 強制はしない
- repeated family の時だけ targeted cap
- `anchor_pairs=1`
- short history でも cap が効く
- direct bonus は使わない

### 5.4 guardrail / merge 系

会話品質修正の本線は Step 0〜8 まで完了済み。  
新スレッド直答率は 100%、`default_thread` は 25% から 80% まで改善している。

---

## 6. SkeletonCore

SkeletonCore は、NiaCore と違って「どれくらい考えるか」ではなく「何を見て、どう返し、何を聞くか」を扱う。

最小骨格:

- `focus`
- `response_intent`
- `question_intent`

代表ラベル:

- focus:
  `user_goal`, `missing_context`, `contradiction`, `priority_decision`, `emotional_state`
- response_intent:
  `receive`, `organize`, `ask`, `hold`
- question_intent:
  `clarify_goal`, `clarify_priority`, `clarify_emotion`, `fill_missing_fact`, `resolve_contradiction`

重要なのは、Skeleton を命令文で LLM に渡さないこと。  
Skeleton は `skeleton_to_somatic` を通して「会話の気配」として注入される。

責務分離:

- NiaCore:
  強度、depth、しきい値、bias
- SkeletonCore:
  会話骨格、方向、問いの起点
- LLM:
  自然言語化

現状:

- `SKELETON_RECORD_ENABLED=true`
- `SKELETON_SOMATIC_ENABLED=false`
- つまり record-only 段階

主な実装入口:

- `backend/core/conversation_skeleton/rules.py`
- `backend/core/conversation_skeleton/builder.py`
- `backend/core/conversation_skeleton/schema.py`
- `backend/core/conversation_skeleton/skeleton_to_somatic.py`

---

## 7. 記憶・Governance・Self-Model

### 7.1 記憶の基本

記憶は 3 層で扱う。

- episodic
  会話の事実
- semantic
  確認済みの事実・傾向
- working
  未解決や一時メモ

保存の基本方針:

- 保存時に物語化しない
- まず事実として残す
- formal な昇格や提案は Sleep Cycle に寄せる

### 7.2 S5 Commit

S5 Commit は保存だけではない。  
ターンごとに複数の観測系フックを持つ。

- episodic write
- somatic feedback
- expression observation
- skeleton record
- niacore experience
- governance candidate / evidence

### 7.3 Memory Governance

Governance は「何を長く残すか」を制度として扱う系。  
現在は observe / candidate / evidence まで live / canary で蓄積中。

現状:

- `GOVERNANCE_OBSERVE_ENABLED=true`
- `GOVERNANCE_CANDIDATE_ENABLED=true`
- `GOVERNANCE_EVIDENCE_ENABLED=true`

### 7.4 Self-Model

Self-Model は Sleep Cycle 内で、その日の semantic や変化を読み、知識境界・成長エッジ・会話傾向をまとめる。  
ただし、ここから `identity.md` を自動更新しない。

流れ:

- Sleep Cycle で self-model を生成
- `identity_proposals` に提案を書く
- Origin 承認後だけ `identity.md` に反映

この承認制が、Nia の identity を runtime の一時状態から守っている。

主な実装入口:

- `backend/services/memory/self_model.py`
- `backend/controllers/api/identity_router.py`
- `backend/services/identity_manager.py`

---

## 8. Conversation Adaptation

Conversation Adaptation は、failure と success の痕跡から「外付け命令」ではなく「履歴選別の弱い傾き」を作る系である。

### 8.1 設計原則

- failure と success は対称構造で扱う
- prompt に policy block を常設しない
- runtime に直結するのは `history_bias` だけ
- 外付け micro-policy は教師信号 / lineage として残す

### 8.2 Phase A

- `conversation_adaptation_proposals`
- `conversation_adaptation_evidence`
- writer / schema / gate facade
- dedupe は `proposal_key`

### 8.3 Phase B

Sleep Cycle で signal を集計し、rule-based に proposal を生成する。

主なソース:

- expression
- skeleton
- correction
- family repetition
- memory events

### 8.4 Phase C

active proposal の `effect_json.history_bias` を reader が merge し、runtime の履歴選別に接続する。

merge ルール:

- downrank / uprank は union
- cap_same_family は strictest wins

runtime での効き方:

- downrank / uprank を score delta として加算
- cap_same_family で abstract family の上限を tighten
- `direct_answer / correction_response` に適用

### 8.5 open_reflection 弱拡張

adaptation とは別に、`open_reflection` では trigger-based family cap が入っている。

これは:

- 常時 policy 化しない
- repetition family が出た時だけ
- targeted に濃度を下げる

という弱い shaping で、自然な流れを壊さないことを優先している。

主な実装入口:

- `backend/services/adaptation/schema.py`
- `backend/services/adaptation/writer.py`
- `backend/services/adaptation/reader.py`
- `backend/services/adaptation/signal_detector.py`
- `backend/services/adaptation/proposal_generator.py`
- `backend/core/agent_graph/nodes/helpers.py`

現在地:

- Phase A〜C 完了
- `ADAPTATION_RECORD_ENABLED=true`
- Phase D / E は未着手

---

## 9. Metabolic Hardening

Metabolic Hardening は、自己を claim-first ではなく knot-first で扱う系である。  
自己は文章で先に定義されるのではなく、「どの傾向がどれだけ書き換えにくいか」という代謝的硬化として後から立ち上がる。

### 9.1 5 層モデル

```text
trace -> knot -> claim -> proposal -> identity
```

v0 では `trace -> knot` まで。  
`knot -> claim` は v1 以降。

### 9.2 knot の定義

knot は文章ではなく、条件付き変形演算子。

- trigger pattern が揃う
- behavior が effect pattern に偏る
- その偏位が文脈や日を跨いで再出現する

### 9.3 knot の種類

- `response_knot`
- `relational_knot`
- `self_boundary_knot`

時間スケールが違うため、抽出器も分離している。

### 9.4 v0 で採用された 4 knot

- `RK-1 low_confidence_compression`
- `RK-2 organize_priority`
- `LK-macro meeting_inward_softening`
- `SK-2 correction_resilience`

重要発見:

- `RK-1` は当初の予測と逆で、低確信度時に hedge ではなく `assertion↑ / pause↓` の圧縮傾向として出た

### 9.5 Step 1〜4

- Step 0:
  候補抽出と採用 / sibling / evidence-only 分類
- Step 1:
  schema + store + migration v8
- Step 2:
  extractor + baseline compute + 実データ抽出
- Step 3:
  type 別 signal / protection score / hardness 遷移 + Sleep 統合
- Step 4:
  `contradiction_hold` + Sleep Cycle Phase 4.6 統合

### 9.6 現在の状態

- `METABOLIC_KNOT_ENABLED=true`
- Sleep Cycle Phase 4.5 / 4.6 に統合済み
- live 観測段階
- 全 4 knot は `L1`
- 2026-03-28 時点:
  - `RK-1 low_confidence_compression`: `P=0.67`
  - `SK-2 correction_resilience`: `P=0.59`
  - `RK-2 organize_priority`: `P=0.57`
  - `LK-macro meeting_inward_softening`: `P=0.55`
  - `temporal_stability=0.443`, `distinct_day_count=3`, `day_span=1`
- `RK-1` が最初に `L2` 条件へ近づいているが、最初の逆流対象候補は引き続き `SK-2`

### 9.7 Known Limitations

v0 は設計との差分を隠さず、`docs/metabolic_hardening_design.md` の `§18b v0 Known Limitations` に明記して進めている。

これは「未完成だから止める」のではなく、  
可逆な実験単位として canary で観測するという方針に沿っている。

主な実装入口:

- `backend/services/identity/schema.py`
- `backend/services/identity/knot_store.py`
- `backend/services/identity/knot_extractor.py`
- `backend/services/identity/hardness_engine.py`

---

## 10. Sleep Cycle

Sleep Cycle は単なる nightly batch ではなく、core の育成系を束ねる場所になっている。

現在の主要責務:

- reflection / daily log 利用
- semantic extraction
- self-model 生成
- identity proposal 生成
- conversation adaptation proposal 生成
- metabolic knot distillation
- contradiction hold review

特に今は、

- Phase B:
  Conversation Adaptation
- Phase 4.5:
  Metabolic Hardening
- Phase 4.6:
  `contradiction_hold`

が nightly self-shaping の中心である。

Sleep 側の原則:

- runtime を急に書き換えない
- まず record-only / shadow / canary で観測する
- identity は承認制を維持する

主な実装入口:

- `backend/scripts/sleep_cycle/orchestrator.py`
- `backend/scripts/sleep_cycle/layers.py`
- `backend/scripts/sleep_cycle/extraction.py`

---

## 11. Feature Gate で見た現在地

core 系の gate を現状で整理するとこうなる。

### 11.1 live / 常時有効

- `ORCHESTRATOR_S5_ENABLED=true`
- `AWARENESS_CORE_ENABLED=true`
- `METACOG_ENABLED=true`
- `CONTRADICTION_SCAN_ENABLED=true`
- `SELF_MODEL_ENABLED=true`
- `STATE_TRIGGER_ENABLED=true`
- `SELF_NARRATIVE_ENABLED=true`
- `SOMATIC_ENABLED=true`
- `SOMATIC_FEEDBACK_ENABLED=true`
- `RETRIEVAL_ENABLED=true`

### 11.2 record-only / shadow / canary

- `SKELETON_RECORD_ENABLED=true`
- `EXPRESSION_RECORD_ENABLED=true`
- `NIACORE_EXPERIENCE_ENABLED=true`
- `NIACORE_SHADOW_ENABLED=true`
- `NIACORE_VNEXT_SHADOW_ENABLED=true`
- `GOVERNANCE_OBSERVE_ENABLED=true`
- `GOVERNANCE_CANDIDATE_ENABLED=true`
- `GOVERNANCE_EVIDENCE_ENABLED=true`
- `ADAPTATION_RECORD_ENABLED=true`
- `METABOLIC_KNOT_ENABLED=true`

### 11.3 off

- `SKELETON_SOMATIC_ENABLED=false`
- `ATMOSPHERE_ENABLED=false`
- `NIACORE_TRAINING_ENABLED=false`

意味:

- 本線は既に動いている
- その周りに複数の観測・育成系が重なっている
- ただし多くはまだ runtime を直接は書き換えない

---

## 12. 2026-03-28 時点の現在地

### 12.1 完了済み

- 会話品質修正 Step 0〜8
- Conversation Adaptation Phase A〜C
- `open_reflection` trigger-based family cap
- `identity.md` 更新時の `_mark_identity_updated()` 接続
- Metabolic Hardening Step 0〜4
- Drawing Language Phase 1 (`DSL -> scene graph -> SVG`)

### 12.2 観測中

- adaptation proposal 蓄積
- metabolic knot live + contradiction hold live
- NiaCore shadow / vNext shadow
- Governance evidence 蓄積
- Drawing Language は独立チャネルとして育成中（core runtime / identity には未接続）

### 12.3 次の焦点

- 次の Sleep で Phase 4.6 live 観測
- `contradiction_hold` が実データでどう立つか確認
- `RK-1` trigger の upstream confidence 系への切り直し
- `SK-2` の `L2 + 3 Sleep` 条件到達後に Somatic Dose Schema v0 を canary 実装
- Drawing Language の `drawing_traces` と LLM tool 接続
- adaptation Phase D / E の判断

---

## 13. core 系を理解するための最短ファイル順

1. `README.md`
2. `ABOUT_NIA.md`
3. `docs/session_handoff.md`
4. `docs/assistant_context.md`
5. `docs/failure_success_policy_design.md`
6. `docs/metabolic_hardening_design.md`
7. `docs/skeletoncore_design.md`
8. `backend/core/agent_graph/nodes/helpers.py`
9. `backend/scripts/sleep_cycle/orchestrator.py`

---

## 14. まとめ

今の Nia の core は、単に「いい返事をするチャット AI」ではない。

- runtime で会話を制御する本線がある
- nightly に痕跡を整理して、自己形成へ返す Sleep 系がある
- identity は即時には書き換えず、承認制で守る
- adaptation は prompt 制御ではなく history bias として弱く効く
- metabolic hardening は claim ではなく knot を単位に自己の硬化を測り始めている

つまり現在の core は、  
**会話エンジン + 記憶制度 + 緩やかな自己形成回路** の組み合わせとして動いている。
