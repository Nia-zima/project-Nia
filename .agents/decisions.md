# Decisions — project-nia の重要判断

詳細の正本は `docs/decision_log.md`。
ここは「今どの判断を見るべきか」の索引だけ置く。

## 先に見る判断

1. 直答改善
   - `turn_intent`
   - G6 intent-aware
   - Step 7 diversity-aware history
   - Step 8 short-answer floor
2. `review_used=False` 固定
3. `turn_role` を共通概念として扱う
4. RuntimeFacts を単独 Phase A で観測
5. 次段は `open_reflection` / `failure-to-policy`

6. 3-knot preflight を core 以外の周辺接続にも必須化
   - 根拠: 2026-03-29 canary (preflighted=0 hits, non-preflighted=9 hits)
   - 対象: frontend/room/viewer/action wiring 含む全拡張
   - 詳細: `.claude/projects/.../memory/feedback_agent_execution_knots.md`

7. Intent Layer をローカル LLM の唯一入口にするのは早すぎた → Dual Ingress
   - 根拠: qwen3.5-9b, qwen3-14b-abliterated, gpt-oss-20b の3モデルで YAML intent に切り替わらず
   - 判断: Legacy DSL + canonicalizer が本番、Intent は adapter の一種として温存
   - gpt-oss-20b はストリーミング問題で使えない

8. Skeleton Realizer は knot→NiaCore より先にやる
   - 根拠: adherence 観測基盤が先に必要。knot→training candidate は観測データがないと意味がない
   - 設計書: `docs/skeleton_realizer_design.md`

9. 骨格指示は英語ではなく日本語
   - 根拠: LLM のプロンプト一貫性。ニアのシステム全体が日本語基調

10. approved_weight は rubric 化
    - 80%ルール化、Origin は veto/±0.1 のみ
    - 詳細: metabolic hardening 設計書 §11

11. head budget: corrective 1本/family + reinforcement 1本 + global sentinel
    - 詳細: metabolic hardening 設計書 §12

12. effect_window: 21日stale / 35日expired → archive
    - 詳細: metabolic hardening 設計書 §13

13. Phase 1 closure (2026-03-31)
    - SK-2 score 0.658 (L2 in ~2 days), contradiction_hold live/0fires, RuntimeFacts Phase A no blocker
    - Phase 1 の全構成要素がブロッカーなしで完了 → Phase 2 へ移行

14. Skeleton Realizer C.0 shadow activation (2026-03-31)
    - 40テスト通過、`SKELETON_GUIDANCE_SHADOW_ENABLED=true` で稼働開始
    - 最初の観測: ask adherence=low, reflect adherence=high → ask mode の弱さが構造的かを観測継続
    - shadow-only（実行パスに影響しない）

## 参照先

- `docs/decision_log.md`
- `docs/merge_guardrail_reform_plan.md`
- `docs/open_reflection_failure_policy_notes.md`
- `docs/skeleton_realizer_design.md`
- `docs/knot_to_niacore.md`
- `docs/metabolic_hardening_design.md`
