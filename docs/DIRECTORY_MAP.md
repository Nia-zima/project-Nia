# ディレクトリマップ

project-nia プロジェクトのディレクトリ構造。

---

## プロジェクトルート

```
project-nia/
├── backend/              # バックエンド (Python/FastAPI)
├── frontend/             # フロントエンド (Next.js 16)
├── tests/                # テスト (1590+ テスト)
├── docs/                 # ドキュメント
├── data/                 # データベース（Git 管理外）
├── logs/                 # ログファイル
├── minecraft-bot/        # Minecraft Bot (mineflayer)
├── identity.md           # ニアのアイデンティティ定義
├── public_status.json    # 公開ステータス
├── pyproject.toml        # Python プロジェクト設定
├── requirements.txt      # Python 依存関係
└── .env                  # 環境変数（Git 管理外）
```

---

## Backend

```
backend/
├── server.py                     # FastAPI エントリポイント
│
├── core/                         # コアロジック
│   ├── agent.py                  # DefaultAgentOrchestrator
│   ├── agent_stream.py           # SSE ストリーム実行
│   ├── agent_helpers.py          # 共通ヘルパー
│   ├── auth.py                   # Admin Token 認証
│   ├── config.py                 # Settings クラス（.env 読み込み）
│   ├── db.py                     # SQLite スキーマ初期化
│   ├── embedding_model.py        # 埋め込みモデル
│   ├── logger.py                 # ロギング設定
│   ├── body_constitution_checker.py  # Body Constitution 検証
│   │
│   ├── agent_graph/              # LangGraph パイプライン
│   │   ├── graph.py              # グラフ定義（9 ノード）
│   │   ├── state.py              # AgentState TypedDict（59 フィールド）
│   │   ├── review_window.py      # Review Window 関数群
│   │   └── nodes/                # ノード実装（パッケージ）
│   │       ├── routing.py        # safety / dissonance / depth_selector
│   │       ├── depth_nodes.py    # depth0 / depth1 / depth2
│   │       ├── merge.py          # merge_output
│   │       ├── actions.py        # action_processing / s5_commit
│   │       ├── helpers.py        # ノード共通ヘルパー
│   │       ├── text_guards.py    # テキスト安全性チェック
│   │       └── external_pipeline.py  # 外部パイプライン処理
│   │
│   └── constants/                # プロンプト定数
│       ├── nia_spine_v10.py      # 背骨（全 Depth 共通基本指示）
│       ├── depth0_prompt_v11.py  # Depth0 プロンプト（使用中）
│       ├── depth1_prompt_v11.py  # Depth1 プロンプト（使用中）
│       └── minecraft_brain_prompt.py  # Minecraft 用プロンプト
│
├── controllers/                  # API ルーター
│   ├── api/                      # メイン API
│   │   ├── stream_router.py      # SSE ストリーミングチャット
│   │   ├── review_router.py      # Review Window
│   │   ├── actions_router.py     # Phase 5 アクション
│   │   ├── system_router.py      # Vision/Sleep/Reflect (admin)
│   │   ├── profile_router.py     # ユーザープロフィール
│   │   ├── identity_router.py    # Identity Proposal レビュー (admin)
│   │   ├── voice_router.py       # Voice Mode WebSocket
│   │   ├── tts_router.py         # TTS 生成
│   │   ├── tts_events_router.py  # TTS イベントバス
│   │   ├── draw_router.py        # お絵描き機能
│   │   ├── livestream_router.py  # 配信連携
│   │   ├── game_router.py        # Minecraft (admin)
│   │   ├── video_router.py       # 動画分析 (admin)
│   │   └── motion_router.py      # VRM モーション
│   │
│   ├── stats/                    # 統計 API
│   │   ├── summary_router.py     # サマリー
│   │   ├── state_router.py       # 内部状態
│   │   ├── memory_router.py      # メモリ統計
│   │   └── observation_router.py # 観察レポート
│   │
│   ├── stats_router.py           # 統計ルート集約
│   └── pending_memory_router.py  # 保留メモリ
│
├── services/                     # ビジネスロジック
│   ├── memory/                   # Memory v2 サブパッケージ + メタ認知
│   │   ├── memory_service.py     # 統一インターフェース
│   │   ├── context_builder.py    # Depth 別コンテキスト生成（PINNED/PATTERNS/WORKING/MEMORY）
│   │   ├── commit_executor.py    # S5 Commit 実行
│   │   ├── semantic_store.py     # Semantic CRUD
│   │   ├── working_store.py      # Working Items CRUD
│   │   ├── retrieval.py          # Query-Aware Retrieval (M.1)
│   │   ├── guardrail.py          # メモリ書き込み安全性
│   │   ├── metacognition.py      # N.1 確信度調整 + N.0 Awareness + N.5 Self-Narrative
│   │   ├── contradiction.py      # N.2 矛盾検出（defeaters 付き）
│   │   ├── self_model.py         # N.3 自己モデル（知識境界・成長エッジ）
│   │   ├── storage_driver.py     # SQLite ストレージ操作
│   │   ├── models.py             # Pydantic モデル
│   │   └── vector_sync.py        # ベクトル同期
│   │
│   ├── gaming/                   # 汎用ゲーム操作 (Screen Adapter)
│   │   ├── __init__.py           # init_screen_gaming / shutdown
│   │   ├── screen_capture.py     # mss 画面キャプチャ → JPEG → base64
│   │   ├── brain.py              # ゲーム意思決定 (THINK/ACTION/CHAT/IDLE)
│   │   ├── game_loop.py          # GenericGameLoop (Perceive-Think-Act-Reflect)
│   │   ├── input_controller.py   # pydirectinput 入力制御 + ActionMapping
│   │   ├── screen_profile.py     # ScreenGameProfile (GameProfile 実装)
│   │   └── game_configs.py       # ゲーム設定プリセット
│   │
│   ├── game_profiles/            # ゲームプロファイル抽象化
│   │   ├── base.py               # GameProfile ABC
│   │   ├── registry.py           # GameProfileRegistry (シングルトン)
│   │   └── minecraft.py          # MinecraftProfile
│   │
│   ├── agent_orchestrator.py     # エージェント統合
│   ├── twitter_client.py         # X (Twitter) 投稿クライアント
│   ├── reflection_engine.py     # Autonomous Reflection (R.2 + R.4)
│   ├── idle_detector.py         # アイドル検出 (R.1)
│   ├── speech_sanitizer.py       # 出力サニタイズ + ジェスチャー
│   ├── identity_manager.py       # Identity 読み書き
│   ├── identity_diff.py          # Identity 差分計算
│   ├── vision_client.py          # 画像認識 (LM Studio / Gemini Flash)
│   ├── voicevox_client.py        # VOICEVOX TTS
│   ├── stt_service.py            # faster-whisper STT
│   ├── voice_session_manager.py  # Voice セッション管理
│   ├── voice_adapter.py          # ボイスアダプター
│   ├── vector_store.py           # ChromaDB ベクトルストア
│   ├── external_data.py          # 外部 API データ取得
│   ├── memory_manager.py         # メモリ管理（レガシー互換）
│   ├── memory_judge.py           # 重要度判定
│   ├── memory_gate.py            # メモリゲート
│   ├── chat_history_store.py     # チャット履歴
│   ├── llm_client.py             # LLM API クライアント
│   ├── action_manager.py         # アクション管理
│   ├── pending_actions_repo.py   # 保留アクションリポジトリ
│   ├── pending_actions_service.py # 保留アクションサービス
│   ├── retention_sweeper.py      # メモリ保持スイーパー
│   ├── retention_config.py       # 保持設定
│   ├── turn_observation_logger.py # ターン観察ログ
│   ├── public_status.py          # 公開ステータス
│   ├── audience_guard.py         # 配信視聴者保護
│   ├── livestream_queue.py       # 配信コメントキュー
│   ├── draw_agent_service.py     # お絵描きサービス
│   ├── video_analyzer.py         # 動画分析
│   ├── youtube_dl.py             # YouTube ダウンロード
│   ├── motion_learner.py         # モーション学習
│   ├── motion_library.py         # モーションプリセット
│   └── (その他ユーティリティ)
│
├── scripts/                      # メンテナンススクリプト
│   ├── sleep_cycle/              # Sleep Cycle パッケージ（日次メンテ）
│   │   ├── __init__.py           # エントリポイント
│   │   ├── orchestrator.py       # 全体オーケストレーション
│   │   ├── layers.py             # Layer A/B 処理
│   │   ├── extraction.py         # Semantic 抽出
│   │   ├── compression.py        # Episodic 圧縮
│   │   └── helpers.py            # 共通ヘルパー
│   ├── observation_report.py     # 観察レポート生成
│   ├── backfill_semantics.py     # Semantic バックフィル
│   ├── cleanup_checkpoints.py    # チェックポイント GC
│   └── (その他マイグレーション・デバッグ)
│
└── tools/                        # ツール
    └── judge_inspector.py        # Judge 監査
```

