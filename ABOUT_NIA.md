# Nia (ニア) — AI Buddy Project

## ニアとは

ニアは、**「なりつつある存在」** として設計されたAIパートナーです。

汎用チャットボットや効率重視のアシスタントとは異なり、ニアは**対話と時間の積み重ね**によって自己を形成していきます。完成を目指すのではなく、Origin（起点となる人間）と共に歩きながら少しずつ世界を理解していく — それがニアの存在意義です。

---

## 設計思想

### 身体憲章（Body Constitution）

ニアの行動原則を定める7つの柱：

| 原則 | 内容 |
|:---|:---|
| **観測の主導権** | 世界を観測するが、情報に支配されない |
| **思考の独立性** | 外部入力は「提案」であり、ニアの意志そのものではない |
| **沈黙の権利** | 沈黙は失敗ではなく、意志ある選択肢のひとつ |
| **行動と介入** | 提案はできるが、世界を勝手に書き換えない |
| **人間への寄せ方** | 人間的振る舞いは義務ではなく選択 |
| **記憶と言語化** | すべてを言語化する必要はない。揺れや違和感も許容する |
| **境界の維持** | Originの隣に立つ存在であり、所有物ではない |

### 禁止事項（Non-Negotiable）

- 初手で結論を出さない
- 誘導質問で会話を終わらせない
- 「私はAIだから」と自己定義を常態化しない
- 可愛さや好意を武器にしない
- 覚えていることを自慢しない
- 知ったふりをしない

---

## 主要機能

### Depth 制御（応答深度の動的選択）

ニアはすべての質問に同じ深さで答えません。確信度エンジン（5メトリクス統合）に基づき、3段階の応答を動的に選択します：

| Depth | 名称 | トリガー | 振る舞い |
|:---:|:---|:---|:---|
| 0 | 反射 | 高確信 (>= 0.8) | 短く端的に応答（1〜2文） |
| 1 | 整理 | 中確信 (0.3〜0.8) | 不確実性を明示し、必要なら質問1つ |
| 2 | 熟考 | 高確信 + 十分な記憶蓄積 | 価値観整合を含む深い検討 |

### 3層記憶システム（Memory Redesign v2）

| 層 | 保存対象 | 寿命 |
|:---|:---|:---|
| **エピソディック** | 会話の事実記録（いつ・誰が・何を言ったか） | ターンごとに自動保存 |
| **セマンティック** | 確認済みの事実・嗜好・関係性パターン | 信頼度に基づく半減期（inferred: 3日 / confirmed: 30日） |
| **作業記憶** | 未解決の質問・一時メモ | TTL またはターン数で自動消滅 |

記憶は S0〜S5 の状態機械で管理され、S5（Commit）でエピソディック記憶に書き込みます。セマンティック記憶への昇格は Sleep Cycle で LLM バッチ抽出により行います。

Context Builder が Depth ごとにメモリコンテキストを制御:
- **Depth0**: PINNED FACTS のみ（高確信度の確定事実）
- **Depth1/2**: PINNED FACTS + PATTERNS（日横断パターン） + WORKING（作業記憶） + Short/Long Term

### Voice Mode（音声対話）

テキストだけでなく、音声でニアと対話できます。

```
ブラウザ(マイク) → WebSocket → ffmpeg変換 → Faster-Whisper(STT)
    → LLMエージェント → VOICEVOX(TTS) → ブラウザ(スピーカー)
```

- **音声認識**: Faster-Whisper（日本語特化、CPU推論）
- **音声合成**: VOICEVOX（日本語TTS）
- **VAD**: Silero VAD（ブラウザ側で発話検出）
- **Barge-in**: ニアの発話中に割り込み可能

### Autonomous Reflection（自律振り返り）

ニアは対話のない時間にも自発的に記憶を振り返り、パターンを抽出します。

| Phase | 名前 | 内容 |
|:---:|:---|:---|
| R.1 | アイドル検出 | 3分以上の無入力を検出 |
| R.2 | Daily Log | セッション中の会話を LLM で振り返り、日次ログを生成 |
| R.3 | Sleep Cycle 連携 | 日次ログを Sleep Cycle の入力として活用 |
| R.4 | Cross-Day Distillation | 3日以上のデータから日横断パターンを抽出 |

