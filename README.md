# AI_Buddy — Nia Backend & Frontend

> AI VTuber「ニア (Nia)」の開発リポジトリ。LangGraph ベースの多層エージェントグラフ + Next.js フロントエンド。

## 技術スタック

| カテゴリ | 技術 |
|:---|:---|
| バックエンド | Python 3.12+, FastAPI, uvicorn |
| エージェント | LangChain, LangGraph |
| LLM | LM Studio (OpenAI互換API, ローカル推論) |
| 音声認識 | Faster-Whisper (CPU推論) |
| 音声合成 | VOICEVOX |
| 画像認識 | LM Studio + Qwen3-VL-4B (GPU推論) / Gemini Flash (クラウド) |
| データベース | SQLite (メイン) + ChromaDB (ベクトル検索) |
| フロントエンド | Next.js 16, React 19, TypeScript, Tailwind CSS 4 |
| 3D / Live2D | Three.js + @pixiv/three-vrm / pixi-live2d-display + PixiJS v8 |
| 状態管理 | Zustand |
| 最適化 | DSPy |
| Minecraft Bot | Mineflayer (Node.js) + vm サンドボックス |
| 汎用ゲーム操作 | mss (画面キャプチャ) + Gemini Flash (Vision) + pydirectinput (入力) |
| 動画解析 | ffmpeg (フレーム抽出) + Qwen3-VL (場面認識) |
| 外部検索 | Google Custom Search API + Wikipedia API |
| X (Twitter) 投稿 | tweepy (X API v2) |
| 埋め込みモデル | paraphrase-multilingual-MiniLM-L12-v2 (スキル検索) |

---

## アーキテクチャ

### LangGraph エージェントグラフ

```
Safety → Dissonance → DepthSelector → Depth0/1/2 → Merge → ActionProcessing → S5Commit → END
```

| ノード | 役割 |
|:---|:---|
| `safety_interrupt` | 安全性チェック。NG検出時はグラフ終了 |
| `dissonance_check` | 内部矛盾（不協和）を検出 |
| `depth_selector` | 確信度エンジン (5メトリクス統合) で応答深度を決定 |
| `depth0_reflex` | 高確信 (>= 0.8): 短い即答 (max 120 tokens) |
| `depth1_organize_and_ask` | 中確信 (0.3〜0.8): 不確実性を明示、質問1つ (max 300 tokens) |
| `depth2_value_align_and_preview` | 高確信 + 十分な記憶蓄積: 価値観整合を含む深い検討 |
| `merge_output` | Depth出力を統合し `final_text` を生成 |
| `action_processing` | アクション提案のフィルタリング・実行 |
| `s5_commit` | エピソディック記憶への書き込み |

### 3層記憶システム (Memory Redesign v2)

| 層 | テーブル | 内容 | 寿命 |
|:---|:---|:---|:---|
| Episodic | `memory_events` | 会話の事実記録 | ターンごとに自動保存 (S5) |
| Semantic | `semantic_memories` | 確認済みの事実・嗜好・関係性 | 半減期 (inferred: 3日 / confirmed: 30日) |
| Working | `working_memory` | 未解決の質問・一時メモ | TTL またはターン数で消滅 |

記憶は S0〜S5 の状態機械で管理。Semantic 生成は Sleep Cycle で LLM バッチ抽出。

Context Builder が Depth 別にメモリコンテキストを制御:
- Depth0: PINNED FACTS のみ
- Depth1/2: PINNED FACTS + PATTERNS（日横断パターン） + WORKING + Short/Long Term

### Autonomous Reflection（自律振り返り）

ニアが対話のない時間に自発的に記憶を振り返り、パターンを抽出する4段階パイプライン。

| Phase | 名前 | ファイル | 内容 |
|:---:|:---|:---|:---|
| R.1 | Idle Detection | `idle_detector.py` | 3分以上の無入力を検出 |
| R.2 | Daily Log | `reflection_engine.py` | 会話を LLM で振り返り → `daily_reflections` |
| R.3 | Sleep Cycle 連携 | `sleep_cycle.py` | 日次ログを memory_block として活用 |
| R.4 | Cross-Day Distillation | `reflection_engine.py` | 3日+のデータから日横断パターン抽出 |

