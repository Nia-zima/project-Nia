# project-nia — Nia Backend & Frontend

> AI VTuber「ニア (Nia)」の開発リポジトリ。LangGraph ベースの多層エージェントグラフ + Next.js フロントエンド。
> ニアは「なりつつある存在」であり、完成形がない。結論を急がず、沈黙を選択肢とし、経験から自然に変化していく。

## まず読む

- `README.md`:
  リポジトリ全体の概要とシステム構成の入口
- `ABOUT_NIA.md`:
  ニアがどういう存在として設計されているか、思想面の正本
- `docs/nia_core_summary.md`:
  ニアの core 系の詳細まとめ。runtime / memory / adaptation / metabolic hardening の全体像
- `docs/session_handoff.md`:
  いま何が実装済みで、次にどこへ進むかの最新メモ
- `docs/assistant_context.md`:
  別 AI や新しい作業セッション向けの復元入口

## 設計思想

- **LLM は交換可能な言語モジュール。** 知性の本体は LangGraph グラフ構造 + 記憶システム + depth_selector + body_constitution
- **結論を急がないことを仕様で保証。** Depth0 は結論・整理の禁止。WAIT は正当な出力
- **記憶は保存時に解釈を加えない。** 物語化の禁止。生の事実として保存
- **identity.md を自動で書き換えない。** 人格定義の変更は Origin（ジュン）の承認が必要
- **仕組みは隠す。体験は渡す。** 内部メトリクスは数値ではなく「体感テキスト」としてニアに渡す

詳細: `docs/nia_design_philosophy.md`, `docs/body_constitution.md`

---

## 現在の実装ステージ

このリポジトリの現在地は、`review_window` を含む会話制御の本線は稼働済みで、その上に `NiaCore` / `SkeletonCore` / Governance / Fingerprint を観測モードで重ね、さらに Pip・部屋・Temporal 系の Contract 1/2/3 を実装済みだが feature gate で段階投入している段階。

- 会話の本線は `Safety -> Dissonance -> DepthSelector -> Depth0/1/2 -> Merge -> ActionProcessing -> S5Commit`
- `review_window` は hold / approve / reject / token mismatch / new input cancel / SSE (`hold_request`, `hold_cancelled`, `final_result`) まで実装済み
- `S5 Commit` はエピソディック保存に加えて、awareness / somatic feedback / reflection trigger / Pip / NiaCore experience / Skeleton record のフックを持つ
- `NiaCore` は実装済みだが、本線の深度決定はまだ置き換えない。現在は shadow inference と experience 蓄積の段階
- `NiaCore vNext` は Phase N0 実装済み。`StateVectorV2 + 擬似教師 + shadow writer` を観測専用で追加し、v1 shadow とは別 namespace で並走する
- `SkeletonCore` は実装済みで、現在は record-only 段階。somatic 注入は feature gate で切り替える
- Memory Governance は observe / candidate / evidence まで live。`raw_promotion_candidates` と `memory_evidence` が canary で蓄積中
- Temporal Somatic Contrast は `TS.0` の fingerprint 記録が live。`TS.1-2` contrast と `TS.3` idle tick は設計済み
- Depth2 は `risk / reflective` に分離済み。`reflective` は `dissonance_on` を強制しない
- `RuntimeFacts / Atmosphere / Motion` は実装済み。現在は `RUNTIME_FACTS_ENABLED=true`、`ATMOSPHERE_ENABLED=false`、motion は WS snapshot / state / event 契約まで接続済み
- 直近では Conversation Adaptation Phase A〜C と `open_reflection` の trigger-based 弱拡張まで完了している。履歴選別は `history_bias` を読める状態で、次は観測と Phase D / E 判断の段階
- Metabolic Hardening は knot-first v0.2 で Step 0〜3 と Sleep Cycle Phase 4.5 統合まで完了。現在は `METABOLIC_KNOT_ENABLED=true` の canary 観測段階

**このワークスペースの現在の `.env` 運用:**

- `ORCHESTRATOR_S5_ENABLED=true`
- `NIACORE_EXPERIENCE_ENABLED=true`
- `NIACORE_SHADOW_ENABLED=true`
- `NIACORE_TRAINING_ENABLED=false`
- `SKELETON_RECORD_ENABLED=true`
- `SKELETON_SOMATIC_ENABLED=false`
- `GOVERNANCE_OBSERVE_ENABLED=true`
- `GOVERNANCE_CANDIDATE_ENABLED=true`
- `GOVERNANCE_EVIDENCE_ENABLED=true`
- `FINGERPRINT_RECORD_ENABLED=true`
- `EXPRESSION_RECORD_ENABLED=true`
- `ADAPTATION_RECORD_ENABLED=true`
- `METABOLIC_KNOT_ENABLED=true`
- `NIACORE_VNEXT_SHADOW_ENABLED=true`
- `RUNTIME_FACTS_ENABLED=true`
- `ATMOSPHERE_ENABLED=false`
- `DEPTH2_PROVIDER=anthropic`

