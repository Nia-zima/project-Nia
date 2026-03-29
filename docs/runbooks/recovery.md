# Recovery Runbook

> **目的:** 障害時に「何を止めて、何を残して、どこから戻すか」を明文化する。
> **前提:** project-nia はローカル完結（SQLite + ChromaDB）。外部サービス依存は LM Studio / VOICEVOX のみ。
> **シェル:** コマンド例は bash (Git Bash / WSL) 前提。PowerShell の場合は `$DATE` → `$DATE`、`mv` → `Move-Item`、`cp` → `Copy-Item`、`mkdir -p` → `New-Item -ItemType Directory -Force` に読み替えること。
> **Python:** `.venv\Scripts\python` または `python`（venv がアクティブな前提）。

---

## バックアップ

### 対象ファイル

| ファイル | 優先度 | 頻度 | 理由 |
|---------|--------|------|------|
| `data/nia.sqlite3` | **最重要** | 日次 | ニアの全記憶・観測データ |
| `identity.md` | **最重要** | 変更時 | ニアの人格定義 |
| `data/room_state.json` | 高 | 日次 | 部屋の状態 |
| `data/somatic_calibration.json` | 高 | 日次 | 体感閾値の学習結果 |
| `data/user_profile.json` | 中 | 週次 | ユーザープロファイル |
| `data/checkpointer.sqlite3` | 低 | 週次 | LangGraph チェックポイント（再生成可能） |
| `.env` | 高 | 変更時 | 設定値 |

### バックアップ手順

```bash
# 日次バックアップ（サーバー停止不要、WAL モードなので安全）
$DATE=$(date +%Y%m%d)
mkdir -p backups/$DATE
sqlite3 data/nia.sqlite3 ".backup backups/$DATE/nia.sqlite3"
cp identity.md backups/$DATE/
cp data/room_state.json backups/$DATE/ 2>/dev/null
cp data/somatic_calibration.json backups/$DATE/ 2>/dev/null
cp .env backups/$DATE/
```

### 復元確認

バックアップ後、以下で整合性を確認:

```bash
sqlite3 backups/$DATE/nia.sqlite3 "PRAGMA integrity_check;"
# → "ok" が返ること
```

---

## 障害別手順

### 1. SQLite 破損（nia.sqlite3）

**症状:** `sqlite3.DatabaseError: database disk image is malformed`

**手順:**

1. サーバーを停止
2. 整合性チェック:
   ```bash
   sqlite3 data/nia.sqlite3 "PRAGMA integrity_check;"
   ```
3. 部分回復を試みる:
   ```bash
   sqlite3 data/nia.sqlite3 ".recover" | sqlite3 data/nia_recovered.sqlite3
   ```
4. 回復成功の場合:
   ```bash
   mv data/nia.sqlite3 data/nia_corrupted_$(date +%Y%m%d).sqlite3
   mv data/nia_recovered.sqlite3 data/nia.sqlite3
   ```
5. 回復失敗の場合: 最新バックアップから復元:
   ```bash
   mv data/nia.sqlite3 data/nia_corrupted_$(date +%Y%m%d).sqlite3
   cp backups/YYYYMMDD/nia.sqlite3 data/nia.sqlite3
   ```
6. migration を再適用:
   ```bash
   python -c "from backend.core.db import init_schema; init_schema()"
   ```
7. サーバー再起動

**データ損失:** バックアップ時点以降の会話・観測データが失われる。
記憶（semantic_memories）は半減期で自然に再構築されるが、episodic は復元不可。

---

### 2. ChromaDB 再構築

**症状:** ベクトル検索が動かない、ChromaDB ディレクトリ破損

**手順:**

1. サーバーを停止
2. ChromaDB ディレクトリを退避:
   ```bash
   # ChromaDB の永続化先は backend/chroma_db_storage/
   mv backend/chroma_db_storage backend/chroma_db_storage_broken_$(date +%Y%m%d)
   ```
3. **Step A: Episodic コレクション再構築**（memory_events 由来の capture を復元）:
   ```bash
   python -m backend.scripts.sync_vector_from_sql
   ```
   これは `memory_events` テーブルの capture を `collection_type="episodic"` で ChromaDB に再投入する。
   `vector_candidates()`（stage="long_term" フィルタ）が依存するデータはここで復元される。

4. **Step B: Semantic 再同期**（semantic_memories の埋め込みを復元）:
   ```bash
   # 全件を再同期対象にする
   sqlite3 data/nia.sqlite3 "UPDATE semantic_memories SET vector_sync_pending = 1 WHERE status = 'active';"

   # 再同期実行
   python -c "
   from backend.services.memory.vector_sync import process_semantic_vector_sync
   synced = process_semantic_vector_sync(limit=10000)
   print(f'Synced: {synced}')
   "
   ```
   これは semantic_memories を同じ episodic コレクションに `type="semantic"` メタデータ付きで投入する。