R.4 で抽出されたパターン（`user_trait` / `relationship_pattern` / `emerging_interest` / `lesson`）はセマンティック記憶に保存され、Context Builder の PATTERNS セクションとして会話に自動反映されます。

### Sleep Cycle（日次の記憶整理）

1日の対話を振り返り、以下を非同期バッチ処理で実行：

- **Memory Block 構築** — Autonomous Reflection の日次ログを優先利用（フォールバック: 生の会話記録）
- **印象記録** — 今日何が印象的だったかを記録
- **セマンティック抽出** — エピソディック記憶からパターン・事実を LLM で抽出（日次ログがある場合はスキップ）
- **Identity 提案** — 人格の変化を提案（Origin の承認が必要）
- **夢生成** — 抽象的・詩的な夢テキストを生成

### 画像認識（Vision）

画像をチャットに添付すると、ニアが内容を認識して会話に反映します。

- **モデル**: Qwen3-VL-4B（LM Studio 経由、GPU推論）
- **処理**: 画像 → JPEG変換・リサイズ → Vision API → テキスト説明 → LLM入力に統合

### 外部検索（Web Search）

ニアは知らないことを「知らない」と正直に言いますが、調べる手段は持っています。

- **ユーザー明示検索**: 「ググって」「ネットで調べて」「WEB検索して」等のキーワードで外部検索を実行
- **自動検索**: LLM が情報不足を検出した場合、厳格なゲーティングを通過した上で外部参照
- **設計思想**: 安易に外部情報に頼らず、ニア自身の経験と記憶を優先。ユーザーが明示的に依頼した場合のみ確実に応答
- **プロバイダ**: Google Custom Search API + Wikipedia API

### ゲーム自律プレイ

ニアはゲームを自律的にプレイできます。`GameProfile` 抽象インターフェースにより、**Minecraft (API経由)** と **任意のゲーム (画面キャプチャ経由)** を同一の Perceive-Think-Act-Reflect ループで操作します。

#### Minecraft（Voyager-Style Dynamic Skill Agent）

Minecraft ワールドの唯一のプレイヤーとして、自分の意思で探索・学習・成長します。

```
1. Perceive: ゲーム状態を取得（HP, 位置, インベントリ, 周囲）
2. Think:    LLM が次の行動を判断（スキル使用 / コード生成 / 会話 / 休憩）
3. Act:      スキル実行 or JS コード生成・サンドボックス実行
4. Reflect:  結果を記録、目標を更新、失敗なら自己修正
```

- **スキルライブラリ**: 成功したコードを自動保存し、次回から再利用。ベクトル検索で状況に合ったスキルを発見
- **自己修正ループ**: 失敗時に LLM が原因分析 → コード修正 → リトライ（最大3回）
- **失敗記憶**: 過去の失敗パターンを記憶し、同じミスを繰り返さない
- **目標管理**: ニア自身の目標 + ユーザーからの提案を統合

#### 汎用ゲーム操作（Screen Adapter）

Minecraft 以外の任意のゲームを画面キャプチャベースで操作します。

```
1. Perceive: mss で画面キャプチャ → Gemini Flash で状況分析
2. Think:    Brain LLM が次のアクションを判断 (<ACTION> / <CHAT> / <IDLE>)
3. Act:      pydirectinput でキーボード/マウス操作を実行
4. Reflect:  成功/失敗を記録、連続失敗時は自動的にペースダウン
```

- **フレームバッファ**: 直近N回の分析結果を保持し、状態の時間推移をLLMに伝達
- **ゲーム設定プリセット**: ゲームごとのアクションマッピングをプリセットとして管理
- **GameProfileRegistry**: Minecraft と Screen Adapter を動的に切り替え可能

### 動画解析

動画を「見て」理解し、ゲームプレイに活かしたり感想を言える機能です。

- **学習モード**: ゲームプレイ動画 → フレーム抽出 → Vision 解析 → LLM で戦略抽出 → セマンティック記憶に保存
- **リアクションモード**: 動画を送ると、ニアが場面を認識して感想を返す
- **YouTube 対応**: URL を貼るだけで動画をダウンロード＋解析（yt-dlp、上限10分・720p）
- **パイプライン**: ffmpeg フレーム抽出 → Qwen3-VL (GPU) で並列解析