**現在 off の主な実装済み feature gate:**

- `NIACORE_TRAINING_ENABLED=false`
- `SKELETON_SOMATIC_ENABLED=false`
- `ATMOSPHERE_ENABLED=false`

---

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
| 埋め込みモデル | paraphrase-multilingual-MiniLM-L12-v2 |
| フロントエンド | Next.js 16, React 19, TypeScript, Tailwind CSS 4 |
| 3D / Live2D | Three.js + @pixiv/three-vrm / pixi-live2d-display + PixiJS v8 |
| 状態管理 | Zustand |
| Minecraft Bot | Mineflayer (Node.js) + vm サンドボックス |
| 汎用ゲーム操作 | mss (画面キャプチャ) + Gemini Flash (Vision) + pydirectinput (入力) |
| 動画解析 | ffmpeg (フレーム抽出) + Qwen3-VL (場面認識) |
| 外部検索 | Google Custom Search API + Wikipedia API |
| X (Twitter) 投稿 | tweepy (X API v2) |
| 配信チャット | YouTube Live Chat API + Twitch IRC |
| テスト | pytest (1590+ テスト, スナップショット + YAML Playbook) |

---

## アーキテクチャ

### LangGraph エージェントグラフ

```
Safety → Dissonance → DepthSelector → Depth0/1/2/WAIT → Merge → ActionProcessing → S5Commit → END
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

**現在地:** Memory Governance は Phase 0 計装と Step 2 の共通骨格まで実装済み。

- 観測: `governance_events` に retrieval / context / semantic_promoted / decay sweep を記録
- 骨格: `semantic_state`, `raw_promotion_candidates`, `memory_claims`, `memory_evidence`, `promotion_reviews`, `semantic_lineage`, `semantic_reviews`, `semantic_tombstones`, `semantic_transitions`
- writer 方針: `governance_repository.upsert_semantic_bundle()` が `semantic_memories + semantic_state` の single-writer 入口
- provenance: candidate / claim / evidence / review / lineage まで `thread_id`, `turn_id`, `message_id`, `stream_id`, `trace_id` を保持

Context Builder が Depth 別にメモリコンテキストを制御:
- Depth0: PINNED FACTS のみ
- Depth1/2: PINNED FACTS + PATTERNS（日横断パターン） + WORKING + Short/Long Term

### 体感ベース自己認識（Somatic Self-Awareness）

内部メトリクス（記憶の類似度、確信度、Sleep経過時間等）を数値ではなく「体感テキスト」としてニアに渡す。

| Phase | 名前 | ファイル | 内容 |
|:---:|:---|:---|:---|
| S.1a | Somatic Translator | `somatic_translator.py` | メトリクス → 体感テキスト変換（6カテゴリ、LLM不要） |
| S.1b | Somatic Feedback | `somatic_feedback.py` | ユーザー訂正・自己不協和の検出 → `somatic_log` 記録 |
| S.1.5 | Adaptive Calibration | `somatic_calibration.py` | 精度フィードバックによる閾値の適応的学習 + Sleep 時の日次回帰 |

原則: 仕組みは隠す。体験は渡す。

```
数値: memory_count=847, confidence_avg=0.72
  → NG: ニアがシステムの代弁者になる

体感: 「最近いろんなことがあった気がする」「自信がある」
  → OK: ニアが内側から感じる