5. サーバー再起動

**データ損失:** なし。ChromaDB は SQLite の memory_events + semantic_memories から再構築できる。
**注意:** Step A → Step B の順序で実行すること。両方とも同じ "episodic" コレクションに書き込む。

---

### 3. Schema Mismatch

**症状:** `sqlite3.OperationalError: no such table` / `no such column`

**原因:** コード更新後に migration が未適用、または DB が古いバージョン

**手順:**

1. 現在の schema version を確認:
   ```bash
   python -c "
   from backend.core.db import managed_conn
   from backend.core.db_migrations import get_current_version, get_latest_version
   with managed_conn() as conn:
       print(f'Current: v{get_current_version(conn)}, Latest: v{get_latest_version()}')
   "
   ```
2. version が古い場合、migration を適用:
   ```bash
   python -c "from backend.core.db import init_schema; init_schema()"
   ```
3. それでも解決しない場合、テーブルの存在を確認:
   ```bash
   sqlite3 data/nia.sqlite3 ".tables"
   ```
4. 特定テーブルのカラムを確認:
   ```bash
   sqlite3 data/nia.sqlite3 "PRAGMA table_info(問題のテーブル名);"
   ```

**注意:** 手動で ALTER TABLE するのは最終手段。まず migration の追加を検討する。

---

### 4. identity.md 誤変更

**症状:** ニアの人格が意図しない方向に変わった

**原因:** Sleep Cycle の Self-Model が意図しない提案を適用した、または手動編集ミス

**手順:**

1. git で差分を確認:
   ```bash
   git diff identity.md
   git log --oneline -5 identity.md
   ```
2. 特定のコミットに戻す:
   ```bash
   git checkout <commit-hash> -- identity.md
   ```
3. identity_proposals テーブルで適用済み提案を確認:
   ```bash
   python -c "
   from backend.core.db import managed_conn
   with managed_conn() as conn:
       rows = conn.execute(
           'SELECT id, status, proposal, chapter_context, created_at FROM identity_proposals ORDER BY created_at DESC LIMIT 10'
       ).fetchall()
       for r in rows:
           print(dict(r))
   "
   ```

**予防:** identity.md の変更は Origin 承認制（不可侵ルール #5）。自動書き換えコードは存在しない設計。

---

### 5. Feature Gate 緊急停止

**症状:** 特定のサブシステムが暴走している（例: NiaCore が異常な depth 推薦を出す）

**手順:**

1. `.env` で該当 gate を `false` に設定:
   ```env
   NIACORE_SHADOW_ENABLED=false
   ```
2. サーバーを再起動（gate は起動時に読み込まれる）
3. 影響を確認:
   ```bash
   python -m backend.scripts.report_gate_status
   ```

**gate 別の影響範囲:**

| Gate を off にした場合 | 影響 |
|-----------------------|------|
| `NIACORE_SHADOW_ENABLED` | shadow 推論が停止。ルールベース depth 選択のみ（現在と同じ）|
| `NIACORE_TRAINING_ENABLED` | Sleep Cycle での学習が停止。モデルは最後の状態で凍結 |
| `SKELETON_RECORD_ENABLED` | 会話骨格の記録が停止。LLM の動作に影響なし |
| `SKELETON_SOMATIC_ENABLED` | 体感テキスト注入が停止。Depth0 のプロンプトが短くなる |
| `GOVERNANCE_*_ENABLED` | 全 off: 候補・証拠の蓄積停止。既存記憶に影響なし |
| `FINGERPRINT_RECORD_ENABLED` | fingerprint 記録停止。TS.1 に影響 |
| `EXPRESSION_RECORD_ENABLED` | 発話メタデータ記録停止。E0.5 に影響 |
| `RUNTIME_FACTS_ENABLED` | RuntimeFacts 注入停止。LLM context が短くなる |

**全 gate の設計原則:** 「壊れても今と同じ」— off にしてもニアの基本動作は変わらない。

---

### 6. checkpointer.sqlite3 肥大化

**症状:** `data/checkpointer.sqlite3` が数百 MB〜GB に膨張

**原因:** LangGraph のチェックポイントが蓄積。WAL ファイルが大きい場合もある。

**手順:**

1. サーバーを停止
2. WAL をチェックポイント:
   ```bash
   sqlite3 data/checkpointer.sqlite3 "PRAGMA wal_checkpoint(TRUNCATE);"
   ```
3. まだ大きい場合、VACUUM:
   ```bash
   sqlite3 data/checkpointer.sqlite3 "VACUUM;"
   ```