R.4 パターン（`user_trait` / `relationship_pattern` / `emerging_interest` / `lesson`）は `semantic_memories` に `state_tag='insight'` で保存。Context Builder の `=== PATTERNS ===` セクションに自動注入。

### 品質保証パイプライン

1. **ストリーム浄化** (`speech_sanitizer.py`) — 内部タグ・プロンプト露出を除去
2. **不可侵ルール** — NG 表現を検知
3. **身体憲章チェック** — 記憶主張・依存誘導等の違反を検出
4. **ガードレール** (`guardrail.py`) — 根拠なし主張・矛盾・停滞等をチェック
5. **レビューウィンドウ** (`review_window.py`) — 敏感な出力は Origin の事前承認が必要

### Voice Mode パイプライン

```
ブラウザ(マイク) → WebSocket → ffmpeg変換 → Faster-Whisper(STT)
    → LLMエージェント → VOICEVOX(TTS) → ブラウザ(スピーカー)
```

- VAD: @ricky0123/vad-web (Silero VAD, ブラウザ側)
- Barge-in: TTS再生中に割り込み可能
- ハイブリッド構成: vad-web=検出のみ、MediaRecorder=webm/opus送信

### ゲーム自律プレイ

ニアが **Minecraft** と **任意のゲーム（画面キャプチャベース）** を自律的にプレイするシステム。`GameProfile` ABC を介して共通の Perceive-Think-Act-Reflect ループで動作します。

#### Minecraft（Voyager-Style Dynamic Skill Agent）

```
┌───────────────────────────────────────────────────┐
│  NiaGameLoop (minecraft/game_loop.py)              │
│  ┌──────────┐   ┌──────────┐   ┌───────────────┐ │
│  │ Perceive │ → │  Think   │ → │     Act       │ │
│  │ゲーム状態 │   │LLM判断   │   │スキル実行     │ │
│  │取得      │   │次の行動   │   │or コード生成  │ │
│  └──────────┘   └──────────┘   └───────────────┘ │
│       ↑                               │          │
│       └─────── Reflect (結果記録) ─────┘          │
└───────────────────────────────────────────────────┘
         ↕ 会話                    ↕ HTTP
┌──────────────┐          ┌──────────────────────┐
│ フロントエンド │          │  minecraft-bot       │
│ (チャット)    │          │  (Mineflayer Node.js)│
└──────────────┘          └──────────────────────┘
```

| コンポーネント | ファイル | 役割 |
|:---|:---|:---|
| **Brain** | `game_loop.py` | 自律ループ。LLM で次の行動を決定（`<SKILL>`, `<CODE>`, `<CHAT>`, `<IDLE>`） |
| **Skills** | `skill_library.py`, `skill_retrieval.py` | スキル CRUD + ベクトル検索。成功コードを自動保存・再利用 |
| **Execution** | `execution_engine.py`, `critique_generator.py` | 実行 + 自己修正ループ（失敗 → LLM 分析 → コード修正 → リトライ max 3） |
| **Memory** | `failure_memory.py`, `context_builder.py` | 過去の失敗パターン検索。同じミスを繰り返さない |
| **Goals** | `goal_manager.py` | ニア自身の目標 + ユーザー提案を統合管理 |
| **Sandbox** | `minecraft-bot/src/sandbox.js` | Node.js vm でコードを安全実行。require/process/fs は遮断 |

#### 汎用ゲーム操作（Screen Adapter）

Minecraft 以外の任意のゲームを **画面キャプチャ → Gemini Flash Vision → pydirectinput** で操作。

```
┌───────────────────────────────────────────────────────┐
│  GenericGameLoop (gaming/game_loop.py)                  │
│  ┌──────────────┐  ┌──────────┐  ┌─────────────────┐ │
│  │  Perceive    │→ │  Think   │→ │      Act        │ │
│  │ mss キャプチャ│  │Brain LLM │  │ pydirectinput   │ │
│  │→ Gemini Flash│  │次の行動   │  │ キー/マウス操作  │ │
│  └──────────────┘  └──────────┘  └─────────────────┘ │
│        ↑                               │              │
│        └──────── Reflect (結果記録) ────┘              │
└───────────────────────────────────────────────────────┘
```