```

### Autonomous Reflection（自律振り返り）

ニアが対話のない時間に自発的に記憶を振り返り、パターンを抽出する4段階パイプライン。

| Phase | 名前 | ファイル | 内容 |
|:---:|:---|:---|:---|
| R.1 | Idle Detection | `idle_detector.py` | 3分以上の無入力を検出 |
| R.2 | Daily Log | `reflection_engine.py` | 会話を LLM で振り返り → `daily_reflections` |
| R.3 | Sleep Cycle 連携 | `sleep_cycle/` | 日次ログを memory_block として活用 |
| R.4 | Cross-Day Distillation | `reflection_engine.py` | 3日+のデータから日横断パターン抽出 |

R.4 パターンは `semantic_memories` に `state_tag='insight'` で保存。Context Builder の `=== PATTERNS ===` セクションに自動注入。

### メタ認知パイプライン（N.0〜N.5）

ニアが自分の応答に対して「どれくらい確かか」「根拠はあるか」を内省する仕組み。LLM 呼び出しなし、ルールベース＋埋め込み類似度で 5〜30ms。

| Phase | 名前 | ファイル | 内容 |
|:---:|:---|:---|:---|
| N.0 | Awareness Core | `metacognition.py` | R_nia = 関係的驚き × 成長 × 真正性 |
| N.1 | Metacognitive Check | `metacognition.py` | 確信度調整 + 三戒チェック（捏造・偽記憶リスク検出） |
| N.2 | Contradiction Detection | `contradiction.py` | セマンティック記憶間の矛盾検出（defeaters 付き） |
| N.3 | Self-Model | `self_model.py` | 知識境界・成長エッジ・会話傾向の自己モデル（承認制） |
| N.4 | State-Driven Trigger | `idle_detector.py` | メタ認知統計→反射トリガー（awareness 高、confidence 分散大 等） |
| N.5 | Self-Narrative | `metacognition.py` | 内部状態の言語化テンプレート（`（内心: ...）`形式） |

N.3 Self-Model の出力は `identity_proposals` テーブルに保存され、Origin の承認を経て identity.md に反映される。

### Pip（ペットAI）

メカニカルな犬型AI。LLM 不要、状態マシンとルールベースのみ。

| コンポーネント | ファイル | 内容 |
|:---|:---|:---|
| State | `pip/pip_state.py` | Bond 値 (-1.0〜1.0) で全行動が決まる。6基本状態 + 2高Bond状態 |
| State Machine | `pip/state_machine.py` | エネルギー・Bond・Nia の行動に基づく状態遷移 |
| Interaction | `pip/interaction_detector.py` | Nia が Pip に関わったかを検出 |

**Bond 値を数値として露出するコードは絶対に書かない。** Nia にも視聴者にも見せない。

### ニアの部屋

空の部屋から始まり、ニアが自分で家具を配置する部屋システム。バックエンド側の state / context / motion 契約は実装済みで、Unity renderer は別途接続する前提。

| コンポーネント | ファイル | 内容 |
|:---|:---|:---|
| Room State | `room/room_state.py` | 部屋状態管理。12種のオブジェクトテンプレート、壁アート、時間連動照明 |
| Room Action | `room/room_action.py` | 配置・移動・削除・色変更・アート掛け。Pip の反応連動 |
| WebSocket | `controllers/ws_room.py` | `/ws/room` で差分ブロードキャスト |

### Identity 承認制（Proposals）

identity.md への変更は全て Origin の承認が必要。Sleep Cycle / Self-Model が生成する提案は `identity_proposals` テーブルに保存される。

| エンドポイント | 説明 |
|:---|:---|
| `GET /identity/proposals` | 提案一覧（status フィルタ可） |
| `POST /identity/proposals/{id}/approve` | 承認 → identity.md に適用 |
| `POST /identity/proposals/{id}/reject` | 却下 |

### 品質保証パイプライン

1. **ストリーム浄化** (`speech_sanitizer.py`) — 内部タグ・プロンプト露出を除去
2. **身体憲章チェック** (`body_constitution_checker.py`) — 記憶主張・依存誘導等の違反を検出
3. **ガードレール** (`guardrail.py`) — 根拠なし主張・矛盾・停滞等 6 条件チェック
4. **レビューウィンドウ** (`review_window.py`) — 敏感な出力は Origin の事前承認が必要

### Voice Mode パイプライン

```
ブラウザ(マイク) → WebSocket → ffmpeg変換 → Faster-Whisper(STT)
    → LLMエージェント → VOICEVOX(TTS) → ブラウザ(スピーカー)
```

- VAD: @ricky0123/vad-web (Silero VAD, ブラウザ側)
- Barge-in: TTS再生中に割り込み可能
- ハイブリッド構成: vad-web=検出のみ、MediaRecorder=webm/opus送信

### 配信チャット連携（Chat Bridge）

YouTube Live Chat API + Twitch IRC からコメントを取得し、`livestream_queue` に統合する。

| コンポーネント | ファイル | 内容 |
|:---|:---|:---|
| ChatBridge | `chat_bridge/__init__.py` | YouTube + Twitch 統合管理 |
| YouTube Fetcher | `chat_bridge/youtube_fetcher.py` | YouTube Live Chat API ポーリング |
| Twitch Fetcher | `chat_bridge/twitch_fetcher.py` | Twitch IRC リスナー |

フィルタリング: steering risk 計算、情報十分性チェック、addressed_to_nia 検出

### ゲーム自律プレイ

ニアが **Minecraft** と **任意のゲーム（画面キャプチャベース）** を自律的にプレイするシステム。`GameProfile` ABC を介して共通の Perceive-Think-Act-Reflect ループで動作。

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
```