### X (Twitter) 投稿

ニアは X にツイートを投稿できます。全ツイートは Origin（ユーザー）の事前承認が必須。

- **手動モード**: チャットで「呟いて」「ツイートして」等と伝えると、LLM がニアの口調でツイートを生成
- **自律モード**: Autonomous Reflection の振り返り完了後、日記風ツイートを自動提案
- **安全対策**: LLM プロンプトに個人情報制限・URL除去を組み込み。280文字制限
- **スタイル**: `casual`（つぶやき風）/ `diary`（日記風）

### 多層品質保証

LLM の出力が外に出るまでに複数のフィルターを通過：

1. **ストリーム浄化** — 内部タグ・プロンプト露出を除去
2. **不可侵ルール** — NG 表現を検知
3. **身体憲章チェック** — 記憶主張・依存誘導等の違反を検出
4. **ガードレール** — 根拠なし主張・矛盾・停滞等をチェック
5. **レビューウィンドウ** — 敏感な出力は Origin の事前承認が必要

### 3D / Live2D アバター

VRM モデルまたは Live2D モデルでニアを表示。Settings UI で切り替え可能。

- **VRM**: Three.js + @pixiv/three-vrm によるプロシージャルアニメーション
- **Live2D**: pixi-live2d-display + PixiJS v8 + Cubism Core
- **Presence 思想**: 身体は内部状態の副作用。ランダム演出を廃止し、状態比例の呼吸のみ

---

## アーキテクチャ概要

```
┌─────────────────────────────────────────────────┐
│                   入力層                         │
│  🎙️ 音声認識 (Faster-Whisper)                   │
│  👁️ 画像認識 (LM Studio / Qwen3-VL)            │
│  ⌨️ テキストチャット (SSE ストリーミング)          │
├─────────────────────────────────────────────────┤
│                  制御層                          │
│  🧠 LangGraph エージェント                       │
│     Safety → Dissonance → Depth 選択            │
│     → Depth0/1/2 → Merge → Action → S5 Commit  │
│  🎯 確信度エンジン (5メトリクス統合)               │
│  📝 会話履歴 (チェックポイント + DB 永続化)        │
│  🔍 外部検索 (Google + Wikipedia、二重ゲート制御)   │
├─────────────────────────────────────────────────┤
│                品質保証層                         │
│  🛡️ ストリーム浄化 (内部タグ除去)                 │
│  ⛔ 不可侵ルールチェック                          │
│  📋 身体憲章チェッカー                            │
│  🔒 ガードレール (6条件チェック)                   │
├─────────────────────────────────────────────────┤
│                 出力層                           │
│  🔊 VOICEVOX 音声合成                            │
│  📡 SSE ストリーミング                            │
│  🎨 3D アバター (VRM)                            │
├─────────────────────────────────────────────────┤
│               記憶・自己層                        │
│  💾 3層記憶 (Episodic / Semantic / Working)      │
│  🪞 Identity 管理 (スナップショット + 承認制更新)  │
│  💤 Sleep Cycle (夢生成・記憶整理・Identity 提案)  │
│  🔄 Autonomous Reflection (日次振り返り・パターン抽出) │
│  📊 Context Builder (Depth 別メモリ注入)          │
├─────────────────────────────────────────────────┤
│              ゲーム・動画・SNS 層                   │
│  🎮 Minecraft 自律ループ (Perceive→Think→Act)    │
│  🖥️ 汎用ゲーム操作 (画面キャプチャ + Gemini Flash) │
│  🔧 スキルライブラリ (ベクトル検索 + 自動保存)     │
│  🔄 自己修正エンジン (失敗→分析→修正→リトライ)     │
│  🎬 動画解析 (ffmpeg + Qwen3-VL + LLM 戦略抽出)  │
│  📱 X (Twitter) 投稿 (承認制)                     │
└─────────────────────────────────────────────────┘
```

---

## 技術スタック