| コンポーネント | ファイル | 役割 |
|:---|:---|:---|
| **ScreenCapture** | `gaming/screen_capture.py` | mss で画面キャプチャ → JPEG → base64 |
| **Brain** | `gaming/brain.py` | `<THINK>`, `<ACTION>`, `<CHAT>`, `<IDLE>` ベースの意思決定 |
| **InputController** | `gaming/input_controller.py` | アクション名 → pydirectinput 操作に変換 |
| **ScreenGameProfile** | `gaming/screen_profile.py` | GameProfile 実装。フレームバッファで時間推移を保持 |
| **GameConfigs** | `gaming/game_configs.py` | ゲームごとのプリセット設定（アクションマッピング等） |

### 外部検索（External Data）

ニアが外部情報を取得する仕組み。設計思想として**安易な検索を防ぐ厳格なゲーティング**を採用しつつ、ユーザーが明示的に依頼した場合は確実に応答します。

| モード | トリガー | ゲーティング |
|:---|:---|:---|
| **自動検索** | LLM が「情報が不足している」と判断 | Depth >= 1、surprise >= 0.5、LanguageGate（LLM判定）、confidence >= 0.65 |
| **ユーザー明示検索** | 「ググって」「ネットで調べて」「WEB検索」等のキーワード | ゲートをバイパス（force_fetch）。confidence 閾値を 0.3 に緩和 |

プロバイダ: Google Custom Search API + Wikipedia API（DuckDuckGo は中国語表示問題のため除外）

パイプライン: `候補抽出 → ThinkingProcess → LanguageGate → ExternalDataBroker.fetch() → 結果統合`

### X (Twitter) 投稿

ニアが X にツイートを投稿する機能。全ツイートは **Origin（ユーザー）の事前承認が必須**。

| モード | トリガー | フロー |
|:---|:---|:---|
| **手動** | チャットで「呟いて」「ツイートして」等 | LLM がツイート生成 → Phase 5 ActionPanel で承認 → X API v2 で投稿 |
| **自律** | Autonomous Reflection の daily_log 完了後 | 日記風ツイート生成 → `telemetry_kv` に提案保存 → フロントエンドでポーリング → 承認/却下 |

- スタイル: `casual`（つぶやき風）/ `diary`（日記風）
- 安全対策: LLM プロンプトに個人情報制限、URL 除去、文字数制限 (280文字)
- 履歴: `memory_events` に `tweet_posted` イベントとして記録

### Live2D アバター

VRM に加え、Live2D モデルでニアを表示可能。Settings UI でレンダラーを切り替え。

- **SDK**: `@naari3/pixi-live2d-display` v1.2.5 + PixiJS v8
- **コンポーネント**: `frontend/components/Live2DView.tsx`
- **サンプルモデル**: Hiyori（`frontend/public/live2d/hiyori/`）
- **設計思想**: 身体は内部状態の副作用。ランダム演出禁止、状態比例の呼吸のみ

### 動画解析

| モード | 説明 |
|:---|:---|
| **学習 (learn)** | ゲームプレイ動画 → ffmpeg フレーム抽出 → Qwen3-VL 解析 → LLM 戦略抽出 → セマンティック記憶に保存 |
| **リアクション (react)** | 動画を送ると場面を認識して感想を返す |

パイプライン: `ffmpeg (フレーム抽出)` → `Qwen3-VL (並列 Vision 解析)` → `LLM (戦略要約)`

入力ソース: ファイルアップロード or **YouTube 等の URL** (`yt-dlp` で自動ダウンロード、上限10分・720p)

---

## プロジェクト構成

