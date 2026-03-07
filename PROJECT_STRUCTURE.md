# project-nia — Full Project Structure

> AI VTuber「ニア (Nia)」- LangGraph multi-layer agent + Next.js frontend
> Last updated: 2026-02-26

```
project-nia/
│
├── .github/
│   └── workflows/
│       └── ci.yml                          # CI パイプライン (lint + test)
│
├── backend/
│   ├── core/                               # === コアエンジン ===
│   │   ├── agent.py                        # Agent ラッパー (SSE ストリーミング)
│   │   ├── agent_stream.py                 # StreamingContext + llm_producer
│   │   ├── agent_helpers.py                # Agent ヘルパー関数
│   │   ├── agent_graph/                    # --- LangGraph ワークフロー ---
│   │   │   ├── graph.py                    # グラフ定義 (Safety→Depth→Merge→S5)
│   │   │   ├── state.py                    # AgentState TypedDict
│   │   │   ├── review_window.py            # レビューウィンドウ管理
│   │   │   ├── utils.py                    # グラフユーティリティ
│   │   │   └── nodes/                      # --- ノード実装 ---
│   │   │       ├── routing.py              #   safety / dissonance / depth_selector
│   │   │       ├── depth_nodes.py          #   depth0 / depth1 / depth2
│   │   │       ├── merge.py                #   merge_output
│   │   │       ├── actions.py              #   action_processing / s5_commit
│   │   │       ├── external_pipeline.py    #   外部検索パイプライン
│   │   │       ├── helpers.py              #   ノードヘルパー
│   │   │       └── text_guards.py          #   テキスト安全チェック
│   │   ├── confidence/                     # --- 確信度エンジン ---
│   │   │   ├── engine.py                   #   5メトリクス統合エンジン
│   │   │   ├── metrics.py                  #   個別メトリクス計算
│   │   │   └── calibrator.py               #   確信度キャリブレーション
│   │   ├── constants/                      # --- プロンプト定義 ---
│   │   │   ├── nia_spine_v10.py            #   Spine（全レイヤー共通の基本指示）
│   │   │   ├── depth0_prompt_v11.py        #   Depth0 プロンプト
│   │   │   ├── depth1_prompt_v11.py        #   Depth1 プロンプト
│   │   │   └── minecraft_brain_prompt.py   #   Minecraft Brain プロンプト
│   │   ├── contracts/                      # --- 出力契約 ---
│   │   │   ├── depth_contracts.py          #   Depth 別出力制約
│   │   │   └── validators.py               #   バリデーター
│   │   ├── actions/                        # --- アクションシステム ---
│   │   │   ├── executor.py                 #   アクション実行
│   │   │   ├── gate.py                     #   アクションゲート
│   │   │   ├── registry.py                 #   アクション登録
│   │   │   └── types.py                    #   型定義
│   │   ├── dspy/                           # --- DSPy 最適化 ---
│   │   │   ├── dataset.py                  #   データセット
│   │   │   ├── metrics.py                  #   評価メトリクス
│   │   │   ├── modules.py                  #   DSPy モジュール
│   │   │   ├── optimizer.py                #   オプティマイザー
│   │   │   └── signatures.py               #   シグネチャ定義
│   │   ├── policy/                         # --- 方策学習 ---
│   │   │   ├── collector.py                #   データ収集
│   │   │   ├── environment.py              #   環境定義
│   │   │   ├── feedback.py                 #   フィードバック処理
│   │   │   └── learner.py                  #   学習ロジック
│   │   ├── config.py                       # Settings (.env → Pydantic)
│   │   ├── config_patch.py                 # 設定パッチ
│   │   ├── auth.py                         # 認証
│   │   ├── correlation.py                  # リクエスト相関ID
│   │   ├── db.py                           # DB 初期化 (SQLite)
│   │   ├── embedding_model.py              # 埋め込みモデル管理
│   │   ├── logger.py                       # ロギング設定
│   │   ├── ports.py                        # ポート抽象化
│   │   ├── rate_limit.py                   # レート制限
│   │   ├── retry.py                        # リトライ機構
│   │   ├── service_health.py               # サービスヘルスチェック
│   │   ├── state.py                        # グローバル状態
│   │   ├── body_constitution.md            # 身体憲章（テキスト）
│   │   ├── body_constitution_checker.py    # 身体憲章チェッカー
│   │   └── tech_manual.md                  # 技術マニュアル
│   │
│   ├── services/                           # === サービス層 ===
│   │   ├── memory/                         # --- 3層記憶システム ---
│   │   │   ├── memory_service.py           #   記憶CRUD（統合エントリポイント）
│   │   │   ├── memory_driver.py            #   低レベルDB操作
│   │   │   ├── context_builder.py          #   Depth別メモリコンテキスト生成
│   │   │   ├── commit_executor.py          #   S5 Commit 実行
│   │   │   ├── semantic_store.py           #   Semantic 記憶 CRUD
│   │   │   ├── working_store.py            #   Working 記憶 CRUD
│   │   │   ├── storage_driver.py           #   ストレージ抽象化
│   │   │   ├── retrieval.py                #   Query-Aware Retrieval (M.1)
│   │   │   ├── models.py                   #   データモデル
│   │   │   ├── vector_sync.py              #   ChromaDB 同期
│   │   │   ├── guardrail.py                #   ガードレール (6条件)
│   │   │   ├── metacognition.py            #   N.0 Awareness + N.1 MetaCog + N.5 Self-Narrative
│   │   │   ├── contradiction.py            #   N.2 矛盾検出 (defeaters)
│   │   │   └── self_model.py               #   N.3 自己モデル
│   │   ├── minecraft/                      # --- Minecraft 自律プレイ ---
│   │   │   ├── game_loop.py                #   自律ゲームループ
│   │   │   ├── client.py                   #   Bot HTTP クライアント
│   │   │   ├── skill_library.py            #   スキル CRUD (SQLite)
│   │   │   ├── skill_retrieval.py          #   ベクトル検索でスキル発見
│   │   │   ├── skill_executor.py           #   Bot へのスキル実行指示
│   │   │   ├── execution_engine.py         #   実行 + 自己修正ループ
│   │   │   ├── critique_generator.py       #   LLM 失敗分析
│   │   │   ├── failure_memory.py           #   過去の失敗パターン検索
│   │   │   ├── goal_manager.py             #   目標管理
│   │   │   ├── state_manager.py            #   ゲーム状態管理
│   │   │   ├── event_listener.py           #   ゲームイベント監視
│   │   │   └── video_learner.py            #   動画から戦略抽出
│   │   ├── gaming/                         # --- 汎用ゲーム操作 (Screen Adapter) ---
│   │   │   ├── brain.py                    #   ゲーム意思決定 (LLM)
│   │   │   ├── game_loop.py                #   GenericGameLoop
│   │   │   ├── screen_capture.py           #   mss 画面キャプチャ
│   │   │   ├── input_controller.py         #   pydirectinput 入力制御
│   │   │   ├── screen_profile.py           #   ScreenGameProfile
│   │   │   └── game_configs.py             #   ゲーム設定プリセット
│   │   ├── game_profiles/                  # --- ゲームプロファイル抽象化 ---
│   │   │   ├── base.py                     #   GameProfile ABC
│   │   │   ├── minecraft.py                #   Minecraft プロファイル
│   │   │   └── registry.py                 #   プロファイルレジストリ
│   │   ├── chat_bridge/                    # --- 外部チャット取り込み ---
│   │   │   ├── twitch_fetcher.py           #   Twitch チャット取得
│   │   │   └── youtube_fetcher.py          #   YouTube チャット取得
│   │   ├── tts/
│   │   │   └── tts_event_bus.py            #   TTS イベントバス
│   │   ├── agent_orchestrator.py           # SSE オーケストレーター
│   │   ├── chat_history_store.py           # 会話履歴ストア
│   │   ├── checkpointer.py                 # チェックポイント管理
│   │   ├── reflection_engine.py            # Autonomous Reflection (R.2 + R.4)
│   │   ├── idle_detector.py                # アイドル検出 (R.1) + N.4 State Trigger
│   │   ├── memory_manager.py               # 記憶マネージャー（統合）
│   │   ├── episode_store.py                # エピソードストア
│   │   ├── dream_store.py                  # ドリームストア
│   │   ├── llm_client.py                   # LLM クライアント
│   │   ├── llm_reflection.py               # LLM リフレクション
│   │   ├── stt_service.py                  # Faster-Whisper STT
│   │   ├── voicevox_client.py              # VOICEVOX TTS クライアント
│   │   ├── voice_session_manager.py        # 音声セッション管理
│   │   ├── voice_adapter.py                # 音声アダプター
│   │   ├── hearing_adapter.py              # 聴覚アダプター
│   │   ├── vision_client.py                # 画像認識 (LM Studio / Gemini)
│   │   ├── vision_adapter.py               # Vision アダプター
│   │   ├── video_analyzer.py               # 動画解析 (ffmpeg + Vision)
│   │   ├── youtube_dl.py                   # yt-dlp ダウンローダー
│   │   ├── external_data.py                # 外部データ取得 (Google/Wikipedia)
│   │   ├── twitter_client.py               # X (Twitter) 投稿
│   │   ├── speech_sanitizer.py             # 出力浄化
│   │   ├── identity_manager.py             # Identity 管理
│   │   ├── identity_diff.py                # Identity 差分検出
│   │   ├── draw_agent_service.py           # お絵かきエージェント
│   │   ├── motion_learner.py               # モーション学習
│   │   ├── motion_library.py               # モーションライブラリ
│   │   ├── livestream_queue.py             # 配信キュー
│   │   ├── vector_store.py                 # ベクトルストア (ChromaDB)
│   │   ├── telemetry_logger.py             # テレメトリログ
│   │   ├── pending_actions_repo.py         # 保留アクション DB
│   │   ├── pending_actions_service.py      # 保留アクション サービス
│   │   ├── action_manager.py               # アクション管理
│   │   ├── retention_sweeper.py            # 記憶の半減期・忘却
│   │   ├── retention_config.py             # 忘却設定
│   │   ├── memory_gate.py                  # 記憶ゲート
│   │   ├── memory_judge.py                 # 記憶判定
│   │   ├── audience_guard.py               # オーディエンスガード
│   │   ├── gate_codes.py                   # ゲートコード定義
│   │   ├── public_status.py                # 公開ステータス管理
│   │   ├── image_store.py                  # 画像ストア
│   │   ├── thought_engine.py               # 思考エンジン
│   │   ├── tool_tag_parser.py              # ツールタグパーサー
│   │   ├── tools.py                        # ツール定義
│   │   ├── startup_tasks.py                # 起動時タスク
│   │   ├── inner_monologue_logger.py       # 内心独白ロガー
│   │   ├── turn_observation_logger.py      # ターン観測ロガー
│   │   ├── knowledge_graph.py              # 知識グラフ
│   │   └── lint_output.py                  # lint 出力整形
│   │
│   ├── controllers/                        # === API ルーター ===
│   │   ├── api/
│   │   │   ├── stream_router.py            # SSE チャットストリーム + 履歴
│   │   │   ├── voice_router.py             # WebSocket 音声入出力
│   │   │   ├── tts_router.py               # TTS エンドポイント
│   │   │   ├── tts_events_router.py        # TTS イベント
│   │   │   ├── review_router.py            # Approve/Reject
│   │   │   ├── system_router.py            # Sleep/Reflect 管理
│   │   │   ├── game_router.py              # ゲーム操作 (MC + Screen)
│   │   │   ├── video_router.py             # 動画解析
│   │   │   ├── actions_router.py           # アクション (Tweet等)
│   │   │   ├── identity_router.py          # Identity 管理
│   │   │   ├── profile_router.py           # プロファイル
│   │   │   ├── livestream_router.py        # 配信管理
│   │   │   ├── draw_router.py              # お絵かき
│   │   │   ├── motion_router.py            # モーション
│   │   │   ├── manager_router.py           # マネージャー
│   │   │   └── memory_query_router.py      # 記憶クエリ
│   │   ├── stats/
│   │   │   ├── observation_router.py       # 観測データ
│   │   │   ├── memory_router.py            # 記憶統計
│   │   │   ├── state_router.py             # 状態統計
│   │   │   └── summary_router.py           # サマリー統計
│   │   ├── pending_memory_router.py        # 保留記憶
│   │   ├── stats_router.py                 # 統計ルーター
│   │   └── ws_security.py                  # WebSocket セキュリティ
│   │
│   ├── scripts/                            # === スクリプト ===
│   │   ├── sleep_cycle/                    # --- Sleep Cycle パッケージ ---
│   │   │   ├── orchestrator.py             #   全体オーケストレーション
│   │   │   ├── layers.py                   #   Layer A/B 処理
│   │   │   ├── extraction.py               #   Semantic 抽出
│   │   │   ├── compression.py              #   Episodic 圧縮
│   │   │   └── helpers.py                  #   ヘルパー
│   │   ├── backfill_semantics.py           # Semantic バックフィル (LLM)
│   │   ├── backfill_semantic.py            # Semantic バックフィル (レガシー)
│   │   ├── backfill_embeddings.py          # Embedding バックフィル
│   │   ├── backfill_origin_message_id.py   # Origin メッセージID バックフィル
│   │   ├── migrate_legacy_to_memory_events.py  # messages → memory_events 移行
│   │   ├── migrate_episodic_to_memory_events.py # episodic → memory_events 移行
│   │   ├── archive_drop_legacy_memory_tables.py # レガシーテーブル削除
│   │   ├── cleanup_checkpoints.py          # チェックポイント掃除
│   │   ├── observation_report.py           # 観測レポート生成
│   │   ├── retention_full.py               # 完全忘却実行
│   │   ├── sync_vector_from_sql.py         # SQL → ChromaDB 同期
│   │   ├── vector_sync_status.py           # ベクトル同期状態
│   │   ├── stream_digest.py                # 配信ダイジェスト
│   │   ├── dump_all.py                     # 全データダンプ
│   │   ├── debug_check_db.py               # DB デバッグ
│   │   ├── generate_docs.py                # ドキュメント生成
│   │   └── show_qr.py                      # QR コード表示
│   │
│   ├── tools/
│   │   └── judge_inspector.py              # 判定ログ検査
│   ├── static/images/                      # 生成画像ストレージ
│   ├── tests/
│   │   └── test_retention_v2.py            # 忘却テスト
│   └── server.py                           # FastAPI エントリポイント
│
├── frontend/                               # === フロントエンド (Next.js 16) ===
│   ├── app/
│   │   ├── layout.tsx                      # ルートレイアウト
│   │   ├── page.tsx                        # メインページ
│   │   ├── globals.css                     # グローバルスタイル
│   │   └── favicon.ico
│   ├── components/
│   │   ├── ChatInterface.tsx               # チャット統合コンポーネント
│   │   ├── chat/
│   │   │   ├── ChatMessages.tsx            #   メッセージ表示
│   │   │   ├── ChatInput.tsx               #   入力フォーム (テキスト・画像・音声)
│   │   │   ├── messageNormalization.ts     #   メッセージ正規化
│   │   │   └── index.ts
│   │   ├── AvatarView.tsx                  # VRM アバター表示
│   │   ├── Live2DView.tsx                  # Live2D アバター表示
│   │   ├── GamePanel.tsx                   # ゲームパネル
│   │   ├── VideoPanel.tsx                  # 動画解析パネル
│   │   ├── ActionPanel.tsx                 # アクションパネル (承認/却下)
│   │   ├── ActionIssuesPanel.tsx           # アクション問題パネル
│   │   ├── MemoryExplorer.tsx              # 記憶エクスプローラー
│   │   ├── MemoryGraph.tsx                 # 記憶グラフ可視化 (Barnes-Hut)
│   │   ├── MemoryTimeline.tsx              # 記憶タイムライン
│   │   ├── DiaryViewer.tsx                 # 日記ビューアー
│   │   ├── DrawLab.tsx                     # お絵かきラボ
│   │   ├── IdentityPanel.tsx               # Identity パネル
│   │   ├── ProfileEditor.tsx               # プロファイル編集
│   │   ├── InnerMonologue.tsx              # 内心独白表示
│   │   ├── LivestreamDashboard.tsx         # 配信ダッシュボード
│   │   ├── ObservationReport.tsx           # 観測レポート
│   │   ├── StatsPanel.tsx                  # 統計パネル
│   │   ├── SettingsPanel.tsx               # 設定パネル
│   │   ├── Sidebar.tsx                     # サイドバー
│   │   └── ServiceWorkerRegistration.tsx   # PWA SW 登録
│   ├── hooks/
│   │   ├── useAudioPlayback.ts             # 音声再生フック
│   │   ├── audioPlaybackUtils.ts           # 音声ユーティリティ
│   │   ├── useVoiceMode.ts                 # ボイスモードフック
│   │   └── voiceModeUtils.ts               # VM ユーティリティ
│   ├── lib/
│   │   ├── apiClient.ts                    # 統合 API クライアント
│   │   ├── types.ts                        # 型定義
│   │   └── stores/
│   │       ├── chatStore.ts                # チャットストア (Zustand)
│   │       ├── avatarStore.ts              # アバターストア
│   │       └── uiStore.ts                  # UI ストア
│   ├── scripts/
│   │   └── priority-lint-report.mjs        # lint レポート
│   ├── tests/
│   │   ├── hookUtils.test.cjs              # フックテスト
│   │   └── messageNormalization.test.cjs   # 正規化テスト
│   ├── public/
│   │   ├── avatar.vrm                      # VRM アバター
│   │   ├── vad/                            # VAD (Silero ONNX + WASM) [省略]
│   │   ├── live2d/                         # Live2D モデル [省略]
│   │   ├── manifest.json                   # PWA マニフェスト
│   │   └── sw.js                           # Service Worker
│   ├── package.json
│   ├── next.config.ts
│   ├── tsconfig.json
│   ├── postcss.config.mjs
│   └── eslint.config.mjs
│
├── minecraft-bot/                          # === Minecraft Bot (Node.js) ===
│   ├── src/
│   │   ├── index.js                        # エントリポイント
│   │   ├── bot.js                          # Bot コア
│   │   ├── sandbox.js                      # vm サンドボックス
│   │   ├── skill_manager.js                # スキルファイル管理
│   │   ├── actions.js                      # アクション定義
│   │   ├── events.js                       # イベントハンドラ
│   │   ├── http.js                         # HTTP API サーバー
│   │   ├── state.js                        # ゲーム状態
│   │   └── ws.js                           # WebSocket
│   ├── skills/                             # 保存されたスキル (.js) [省略]
│   └── package.json
│
├── tests/                                  # === テストスイート (950+) ===
│   ├── conftest.py                         # 共通フィクスチャ
│   ├── test_awareness.py                   # N.0 Awareness
│   ├── test_metacognition.py               # N.1 MetaCog
│   ├── test_contradiction.py               # N.2 矛盾検出
│   ├── test_self_model.py                  # N.3 自己モデル
│   ├── test_self_narrative.py              # N.5 自己ナラティブ
│   ├── test_reflection_engine.py           # R.2-R.4 リフレクション
│   ├── test_context_builder.py             # Context Builder
│   ├── test_retrieval.py                   # M.1 Retrieval
│   ├── test_s5_commit.py                   # S5 Commit
│   ├── test_guardrail.py                   # ガードレール
│   ├── test_depth_selector.py              # Depth 選択
│   ├── test_depth2_gate.py                 # Depth2 ゲート
│   ├── test_confidence.py                  # 確信度エンジン
│   ├── test_speech_sanitizer.py            # 出力浄化
│   ├── test_game_brain.py                  # ゲーム Brain
│   ├── test_game_loop.py                   # ゲームループ
│   ├── test_failure_memory.py              # 失敗記憶
│   ├── test_video_learner.py               # 動画学習
│   ├── test_twitter_client.py              # Twitter クライアント
│   ├── test_external_data.py               # 外部データ
│   ├── test_llm_client.py                  # LLM クライアント
│   ├── test_rate_limit.py                  # レート制限
│   ├── test_retry.py                       # リトライ
│   ├── test_correlation.py                 # 相関ID
│   ├── test_service_health.py              # ヘルスチェック
│   ├── test_ws_security.py                 # WS セキュリティ
│   ├── ... (100+ test files)               # その他テスト
│   └── archive/                            # アーカイブ済みテスト
│
├── scripts/                                # === ユーティリティスクリプト ===
│   ├── backup_project.py                   # プロジェクトバックアップ
│   ├── bundle_sources.py                   # ソースバンドル
│   ├── pack_project.ps1                    # PowerShell パッキング
│   ├── console_chat.py                     # コンソールチャット
│   ├── contract_compliance_report.py       # 契約準拠レポート
│   ├── recover_pending_actions.py          # 保留アクション復旧
│   ├── reprocess_pending_errors.py         # エラー再処理
│   └── secure_memories.py                  # 記憶セキュア化
│
├── docs/                                   # === ドキュメント ===
│   ├── nia_design_philosophy.md            # ニアの設計思想
│   ├── somatic_self_awareness_design.md    # 体感ベース自己認識 v0.2
│   ├── pip_and_room_design.md              # Pip & 部屋 統合設計
│   ├── nia_metacognition_design.md         # メタ認知 (N.0-N.5) 設計
│   ├── memory_redesign_v2.md               # Memory Redesign v2
│   ├── memory_retrieval_design.md          # Retrieval 設計 (M.1)
│   ├── memory_system_overview.md           # 記憶システム概要
│   ├── autonomous_reflection.md            # 自律振り返り (R.1-R.4)
│   ├── ARCHITECTURE.md                     # アーキテクチャ
│   ├── DIRECTORY_MAP.md                    # ディレクトリマップ
│   ├── SETUP.md                            # セットアップガイド
│   ├── improvement_plan.md                 # 改善計画表
│   ├── body_constitution.md                # 身体憲章
│   ├── constitution_mapping.md             # 憲章マッピング
│   ├── contracts.md                        # 出力契約
│   ├── livestream_design.md                # 配信設計
│   ├── pre_streaming_checklist.md          # 配信前チェックリスト
│   ├── SYSTEM_SPEC.md                      # システム仕様
│   ├── OPERATION_MANUAL.md                 # 運用マニュアル
│   ├── NIA_NON_NEGOTIABLE.md               # 不可侵ルール
│   ├── memory_legacy_deprecation_plan.md   # レガシー記憶廃止計画
│   └── archived/                           # アーカイブ済みドキュメント
│
├── logs/                                   # === ログ ===
│   ├── run_api.bat                         # API 起動バッチ
│   ├── run_brain.bat                       # Brain 起動バッチ
│   ├── run_frontend.bat                    # Frontend 起動バッチ
│   ├── run_obs.bat                         # OBS 起動バッチ
│   ├── observations/                       # 観測ログ
│   ├── inner/                              # 内心独白ログ
│   └── archive/                            # アーカイブ済みログ
│
├── _ARCHIVE/                               # === プロジェクトアーカイブ ===
│   ├── backend_legacy/                     # 旧バックエンド
│   ├── frontend_legacy/                    # 旧フロントエンド
│   └── ...                                 # 各種旧ファイル
│
├── identity.md                             # ニアの人格定義（ランタイム読み込み）
├── CLAUDE.md                               # Claude Code 設計ガイドライン
├── README.md                               # プロジェクト README
├── ABOUT_NIA.md                            # ニア紹介ドキュメント
├── AGENTS.md                               # エージェント定義
├── pyproject.toml                          # Python プロジェクト設定
├── requirements.txt                        # Python 依存関係
├── .env                                    # 環境変数（Git管理外）
├── .env.example                            # 環境変数テンプレート
├── .gitignore
├── LAUNCH_NIA_COMPLETE.bat                 # 全サービス一括起動
└── FORCE_SLEEP.bat                         # Sleep Cycle 強制実行
```

