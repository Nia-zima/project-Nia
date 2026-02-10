# 📂 ディレクトリマップ

このドキュメントでは、AI_Buddy (Nia) プロジェクトの全体的なディレクトリ構造を説明します。

---

## プロジェクトルート

```
AI_Buddy/
├── backend/              # バックエンド (Python/FastAPI)
├── frontend/             # フロントエンド (Next.js/TypeScript)
├── data/                 # データベース・ユーザーデータ
├── docs/                 # ドキュメント
├── logs/                 # ログファイル
├── scripts/              # ユーティリティスクリプト
├── tests/                # テストファイル
├── identity.md           # ニアのアイデンティティ定義
├── README.md             # プロジェクト概要
├── requirements.txt      # Python依存関係
├── pyproject.toml        # Pythonプロジェクト設定
└── .env                  # 環境変数（Git管理外）
```

---

## Backend 構造

```
backend/
├── api/                      # API層（新規アーキテクチャ）
│   └── memory_router.py      # メモリAPI
│
├── controllers/              # ルーター・コントローラー
│   ├── api/                  # API endpoints
│   │   ├── __init__.py
│   │   ├── actions_router.py     # アクション管理
│   │   ├── profile_router.py     # ユーザープロフィール
│   │   ├── review_router.py      # レビューウィンドウ
│   │   ├── stream_router.py      # SSEストリーミングチャット
│   │   ├── system_router.py      # システム情報
│   │   ├── tts_events_router.py  # TTSイベント
│   │   └── tts_router.py         # TTS制御
│   │
│   ├── stats/                # 統計API
│   │   ├── __init__.py
│   │   ├── memory_router.py      # メモリ統計
│   │   ├── state_router.py       # 状態統計
│   │   └── summary_router.py     # サマリー
│   │
│   ├── pending_memory_router.py  # 保留メモリ
│   └── stats_router.py           # 統計（レガシー）
│
├── core/                     # コアロジック
│   ├── agent_graph/          # LangGraph定義（Phase 1+）
│   │   ├── __init__.py
│   │   ├── graph.py          # グラフ定義
│   │   ├── nodes.py          # 5ノード実装
│   │   ├── review_window.py  # Phase 2: レビューウィンドウ
│   │   ├── state.py          # 状態定義
│   │   ├── tools.py          # ツール定義
│   │   └── utils.py          # ユーティリティ
│   │
│   ├── constants/            # 定数定義
│   │   └── nia_spine_v09.py  # システムプロンプト
│   │
│   ├── agent.py              # Agentオーケストレーション
│   ├── config.py             # 設定管理
│   ├── config_patch.py       # 設定パッチ
│   ├── db.py                 # DB管理
│   ├── logger.py             # ロギング設定
│   ├── ports.py              # ポート定義
│   └── state.py              # 状態管理
│
├── services/                 # ビジネスロジック
│   ├── tts/                  # TTSサービス
│   │   ├── __init__.py
│   │   └── tts_event_bus.py  # TTSイベントバス
│   │
│   ├── action_manager.py         # アクション管理
│   ├── agent_orchestrator.py     # エージェント統合
│   ├── audience_guard.py         # ストリーム視聴者保護
│   ├── chat_history_store.py     # チャット履歴ストア
│   ├── dream_store.py            # ドリームストア
│   ├── gate_codes.py             # Phase 3: ゲートコード定義
│   ├── hearing_adapter.py        # STT統合
│   ├── identity_diff.py          # アイデンティティ差分
│   ├── identity_manager.py       # アイデンティティ管理
│   ├── image_store.py            # 画像ストア
│   ├── inner_monologue_logger.py # 内部独白ログ
│   ├── knowledge_graph.py        # 知識グラフ
│   ├── lint_output.py            # 出力検証
│   ├── llm_client.py             # LLM APIクライアント
│   ├── llm_reflection.py         # LLM振り返り
│   ├── memory_gate.py            # Phase 3: メモリゲート
│   ├── memory_judge.py           # メモリ重要度判定
│   ├── memory_manager.py         # メモリ管理統合
│   ├── memory_store.py           # メモリストア
│   ├── non_negotiable.py         # 非交渉可能な原則チェック
│   ├── pending_actions_repo.py   # 保留アクションリポジトリ
│   ├── pending_actions_service.py # 保留アクションサービス
│   ├── public_status.py          # 公開ステータス
│   ├── retention_config.py       # 保持設定
│   ├── retention_sweeper.py      # メモリ保持スイーパー
│   ├── speech_sanitizer.py       # 出力サニタイザー
│   ├── startup_tasks.py          # 起動タスク
│   ├── telemetry_logger.py       # テレメトリログ
│   ├── thought_engine.py         # 思考エンジン
│   ├── tool_tag_parser.py        # ツールタグパーサー
│   ├── tools.py                  # ツール定義
│   ├── vector_store.py           # ベクトルストア
│   ├── vision_adapter.py         # ビジョンアダプター
│   ├── vision_client.py          # ビジョンクライアント
│   ├── voice_adapter.py          # ボイスアダプター
│   └── voicevox_client.py        # VOICEVOXクライアント
│
├── scripts/                  # メンテナンススクリプト
│   ├── backfill_origin_message_id.py  # Origin ID バックフィル
│   ├── chapter_decision.py            # 章の決裁
│   ├── chapter_reflection.py          # 章の振り返り
│   ├── debug_check_db.py              # DB整合性チェック
│   ├── dump_all.py                    # データダンプ
│   ├── generate_docs.py               # ドキュメント生成
│   ├── retention_full.py              # 保持処理フル実行
│   ├── show_qr.py                     # QRコード表示
│   ├── sleep_cycle.py                 # スリープサイクル
│   ├── stream_digest.py               # ストリームダイジェスト
│   ├── sync_vector_from_sql.py        # ベクトル同期
│   └── vector_sync_status.py          # ベクトル同期ステータス
│
├── tests/                    # バックエンドテスト
│   ├── __init__.py
│   └── (テストファイル)
│
├── static/                   # 静的ファイル
│   └── audio/                # 生成されたオーディオ
│       └── (*.wav ファイル - Git管理外)
│
├── chroma_db_storage/        # ChromaDBストレージ
│   ├── chroma.sqlite3        # ChromaDB メタデータ
│   └── (コレクションディレクトリ)
│
├── tools/                    # ツール
│   └── judge_inspector.py    # Judge監査ツール
│
└── server.py                 # FastAPIエントリポイント
```