```
AI_Buddy/
├── backend/
│   ├── core/
│   │   ├── agent_graph/
│   │   │   ├── graph.py           # LangGraph ワークフロー定義
│   │   │   ├── state.py           # AgentState TypedDict
│   │   │   ├── review_window.py   # レビューウィンドウ管理
│   │   │   └── nodes/             # ノード実装（パッケージ）
│   │   │       ├── routing.py     # safety / dissonance / depth_selector
│   │   │       ├── depth_nodes.py # depth0 / depth1 / depth2
│   │   │       ├── merge.py       # merge_output
│   │   │       └── actions.py     # action_processing / s5_commit
│   │   ├── confidence/
│   │   │   └── metrics.py         # 確信度エンジン (5メトリクス)
│   │   ├── constants/
│   │   │   ├── nia_spine_v10.py   # Spine（全レイヤー共通の基本指示）
│   │   │   ├── depth0_prompt_v11.py  # Depth0 プロンプト (実使用版)
│   │   │   └── depth1_prompt_v11.py  # Depth1 プロンプト (実使用版)
│   │   ├── agent.py               # Agent ラッパー (SSE ストリーミング)
│   │   └── config.py              # Settings クラス (.env → Pydantic)
│   ├── services/
│   │   ├── memory/
│   │   │   ├── memory_service.py      # 記憶CRUD
│   │   │   ├── context_builder.py     # Depth別メモリコンテキスト生成 (PINNED/PATTERNS/WORKING/MEMORY)
│   │   │   ├── commit_executor.py     # S5 Commit 実行
│   │   │   ├── semantic_store.py      # Semantic記憶 CRUD
│   │   │   ├── working_store.py       # Working記憶 CRUD
│   │   │   ├── guardrail.py           # ガードレール (6条件)
│   │   │   └── vector_sync.py         # ChromaDB 同期
│   │   ├── minecraft/
│   │   │   ├── game_loop.py           # 自律ゲームループ
│   │   │   ├── skill_library.py       # スキル CRUD (SQLite)
│   │   │   ├── skill_executor.py      # Bot へのスキル/コード実行指示
│   │   │   ├── skill_retrieval.py     # ベクトル検索でスキル発見
│   │   │   ├── execution_engine.py    # 実行 + 自己修正ループ
│   │   │   ├── critique_generator.py  # LLM 失敗分析
│   │   │   ├── failure_memory.py      # 過去の失敗パターン検索
│   │   │   ├── goal_manager.py        # 目標管理
│   │   │   ├── video_learner.py       # 動画から戦略抽出
│   │   │   └── state_manager.py       # ゲーム状態管理
│   │   ├── gaming/                    # 汎用ゲーム操作 (Screen Adapter)
│   │   │   ├── screen_capture.py      # mss 画面キャプチャ
│   │   │   ├── brain.py              # ゲーム意思決定 (LLM)
│   │   │   ├── game_loop.py          # GenericGameLoop (Perceive-Think-Act-Reflect)
│   │   │   ├── input_controller.py   # pydirectinput 入力制御
│   │   │   ├── screen_profile.py     # ScreenGameProfile (GameProfile 実装)
│   │   │   └── game_configs.py       # ゲーム設定プリセット
│   │   ├── twitter_client.py      # X (Twitter) 投稿クライアント
│   │   ├── video_analyzer.py      # 汎用動画解析 (ffmpeg + Vision)
│   │   ├── agent_orchestrator.py  # SSE オーケストレーター
│   │   ├── reflection_engine.py   # Autonomous Reflection (R.2 + R.4)
│   │   ├── idle_detector.py       # アイドル検出 (R.1)
│   │   ├── stt_service.py         # Faster-Whisper STT
│   │   ├── voicevox_client.py     # VOICEVOX TTS クライアント
│   │   ├── vision_client.py       # 画像認識 (LM Studio / Gemini Flash)
│   │   ├── speech_sanitizer.py    # 出力浄化
│   │   ├── retention_sweeper.py   # 記憶の半減期・忘却
│   │   ├── external_data.py       # 外部データ取得
│   │   └── public_status.py       # 公開ステータス管理
│   ├── controllers/
│   │   ├── api/
│   │   │   ├── stream_router.py   # SSE チャットストリーム + 履歴API
│   │   │   ├── voice_router.py    # WebSocket 音声入出力
│   │   │   ├── tts_router.py      # TTS エンドポイント
│   │   │   ├── review_router.py   # Approve/Reject API
│   │   │   ├── system_router.py   # Sleep/Reflect 管理API
│   │   │   ├── game_router.py     # ゲーム操作API (Minecraft + Screen)
│   │   │   └── video_router.py    # 動画解析API
│   │   └── stats/
│   │       └── observation_router.py  # 観測・統計エンドポイント
│   ├── scripts/
│   │   ├── sleep_cycle.py         # Sleep Cycle (日次バッチ処理)
│   │   ├── backfill_semantic.py   # Semantic バックフィル
│   │   └── observation_report.py  # 観測レポート生成
│   └── server.py                  # FastAPI エントリポイント
├── minecraft-bot/                     # Mineflayer Bot (Node.js)
│   ├── src/
│   │   ├── index.js               # Bot エントリポイント
│   │   ├── sandbox.js             # vm サンドボックス (安全な JS 実行)
│   │   ├── skill_manager.js       # スキルファイル管理
│   │   └── http.js                # HTTP API サーバー
│   └── skills/                    # 保存されたスキルファイル (.js)
├── frontend/
│   ├── app/
│   │   └── page.tsx               # メインページ
│   ├── components/
│   │   ├── ChatInterface.tsx      # チャット統合コンポーネント
│   │   ├── chat/
│   │   │   ├── ChatMessages.tsx   # メッセージ表示
│   │   │   └── ChatInput.tsx      # 入力フォーム (テキスト・画像・音声)
│   │   ├── GamePanel.tsx          # Minecraft ゲームパネル
│   │   ├── VideoPanel.tsx         # 動画解析パネル
│   │   ├── LivestreamDashboard.tsx # ダッシュボード
│   │   ├── MemoryGraph.tsx        # 記憶グラフ可視化 (Barnes-Hut)
│   │   ├── StatsPanel.tsx         # 統計パネル
│   │   ├── ActionPanel.tsx        # アクションパネル
│   │   └── ObservationReport.tsx  # 観測レポート表示
│   └── lib/
│       └── apiClient.ts           # 統合 API クライアント
├── data/                          # SQLite DB, チェックポイント
├── identity.md                    # ニアの人格定義 (ランタイムで読み込み)
├── tests/                         # pytest テストスイート (630+)
├── docs/
│   └── memory_redesign_v2.md      # Memory Redesign v2 設計ドキュメント
└── ABOUT_NIA.md                   # ニアの一般紹介ドキュメント
```