## 統計

| カテゴリ | 数 |
|:---|:---|
| Python ソースファイル (backend/) | ~130 |
| TypeScript/TSX ソースファイル (frontend/) | ~35 |
| JavaScript ソースファイル (minecraft-bot/) | ~8 |
| テストファイル | ~100 |
| ドキュメント (docs/) | ~20 |
| 設計ドキュメント (新規) | 3 (philosophy / somatic / pip+room) |

## 技術スタック

| カテゴリ | 技術 |
|:---|:---|
| バックエンド | Python 3.12+, FastAPI, uvicorn |
| エージェント | LangChain, LangGraph |
| LLM | LM Studio (OpenAI互換, ローカル推論) |
| STT | Faster-Whisper (CPU) |
| TTS | VOICEVOX |
| Vision | LM Studio + Qwen3-VL-4B (GPU) / Gemini Flash |
| DB | SQLite + ChromaDB (ベクトル検索) |
| 埋め込み | paraphrase-multilingual-MiniLM-L12-v2 |
| フロントエンド | Next.js 16, React 19, TypeScript, Tailwind CSS 4 |
| 3D/Live2D | Three.js + @pixiv/three-vrm / pixi-live2d-display + PixiJS v8 |
| 状態管理 | Zustand |
| ゲーム (MC) | Mineflayer (Node.js) + vm サンドボックス |
| ゲーム (汎用) | mss + Gemini Flash Vision + pydirectinput |
| CI | GitHub Actions (ruff lint + pytest) |