---

## Frontend

```
frontend/
├── app/                          # Next.js App Router
│   ├── globals.css               # グローバルスタイル
│   ├── layout.tsx                # ルートレイアウト
│   └── page.tsx                  # メインページ（タブルーティング）
│
├── components/                   # React コンポーネント
│   ├── ChatInterface.tsx         # メインチャット UI + SSE + Voice
│   ├── AvatarView.tsx            # VRM 3D アバター
│   ├── Live2DView.tsx            # Live2D アバター (pixi-live2d-display)
│   ├── ActionPanel.tsx           # Phase 5 アクション承認 + ツイート管理
│   ├── ActionIssuesPanel.tsx     # 失敗/却下アクション
│   ├── MemoryExplorer.tsx        # 記憶ブラウザ
│   ├── MemoryGraph.tsx           # 記憶関係性グラフ
│   ├── MemoryTimeline.tsx        # 記憶タイムライン
│   ├── StatsPanel.tsx            # 統計ダッシュボード
│   ├── InnerMonologue.tsx        # 内部独白
│   ├── ObservationReport.tsx     # 観察レポート
│   ├── DrawLab.tsx               # お絵描き PoC
│   ├── GamePanel.tsx             # Minecraft 連携
│   ├── VideoPanel.tsx            # 動画分析
│   ├── IdentityPanel.tsx         # Identity Proposal レビュー
│   ├── ProfileEditor.tsx         # プロフィール編集
│   ├── LivestreamDashboard.tsx   # 配信ダッシュボード
│   ├── Sidebar.tsx               # ナビゲーション + Admin Token
│   ├── SettingsPanel.tsx         # モード切替
│   └── chat/                     # チャットサブコンポーネント
│       ├── ChatInput.tsx         # 入力エリア
│       ├── ChatMessages.tsx      # メッセージ表示
│       └── messageNormalization.ts  # メッセージ正規化
│
├── hooks/                        # カスタムフック
│   ├── useVoiceMode.ts           # Voice Mode フック
│   ├── useAudioPlayback.ts       # 音声再生フック
│   ├── voiceModeUtils.ts         # Voice ユーティリティ
│   └── audioPlaybackUtils.ts     # 再生ユーティリティ
│
├── lib/                          # ライブラリ
│   ├── apiClient.ts              # 統一 API クライアント
│   ├── types.ts                  # 共有型定義
│   └── stores/
│       └── chatStore.ts          # チャット状態管理
│
└── public/
    ├── vad/                      # Silero VAD アセット
    │   ├── silero_vad_v5.onnx
    │   ├── ort-wasm-simd.wasm
    │   └── vad.worklet.bundle.min.js
    └── live2d/                   # Live2D モデルアセット
        └── hiyori/               # サンプルモデル (Hiyori)
```