---

## Frontend 構造

```
frontend/
├── app/                      # Next.js App Router
│   ├── globals.css           # グローバルスタイル
│   ├── layout.tsx            # ルートレイアウト
│   └── page.tsx              # メインページ
│
├── components/               # Reactコンポーネント
│   ├── AvatarView.tsx        # 3Dアバター表示
│   ├── ChatInterface.tsx     # チャットUI
│   ├── InnerMonologue.tsx    # 内部独白表示
│   ├── MemoryExplorer.tsx    # メモリエクスプローラー
│   ├── MemoryGraph.tsx       # メモリグラフ
│   ├── MemoryTimeline.tsx    # メモリタイムライン
│   ├── ServiceWorkerRegistration.tsx  # PWA登録
│   ├── SettingsPanel.tsx     # 設定パネル
│   ├── Sidebar.tsx           # サイドバー
│   └── StatsPanel.tsx        # 統計パネル
│
├── lib/                      # ライブラリ・ユーティリティ
│   └── api.ts                # APIクライアント
│
├── public/                   # 公開ファイル
│   └── (画像・アイコン等)
│
├── .next/                    # ビルド出力（Git管理外）
├── node_modules/             # npm依存関係（Git管理外）
├── package.json              # npm設定
├── tsconfig.json             # TypeScript設定
└── tailwind.config.js        # TailwindCSS設定
```

---

## Data 構造

```
data/
├── nia.sqlite3               # メインデータベース
│   ├── chat_messages         # チャット履歴
│   ├── memories              # メモリメタデータ
│   ├── pending_actions       # 保留アクション
│   └── (その他テーブル)
│
├── checkpointer.sqlite3      # LangGraphチェックポインター
│   └── checkpoints           # グラフ実行状態
│
├── user_profile.json         # ユーザープロフィール（Git管理外）
│
└── (*.sqlite3-wal, *.sqlite3-shm) # WALファイル（Git管理外）
```

---

## Logs 構造

```
logs/
├── inner/                    # 内部ログ
│   └── monologue.jsonl       # 内部独白ログ（Git管理外）
│
├── app.log                   # アプリケーションログ
├── app.log.1                 # ローテーションログ（Git管理外）
├── app.log.2                 # ローテーションログ（Git管理外）
└── app.log.3                 # ローテーションログ（Git管理外）
```

---

## Docs 構造

```
docs/
├── adr/                      # Architecture Decision Records
│   └── 001-phase3-pending-actions-review-request.md
│
├── A_safety_spec.md          # 安全性仕様
├── ARCHITECTURE.md           # システムアーキテクチャ詳細
├── DIRECTORY_MAP.md          # このファイル
├── NIA_NON_NEGOTIABLE.md     # 非交渉可能な原則
├── NIA_OVERVIEW.md           # Nia概要
├── OPERATION_MANUAL.md       # 運用マニュアル
├── project_overview.md       # プロジェクト概要
├── SETUP.md                  # セットアップガイド
└── source_code_bundle.md     # ソースコードバンドル説明
```

---

## Scripts 構造（プロジェクトルート）

```
scripts/
├── __init__.py
├── backup_project.py         # プロジェクトバックアップ
├── bundle_sources.py         # ソースバンドル作成
├── console_chat.py           # コンソールチャット
├── diagnose_memory_pipeline.py  # メモリパイプライン診断
├── qwen3_tts_smoke.py        # Qwen3 TTSスモークテスト
├── recover_pending_actions.py   # 保留アクション復旧
└── secure_memories.py        # メモリセキュリティ
```

