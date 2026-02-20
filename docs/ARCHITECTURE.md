# システムアーキテクチャ

AI VTuber「ニア (Nia)」のシステムアーキテクチャ。

---

## 全体構成

```
┌────────────────────────────────────────────────────────────┐
│                   Frontend (Next.js 14)                     │
│  Chat / Avatar / Memory / Stats / Draw / Game / Video ...  │
└─────────────────────────┬──────────────────────────────────┘
                          │ HTTP / WebSocket / SSE
┌─────────────────────────▼──────────────────────────────────┐
│                   Backend (FastAPI)                          │
│                                                              │
│  ┌─ API Router Layer ─────────────────────────────────────┐ │
│  │ stream / review / actions / voice / identity / game …  │ │
│  └────────────────────────────────────────────────────────┘ │
│                          │                                   │
│  ┌─ Agent Core ──────────▼────────────────────────────────┐ │
│  │  LangGraph Pipeline (9-Node)                           │ │
│  │  Safety → Dissonance → DepthSelector                   │ │
│  │    → [Depth0 | Depth1 | Depth2]                        │ │
│  │    → Merge → ActionProcessing → S5Commit → END         │ │
│  └────────────────────────────────────────────────────────┘ │
│                          │                                   │
│  ┌─ Memory v2 ───────────▼────────────────────────────────┐ │
│  │  Episodic (memory_events) ← source of truth            │ │
│  │  Semantic (semantic_memories) ← Sleep Cycle で生成      │ │
│  │  Working  (working_items) ← ターン中の作業記憶         │ │
│  │  Context Builder → Depth ごとに注入                    │ │
│  └────────────────────────────────────────────────────────┘ │
│                          │                                   │
│  ┌─ Services ────────────▼────────────────────────────────┐ │
│  │  Speech / Vision / Voice(STT+TTS) / Identity …        │ │
│  └────────────────────────────────────────────────────────┘ │
└──────────────┬───────────────────────┬─────────────────────┘
               │                       │
       ┌───────▼────────┐      ┌───────▼────────┐
       │ LM Studio      │      │ VOICEVOX       │
       │ (ローカルLLM)   │      │ (TTS)          │
       └───────┬────────┘      └───────┬────────┘
               │                       │
       ┌───────▼───────────────────────▼────────┐
       │          Storage Layer                  │
       │  SQLite (nia.sqlite3)                   │
       │  ChromaDB (ベクトル検索)                │
       └────────────────────────────────────────┘
```

---

## LangGraph Pipeline（9 ノード）

```
User Input
    │
    ▼
┌──────────┐    blocked
│ Safety   │──────────→ END
└────┬─────┘
     │ safe
     ▼
┌──────────────┐
│ Dissonance   │  違和感スコア算出
└────┬─────────┘
     ▼
┌──────────────┐
│ DepthSelector│  確信度 × コンテキスト → Depth 決定
└──┬───┬───┬───┘
   │   │   │
   ▼   ▼   ▼
 D0   D1   D2      ← 排他的に1つが実行
   │   │   │
   └───┼───┘
       ▼
┌──────────────┐
│ Merge        │  Hold 判定 / WAIT / 通常出力
└────┬─────────┘
     ▼
┌──────────────────┐
│ ActionProcessing │  Phase 5 アクション評価
└────┬─────────────┘
     ▼
┌──────────────┐
│ S5 Commit    │  Episodic 保存 / Working 更新
└────┬─────────┘
     ▼
    END
```

### ノード詳細

| ノード | ファイル | 役割 |
|--------|---------|------|
| **Safety** | `nodes/routing.py` | 有害入力ブロック、新入力で Review Window キャンセル |
| **Dissonance** | `nodes/routing.py` | Identity との矛盾を検出、スコア付与 |
| **DepthSelector** | `nodes/routing.py` | 確信度 + context_coverage で Depth 振り分け |
| **Depth0 (Reflex)** | `nodes/depth_nodes.py` | 即応答。PINNED FACTS のみ参照 |
| **Depth1 (Organize)** | `nodes/depth_nodes.py` | 深い分析。フルメモリコンテキスト参照 |
| **Depth2 (ValueAlign)** | `nodes/depth_nodes.py` | 結論層。Depth2ゲート通過時のみ実行 |
| **Merge** | `nodes/merge.py` | Hold/WAIT 判定、最終テキスト統合 |
| **ActionProcessing** | `nodes/actions.py` | アクション提案をリスク評価 |
| **S5 Commit** | `nodes/actions.py` | Episodic 保存、Working 更新（Memory v2） |