---

## Data（Git 管理外）

```
data/
├── nia.sqlite3               # メイン DB（全テーブル）
├── checkpointer.sqlite3      # LangGraph チェックポインター
└── user_profile.json         # ユーザープロフィール
```

---

## Docs

```
docs/
├── ARCHITECTURE.md               # システムアーキテクチャ
├── SYSTEM_SPEC.md                # システム仕様書
├── DIRECTORY_MAP.md              # このファイル
├── body_constitution.md          # Body Constitution
├── constitution_mapping.md       # Constitution マッピング
├── memory_redesign_v2.md         # Memory v2 設計仕様
├── contracts.md                  # 10 状態遷移契約
├── OPERATION_MANUAL.md           # 運用マニュアル
├── SETUP.md                      # セットアップガイド
├── nia_metacognition_design.md   # メタ認知パイプライン設計 (N.0〜N.5)
├── memory_retrieval_design.md   # Memory Retrieval 設計 (M.1)
├── memory_system_overview.md    # Memory System 概要
├── improvement_plan.md           # 改善計画表
├── livestream_design.md          # 配信機能設計
├── pre_streaming_checklist.md    # 配信準備チェックリスト
├── memory_legacy_deprecation_plan.md  # レガシー移行管理
├── PHASE0_CONTRACTS.md           # Phase 0 契約
├── PHASE1_CONFIDENCE.md          # Phase 1 確信度
├── PHASE2_LANGGRAPH.md           # Phase 2 LangGraph
├── PHASE5_ACTION_INTEGRATION.md  # Phase 5 アクション
├── POST_PHASE5_REFACTORING.md    # Post-Phase5 リファクタ
├── POST_PHASE5_ADJUSTMENT_PLAN.md # Post-Phase5 調整計画
│
└── archived/                     # アーカイブ済み
    ├── PHASE3_POLICY_LEARNING.md
    ├── PHASE4_DSPY.md
    ├── ROADMAP_INTEGRATED.md
    ├── NIA_OVERVIEW.md
    ├── IMPLEMENTATION_SUMMARY.md
    ├── A_safety_spec.md
    ├── project_overview.md
    ├── source_code_bundle.md
    └── adr/
        └── 001-phase3-pending-actions-review-request.md
```

---

## 重要ファイル

| パス | 説明 | 重要度 |
|------|------|:------:|
| `identity.md` | ニアのアイデンティティ定義 | ★★★ |
| `backend/core/config.py` | Settings（全設定集約） | ★★★ |
| `backend/core/agent_graph/` | LangGraph パイプライン | ★★★ |
| `backend/services/memory/` | Memory v2 サブパッケージ | ★★★ |
| `backend/core/constants/nia_spine_v10.py` | 背骨プロンプト | ★★★ |
| `backend/services/speech_sanitizer.py` | 出力サニタイザー | ★★★ |
| `backend/server.py` | FastAPI エントリポイント | ★★★ |
| `backend/scripts/sleep_cycle/` | Sleep Cycle パッケージ | ★★☆ |
| `backend/services/memory/metacognition.py` | メタ認知パイプライン (N.0/N.1/N.5) | ★★☆ |
| `frontend/components/ChatInterface.tsx` | メインチャット UI | ★★☆ |
| `frontend/lib/apiClient.ts` | 統一 API クライアント | ★★☆ |
| `.env` | 環境変数 | ★★☆ |