4. それでも巨大な場合、削除して再作成:
   ```bash
   mv data/checkpointer.sqlite3 data/checkpointer_old_$(date +%Y%m%d).sqlite3
   ```
   次回起動時に LangGraph が新規作成する。

**データ損失:** チェックポイント削除により、進行中の会話コンテキストが失われる。
新しい会話は正常に開始できる。

---

## 定期リハーサル（最小セット）

本番障害時に詰まらないため、最低でも以下の 3 本は定期的に実施する。
優先順は 1 → 2 → 3。

### 1. Chroma 再構築リハーサル（最優先）

**頻度:** 月1回、または Chroma / Retrieval 周りの変更後

**目的:** `backend/chroma_db_storage` を失っても、runbook 通りに検索面を戻せることを確認する。

**手順:**

1. サーバーを停止
2. 事前確認:
   ```bash
   python -m backend.scripts.report_gate_status
   ```
3. ChromaDB を退避:
   ```bash
   mv backend/chroma_db_storage backend/chroma_db_storage_rehearsal_$(date +%Y%m%d)
   ```
4. Chroma 再構築手順の Step A / Step B をそのまま実行
5. サーバー再起動
6. 確認:
   - 起動ログに VectorStore 初期化エラーが出ていない
   - 既知の記憶クエリで retrieval が 1 件以上返る
   - `python -m backend.scripts.report_gate_status` が正常に出る

**成功条件:** Retrieval が復旧し、通常会話で記憶参照が再び機能する。

### 2. SQLite バックアップ / 復元リハーサル

**頻度:** 月1回、または schema 変更の前後

**目的:** `.backup` で取得した DB を、慌てず検証・復元できることを確認する。

**手順:**

1. バックアップ取得:
   ```bash
   $DATE=$(date +%Y%m%d)
   mkdir -p backups/$DATE
   sqlite3 data/nia.sqlite3 ".backup backups/$DATE/nia.sqlite3"
   ```
2. 整合性確認:
   ```bash
   sqlite3 backups/$DATE/nia.sqlite3 "PRAGMA integrity_check;"
   ```
3. 復元先のコピーを作る:
   ```bash
   cp backups/$DATE/nia.sqlite3 tmp/rehearsal_restore.sqlite3
   ```
4. 最低限の内容確認:
   ```bash
   sqlite3 tmp/rehearsal_restore.sqlite3 ".tables"
   sqlite3 tmp/rehearsal_restore.sqlite3 "SELECT COUNT(*) FROM semantic_memories;"
   ```

**成功条件:** `integrity_check=ok`、主要テーブルが見え、復元コピーを読める。

### 3. Migration / Schema Mismatch リハーサル

**頻度:** リリース前、または migration 追加後

**目的:** 旧 DB からの追従と、現在 DB の version 整合が壊れていないことを確認する。

**手順:**

1. migration テストを実行:
   ```bash
   python -m pytest -q tests/test_db_migrations.py
   ```
2. 現在 DB の version を確認:
   ```bash
   python -c "
   from backend.core.db import managed_conn
   from backend.core.db_migrations import get_current_version, get_latest_version
   with managed_conn() as conn:
       print(f'Current: v{get_current_version(conn)}, Latest: v{get_latest_version()}')
   "
   ```
3. `Current == Latest` であることを確認

**成功条件:** migration テストが通り、現在 DB の schema_version が最新に追従している。

---

## リハーサル履歴

定期リハーサルを実施したら、日付・結果・発見事項をここに追記する。
「手順はあるが、最後にいつ通したか分からない」状態を避けるための簡易ログ。

| 日付 | リハーサル | 結果 | 発見事項 / 対応 | 次回 |
|------|-----------|------|-----------------|------|
| 2026-03-17 | SQLite バックアップ / 復元 | PASS | `integrity_check=ok`、48 テーブル確認、記憶データ読取確認 | 次回 schema 変更前後または月次 |
| 2026-03-17 | Migration / Schema Mismatch | PASS | `tests/test_db_migrations.py` 16件通過。本番 DB が `v2` のまま `v3` 未適用だったため、その場で適用完了 | migration 追加後またはリリース前 |
| 2026-03-17 | Chroma 再構築 | PENDING | サーバー停止前提のため未実施 | 次回メンテナンス時 |

---

## チェックリスト

障害対応後に確認すること:

- [ ] `python -m backend.scripts.report_gate_status` で gate と table が正常
- [ ] `sqlite3 data/nia.sqlite3 "PRAGMA integrity_check;"` → `ok`
- [ ] サーバー起動後、テスト会話を1往復行って応答を確認
- [ ] `identity.md` が意図した内容であること
- [ ] 必要に応じてバックアップを取り直す