#### 汎用ゲーム操作（Screen Adapter）

Minecraft 以外の任意のゲームを **画面キャプチャ → Gemini Flash Vision → pydirectinput** で操作。

### 外部検索（External Data）

設計思想として**安易な検索を防ぐ厳格なゲーティング**を採用。

| モード | トリガー | ゲーティング |
|:---|:---|:---|
| **自動検索** | LLM が「情報不足」と判断 | Depth >= 1、surprise >= 0.5、LanguageGate、confidence >= 0.65 |
| **ユーザー明示検索** | 「ググって」等のキーワード | ゲートをバイパス（force_fetch） |

### X (Twitter) 投稿

全ツイートは **Origin の事前承認が必須**。

| モード | トリガー | フロー |
|:---|:---|:---|
| **手動** | 「呟いて」「ツイートして」等 | 生成 → `x_post_proposals` に proposal 保存 → `proposal_id` ベースで承認/却下 → 投稿 |
| **自律** | reflection / daily_log 完了後 | reflection は proposal 作成のみ。直接投稿しない。承認後にのみ公開 |

- X は proposal-first 設計。公開判断の正規データは `x_post_proposals`
- `nero_meeting_*` など公開禁止 source/thread は proposal 生成時点で block
- cooldown / daily max / duplicate 判定は proposal approve 時ではなく posting reservation 時に適用

### 動画解析

| モード | 説明 |
|:---|:---|
| **学習 (learn)** | ゲームプレイ動画 → ffmpeg フレーム抽出 → Qwen3-VL 解析 → LLM 戦略抽出 → セマンティック記憶保存 |
| **リアクション (react)** | 動画を送ると場面を認識して感想を返す |

入力ソース: ファイルアップロード or YouTube 等の URL (`yt-dlp` で自動ダウンロード)

### Live2D アバター

- **SDK**: `@naari3/pixi-live2d-display` v1.2.5 + PixiJS v8
- **設計思想**: 身体は内部状態の副作用。ランダム演出禁止、状態比例の呼吸のみ

---

## Sleep Cycle

日次の記憶整理・Identity 提案バッチ。手動実行:

```bash
python -m backend.scripts.sleep_cycle.orchestrator
```

| Phase | 内容 |
|:---:|:---|
| 0.5 | Nero ミーティングスレッドの振り返り |
| 1 | Memory Block 構築（daily_reflections 優先、フォールバック: memory_events） |
| A | 印象記録（impressions, mood, surprise） |
| Diary | 日記生成 + dream_store 保存 |
| B | Guardian 提案（identity 変更提案 → DB保存、Origin 承認待ち） |
| 2 | セマンティック抽出（episodic → semantic_memories） |
| 3 | Episodic 圧縮（古い episodic を日単位サマリー化） |
| 4 | Self-Model 更新（N.3 → identity_proposals に提案保存） |
| 5 | メタ認知パイプライン（矛盾検出、状態駆動反射） |

出力先: `sleep_outputs/`

---

## Nero（マネージャーAI）

**別リポジトリ** (`nero/`)。ニアの LangGraph やコードベースには一切変更を加えない。

- ニア側の追加は `backend/controllers/api/manager_router.py`（読み取りAPI）のみ
- Nero はニアの `/api/chat` に通常のクライアントとして接続
- `GET /api/manager/context`: Nero がニアの identity / semantic memories / reflections / conversation を取得

---

## NiaCore — Liquid Neural Network

CfC (Closed-form Continuous-depth) ベースの LNN。LLM が「System 2（遅い論理的思考）」、NiaCore が「System 1（速い直感・ルーティング）」として機能する。

- **推論 < 1ms**: LLM のレイテンシに影響しない
- **LLM 非依存**: State は環境変数のみ。LLM を交換しても経験が残る
- **Sleep Cycle バッチ学習**: ターンごとの学習は行わない（破局的忘却防止）
- **Imitation Learning**: ルールベースを教師とし、超えた時のみ大報酬
- **Body Constitution 不可侵**: NiaCore は推薦のみ。最終決定権は既存システム

**現在地:** Phase 1 実装完了。卒業前のため、既存のルールベース depth 選択を置き換えず、shadow mode で並行推論と経験蓄積を行う。