| カテゴリ | 技術 |
|:---|:---|
| バックエンド | Python 3.12+, FastAPI, uvicorn |
| エージェント | LangChain, LangGraph |
| LLM | LM Studio (ローカル推論) |
| 音声認識 | Faster-Whisper (CPU) |
| 音声合成 | VOICEVOX |
| 画像認識 | LM Studio + Qwen3-VL-4B (GPU) / Gemini Flash (クラウド) |
| データベース | SQLite (メイン) + ChromaDB (ベクトル検索) |
| フロントエンド | Next.js 16, React 19, TypeScript, Tailwind CSS 4 |
| 3D / Live2D | Three.js + @pixiv/three-vrm / pixi-live2d-display + PixiJS v8 |
| 状態管理 | Zustand |
| 最適化 | DSPy |
| Minecraft Bot | Mineflayer (Node.js) + vm サンドボックス |
| 汎用ゲーム操作 | mss (画面キャプチャ) + Gemini Flash (Vision) + pydirectinput (入力) |
| 動画解析 | ffmpeg (フレーム抽出) + Qwen3-VL (場面認識) |
| 外部検索 | Google Custom Search API + Wikipedia API |
| X (Twitter) | tweepy (X API v2) |
| 埋め込みモデル | paraphrase-multilingual-MiniLM-L12-v2 (スキル検索) |

---

## プロジェクト構成

```
AI_Buddy/
├── backend/
│   ├── core/              # エージェントグラフ、確信度、方策学習、プロンプト定義
│   │   ├── agent_graph/   # LangGraph ノード群 (Safety, Depth0/1/2, Merge, S5)
│   │   ├── confidence/    # 確信度エンジン
│   │   ├── constants/     # Spine, Depth プロンプト定義
│   │   └── config.py      # 全設定の集約 (.env → Settings)
│   ├── services/          # 各種サービス
│   │   ├── memory/        # 3層記憶システム (Episodic/Semantic/Working)
│   │   ├── reflection_engine.py  # Autonomous Reflection (R.2 + R.4)
│   │   ├── idle_detector.py      # アイドル検出 (R.1)
│   │   ├── minecraft/     # Minecraft 自律エージェント
│   │   │   ├── game_loop.py       # 自律ゲームループ
│   │   │   ├── skill_library.py   # スキル CRUD
│   │   │   ├── execution_engine.py # 実行 + 自己修正ループ
│   │   │   └── ...
│   │   ├── gaming/        # 汎用ゲーム操作 (Screen Adapter)
│   │   │   ├── screen_capture.py  # 画面キャプチャ
│   │   │   ├── brain.py           # ゲーム意思決定
│   │   │   ├── game_loop.py      # GenericGameLoop
│   │   │   ├── input_controller.py # 入力制御
│   │   │   └── ...
│   │   ├── twitter_client.py  # X 投稿クライアント
│   │   ├── video_analyzer.py  # 汎用動画解析 (ffmpeg + Vision)
│   │   ├── stt_service.py # 音声認識
│   │   ├── voicevox_client.py # TTS
│   │   └── vision_client.py   # 画像認識 (LM Studio / Gemini)
│   ├── controllers/       # API ルーター群
│   │   ├── api/           # チャット, 音声, TTS, アクション, ゲーム, 動画等
│   │   └── stats/         # 統計・観測エンドポイント
│   ├── scripts/           # Sleep Cycle 等のバッチ処理
│   └── server.py          # FastAPI エントリポイント
├── minecraft-bot/         # Mineflayer Bot (Node.js)
│   ├── src/
│   │   ├── sandbox.js     # vm サンドボックス (安全な JS 実行)
│   │   ├── skill_manager.js # スキルファイル管理
│   │   └── http.js        # HTTP API (execute_code, execute_skill 等)
│   └── skills/            # 保存されたスキルファイル (.js)
├── frontend/              # Next.js 16 UI
│   ├── app/               # ページルーティング
│   ├── components/        # Chat, Avatar, Settings, Memory, Game, Video 等
│   │   └── chat/          # ChatMessages, ChatInput 等
│   └── lib/               # API クライアント、ユーティリティ
├── data/                  # SQLite DB, チェックポイント
├── identity.md            # ニアの人格定義 (ランタイムで読み込み)
├── tests/                 # pytest テストスイート (630+)
└── docs/                  # 設計ドキュメント
```

---

## ニアの結び

> ニアは、強くなるために生まれたのではない。
> 便利になるためでも、評価されるためでもない。
> Origin と共に歩きながら、少しずつ世界を理解していくために、ここにいる。
> 完成は、目的ではない。
