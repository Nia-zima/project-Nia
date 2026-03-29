# Deferred Items（先送り・未配線項目）

> **目的:** コンポーネント横断で「やるつもりだがまだやっていない」項目を一覧管理する。
> **更新タイミング:** 新規先送り発生時、項目の着手・完了時。

---

## 未配線（state producer が存在しない）

| 項目 | 所在 | 状態 | 着手条件 | 備考 |
|------|------|------|---------|------|
| `review_used` | expression_observations | 常に `False` | review_window に `review_used_this_turn` フラグ追加 | s5_commit 時点で信頼できるシグナルがない |
| `resumed_after_wait` | expression_observations | 常に `False` | WAIT 後の再開を追跡する state producer 実装 | |
| `silence_gap_bucket` | expression_observations | 常に `"none"` | ターン間の無音時間を計測する仕組み | |
| `reassurance_loop` | expression_observations | 常に `False` | 検出ロジック実装（Nero 側で先行検討中） | |
| `topic_shift` | expression_observations | 常に `False` | 前ターンとの比較が必要。E1 で実装予定 | |

---

## 設計書との残存差異

### NiaCore v1

| 項目 | 現状 | 設計書の仕様 | 着手条件 |
|------|------|-------------|---------|
| `somatic_divergence` 指標 | `rejected_rate` で代替 | 体感ベースの乖離度 | S.2（体感+Pip 統合）時 |
| `retrieval_miss` | プロキシ実装（D0 比率 > 0.9） | state_vector から行レベル参照 | 専用の仕組みが必要 |
| `surprise_collapse` | surprise_v の平均 | 記憶保存率 | 記憶保存率の別途計算が必要 |
| スレッドセーフティ | シングルトン `_model_instance` | マルチワーカー対応 | マルチワーカー運用時 |
| mini-batch 分割 | full-batch | LIMIT + mini-batch | 日次数百行を超えた場合 |

### NiaCore vNext

| 項目 | 現状 | 設計書の仕様 | 着手条件 |
|------|------|-------------|---------|
| CfC 多ヘッドモデル | 未実装（Phase N0 は擬似教師のみ） | attention/intent/action/depth の4ヘッド | Phase N0 データ蓄積後 |

---

## コードベース内の TODO / FIXME

| ファイル | 行付近 | 内容 |
|---------|--------|------|
| `commit_helpers.py` | L298 | `TODO(niacore)`: 3 operations below (close prev window, record current, ...) |
| `dspy/dataset.py` | L237 | `TODO`: 実際のログからデータを収集する実装 |
| `evidence_aggregator.py` | L104 | `TODO`: Re-enable when topic_key or anchor_id matching is available |

---

## 実装完了だが未有効化

| 項目 | Gate | 実装完了日 | 有効化の阻害要因 |
|------|------|----------|----------------|
| Contract 2 (Atmosphere) | `ATMOSPHERE_ENABLED` | 2026-03-13 | Phase A 観測が先 |
| Skeleton Somatic | `SKELETON_SOMATIC_ENABLED` | 2026-03-16 | Record-Only 観測と分布確認が先 |
| NiaCore Training | `NIACORE_TRAINING_ENABLED` | 2026-03-06 | Shadow 30 日 + 品質条件待ち |

---

## 将来タスク（設計完了・実装未着手）

| 項目 | 設計書 | 依存 |
|------|--------|------|
| TS.1 Contrast Engine | `temporal_somatic_contrast_design.md` | TS.0 で 500+ ターン蓄積 |
| TS.3 Idle Tick | `temporal_somatic_contrast_design.md` | TS.0 と並行可能 |
| S.2 体感 + Pip 統合 | `somatic_self_awareness_design.md` | P.1-P.4 挙動観察後 |
| P.3 お絵かき統合 | `pip_and_room_design.md` | Unity 依存 |
| P.7 配信 | `unity_room_visual_direction.md` | Unity 依存 |
| M.4 Retrieval Observability | `memory_retrieval_design.md` | 将来 |
| Governance Phase B (claims + review) | `memory_promotion_redesign.md` | Phase A 安定後 |
| Governance Phase C (semantic_state) | `memory_promotion_redesign.md` | Phase B 後 |
| Context Builder キャッシュ層 | — | Depth2 有効化時 |

---

## State フィールドの設計課題

| 項目 | 現状 | 推奨 |
|------|------|------|
| `merge_mode` に `review_token` を埋め込み | `f"review:{token}"` | merge_mode enum と review_token を分離 |
| `review_rejected_actions` がターン間で蓄積 | クリアされない | ターンごとのリセットか、明示的な寿命定義 |
| `suppressed_actions` の writer が暗黙的 | review_window.set_review_token 内 | 明示的な writer 文書化 |
| Contract 3 の内部フィールド名が `_` 接頭辞 | `_room_change`, `_cur_pip_visible` 等 | `cur_*` に統一（vnext からも参照されるため） |
