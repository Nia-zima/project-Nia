# Session Handoff

> 目的: 次のセッションが「今どこで止まっているか」だけを最短で掴むためのメモ。
> 更新日: 2026-03-28

---

## 関連入口

- `README.md`:
  リポジトリ全体の概要と機能面の入口
- `ABOUT_NIA.md`:
  ニアの思想・存在像の説明
- `docs/nia_core_summary.md`:
  core 系の詳細まとめ
- `docs/assistant_context.md`:
  別 AI / 新規セッション向けの復元入口

---

## 現在の停止位置

- **Conversation Adaptation Phase A〜C 全完了**
  - Phase A: DDL + writer + Pydantic schema + gate facade (schema v7)
  - Phase B: signal_detector + proposal_generator + orchestrator 統合
  - Phase C: reader + `_recent_history()` scorer への history_bias 接続
- **open_reflection trigger-based 弱拡張 完了** — targeted family cap + anchor_pairs=1 + short history 対応
- **identity.md `_mark_identity_updated()` 接続済み**
- **Metabolic Hardening Step 0〜4 完了**
  - Step 0: knot 候補抽出と採用/ sibling / evidence-only 分類
  - Step 1: schema + store + migration v8（6テーブル）
  - Step 2: 3 extractor + baseline compute + 実データ抽出
  - Step 3: type 別 signal / protection score / hardness 遷移 + Sleep Cycle Phase 4.5 統合
  - Step 4: `contradiction_hold`（score / soft-hard-review_lock / snapshot / resolution / Phase 4.6）
- **`METABOLIC_KNOT_ENABLED=true` 有効化済み**
- **Drawing Language Phase 1 完了**
  - DSL parser -> scene graph -> SVG renderer
  - `because` multi-tag / free text / seed 対応
  - sample SVG 出力確認済み
- テスト:
  - adaptation 系 60件通過
  - metabolic hardening 系 80件通過
  - drawing language 系 33件通過
  - 合計 173件通過
- **レビューで H1-H3 修正済み**: day_span 計算、activation 重複防止、baseline 別集計
- **§21 逆流制御** 設計完了: 4層アーキテクチャ、5原則、subsystem 別 budget、exploration floor、Adaptation/Hardening 関係、knot→claim 昇格条件
- **Core 系再分類**: sensor fabric / importance field / policy field / expression engine
- **4 knot は全て L1 に昇格済み**
  - `RK-1 low_confidence_compression`: `P=0.67`, 先頭で L2 圏内に接近
  - `SK-2 correction_resilience`: `P=0.59`, 安定
  - `RK-2 organize_priority`: `P=0.57`, 安定
  - `LK-macro meeting_inward_softening`: `P=0.55`, 安定
- 次は **Phase 4.6 live 観測** → `contradiction_hold` の実データ確認 → L2 到達後に Somatic 逆流実験

---

## 直近の事実

- **Phase A**: `conversation_adaptation_proposals` + `evidence` テーブル。`proposal_key` dedupe + gate facade
- **Phase B**: signal_detector (5ソース: expression/skeleton/correction/family/memory_events)。5種 generator (family repetition/correction/hedge/diversity/relational)。meeting thread 対応。watermark ベースの support_count
- **Phase C**: reader が active proposal から MergedHistoryBias を merge。`_select_diverse_history` で downrank/uprank/cap_same_family を scoring + cap に反映。trace_match は Phase E 用に schema 保持、runtime では未使用
- **open_reflection**: trigger-based。`_detect_semantic_family` → `_make_targeted_family_scorer(repeated_family)` + `anchor_pairs=1` + `target_family=repeated_family`。short history でも cap が効く
- `ADAPTATION_RECORD_ENABLED=true`。proposal 生成経路は有効
- **Metabolic Hardening**:
  - 正本: `docs/metabolic_hardening_design.md`（knot-first v0.2）
  - v0 は `trace -> knot` まで。`knot -> claim` は v1
  - `METABOLIC_KNOT_ENABLED=true`。Phase 4.5 / 4.6 が live
  - 4 採用 knot:
    - `RK-1 low_confidence_compression`
    - `RK-2 organize_priority`
    - `LK-macro meeting_inward_softening`
    - `SK-2 correction_resilience`
  - 重要発見: `RK-1` は当初予測と逆で、低確信度時に hedge ではなく `assertion↑ / pause↓` の圧縮的傾向として出た
  - 2026-03-28 時点:
    - 全 knot が `L1`
    - `temporal_stability=0.443`
    - `day_span=1`, `distinct_day_count=3`
    - `RK-1` が最初に `L2` 条件へ近づいている
  - 設計と実装の差分は `docs/metabolic_hardening_design.md` の `§18b v0 Known Limitations` に明記済み