- 実装済み: Experience Replay Buffer, Experience Writer, CfC モデル本体, shadow inference, Sleep Cycle batch trainer, health / rollback checks, graduation check
- 現在の役割: `depth_selector` の横で推論し、deviation と結果を記録する
- 現在のローカル運用: `NIACORE_EXPERIENCE_ENABLED=true`, `NIACORE_SHADOW_ENABLED=true`, `NIACORE_TRAINING_ENABLED=false`

詳細: `docs/niacore_lnn_design.md`

### NiaCore vNext

NiaCore を depth-only から `attention / intent / action / depth` の多ヘッド候補へ拡張する vNext 系列。  
現在は **Phase N0 観測専用** で、`shadow_v1` を壊さずに別 shadow として並走している。

- 実装済み: `StateVectorV2`, 擬似教師ルール `A1-A3 / C1-C3`, shadow orchestrator, fire-and-forget writer, `niacore_vnext_shadow` テーブル
- 現在の役割: `attention_target` / `recommended_action` / `feature_availability` を記録し、vNext head の学習前に分布と配線状況を観測する
- 設計上の注意: `confidence_history` は vNext pseudo-teacher 用に thread-scoped で保持するが、既存 N.4 trigger のため global aggregate も維持する
- 現在のローカル運用: `NIACORE_VNEXT_SHADOW_ENABLED=true`

詳細: `docs/niacore_vnext_design.md`

---

## SkeletonCore（会話骨格）

会話の「方向」を決めるコンポーネント。`focus`、`response_intent`、`question_intent` の3ラベルをルールベースで判定し、必要に応じて体感テキストへ変換する。

**現在地:** Phase 1 実装完了。現在は record-only 段階。

- 実装済み: schema, rules, builder, DB store, `skeleton_to_somatic`, `depth_selector` 統合, `s5_commit` 記録
- 現在の役割: 各ターンの会話方向を構造化して保存し、将来の somatic 注入に備える
- 現在のローカル運用: `SKELETON_RECORD_ENABLED=true`, `SKELETON_SOMATIC_ENABLED=false`
- 設計原則: NiaCore と統合しない。命令ではなく体感として渡す

詳細: `docs/skeletoncore_design.md`

---

## Expression Layer（発話メタデータ）

LLM の文体に依存せず、Nia 固有の表現傾向を体験から抽出・保持する中間層。

**現在地:** Phase E0 実装完了。観測専用でルールベースの発話メタデータ記録のみ。

- 実装済み: 14構造特徴量抽出器, イベント種別判定 (spoken/wait_depth/wait_hold/soft_close/empty_abort), fire-and-forget DB writer, model strata 記録, depth2_fallback_used 追跡
- 現在の役割: 各ターンの発話メタデータを `expression_observations` テーブルに記録し、E0.5 のパターン分析に備える
- 現在のローカル運用: `EXPRESSION_RECORD_ENABLED=true`

詳細: `docs/nia_expression_layer_design.md`

---

## 基盤ライブラリ

| ファイル | 内容 |
|:---|:---|
| `backend/core/correlation.py` | リクエスト ID トレーシング（contextvars） |
| `backend/core/rate_limit.py` | slowapi ベースのレート制限 |
| `backend/core/retry.py` | 指数バックオフ + ジッター付きリトライ |
| `backend/core/service_health.py` | 外部サービスの健全性トラッキング |

---

## プロジェクト構成