### Depth 優先チェーン

```
high_dissonance (≥ 0.65)  → depth1  [最優先]
confidence-based           → depth0/1/2
user_request               → depth1
depth2 gate (≥100 turns)  → depth2
default                    → depth0
```

---

## Memory v2（3 層構成）

詳細: [memory_redesign_v2.md](memory_redesign_v2.md)

### 層構成

| 層 | テーブル | 書き込みタイミング | 役割 |
|----|---------|-------------------|------|
| **Episodic** | `memory_events` | S5 Commit（毎ターン末尾） | append-only の生ログ |
| **Semantic** | `semantic_memories` | Sleep Cycle（日次バッチ） | 事実・価値観の抽出 |
| **Working** | `working_items` | S5 Commit | ターン中の作業記憶 |

### 状態機械 (S0 → S5)

```
S0: Idle
S1: ルールベース判定（LLM 不要）
S2: Dissonance スコアリング
S3: Depth ノードで LLM 呼び出し
S4: Merge / Action 処理
S5: Commit（episodic 保存 + working 更新）
```

### Context Builder

- `backend/services/memory/context_builder.py`
- Depth0: PINNED FACTS のみ（confirmed semantic）
- Depth1/2: フルメモリコンテキスト（PINNED FACTS + PATTERNS + WORKING + Short/Long Term）

#### コンテキストセクション

| セクション | 内容 | 表示条件 |
|-----------|------|---------|
| **PINNED FACTS** | confirmed かつ高 confidence の semantic | confidence ≥ 0.7 |
| **PATTERNS** | 日横断パターン（`state_tag='insight'`） | R.4 で生成された insight |
| **WORKING** | 未解決の working items | open 状態の items |
| **Short Term** | 直近のやり取り | 短期記憶あり時 |
| **Long Term** | semantic memories（query-aware retrieval） | semantic あり時 |

### Semantic 生成

- Sleep Cycle で1日分の episodic を LLM に渡し、バッチ抽出
- ステータス: `inferred` → `confirmed` / `revoked`（24h 後に確定）
- 忘却: status 別半減期（inferred: 3日、confirmed: 30日）

---

## Review Window（Phase 2）

```
敏感な内容を Merge が検出
    │
    ▼
hold_required = True → SSE: hold_request {preview, token}
    │
    ├─ Approve → identity.md に適用 → 出力続行
    └─ Reject  → "WAIT" で終了
    │
新しいユーザー入力 → cancel_review_on_new_input()
```

定数: `D_LOW=0.30`, `D_MAX=0.95`, `K_HOLD=0.03`, `K_REJECT=0.07`, `MAX_PENDING=10`

---

## Services Layer

### コアサービス

| サービス | ファイル | 役割 |
|---------|---------|------|
| **AgentOrchestrator** | `core/agent.py` + `core/agent_stream.py` | SSE ストリーム / 非ストリーム実行 |
| **MemoryService** | `services/memory/memory_service.py` | Memory v2 統一インターフェース |
| **ContextBuilder** | `services/memory/context_builder.py` | Depth 別メモリコンテキスト生成 |
| **CommitExecutor** | `services/memory/commit_executor.py` | S5 の episodic 書き込み |
| **SemanticStore** | `services/memory/semantic_store.py` | semantic CRUD |
| **WorkingStore** | `services/memory/working_store.py` | working items CRUD |
| **SpeechSanitizer** | `services/speech_sanitizer.py` | タグ除去・リーク防止・ジェスチャー抽出 |
| **IdentityManager** | `services/identity_manager.py` | identity.md の読み書き |
| **VisionClient** | `services/vision_client.py` | LM Studio + Qwen3-VL-4B (ローカル) / Gemini Flash (クラウド) |
| **TwitterClient** | `services/twitter_client.py` | X API v2 投稿 + LLM ツイート生成 |
| **VoicevoxClient** | `services/voicevox_client.py` | VOICEVOX TTS 統合 |
| **STTService** | `services/stt_service.py` | faster-whisper (CPU) による STT |
| **ReflectionEngine** | `services/reflection_engine.py` | Autonomous Reflection（R.2 + R.4） |
| **IdleDetector** | `services/idle_detector.py` | アイドル検出（R.1） |
| **ExternalData** | `services/external_data.py` | 外部 API データ取得 |