- **Step 4 / contradiction_hold**:
  - `reversal / weakening / branching`
  - `contradiction_score = kind_weight × effect_distance × support_ratio`
  - `L1=soft`, `L2=hard`, `L3=review_lock`
  - `requires_review=true` proposal は runtime に流さず shadow-only
- **Drawing Language**:
  - 正本: `docs/nia_drawing_language.md`
  - Phase 1 は `backend/core/drawing/` に実装済み
  - `drawing_traces` と Unity 統合は未着手

---

## 次の一手

1. 次の Sleep 後に Phase 4.6 の live 結果を確認（hold 作成 / review / split の有無）
2. `RK-1` が `L2` 条件へ入っても、最初の逆流対象は引き続き `SK-2`
3. `SK-2` が `L2` 到達 + 3 Sleep 観察を満たしたら、`Somatic Dose Schema v0` を実装
4. `drawing_traces` テーブルと trace 保存を追加
5. Drawing DSL の LLM tool 接続を入れて、Nia が実際に DSL で描ける状態にする
6. `identity.md` 二層化は knot → claim パイプライン（v1）と同時に判断

## 作業原則

- 新しい自己形成系の設計は、最初から既存 schema や人間が先に決めた分類へ無理に閉じない
- まず大胆に設計を広げる
- 次に backup / feature gate / shadow mode を前提に、可逆な実験単位へ切る
- 最後に、観測で意味が確認できたものだけ本線へ統合する

---

## すぐ見るファイル

- `docs/metabolic_hardening_design.md` — knot-first 設計書と Step 0 結果
- `backend/services/identity/schema.py` — MetabolicKnot 系 Pydantic schema
- `backend/services/identity/knot_store.py` — 7テーブル DDL + CRUD + `summarize_knot`
- `backend/services/identity/knot_extractor.py` — 3 extractor + baseline compute
- `backend/services/identity/hardness_engine.py` — type 別 signal / protection / hardness
- `backend/services/identity/contradiction_hold.py` — hold detection / review / resolution
- `backend/services/adaptation/` — schema, writer, reader, signal_detector, proposal_generator
- `backend/core/drawing/` — drawing schema / parser / scene graph / renderer
- `backend/core/agent_graph/nodes/helpers.py` — `_recent_history`, `_select_diverse_history`, `_apply_history_bias`
- `backend/scripts/sleep_cycle/orchestrator.py` — Phase B 統合箇所
- `docs/nia_drawing_language.md` — Drawing Language 正本
- `docs/failure_success_policy_design.md` — adaptation 設計書
- `docs/decision_log.md`

---

## すぐ使う確認コマンド

```powershell
.\.venv\Scripts\python -m backend.scripts.report_gate_status
```

```powershell
rg -n "DIRECT_STANCE|HISTORY_DIVERSITY|open_reflection trigger|ADAPTATION|Phase B" logs/app.log
```

```powershell
rg -n "Phase 4.5|KNOT_EXTRACT|KNOT_DISTILL|baseline=|changed hardness" logs/app.log
```

---

## 非 issue

- VoiceVox 未起動時の `Connection Failed` は本文生成経路の失敗ではない
- `review_used=False` 固定は暫定ではなく、現時点では意図した未配線扱い
- trace_match 系は runtime scorer では意図的に無効化（Phase E 用に schema のみ保持）