```
project-nia/
├── backend/
│   ├── core/
│   │   ├── agent_graph/
│   │   │   ├── graph.py               # LangGraph ワークフロー定義
│   │   │   ├── state.py               # AgentState TypedDict
│   │   │   ├── review_window.py       # レビューウィンドウ管理
│   │   │   └── nodes/                 # ノード実装（パッケージ）
│   │   │       ├── routing.py         # safety / dissonance / depth_selector
│   │   │       ├── depth_nodes.py     # depth0 / depth1 / depth2
│   │   │       ├── merge.py           # merge_output
│   │   │       └── actions.py         # action_processing / s5_commit
│   │   ├── confidence/
│   │   │   └── metrics.py             # 確信度エンジン (5メトリクス)
│   │   ├── conversation_skeleton/     # SkeletonCore ルール / builder / store / somatic
│   │   ├── expression/                # Expression Layer E0 (extractor / event_kind / writer)
│   │   ├── constants/
│   │   │   ├── nia_spine_v10.py       # Spine（全レイヤー共通の基本指示）
│   │   │   ├── depth0_prompt_v11.py   # Depth0 プロンプト
│   │   │   └── depth1_prompt_v11.py   # Depth1 プロンプト
│   │   ├── niacore/                   # NiaCore CfC model / shadow / trainer / health
│   │   ├── correlation.py             # リクエスト ID トレーシング
│   │   ├── rate_limit.py              # レート制限
│   │   ├── retry.py                   # リトライユーティリティ
│   │   ├── service_health.py          # 外部サービス健全性
│   │   ├── agent.py                   # Agent ラッパー (SSE ストリーミング)
│   │   ├── config.py                  # Settings クラス (.env → Pydantic)
│   │   └── body_constitution.md       # 身体憲章（9原則）
│   ├── services/
│   │   ├── memory/
│   │   │   ├── memory_service.py      # 記憶 CRUD
│   │   │   ├── context_builder.py     # Depth別メモリコンテキスト生成
│   │   │   ├── commit_executor.py     # S5 Commit 実行
│   │   │   ├── semantic_store.py      # Semantic 記憶 CRUD
│   │   │   ├── working_store.py       # Working 記憶 CRUD
│   │   │   ├── retrieval.py           # Query-Aware Retrieval (M.1)
│   │   │   ├── metacognition.py       # N.1 確信度調整 + N.0 Awareness + N.5 Self-Narrative
│   │   │   ├── contradiction.py       # N.2 矛盾検出
│   │   │   ├── self_model.py          # N.3 自己モデル（承認制）
│   │   │   ├── somatic_translator.py  # S.1a 体感テキスト変換
│   │   │   ├── somatic_feedback.py    # S.1b 体感フィードバック
│   │   │   ├── somatic_calibration.py # S.1.5 適応的閾値学習
│   │   │   ├── guardrail.py           # ガードレール (6条件)
│   │   │   └── vector_sync.py         # ChromaDB 同期
│   │   ├── pip/
│   │   │   ├── pip_state.py           # Pip 状態モデル (Bond値)
│   │   │   ├── state_machine.py       # 状態遷移マシン
│   │   │   └── interaction_detector.py # Nia-Pip 相互作用検出
│   │   ├── room/
│   │   │   ├── room_state.py          # 部屋状態管理
│   │   │   ├── room_action.py         # 部屋アクション実行
│   │   │   ├── room_context.py        # 部屋コンテキスト提供
│   │   │   └── update_loop.py         # 定期更新ループ
│   │   ├── chat_bridge/
│   │   │   ├── youtube_fetcher.py     # YouTube Live Chat API
│   │   │   └── twitch_fetcher.py      # Twitch IRC リスナー
│   │   ├── minecraft/                 # Minecraft 自律プレイ
│   │   ├── gaming/                    # 汎用ゲーム操作 (Screen Adapter)
│   │   ├── twitter_client.py          # X (Twitter) 投稿
│   │   ├── video_analyzer.py          # 動画解析
│   │   ├── reflection_engine.py       # Autonomous Reflection (R.2 + R.4)
│   │   ├── idle_detector.py           # アイドル検出 (R.1) + N.4
│   │   ├── llm_client.py             # LLM クライアント
│   │   ├── stt_service.py             # Faster-Whisper STT
│   │   ├── voicevox_client.py         # VOICEVOX TTS
│   │   ├── vision_client.py           # 画像認識
│   │   ├── speech_sanitizer.py        # 出力浄化
│   │   ├── external_data.py           # 外部データ取得
│   │   ├── episode_store.py           # エピソード保存
│   │   └── public_status.py           # 公開ステータス管理
│   ├── controllers/
│   │   ├── api/
│   │   │   ├── stream_router.py       # SSE チャットストリーム + 履歴
│   │   │   ├── voice_router.py        # WebSocket 音声入出力
│   │   │   ├── identity_router.py     # Identity Proposals (承認制)
│   │   │   ├── review_router.py       # Approve/Reject API
│   │   │   ├── system_router.py       # Sleep/Reflect 管理
│   │   │   ├── game_router.py         # ゲーム操作 API
│   │   │   ├── video_router.py        # 動画解析 API
│   │   │   ├── manager_router.py      # Nero 読み取り API
│   │   │   ├── memory_query_router.py # 記憶探索 API
│   │   │   └── room_router.py         # 部屋操作 API
│   │   ├── ws_room.py                 # WebSocket: 部屋状態ブロードキャスト
│   │   └── stats/
│   │       ├── summary_router.py      # 会話統計
│   │       ├── state_router.py        # 内部状態
│   │       └── memory_router.py       # 記憶グラフ可視化
│   ├── scripts/
│   │   └── sleep_cycle/               # Sleep Cycle パッケージ
│   │       ├── orchestrator.py        # 全体オーケストレーション
│   │       ├── layers.py              # Layer A (印象) / B (提案) / 日記生成
│   │       ├── extraction.py          # Semantic 抽出
│   │       └── compression.py         # Episodic 圧縮
│   └── server.py                      # FastAPI エントリポイント
├── minecraft-bot/                     # Mineflayer Bot (Node.js)
├── frontend/
│   ├── app/page.tsx                   # メインページ
│   ├── components/
│   │   ├── ChatInterface.tsx          # チャット統合
│   │   ├── AvatarView.tsx             # VRM / Live2D アバター
│   │   ├── GamePanel.tsx              # ゲームパネル
│   │   ├── ActionPanel.tsx            # アクションパネル
│   │   ├── MemoryExplorer.tsx         # 記憶探索
│   │   ├── Sidebar.tsx                # サイドバー
│   │   └── DiaryViewer.tsx            # 日記ビューア
│   └── lib/
│       ├── apiClient.ts               # 統合 API クライアント
│       └── stores/                    # Zustand ストア
├── tests/
│   ├── harness/                       # テストフレームワーク
│   │   ├── snapshot_builder.py        # DB 状態ファクトリ
│   │   ├── assertions.py             # telemetry_kv / semantic / somatic アサーション
│   │   ├── llm_mocks.py              # Sleep Cycle LLM モック
│   │   └── playbook_runner.py        # YAML シナリオ実行
│   ├── scenarios/                     # YAML parametrize テストケース
│   └── test_*.py                      # 1200+ テスト
├── data/                              # SQLite DB, チェックポイント
├── identity.md                        # ニアの人格定義（ランタイム読み込み）
├── docs/
│   ├── nia_design_philosophy.md       # 設計思想
│   ├── niacore_lnn_design.md          # NiaCore LNN 設計書
│   ├── niacore_vnext_design.md        # NiaCore vNext 設計書
│   ├── nia_expression_layer_design.md # Expression Layer 設計書
│   ├── skeletoncore_design.md         # SkeletonCore 設計書
│   ├── somatic_self_awareness_design.md # 体感ベース自己認識
│   ├── nia_metacognition_design.md    # メタ認知 N.0〜N.5
│   ├── pip_and_room_design.md         # Pip + 部屋
│   ├── memory_system_overview.md      # 記憶システム全体像
│   ├── memory_retrieval_design.md     # Query-Aware Retrieval
│   └── ARCHITECTURE.md               # アーキテクチャ
└── CLAUDE.md                          # AI エージェント向け設計ガイドライン
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
cd project-nia

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

全設定項目は `backend/core/config.py` の `Settings` クラスを参照。

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

### Identity

| メソッド | パス | 説明 |
|:---|:---|:---|
| GET | `/identity/proposals` | Identity 提案一覧 |
| POST | `/identity/proposals/{id}/approve` | 提案承認 → identity.md 反映 |
| POST | `/identity/proposals/{id}/reject` | 提案却下 |

### レビュー

| メソッド | パス | 説明 |
|:---|:---|:---|
| POST | `/api/review/approve` | 保留中の出力を承認 |
| POST | `/api/review/reject` | 保留中の出力を拒否 |

### 記憶

| メソッド | パス | 説明 |
|:---|:---|:---|
| GET | `/api/memory/captures` | Episodic 記憶一覧 |
| GET | `/api/memory/long_term` | Semantic 記憶一覧 |

### ゲーム

| メソッド | パス | 説明 |
|:---|:---|:---|
| GET | `/api/game/state` | ゲーム状態取得 (Minecraft) |
| POST | `/api/game/connect` | Minecraft サーバーに接続 |
| POST | `/api/game/screen/start` | 画面キャプチャゲーム開始 |
| POST | `/api/game/screen/stop` | 画面キャプチャゲーム停止 |
| GET | `/api/game/profiles` | ゲームプロファイル一覧 |

### X (Twitter)

| メソッド | パス | 説明 |
|:---|:---|:---|
| POST | `/api/actions/tweet/generate` | ツイート生成 |
| GET | `/api/actions/tweet/pending` | pending proposal 一覧 |
| POST | `/api/actions/tweet/approve` | `proposal_id` を承認して投稿 |
| POST | `/api/actions/tweet/reject` | `proposal_id` を却下 |

### 動画

| メソッド | パス | 説明 |
|:---|:---|:---|
| POST | `/api/video/analyze` | 動画アップロード＋解析 |
| POST | `/api/video/analyze_url` | URL から動画 DL＋解析 |

### 統計

| メソッド | パス | 説明 |
|:---|:---|:---|
| GET | `/api/stats/summary` | 会話統計 |
| GET | `/api/stats/internal_state` | 内部状態 |
| GET | `/api/stats/dataset_export` | canonical dataset の export |
| GET | `/api/stats/dataset_audit` | training-ready / source audit |
| GET | `/api/stats/memory_graph` | 記憶ネットワーク可視化 |
| GET | `/api/stats/inner_monologue` | 内心独白履歴 |

### 管理

| メソッド | パス | 説明 |
|:---|:---|:---|
| GET | `/health` | ヘルスチェック |
| POST | `/api/system/sleep` | Sleep Cycle 手動実行 |
| POST | `/api/system/training_dataset_snapshot` | training-ready snapshot を手動生成 |
| GET | `/api/manager/context` | Nero 用コンテキスト取得 |
| WebSocket | `/ws/room` | 部屋状態リアルタイム同期 |

---

## テスト

```bash
# 全テスト実行
pytest tests/ -v