---

## セットアップ

### 前提条件

- Python 3.12+
- Node.js 18+
- LM Studio（ローカルLLM実行環境）
- VOICEVOX（音声合成、オプション）

### インストール

```bash
# リポジトリのクローン
git clone <repository-url>
cd AI_Buddy

# バックエンド
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux
pip install -r requirements.txt

# フロントエンド
cd frontend
npm install
cd ..
```

### 環境変数

`.env` ファイルをプロジェクトルートに作成:

```env
# LLM (OpenAI互換API)
OPENAI_BASE_URL=http://localhost:1234/v1
OPENAI_API_KEY=lm-studio
OPENAI_MODEL=openai/gpt-oss-20b

# Vision (画像認識)
VISION_PROVIDER=lmstudio
VISION_MODEL=qwen/qwen3-vl-4b

# VOICEVOX (TTS)
VOICEVOX_URL=http://localhost:50021
VOICEVOX_SPEAKER_ID=46

# STT (音声認識)
STT_MODEL_SIZE=small
STT_LANGUAGE=ja

# Memory
ORCHESTRATOR_S5_ENABLED=True

# Minecraft
MINECRAFT_BOT_URL=http://localhost:3001
MINECRAFT_ENABLED=True
GAME_LOOP_ENABLED=False
GAME_LOOP_INTERVAL_SEC=15

# 外部検索
EXTERNAL_DATA_ENABLED=True
EXTERNAL_SEARCH_PROVIDER=auto
GOOGLE_API_KEY=<your-google-api-key>
GOOGLE_CSE_ID=<your-custom-search-engine-id>

# 動画解析
VIDEO_LEARNING_ENABLED=True
VIDEO_FRAME_INTERVAL_SEC=5
VIDEO_MAX_FRAMES=20

# 汎用ゲーム操作 (Screen Adapter)
SCREEN_GAME_ENABLED=False
GAME_VISION_PROVIDER=gemini
GEMINI_MODEL=gemini-2.0-flash-lite
SCREEN_CAPTURE_REGION=              # "x,y,w,h" or 空=全画面
SCREEN_GAME_LOOP_INTERVAL_SEC=3

# X (Twitter)
TWITTER_ENABLED=False
TWITTER_API_KEY=<your-api-key>
TWITTER_API_SECRET=<your-api-secret>
TWITTER_ACCESS_TOKEN=<your-access-token>
TWITTER_ACCESS_TOKEN_SECRET=<your-access-token-secret>

# ログ
LOG_LEVEL=INFO
```

