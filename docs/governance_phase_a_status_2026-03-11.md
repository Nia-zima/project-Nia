# Governance Phase A Status (2026-03-11)

このメモは、2026年3月11日時点のニアのデータ収集・記憶ガバナンス Phase A の現在地をまとめたもの。

目的は3つ。

- いま何が live / shadow / scaffold かを短く固定する
- `raw_promotion_candidates` がまだ 0 件である理由を整理する
- 本番の会話記憶を汚さずに Phase A を検証する運用方針を残す

これは実装メモ兼運用メモであり、長期設計の本体は以下を参照する。

- `docs/data_store_map.md`
- `docs/memory_governance_redesign.md`
- `docs/memory_promotion_redesign.md`
- `docs/memory_system_supplementary.md`

## 1. 全体方針

現時点の優先順位は `governance first`。

理由:

- NiaCore が学習しても、SkeletonCore が方向を持っても、元になる記憶の精度が低いと全体が不安定になる
- `candidate -> evidence -> claim -> review -> semantic_state` の制度を先に整える方が、後段の学習・制御が安定する

実装順の大枠:

- Phase A: `raw_promotion_candidates` + `memory_evidence`
- Phase B: `memory_claims` + `promotion_reviews`
- Phase C: `semantic_state` の lifecycle 管理
- 並走: `review_window` を canonical dataset に入るようにする
- 後段: `SkeletonCore somatic`、`NiaCore training`

## 2. データの現在地

### live

- `messages`
- `memory_events`
- `semantic_memories`
- `somatic_log`
- `daily_reflections`
- `events`
- `x_post_proposals`
- `telemetry_kv`
- canonical dataset export パイプライン

### shadow / record-only

- `niacore_experience`
- `conversation_skeletons`
- `retrieval_logs`

### live（observability / monitoring）

- `governance_events`（制度本体ではないが、記録自体は本番稼働中）

### scaffold / 器のみ

- `raw_promotion_candidates`
- `memory_claims`
- `memory_evidence`
- `promotion_reviews`
- `semantic_state`
- `semantic_lineage`
- `semantic_reviews`
- `semantic_tombstones`
- `semantic_transitions`

重要なのは、`governance_events` は live だが、ガバナンス本体テーブルはまだほぼ空という点。

## 3. 学習データの現在地

2026年3月11日時点の確認値:

- canonical sample 総数: `554`
- `eligible_samples`: `10`
- `high_confidence_samples`: `10`
- `training_ready_samples`: `10`
- `excluded_samples`: `544`

増えている主力は以下。

- `phase5`
- `x_post_proposals`

一方で `review_window` はまだ training-ready にほぼ入っていない。

現状の読み方:

- データが全く無いわけではない
- ただし「新制度の高信頼データ」はまだ少ない
- 量より、正規 schema に乗ったサンプルを増やす段階

## 4. Governance Phase A 実装の現在地

追加済み:

- `backend/services/memory/candidate_harvester.py`
- `backend/core/agent_graph/nodes/commit_helpers.py` の `_harvest_governance_candidates()`
- `backend/core/agent_graph/nodes/actions.py` の `s5_commit` 接続
- `GOVERNANCE_CANDIDATE_ENABLED`

現在の rule set:

- H1: `correction_strong -> contradiction`
- H2: `dissonance_on -> dissonance`
- H3: `surprise >= 0.6 -> surprise`
- H4: `depth >= 2 -> deep_processing`
- H5: `skeleton_focus=contradiction -> contradiction`
- H6: `skeleton_focus=emotional_state && surprise >= 0.3 -> emotional_pattern`

反映済みの修正:

- H1 は `detect_correction_level(user_text)` をその場で呼ぶ（somatic_feedback は DB に書くため state に correction_level は乗らない）
- H3/H6 は `awareness composite` ではなく `state.surprise_score` を使用（composite は汎用指標、surprise_score が実際の驚き）
- docstring は「fire-and-forget」ではなく「同期実行。例外は呼び出し元で握りつぶされる」に修正

追加済みの observability:

- 0 件ターンでも `[CANDIDATE_HARVESTER] checked turn=... 0 candidates (depth=... surprise=... dissonance=... correction=...)` を DEBUG ログに出力
- これにより、harvest が呼ばれたが候補なしだったのか、そもそも呼ばれていないのかを区別できる

## 5. なぜ `raw_promotion_candidates` がまだ 0 件か

2026年3月11日時点では、`raw_promotion_candidates` はまだ `0` 件。