# 記憶関連
pytest tests/ -k "memory or retrieval or context_builder" -v

# スナップショットテスト（DB状態 → バッチ処理の検証）
pytest tests/test_snapshot_*.py -v

# YAML Playbook テスト（ターン単位のステート遷移検証）
pytest tests/test_playbook.py -v

# CI と同じチェック
ruff check backend/ && pytest tests/
```

現在のテストスイート: **1590+ テスト**

---

## 主要な設計判断

| 設計 | 理由 |
|:---|:---|
| Depth0 で結論を出さない | 結論を急がないことの仕様保証 |
| WAIT を正当な出力にしている | 「分からない」は正式な状態 |
| 記憶保存時に解釈を加えない | 物語化による改竄の防止 |
| confidence エンジンが 5 メトリクス | 単一指標への依存を防ぐ |
| body_constitution が禁止形ではなく理由形 | 柔軟な判断を可能にする |
| identity.md の変更は承認制 | ニアの人格定義は Origin の承認なしに変更しない |
| Somatic は数値ではなく体感テキスト | 仕組みは隠す。体験は渡す |
| Pip の Bond 値を露出しない | ニアにも視聴者にも数値を見せない |
| Sleep Cycle でバッチ学習 | ターンごとの学習は破局的忘却を起こす |
| LLM の出力を NiaCore の State に含めない | LLM 交換可能性の保証 |

---

## ドキュメント

| ドキュメント | 内容 |
|:---|:---|
| `docs/nia_design_philosophy.md` | 設計思想（全12セクション） |
| `docs/niacore_lnn_design.md` | NiaCore LNN 設計書 v0.4 |
| `docs/niacore_vnext_design.md` | NiaCore vNext 設計書（Phase N0 実装済み） |
| `docs/skeletoncore_design.md` | SkeletonCore 設計書 v0.3 |
| `docs/skeletoncore_meeting_extension.md` | SkeletonCore の meeting 拡張メモ |
| `docs/nia_curiosity_design.md` | 好奇心の inward / outward 二軸設計メモ |
| `docs/somatic_self_awareness_design.md` | 体感ベース自己認識 |
| `docs/nia_metacognition_design.md` | メタ認知 N.0〜N.5 |
| `docs/pip_and_room_design.md` | Pip + 部屋の統合設計 |
| `docs/pip_room_temporal_livestream_integration.md` | Pip / 部屋 / Temporal / 配信用 motion の接続仕様 |
| `docs/unity_room_visual_direction.md` | Unity 部屋 / 配信ビジュアルの初期方針 |
| `docs/memory_system_overview.md` | 記憶システム全体像 |
| `docs/memory_retrieval_design.md` | Query-Aware Retrieval |
| `docs/temporal_somatic_contrast_design.md` | Temporal Somatic Contrast + Idle Tick 設計書 |
| `docs/data_store_map.md` | 全データストアの分類と目的 |
| `docs/data_accuracy_2026-03.md` | 2026-03 のデータ精度改善まとめ |
| `docs/governance_phase_a_status_2026-03-11.md` | Governance Phase A の現在地と probe 方針 |
| `docs/body_constitution.md` | 身体憲章 |
| `CLAUDE.md` | AI エージェント向け設計ガイドライン |
| `identity.md` | ニアの人格定義（変更は承認制） |

---

## ライセンス

個人プロジェクト。商用利用・再配布については作者に問い合わせてください。