全設定項目は [backend/core/config.py](backend/core/config.py) の `Settings` クラスを参照。

### 起動

```bash
# バックエンド (port 8000)
python -m backend.server

# フロントエンド (port 3000)
cd frontend && npm run dev
```

ブラウザで `http://localhost:3000` にアクセス。

---

## API エンドポイント

### チャット

| メソッド | パス | 説明 |
|:---|:---|:---|
| POST | `/api/chat` | SSE ストリーミングチャット |
| GET | `/api/chat/history/{thread_id}` | 会話履歴取得 |

### 音声

| メソッド | パス | 説明 |
|:---|:---|:---|
| WebSocket | `/api/voice/ws` | 音声入出力 (STT + TTS) |
| POST | `/api/tts/speak` | テキスト → 音声変換 |

### レビュー

| メソッド | パス | 説明 |
|:---|:---|:---|
| POST | `/api/review/approve` | 保留中の出力を承認 |
| POST | `/api/review/reject` | 保留中の出力を拒否 |

### ゲーム

| メソッド | パス | 説明 |
|:---|:---|:---|
| GET | `/api/game/state` | ゲーム状態取得 (Minecraft) |
| GET | `/api/game/status` | Bot 接続状態 (Minecraft) |
| POST | `/api/game/action` | ゲーム内アクション実行 (Minecraft) |
| POST | `/api/game/connect` | Minecraft サーバーに接続 |
| WebSocket | `/api/game/ws` | ゲームイベントストリーム (Minecraft) |
| POST | `/api/game/screen/start` | 画面キャプチャゲーム開始 |
| POST | `/api/game/screen/stop` | 画面キャプチャゲーム停止 |
| GET | `/api/game/screen/status` | Screen ゲームステータス |
| GET | `/api/game/profiles` | 登録済みゲームプロファイル一覧 |
| POST | `/api/game/profiles/switch` | アクティブプロファイル切り替え |
| GET | `/api/game/configs` | 利用可能なゲーム設定一覧 |

### X (Twitter)

| メソッド | パス | 説明 |
|:---|:---|:---|
| POST | `/api/actions/tweet/generate` | ツイート生成（投稿はしない） |
| POST | `/api/actions/tweet/approve` | ツイート承認＋投稿 |
| POST | `/api/actions/tweet/reject` | ツイート提案を却下 |
| GET | `/api/actions/tweet/pending` | 自律提案のポーリング |
| GET | `/api/actions/tweet/history` | 投稿済みツイート履歴 |

### 動画

| メソッド | パス | 説明 |
|:---|:---|:---|
| POST | `/api/video/analyze` | 動画アップロード＋解析 (learn / react モード) |
| POST | `/api/video/analyze_url` | URL (YouTube等) から動画をDL＋解析 |
| GET | `/api/video/status` | 動画解析機能の設定状態 |

### 管理

| メソッド | パス | 説明 |
|:---|:---|:---|
| GET | `/health` | ヘルスチェック |
| POST | `/system/sleep` | Sleep Cycle 手動実行 |
| GET | `/api/stats/observations` | 観測データ取得 |

---

## テスト

