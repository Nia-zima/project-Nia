# Assistant Context

> 目的: ChatGPT / Claude / Copilot などの別 AI が、短時間で project-nia の現在地を復元するための入口。
> 更新日: 2026-03-31

---

## 1. 先に読む順番

1. このファイル
2. `docs/session_handoff.md`
3. 必要に応じて正本:
   - `docs/nia_integration_roadmap.md` — 統合順序の正本
   - `docs/nia_core_summary.md`
   - `docs/metabolic_hardening_design.md`
   - `docs/skeleton_realizer_design.md`
   - `docs/knot_to_niacore.md`
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
- `SKELETON_GUIDANCE_SHADOW_ENABLED=true`
- `ATMOSPHERE_ENABLED=false`
- `DRAWING_INTENT_ONLY=false`
- `DEPTH2_PROVIDER=anthropic`
- `depth2_reflective` は Anthropic、`depth2_risk` は local
- 会話品質修正は **Step 0〜8 完了**
- Conversation Adaptation は **Phase A〜C 完了**
- open_reflection は **trigger-based family cap 完了**
- Metabolic Hardening は **Step 0〜4 完了**
- Drawing Language は **Dual Ingress 完了**（Intent Layer 温存、Legacy DSL + canonicalizer が本番）
- **Phase 1 closed** (SK-2 score 0.658, contradiction_hold live/0fires, RuntimeFacts Phase A complete)
- **Phase 2 live**: Skeleton Realizer C.0 shadow 稼働中（40テスト、`SKELETON_GUIDANCE_SHADOW_ENABLED=true`）
- Drawing intent path は live success を 1 回確認済み（`DRAWING_INTENT_ONLY=true`）

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
  - 設計書追記: Prompt Stack統治順位(§12), Adherence Low還流分類(§13), Approved Weight Rubric(§11), Head Budget(§12), Effect Window Timeout(§13)
- skeleton realizer:
  - C.0 shadow 実装完了（40テスト通過）
  - 最初の観測: ask mode adherence=low, reflect mode adherence=high (composite 1.0)
  - SK-2 L2 promotion expected in ~2 days
- drawing language:
  - Dual Ingress: Legacy DSL + canonicalizer が本番
  - Intent Layer は adapter の一種として温存（ローカル LLM 3モデルで YAML intent 未達）
  - DSL parser + scene graph + SVG renderer + trace viewer + debug UI + DrawingCard 表示

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
- metabolic hardening:
  - Phase 1 closed. SK-2 score `0.658`（L2 到達 ~2日、day_span=5/7）
  - `contradiction_hold` live 統合済み、発火 0 回（正常）
  - RuntimeFacts Phase A ブロッカーなし完了
- skeleton realizer C.0 shadow:
  - 最初の 3 shadow レコード: ask adherence=low, reflect adherence=high
  - 最初の非対称性: ask < reflect
- drawing language:
  - 151件テスト通過
  - ローカル LLM 3モデル（qwen3.5-9b, qwen3-14b-abliterated, gpt-oss-20b）で YAML intent 未達
  - gpt-oss-20b はストリーミング問題で使えず
  - その後、` ```draw ` transport + 2-pass normalize + intent-like reject で intent YAML live success を 1 回確認
  - 未解決 cleanup:
    - `last_drawing_ts:{thread_id}` は 10 分 window だと広すぎる。one-shot / short TTL に再設計予定
    - Skeleton adherence は timeout fallback turn を除外して集計する必要あり

可変データの正本は常に `python -m backend.scripts.report_gate_status`。

---

## 4. 今の主眼

1. **C.0 shadow データ蓄積** — ask/low の分布を depth/focus/turn_role 別に確認
2. **SK-2 L2 到達確認** — ~2日後
3. **adherence パターン分析** — ask mode の低 adherence が構造的か文脈依存か
4. **knot→training candidate** — C.0 データ蓄積後に実装
5. Drawing は canonicalizer 観測継続
6. 統合順序は `docs/nia_integration_roadmap.md` が正本

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
- `contradiction_hold` は live 統合済み、発火 0 回（正常）
- `RK-1` は初期仮説と逆で、低確信度時の圧縮的応答として出ている
- hardness は type 別に分けて計算する前提
- `docs/metabolic_hardening_design.md` の `§18b v0 Known Limitations` が実装との差分の正本
- Drawing Language はまだ独立チャネルで、core runtime / metabolic extractor には未接続
- Intent Layer は温存されているが、ローカル LLM では YAML intent に切り替わらない
- Skeleton Realizer C.0 は shadow-only（実行パスに影響しない）
- VoiceVox 未起動時の失敗は本文生成不具合ではない

---

## 6. 次にやる候補

1. C.0 shadow データ蓄積・パターン分析
2. SK-2 L2 到達確認（~2日後）
3. adherence の depth/focus/turn_role 別分布分析
4. knot→training candidate（設計書完了、C.0 データ蓄積後に実装）
5. L2 後: Somatic intensity modulation（最初の逆流実験）
6. Drawing: canonicalizer 観測 / drawing knot 抽出
7. v1: knot → claim → proposal → identity パイプライン + `identity.md` 二層化
8. adaptation 観測継続。Phase D / E は proposal 蓄積後

---

## 7. 参照先

- 統合順序の正本: `docs/nia_integration_roadmap.md`
- merge/guardrail 正本: `docs/merge_guardrail_reform_plan.md`
- 判断理由: `docs/decision_log.md`
- gate の現在値: `docs/feature_gate_registry.md`
- 未配線・残タスク: `docs/deferred_items.md`
- state の寿命: `docs/state_field_taxonomy.md`
- 障害対応: `docs/runbooks/recovery.md`
- 会話 role 方針: `docs/turn_role_policy.md`
- meeting role 方針: `docs/meeting_turn_role_policy.md`
- open_reflection / failure-to-policy メモ: `docs/open_reflection_failure_policy_notes.md`
- failure/success 対称設計: `docs/failure_success_policy_design.md`
- 処理パイプライン段階分離メモ: `docs/processing_pipeline_staging_memo.md`
- metabolic hardening 正本: `docs/metabolic_hardening_design.md`
- skeleton realizer 設計: `docs/skeleton_realizer_design.md`
- knot→NiaCore 設計: `docs/knot_to_niacore.md`
- drawing 正本: `docs/nia_drawing_language.md`
