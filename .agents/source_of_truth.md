# Sources of Truth

このプロジェクトでは、詳細設計は `docs/` を正本とする。

優先度:

1. `CLAUDE.md`
   - 不可侵ルール
   - 設計思想
2. `docs/assistant_context.md`
   - 現在地
3. `docs/session_handoff.md`
   - 直近の停止位置
4. 各個別設計書
   - `nia_design_philosophy.md`
   - `niacore_lnn_design.md`
   - `niacore_vnext_design.md`
   - `skeletoncore_design.md`
   - `failure_success_policy_design.md`
   - `merge_guardrail_reform_plan.md`
   - その他対象領域の正本

`.agents/` は正本ではなく、

- 現在地の要約
- 引き継ぎ
- 判断理由の短縮版

を担う。
