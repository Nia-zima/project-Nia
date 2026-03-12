# Data Accuracy Maintenance (2026-03)

このドキュメントは、2026年3月時点で「ニアの学習用・分析用データを、あとから再構成できる形で正確に貯める」ために行った保守とリファクタリングをまとめた実装記録。

これは計画書ではなく、すでにコードへ入った変更の要約。

## 目的

- review / phase5 / X 投稿の判断を、同じ分析基盤で追えるようにする
- legacy 経路と新経路を分離し、「何を正とするか」を固定する
- 学習に使うサンプルを `training_ready` として明示し、日次 snapshot で保存できるようにする

## 今回そろえた正規データの基準

- 会話判断の正規イベントは `decision_event.v2`
- review の補助ログは `commit_log.v2`
- X の公開判断は `x_post_proposals`
- 学習候補の join key は `thread_id`, `turn_id`, `message_id`, `stream_id`
- 高信頼データの運用基準は `baseline_after_high_confidence_only`

## 実施した変更

### 1. 記憶 write path の正規化

- `capture_recorded` payload の正規化 helper を追加
- `text_hash` / `message_id` ベースの dedupe を event path で実施
- legacy capture table を正系にせず、`memory_events` 側を主系として扱う方向に整理
- `pending_actions_service` と `chat_history_store` の event path 重複記録を抑止

狙い:

- 同じ capture が複数経路から二重記録されるのを防ぐ
- 将来の学習対象を legacy table 依存にしない

### 2. review と Phase5 の state 責務分離

- review 用 preview hold を `review_pending_actions` に分離
- generic action pending は従来どおり `pending_actions`
- review の reject / cancel 履歴を `review_rejected_actions` に分離
- 旧 checkpoint 互換は `normalize_checkpoint_state()` に集約

狙い:

- 「発話プレビューの保留」と「汎用アクション待ち」を同じ箱で持たない
- 古い state 互換を各 router に散らさない

### 3. 判断イベント schema の統一

- `decision_event.v2` を基準 schema に統一
- 共通キーを固定:
  - `schema_version`
  - `source`
  - `actor`
  - `entity_kind`
  - `decision`
  - `status`
  - `reason`
  - `reason_codes`
  - `thread_id`
  - `turn_id`
  - `message_id`
  - `stream_id`
  - `review_token` / `pending_id` / `action_id`
  - `ts`
- review の commit 側も `commit_log.v2` として構造化

狙い:

- review / phase5 / X proposal を同じ単位で見られるようにする
- reason code と join key を後計算でなく発生時保存にする

### 4. review 分析と thread scoped stats

- `/api/stats/summary` を `thread_id` 対応に変更
- hold / reject / cancel / token mismatch / legacy schema を集計
- `actor_breakdown`, `top_reason_codes`, `recommended_baseline_ts` を追加
- `/api/stats/internal_state` で `review_state` の backlog / suppressed 件数を可視化
- frontend Stats に review 分析表示を追加

狙い:

- 全 thread 混在を避ける
- 「なぜ hold/reject されたか」を UI 上で追えるようにする

### 5. canonical dataset exporter の追加

- `canonical_dataset_service.py` を追加
- `decision_event.v2` を基準に review / phase5 を正規化
- review は `commit_log.v2` を結合
- X は `x_post_proposals` を正とする
- サンプルごとに以下を付与:
  - `training_label`
  - `eligible_for_training`
  - `high_confidence`
  - `confidence_tier`
  - `exclude_reason`
  - `confidence_issues`

狙い:

- データセット化のルールをコードに固定する
- どのサンプルが学習に使え、どれが除外かを明示する

### 6. training-ready と source audit の追加

- `select_training_ready_samples()` を追加
- `summarize_canonical_dataset()` に以下を追加:
  - `training_ready_samples`
  - `training_policy`
  - `source_audit`
  - `join_completeness`
  - `x_post_status_breakdown`
- `/api/stats/dataset_export`
- `/api/stats/dataset_audit`

`training_ready` の考え方:

- `high_confidence == True`
- 現行 schema
- required join key が埋まっている
- review approve/reject は `commit_log.v2` と対応が取れている
- baseline 以後のみを採用

除外例:

- `cancelled_flow`
- `token_mismatch`
- `legacy_schema`
- `orphan_commit_log`
- join 欠損や commit 欠損を含む low confidence サンプル

### 7. X 投稿を proposal-first に再設計

- `x_post_proposals` テーブルを追加
- reflection / manual generate / phase5 tweet は直接投稿せず proposal を作成
- approve / reject は `proposal_id` ベース
- public actuation の正規データを proposal と posted に分離
- `nero_meeting_*` など公開禁止 thread は policy で block
- cooldown / daily max / duplicate は proposal service 側に集約

狙い:

- X 投稿を会話ログや reflection 副作用にしない
- 「何が提案され、何が却下され、何が公開されたか」を分離する

### 8. 日次 snapshot 運用の追加

- CLI:
  - `backend/scripts/export_canonical_dataset.py`
  - `backend/scripts/snapshot_training_dataset.py`
- service:
  - `backend/services/training_dataset_snapshot.py`
- backend 常駐 loop:
  - `TRAINING_DATASET_SNAPSHOT_ENABLED`
  - `TRAINING_DATASET_SNAPSHOT_BOOT`
  - `TRAINING_DATASET_SNAPSHOT_INTERVAL_SEC`
  - `TRAINING_DATASET_SNAPSHOT_HOUR_LOCAL`
  - `TRAINING_DATASET_SNAPSHOT_FORMAT`
  - `TRAINING_DATASET_SNAPSHOT_THREAD_ID`
  - `TRAINING_DATASET_SNAPSHOT_DIR`
- system API:
  - `POST /api/system/training_dataset_snapshot`
  - `GET /api/system/diagnostics` に snapshot telemetry を追加

生成物:

- `data/training_exports/YYYY-MM-DD/<scope>_training_ready.jsonl`
- `data/training_exports/YYYY-MM-DD/<scope>_training_ready.summary.json`
- `data/training_exports/latest/...`

狙い:

- 毎日同じポリシーで `training_ready` snapshot を残す
- baseline と件数を telemetry で追えるようにする

## 現在の信頼モデル

今回の変更で改善したのは「たくさん貯まること」ではなく、「あとから壊れずに再構成できること」。

現時点では次を前提に扱う。

- 学習用の主系は `decision_event.v2 + commit_log.v2 + x_post_proposals`
- まずは baseline 以後の `training_ready` を高信頼母集団とする
- legacy データや join 欠損データは可視化するが、自動で学習母集団には混ぜない
- `review_window`, `phase5`, `x_post` は同じ canonical exporter で吐き出す

## 運用で見る場所

### API

- `GET /api/stats/summary?thread_id=<thread>`
- `GET /api/stats/dataset_audit?thread_id=<thread>`
- `GET /api/stats/dataset_export?thread_id=<thread>`
- `POST /api/system/training_dataset_snapshot`
- `GET /api/system/diagnostics`

### CLI

```bash
python backend/scripts/export_canonical_dataset.py ^
  --thread-id default_thread ^
  --training-ready-only ^
  --out data/exports/default_thread_training_ready.jsonl ^
  --summary-out data/exports/default_thread_training_ready.summary.json
```

```bash
python backend/scripts/snapshot_training_dataset.py
```

## まだ残る注意点

- 過去の legacy データそのものは綺麗にならない
- join key が薄い古いイベントは引き続き low confidence / excluded になる
- baseline 以前のデータを学習に混ぜるかどうかは別途判断が必要

## 関連ファイル

- `backend/services/canonical_dataset_service.py`
- `backend/services/training_dataset_snapshot.py`
- `backend/services/x_post_service.py`
- `backend/core/decision_events.py`
- `backend/core/agent_graph/state_normalizer.py`
- `backend/controllers/stats/summary_router.py`
- `backend/controllers/api/system_router.py`
- `backend/scripts/export_canonical_dataset.py`
- `backend/scripts/snapshot_training_dataset.py`
