# Context — project-nia 現在地

最終更新: 2026-03-31

- 北極星:
  - ニアを、交換可能な LLM の上にある `state / graph / memory / constitution` で育てる
- 現在地:
  - 会話品質修正 Step 0〜8 完了
  - Metabolic Hardening Step 0〜4 完了、**Phase 1 closed**（SK-2 score 0.658, L2 ~2日）
  - Drawing Language Dual Ingress 完了（Intent Layer 温存、Legacy DSL が本番）
  - **Phase 2 live: Skeleton Realizer C.0 shadow 稼働中**（40テスト、`SKELETON_GUIDANCE_SHADOW_ENABLED=true`）
  - 最初の観測: ask adherence=low, reflect adherence=high（composite 1.0）
  - `nia_integration_roadmap.md` が統合順序の正本
- 今見るべきこと:
  - **C.0 shadow データ蓄積** — ask/low の分布を depth/focus/turn_role 別に確認
  - **SK-2 L2 到達確認**（~2日後）
  - adherence パターン分析 → knot→training candidate への接続
  - Drawing canonicalizer 観測継続

詳細の正本:
- `docs/nia_integration_roadmap.md`
- `docs/assistant_context.md`
- `docs/session_handoff.md`
- `docs/skeleton_realizer_design.md`
- `docs/knot_to_niacore.md`
- `docs/metabolic_hardening_design.md`
- `docs/feature_gate_registry.md`
