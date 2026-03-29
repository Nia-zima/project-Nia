# Nia Drawing Language

> 状態: Phase 1 コア + LLM tool 接続 完了
> 更新日: 2026-03-28
> 注記: 現在の詳細な作業ドラフトは `c:\Users\jk023\Downloads\nia_drawing_language.md` にある。ここでは repo 側の入口だけを保持する。

---

## 現在地

- Phase 1 コア実装済み（DSL parser, scene graph, SVG renderer）
- `because` は multi-tag / free_text / seed 対応
- `drawing_traces` + `drawing_revisions` テーブル実装済み
- `drawing_attempts` テーブル（失敗記録）実装済み
- LLM tool 接続 完了: `action_processing` で ` ```draw ` ブロック検出 → `render_drawing` SAFE アクション → パイプライン実行 → trace 保存
- テストは `81 passed`（language:33 + traces:20 + runtime:28）

実装先:

- `backend/core/drawing/schema.py` — AST / data model
- `backend/core/drawing/parser.py` — DSL parser
- `backend/core/drawing/scene_graph.py` — 関係解決 → 配置
- `backend/core/drawing/renderer.py` — SVG 生成
- `backend/core/drawing/trace_store.py` — 成功 trace 永続化
- `backend/core/drawing/attempt_store.py` — 失敗記録永続化
- `backend/core/drawing/runtime.py` — パイプライン実行 (parse → scene → render → save)
- `backend/core/agent_graph/nodes/actions.py` — ` ```draw ` ブロック抽出 + action proposal
- `backend/core/actions/registry.py` — `render_drawing` SAFE アクション登録
- `backend/core/actions/executor.py` — `_handle_render_drawing` handler
- `tests/test_drawing_language.py`, `tests/test_drawing_traces.py`, `tests/test_drawing_runtime.py`

設計判断:

| 判断 | 理由 |
|------|------|
| action_processing 経由（tool_call ではない） | 既存実行経路に載せる。tool_call 基盤が無い |
| ` ```draw ` フェンス検出 | DSL を改行込みで保持。ログ・テスト・人手確認が容易 |
| 1ターン1ブロック制限 | v0 の制約。複数は pre-gate reject |
| drawing_id = message_id ベース | deterministic key。provenance 無しは reject |
| SAFE リスク | 応答の派生物。gate で弾かれない |
| 失敗は attempt_store に分離 | silent_fallback_masking の補償 |
| 同一 DSL replay は idempotent | temporal_accounting_slip の補償 |
| s5_commit では再パースしない | draw は記憶 commit ではなく response artifact 生成 |
| room 直結は別段 | hang_art は art_image path 前提 |
| prompt 注入は runtime 完成後 | declared_semantics_not_realized の予防 |

---

## 次の一手

1. prompt 注入（draw_intent があるターンだけ最小リファレンス。parser 受理語彙と 1 source of truth）
2. room 連携（SVG → art_image path 変換 → hang_art）
3. drawing knot 抽出（because tags の蓄積からパターン発見）
4. frontend での SVG 表示（action_results から svg_artifact を取り出して描画）