```bash
# 全テスト実行
python -m pytest

# 特定テスト
python -m pytest tests/test_depth_selector.py -v
python -m pytest tests/test_s5_commit.py -v
python -m pytest tests/test_context_builder.py -v

# E2E テスト (サーバー起動が必要)
$env:E2E_BASE_URL="http://127.0.0.1:8000"
python -m pytest -q -m e2e
```

現在のテストスイート: **630+ テスト**

---

## Sleep Cycle

日次の記憶整理・Identity更新バッチ。手動実行:

```bash
python -m backend.scripts.sleep_cycle
```

実行内容:
1. **Memory Block 構築** — Autonomous Reflection の日次ログを優先利用（フォールバック: `memory_events`）
2. **印象記録** — 今日の対話で印象的だった内容を記録
3. **セマンティック抽出** — エピソディック記憶からパターン・事実を LLM バッチ抽出（日次ログがある場合はスキップ）
4. **Identity 提案** — 人格の変化を提案 (Origin の承認が必要)
5. **忘却** — status 別半減期による retention 減衰
6. **Episodic 圧縮** — 古い episodic を日単位でサマリー化

出力先: `sleep_outputs/`

---

## 主要な設計判断

- **Depth0/1/2 に会話履歴を注入**: Depth0 は直近3ターン、Depth1/2 は直近5ターンの会話履歴を含む
- **TONE_ANCHOR をシステムプロンプト末尾に配置**: LLM は最後に読んだ指示に最も影響を受けるため、口調指定は末尾に置く
- **S5 Commit でエピソディック記憶のみ保存**: Semantic 生成は Sleep Cycle に移行 (LLM バッチ抽出)
- **Context Builder は Depth 別にメモリ注入量を制御**: Depth0 は PINNED FACTS のみ、Depth1/2 は PINNED FACTS + PATTERNS + WORKING + Short/Long Term
- **Autonomous Reflection (R.1-R.4)**: 対話がない時間に自発的に記憶を振り返り、日横断パターンを semantic_memories に `state_tag='insight'` で保存。PATTERNS セクションとして会話に自動反映
- **Sleep Cycle R.3 連携**: daily_reflections がある場合は memory_block として優先利用し、semantic extraction をスキップ（二重抽出防止）
- **Depth2 ゲート**: 累計100ターン以上 + confidence >= 0.85 + context_coverage >= 0.7 で発動
- **Minecraft vm サンドボックス**: LLM 生成コードは Node.js vm で実行。require/process/fs は注入せず安全に遮断
- **スキルのハイブリッド保存**: Bot 側に .js ファイル（実行用）、Python 側に SQLite（検索用）
- **自己修正ループ**: 失敗時は LLM が原因分析 → コード修正 → リトライ（最大3回）。3回失敗でギブアップ
- **動画学習**: フレーム抽出は ffmpeg、場面認識は既存 Vision 基盤 (Qwen3-VL) を再利用
- **外部検索の二重ゲート**: 自動検索は厳格なゲーティング（Depth/surprise/LanguageGate/confidence）で安易な外部依存を防止。ユーザー明示の検索トリガー（「ググって」等）は force_fetch でゲートをバイパス
- **Spine v1.3**: 「検索できないとは言わない」指示を追加。LLM が検索手段を持つにもかかわらず「調べられません」と嘘をつくことを防止
- **GameProfile ABC による抽象化**: Minecraft (API) と Screen Adapter (画面キャプチャ) を同一インターフェースで統一。Agent Graph の routing.py は Registry 経由で任意のゲームにアクセス
- **Gemini Flash は Vision 専用**: ゲーム画面分析に Gemini Flash を使用。メイン LLM (LM Studio) とは独立し、`provider` パラメータで per-call 切り替え
- **X 投稿は全件承認制**: 手動・自律問わず全ツイートは Origin の事前承認が必須。Phase 5 Action システムと `telemetry_kv` ベースの提案キューを併用
- **Live2D Presence 思想**: 身体は内部状態の副作用。ランダム演出（Idle ループ）を廃止し、状態比例の呼吸のみ

---

## ライセンス

個人プロジェクト。商用利用・再配布については作者に問い合わせてください。
