# Assistant Context

> 目的: ChatGPT / Claude / Copilot などの別 AI が、短時間で project-nia の現在地を復元するための入口。
> 更新日: 2026-03-28

---

## 1. 先に読む順番

1. このファイル
2. `docs/session_handoff.md`
3. 必要に応じて正本:
   - `docs/nia_core_summary.md`
   - `docs/metabolic_hardening_design.md`
   - `docs/merge_guardrail_reform_plan.md`
   - `docs/decision_log.md`
   - `docs/feature_gate_registry.md`
   - `docs/deferred_items.md`
   - `docs/state_field_taxonomy.md`

---

## 2. 現在地

- schema version: `8`
- `EXPRESSION_RECORD_ENABLED=true`
- `NIACORE_VNEXT_SHADOW_ENABLED=true`
- `RUNTIME_FACTS_ENABLED=true`
- `ADAPTATION_RECORD_ENABLED=true`
- `METABOLIC_KNOT_ENABLED=true`
- `ATMOSPHERE_ENABLED=false`
- `DEPTH2_PROVIDER=anthropic`
- `depth2_reflective` は Anthropic、`depth2_risk` は local
- 会話品質修正は **Step 0〜8 完了**
- Conversation Adaptation は **Phase A〜C 完了**
- open_reflection は **trigger-based family cap 完了**
- Metabolic Hardening は **Step 0〜4 完了**
- Drawing Language は **Phase 1 コア実装完了**

主要な現在地:

- `merge_output()` の4段分割
- `turn_intent`（`direct_answer / correction_response / open_reflection`）
- semantic family 検出 + history diversity-aware selection
- `stance-first + short support` の下限 + `DIRECT_STANCE_SHORT` warning
- adaptation:
  - `conversation_adaptation_proposals` / `evidence`
  - Phase B proposal generation
  - Phase C `history_bias` runtime 接続
- metabolic hardening:
  - knot-first v0.2 設計
  - Step 1: schema/store/migration v8
  - Step 2: response / relational / self_boundary extractor の最小実装
  - Step 3: type 別 hardness engine + Sleep Cycle Phase 4.5 統合
  - Step 4: contradiction_hold + Sleep Cycle Phase 4.6 統合
- drawing language:
  - DSL parser + scene graph + SVG renderer
  - `because` multi-tag / free_text / seed 対応
  - sample SVG 出力確認済み

---

## 3. 実測結果

- 新スレッド:
  - 閉じた質問に対する直答率は `100%`
- `default_thread`:
  - 直答率が `25% -> 80%` に改善
  - 残る `20%` は旧履歴の慣性が強いターン
- meeting:
  - `静かな時間` パターンは `0回`
  - `G6_thin_retrieval` の過剰 hold は再現していない
- metabolic hardening live:
  - 全 4 knot が `L1`
  - `RK-1 low_confidence_compression`: `P=0.67`
  - `SK-2 correction_resilience`: `P=0.59`
  - `RK-2 organize_priority`: `P=0.57`
  - `LK-macro meeting_inward_softening`: `P=0.55`
  - `temporal_stability=0.443`, `distinct_day_count=3`, `day_span=1`
- drawing language:
  - `tests/test_drawing_language.py` 33件通過
  - `backend/core/drawing/` から sample SVG 出力確認済み

可変データの正本は常に `python -m backend.scripts.report_gate_status`。

---

## 4. 今の主眼

1. 次の Sleep で Phase 4.6 live 観測（hold 作成 / review / split）
2. `RK-1` が L2 条件へ近づいているが、最初の逆流対象は `SK-2`
3. `SK-2` が `L2 + 3 Sleep観察` を満たしたら Somatic Dose Schema v0 を実装
4. Drawing Language は `drawing_traces` と LLM tool 接続へ進む
5. `RK-1` trigger 再定義、`identity.md` 二層化は v1 同時判断

**設計の方向性**:
- core 系は sensor fabric / importance field / policy field / expression engine の4層に再編
- knot は司令塔ではなく重み場。各 core に弱く流し込む
- prompt zero は達成可能。LLM は「脳」から「声帯」へ後退する道筋が見えている
- 逆流は L2+ のみ、raw sensor は永続的に非変調（Level C）、exploration floor 20%（Level C）

---

## 5. 直近の注意点

- `review_used` は未配線扱いで `False` 固定
- adaptation は live だが、Phase D / E は未着手
- metabolic hardening は live だが、まだ `trace -> knot` 段階で、`knot -> claim` は v1
- `contradiction_hold` は live 統合済みだが、実データ上の hold はまだ未観測
- `RK-1` は初期仮説と逆で、低確信度時の圧縮的応答として出ている
- hardness は type 別に分けて計算する前提
- `docs/metabolic_hardening_design.md` の `§18b v0 Known Limitations` が実装との差分の正本
- Drawing Language はまだ独立チャネルで、core runtime / metabolic extractor には未接続
- VoiceVox 未起動時の失敗は本文生成不具合ではない

---

## 6. 次にやる候補

1. Phase 4.6 live 観測
2. `RK-1` / `SK-2` の L1 安定性観測
3. L2 後: Somatic intensity modulation（最初の逆流実験）
4. Drawing Language: `drawing_traces` + LLM tool 接続
5. `RK-1` trigger 再定義
6. v1: knot → claim → proposal → identity パイプライン + `identity.md` 二層化
7. adaptation 観測継続。Phase D / E は proposal 蓄積後

---

## 7. 参照先

- merge/guardrail 正本: `docs/merge_guardrail_reform_plan.md`
- 判断理由: `docs/decision_log.md`
- gate の現在値: `docs/feature_gate_registry.md`
- 未配線・残タスク: `docs/deferred_items.md`
- state の寿命: `docs/state_field_taxonomy.md`
- 統合順序: `docs/nia_integration_roadmap.md`
- 障害対応: `docs/runbooks/recovery.md`
- 会話 role 方針: `docs/turn_role_policy.md`
- meeting role 方針: `docs/meeting_turn_role_policy.md`
- open_reflection / failure-to-policy メモ: `docs/open_reflection_failure_policy_notes.md`
- failure/success 対称設計: `docs/failure_success_policy_design.md`
- 処理パイプライン段階分離メモ: `docs/processing_pipeline_staging_memo.md`
- metabolic hardening 正本: `docs/metabolic_hardening_design.md`