### Voice Mode パイプライン

```
Browser (MediaRecorder)
    │ webm/opus via WebSocket
    ▼
ffmpeg → faster-whisper (STT)
    │
    ▼
LLM → VOICEVOX (TTS)
    │ audio_b64 via WebSocket
    ▼
Browser (再生 + VAD pause/resume)
```

- VAD: @ricky0123/vad-web (Silero VAD) — 検出のみ
- Barge-in 対応: TTS 再生中 → VAD pause、終了 → resume

---

## API 構造

### ルーター一覧

| ルーター | プレフィックス | 認証 | 用途 |
|---------|--------------|------|------|
| `stream_router` | `/api` | - | SSE ストリーミングチャット |
| `system_router` | `/api` | admin | Vision/Sleep/Reflect 制御 |
| `review_router` | `/api` | - | Review Window 操作 |
| `actions_router` | `/api` | - | Phase 5 アクション管理 |
| `profile_router` | `/api` | - | ユーザープロフィール |
| `tts_router` | `/api` | - | TTS 生成 |
| `tts_events_router` | `/api` | - | TTS イベントバス |
| `draw_router` | `/api` | - | お絵描き機能 |
| `livestream_router` | `/api` | - | 配信連携 |
| `voice_router` | `/api` | - | Voice Mode (WebSocket) |
| `game_router` | `/api` | admin | ゲーム連携 (Minecraft + Screen Adapter) |
| `video_router` | `/api` | admin | 動画分析 |
| `motion_router` | - | - | VRM モーション |
| `identity_router` | `/api` | admin | Identity Proposal レビュー |
| `memory_router` | `/api` | - | メモリ CRUD |
| `stats_router` | - | - | 統計情報 |

### SSE イベント

```
event: message       → {text: "..."}           テキストチャンク
event: metadata      → {emotion, tags, ...}    メタデータ
event: hold_request  → {preview, token, ...}   Review Window
event: hold_cancelled → {reason}               キャンセル通知
event: final_result  → {text, ...}             最終結果（1回のみ）
event: done          → {}                      ストリーム終了
```

---

## Frontend コンポーネント

| コンポーネント | 役割 |
|--------------|------|
| **ChatInterface** | メインチャット UI + SSE + Voice Mode |
| **AvatarView** | VRM 3D アバター表示 |
| **ActionPanel** | Phase 5 アクション承認/却下 |
| **ActionIssuesPanel** | 失敗/却下アクション一覧 |
| **MemoryExplorer** | 記憶ブラウザ |
| **MemoryGraph** | 記憶関係性グラフ |
| **MemoryTimeline** | 記憶タイムライン |
| **StatsPanel** | 統計ダッシュボード |
| **InnerMonologue** | 内部独白表示 |
| **ObservationReport** | 観察レポート |
| **DrawLab** | お絵描き PoC |
| **GamePanel** | Minecraft 連携 |
| **VideoPanel** | 動画分析 |
| **IdentityPanel** | Identity Proposal レビュー |
| **ProfileEditor** | ユーザープロフィール編集 |
| **LivestreamDashboard** | 配信ダッシュボード |
| **Sidebar** | ナビゲーション + Admin Token |
| **SettingsPanel** | モード切替設定 |

---

## External Dependencies

| サービス | 用途 | プロトコル | 必須 |
|---------|------|----------|------|
| **LM Studio** | ローカル LLM (Qwen 系) | OpenAI 互換 API | 必須 |
| **VOICEVOX** | 日本語 TTS | REST API | Voice Mode 使用時 |
| **ChromaDB** | ベクトル検索 | Embedded | 必須 |
| **SQLite** | メイン DB (`nia.sqlite3`) | File | 必須 |
| **Gemini Flash** | ゲーム画面 Vision | REST API | Screen Adapter 使用時 |
| **X (Twitter) API** | ツイート投稿 | tweepy (X API v2) | Twitter 機能使用時 |

---

## Autonomous Reflection（R.1 〜 R.4）

ニアが自発的に記憶を振り返り、パターンを抽出する仕組み。

```
アイドル検出 (R.1)
    │ 3分以上無入力
    ▼
Daily Log 生成 (R.2)
    │ セッション中の会話を振り返り
    ▼
Sleep Cycle 連携 (R.3)
    │ daily_reflections → memory_block
    ▼
Cross-Day Distillation (R.4)
    │ 3日以上のデータ → パターン抽出
    ▼
semantic_memories (state_tag='insight')
    │
    ▼
Context Builder の PATTERNS セクションに注入
```