---

## Tests 構造（プロジェクトルート）

```
tests/
├── test_agent_direct.py      # エージェント直接テスト
├── test_agent_persistence.py # エージェント永続化テスト
├── test_api_integration.py   # API統合テスト
├── test_dataset_builder.py   # データセットビルダーテスト
├── test_gate_codes.py        # ゲートコードテスト
├── test_history_api.py       # 履歴APIテスト
├── test_lint_output.py       # 出力検証テスト
├── test_memory.py            # メモリテスト
├── test_pending_actions.py   # 保留アクションテスト
├── test_phase1.py            # Phase 1テスト
├── test_phase2.py            # Phase 2テスト
├── test_review_e2e.py        # レビューE2Eテスト
├── test_review_window.py     # レビューウィンドウテスト
├── test_run.py               # 実行テスト
├── test_safety_spec.py       # 安全性仕様テスト
├── test_server_api.py        # サーバーAPIテスト
└── test_server_connection.py # サーバー接続テスト
```

---

## 重要ファイル一覧

| パス | 説明 | 重要度 | 変更頻度 |
| :--- | :--- | :---: | :---: |
| **identity.md** | ニアのアイデンティティ定義。性格・価値観の根幹 | ★★★ | 低 |
| **backend/core/config.py** | 設定管理。API URL、パス、環境変数 | ★★★ | 中 |
| **backend/core/agent_graph/** | LangGraphワークフロー。思考プロセスの中核 | ★★★ | 中 |
| **backend/services/memory_manager.py** | メモリ管理統合。短期・長期記憶の橋渡し | ★★★ | 中 |
| **backend/services/speech_sanitizer.py** | 出力浄化。内部タグ除去とリーク防止 | ★★★ | 低 |
| **backend/server.py** | FastAPIエントリポイント。アプリケーション起動 | ★★★ | 低 |
| **frontend/components/ChatInterface.tsx** | チャットUI。ユーザーとの主要インターフェース | ★★★ | 中 |
| **data/nia.sqlite3** | メインデータベース。会話履歴と記憶 | ★★★ | 高 |
| **backend/chroma_db_storage/** | ベクトルDB。長期記憶の実体 | ★★★ | 高 |
| **backend/core/constants/nia_spine_v09.py** | システムプロンプト。AIの思考基盤 | ★★☆ | 低 |
| **logs/inner/monologue.jsonl** | 内部独白ログ。デバッグと振り返り | ★★☆ | 高 |
| **.env** | 環境変数。APIキー、URL設定 | ★★☆ | 低 |

---

## Git管理外のファイル（.gitignoreに含まれる）

以下のファイルは `.gitignore` で管理外にされています:

### 生成ファイル
- `backend/static/audio/**/*.wav` - 生成されたTTS音声
- `data/*.sqlite3-wal`, `data/*.sqlite3-shm` - SQLite WALファイル
- `backend/logs/*.log.*` - ローテーションログ

### プライバシー関連
- `data/user_profile.json` - ユーザープロフィール
- `identity_snapshots/` - アイデンティティスナップショット
- `sleep_outputs/*.jsonl` - スリープ出力

### 開発環境
- `.venv/` - Python仮想環境
- `__pycache__/` - Pythonキャッシュ
- `node_modules/` - npm依存関係
- `.next/` - Next.jsビルド出力

### レガシー
- `faiss_index/` - 旧ベクトルインデックス
- `backend/chroma_db/` - 旧ChromaDBディレクトリ

---

## ディレクトリの役割マトリックス

| ディレクトリ | 読み取り | 書き込み | Git管理 | 目的 |
|------------|---------|---------|---------|------|
| `backend/core/` | 高頻度 | 低頻度 | ✅ | システムコア |
| `backend/services/` | 高頻度 | 中頻度 | ✅ | ビジネスロジック |
| `backend/controllers/` | 中頻度 | 低頻度 | ✅ | APIルーティング |
| `frontend/components/` | 高頻度 | 中頻度 | ✅ | UIコンポーネント |
| `data/` | 高頻度 | 高頻度 | ⚠️ 部分的 | データ永続化 |
| `logs/` | 中頻度 | 高頻度 | ❌ | ログ出力 |
| `docs/` | 低頻度 | 低頻度 | ✅ | ドキュメント |
| `tests/` | 中頻度 | 中頻度 | ✅ | テストコード |
| `scripts/` | 低頻度 | 低頻度 | ✅ | ユーティリティ |

---

## 追加の構造ファイル

プロジェクトルートには、以下のドキュメント・設定ファイルも含まれています:

- **AGENTS.md**: エージェント説明
- **constraints.txt**: 制約条件
- **dataset_builder.py**: データセットビルダー
- **summarize_gate_logs.py**: ゲートログサマリー
- **train_gate.py**: ゲートトレーニング

---

**このディレクトリマップは、プロジェクトの全体像を理解するためのリファレンスです。詳細は各ファイルのドキュメントを参照してください。**
