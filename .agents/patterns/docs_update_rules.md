# Docs Update Rules — project-nia

## 更新タイミング

- gate の on/off や stage が変わった時
- Step 進行や品質改善の到達点が変わった時
- 新しい運用ルールや復旧手順が増えた時

## 主な更新対象

| ファイル | いつ更新 | 何を |
|---------|---------|------|
| `README.md` | 大きい現在地変更 | 実装ステージ、ローカル運用 gate |
| `CLAUDE.md` | 構造変更 / 現在地変更 | 現在地一覧、参照 docs |
| `docs/assistant_context.md` | セッション区切り | AI 向け現在地 |
| `docs/session_handoff.md` | セッション区切り | 最新の停止位置 |
| `docs/decision_log.md` | 新しい判断 | なぜそうしたか |
| `docs/feature_gate_registry.md` | gate 変更 | 現在値、stage、次候補 |
| `docs/nia_integration_roadmap.md` | 順序変更 | 統合順序 |
| `docs/merge_guardrail_reform_plan.md` | Step 進行 | 完了状況、次段 |

## 原則

- 可変データの正本は `python -m backend.scripts.report_gate_status`
- docs を更新する時は、gate 実値と現コードの両方を見る
- `.agents/` は入口、詳細は docs 側を正とする
