# Data Retention Policy

> **目的:** 観測テーブルの保持期間・アーカイブ・削除方針を定義する。
> **更新タイミング:** 新規観測テーブル追加時、保持期間の見直し時。
> **現在地:** 方針定義のみ。自動化（Sleep Cycle 統合）は後回し。

---

## 背景

project-nia は観測専用テーブルが多い。記憶システムには半減期による自然な忘却があるが、
観測データ（fingerprint, expression, experience, governance 等）にはそれがない。
無制限に蓄積すると DB ファイルが肥大化し、バックアップ・VACUUM・クエリ性能に影響する。

**現在のデータ量（2026-03-17 時点）:**

| ファイル | サイズ | 備考 |
|---------|--------|------|
| `data/nia.sqlite3` | 19 MB | メイン DB |
| `data/checkpointer.sqlite3` | 540 MB | LangGraph チェックポイント（最大） |
| `data/nia_test.sqlite3` | 0.7 MB | テスト用 |

---

## テーブル別方針

### Tier 1: 長期保持（削除しない）

ニアの「記憶」に相当するデータ。削除は記憶の喪失を意味する。

| テーブル | 現在行数 | 方針 | 理由 |
|---------|---------|------|------|
| `semantic_memories` | 455 | **保持** | ニアの確定知識。半減期で自然減衰 |
| `memory_events` | 373 | **保持**（圧縮あり） | エピソード記憶。Sleep Cycle で `episodic_summaries` に圧縮済み |
| `episodic_captures` | 237 | **保持** | 構造化エピソード |
| `daily_reflections` | 147 | **保持** | 日次振り返り。Sleep Cycle の入力 |
| `dreams` | 19 | **保持** | Sleep Cycle 出力 |
| `identity_proposals` | — | **保持** | Origin 承認制。履歴として重要 |
| `telemetry_kv` | 30 | **保持** | KV ストア。行数が増えない設計 |

### Tier 2: 中期保持（90日 → アーカイブ or 削除）

分析用の観測データ。一定期間後は集計値だけ残せばよい。

| テーブル | 現在行数 | 保持期間 | アクション | 理由 |
|---------|---------|---------|-----------|------|
| `somatic_log` | 1,721 | 90日 | 90日超を DELETE | 体感フィードバック。直近の傾向分析に使用 |
| `retrieval_logs` | 1,396 | 90日 | 90日超を DELETE | 検索ログ。M.4 Observability で集計後は不要 |
| `governance_events` | 1,263 | 90日 | 90日超を DELETE | 観測イベント。Phase A 分析後は集計値で十分 |
| `niacore_experience` | 500 | 90日 | 90日超で `used_in_training=1` の行のみ DELETE | 学習済みデータは保持価値低下 |
| `conversation_skeletons` | 457 | 90日 | 90日超を DELETE | ラベル分布は集計で保持 |

### Tier 3: 短期保持（30日 → 削除）

高頻度の詳細観測。蓄積が速い。

| テーブル | 現在行数 | 保持期間 | アクション | 理由 |
|---------|---------|---------|-----------|------|
| `turn_fingerprints` | 293 | 30日 | 30日超を DELETE | TS.1 Contrast は直近データで動作。古い fingerprint は不要 |
| `expression_observations` | 0 | 30日 | 30日超を DELETE | E0.5 パターン分析は直近の傾向に焦点 |
| `niacore_vnext_shadow` | 0 | 30日 | 30日超を DELETE | Phase N0 観測データ。分布安定後は不要 |

### Tier 4: 特殊

| ファイル/テーブル | 方針 | 理由 |
|-----------------|------|------|
| `checkpointer.sqlite3` | **VACUUM のみ** | LangGraph 内部管理。手動削除は危険。`PRAGMA wal_checkpoint(TRUNCATE)` で WAL を圧縮 |
| `raw_promotion_candidates` | **Phase B 移行まで保持** | candidate → claim 変換後は削除可能 |
| `memory_evidence` | **Phase B 移行まで保持** | claim に紐付いた後は集計で十分 |
| `messages` | **保持** | 会話履歴ストア（chat_history_store が管理）。直接 prune しない |
| `nia_test.sqlite3` | **随時削除可** | テスト用。スキーマ変更後に再作成 |

---

## VACUUM 方針

SQLite は DELETE しても物理ファイルサイズが減らない。定期的に VACUUM が必要。

| 対象 | タイミング | コマンド |
|------|----------|---------|
| `nia.sqlite3` | 月次 or prune 実行後 | `VACUUM;` |
| `checkpointer.sqlite3` | 月次 | `PRAGMA wal_checkpoint(TRUNCATE);` |

**注意:** VACUUM は DB を排他ロックする。サーバー停止中に実行すること。

---

## 実行方法（現在: 手動）

```bash
# dry-run: 削除対象の行数を確認
python -m backend.scripts.prune_observation_tables --dry-run

# 実行
python -m backend.scripts.prune_observation_tables

# VACUUM（サーバー停止後）
sqlite3 data/nia.sqlite3 "VACUUM;"
```

---

## 自動化ロードマップ

1. **Phase 1（現在）:** 手動スクリプト + dry-run
2. **Phase 2:** Sleep Cycle の最終フェーズに prune を追加
3. **Phase 3:** VACUUM を Sleep Cycle 後に自動実行（サーバー再起動前提）

---

## 変更時の注意

- 保持期間の変更は、該当テーブルを使う分析（E0.5, TS.1, NiaCore 学習等）の要件を確認してから行う
- Tier 1 のテーブルは「削除しない」が原則。例外は Origin の判断が必要
- prune スクリプトは必ず dry-run を先に実行する