### コンポーネント

| Phase | ファイル | 役割 |
|-------|---------|------|
| **R.1** | `services/idle_detector.py` | アイドル検出（3分閾値） |
| **R.2** | `services/reflection_engine.py` | Daily Log 生成（LLM 振り返り） |
| **R.3** | `scripts/sleep_cycle.py` | daily_reflections → memory_block 変換 |
| **R.4** | `services/reflection_engine.py` | Cross-Day Distillation（日横断パターン抽出） |

### R.4 Cross-Day Distillation

- 3日以上の `daily_reflections` を分析
- 4カテゴリ: `user_trait` / `relationship_pattern` / `emerging_interest` / `lesson`
- confidence cap: 3-4日→0.6、5-6日→0.8、7日+→0.9
- `semantic_memories` に `state_tag='insight'` で保存
- Context Builder の `=== PATTERNS ===` セクションに自動反映

---

## Sleep Cycle（日次メンテナンス）

`backend/scripts/sleep_cycle.py`

1. **Memory Block 構築**: `daily_reflections` を優先、フォールバックで `memory_events`（R.3）
2. **Layer A**: memory_block の振り返り・印象記録
3. **Layer B**: Identity 変更提案（importance で自動適用 or 承認待ち）
4. **Semantic Extraction**: episodic → semantic memories（LLM バッチ）※ R.3 で daily_reflections がある場合はスキップ
5. **忘却**: status 別半減期による retention 減衰
6. **Episodic 圧縮**: 古い episodic を日単位でサマリー化

---

## ゲーム統合（GameProfile 抽象化）

Minecraft と汎用ゲーム操作（Screen Adapter）を統一インターフェースで管理。

### GameProfile ABC

```python
class GameProfile(ABC):
    game_id: str
    game_name: str
    async def get_state() -> dict           # ゲーム状態取得
    async def execute_action(action, params) -> dict  # アクション実行
    async def is_connected() -> bool        # 接続確認
    def format_state_for_llm(state, depth) -> str     # LLM向け整形
    def get_available_actions() -> list[dict]          # 利用可能アクション
```

### 実装

| プロファイル | アダプター | Vision | 入力 |
|------------|----------|--------|------|
| **MinecraftProfile** | Mineflayer API 経由 | 不要（API で状態取得） | Bot コマンド |
| **ScreenGameProfile** | 画面キャプチャ (mss) | Gemini Flash (クラウド) | pydirectinput |

### GameProfileRegistry

```
game_profile_registry.register(profile)
game_profile_registry.set_active("minecraft")  # or "generic"
active = game_profile_registry.get_active()     # routing.py で使用
```

Agent Graph の `routing.py` は Registry 経由でアクティブなゲームの状態を取得し、会話コンテキストに注入。

### Screen Adapter パイプライン

```
mss キャプチャ → JPEG → Gemini Flash API → テキスト分析
    → Brain LLM → <ACTION>/<CHAT>/<IDLE>
    → InputController → pydirectinput
```

---

## X (Twitter) 投稿

### フロー

```
手動: チャットで「呟いて」→ action_processing で検出 → Phase 5 pending
自律: ReflectionEngine → daily_log 完了 → telemetry_kv に提案

承認: ActionPanel or tweet/approve → TwitterClient.post_tweet()
却下: ActionPanel or tweet/reject → 提案削除
```

### コンポーネント

| コンポーネント | ファイル | 役割 |
|------------|---------|------|
| **TwitterClient** | `services/twitter_client.py` | LLM ツイート生成 + X API v2 投稿 |
| **ActionsRouter** | `controllers/api/actions_router.py` | tweet approve/reject/generate/pending/history |
| **ReflectionEngine** | `services/reflection_engine.py` | 自律ツイート提案（daily_log 後） |

---

## 設計原則

1. **ストリーミングファースト**: 全応答は SSE、リアルタイムサニタイゼーション
2. **三権分立**: AI は考える / 人間は決める / システムは従う
3. **メモリの哲学**: 保存時は生データ、取り出し時にコンテキスト依存で意味付け
4. **非交渉原則**: [NIA_NON_NEGOTIABLE.md](NIA_NON_NEGOTIABLE.md) 参照