確認済み:

- `GOVERNANCE_CANDIDATE_ENABLED=true`
- `s5_commit` 自体は通っている
- candidate harvester のテストは通っている

それでも 0 件である主因は、現時点では配線切れより「直近会話が H1〜H6 を踏んでいない」可能性が高い。

直近 `default_thread` の傾向:

- `depth=0/1`
- `surprise_score` が立っていない
- `dissonance_on` が立っていない
- skeleton も `missing_context` または `user_goal` が中心

つまり、今のルールでは自然に candidate が出ない会話が続いている。

補足:

- `logs/app.log` 上の `[CANDIDATE_HARVESTER]` は主に `turn_test` 由来だった
- 本番ターンで harvest された形跡は、少なくとも 2026-03-11 時点では確認できていない
- ただし current implementation は「候補が 1 件以上出た時だけ info log」を出すため、0 件ターンではログだけでは実行可否が分かりにくい

## 6. Probe をどう回すか

### 原則

確認用ケースを `default_thread` や `nero_meeting_*` に流すのは避ける。

理由:

- テスト口調や不自然な矛盾が自然会話の記憶に混ざる
- `memory_events` や reflection に synthetic な味が混入する

### 推奨運用

- 専用 thread を使う  
  例: `governance_probe_h1`, `governance_probe_h2`
- synthetic であることを明示する  
  例: `source=synthetic_eval`
- canonical dataset にはデフォルトで入れない
- semantic 昇格・reflection の対象にも原則しない

短く言うと、probe は有効だが「本番会話」と混ぜないことが前提。

## 7. Synthetic probe の作り方

自由会話 AI をそのまま相手役にするより、まずは `H1〜H6` ごとの eval ケース集として扱う方が安全。

推奨構成:

- 手書きテンプレート
- 軽量ローカルモデル: 文面の言い換え専用
- クラウド AI: 難ケースだけ追加生成

モデルの役割は「自然な言い換え生成」に留める。

避けたいこと:

- 本番相手として長く会話させる
- synthetic 会話をそのまま教師データ扱いする
- runtime 記憶に自然データと同列で混ぜる

### ケース管理の最小フォーマット

- `case_id`
- `target_rule`
- `thread_id`
- `prompt`
- `expected_candidate_kind`

最初の運用は `H1〜H6` 各5件、合計30件程度で十分。

### 実装済み probe スクリプト

`backend/scripts/probe_candidate_harvester.py` に 3-stage probe を実装済み。

| Stage | 内容 | DB アクセス |
|-------|------|-----------|
| 1 | `_should_harvest()` ルールチェック | なし |
| 2 | `harvest_candidates()` DB 書き込み | あり |
| 3 | `_harvest_governance_candidates()` パイプライン信号マッピング | なし（mock） |

probe ケース: H1〜H6 各1件 + NONE 1件 = 計7件。

2026-03-11 実行結果:

- Stage 1: 全 PASS（7/7）
- Stage 2: 全 PASS（6件挿入、NONE ケースは正しくスキップ）
- Stage 3: 全 PASS（state → HarvestSignals のマッピング正常）

DB に挿入された probe 行は `thread_id LIKE 'governance_probe_%'` で識別可能。

## 8. 次の実務ステップ

完了済み:

- [x] `GOVERNANCE_CANDIDATE_ENABLED=true` 有効化
- [x] 3-stage probe 作成・実行・全 PASS
- [x] probe 行 6件が `raw_promotion_candidates` に入ることを確認
- [x] 0 件ターンの DEBUG ログ追加（pipeline 実行の可視化）
- [x] コードレビュー修正 3件（H1 correction source, H3/H6 surprise source, docstring）

次の優先度順:

1. 自然会話から `raw_promotion_candidates` に candidate が入ることを確認する（probe ではなく本番ターン由来）
2. 分布を観察する（どの rule が多いか、品質はどうか）
3. candidate が安定して入ることを確認したら `memory_evidence` live 化へ進む
4. 並走で `review_window` の `decision_event.v2 / commit_log.v2` 配線を進める

ここで重要なのは、自然会話の量を増やすことではなく、制度イベントを正しい形で増やすこと。

## 9. 一言で言うと

2026年3月11日時点のニアは、

- runtime / reflection / action / export はかなり live
- governance は `events` と `observe` までは live
- でも `candidate -> evidence -> claim -> review -> semantic_state` の本体制度はまだ始動前

今はその入口である `raw_promotion_candidates` を、安全に live 化し始める段階にある。
