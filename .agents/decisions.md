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

## 参照先

- `docs/decision_log.md`
- `docs/merge_guardrail_reform_plan.md`
- `docs/open_reflection_failure_policy_notes.md`
