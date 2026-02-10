# システムアーキテクチャ

このドキュメントでは、AI_Buddy (Nia) のシステムアーキテクチャを詳細に説明します。

---

## 目次

1. [全体構成](#全体構成)
2. [コンポーネント詳細](#コンポーネント詳細)
3. [データフロー](#データフロー)
4. [設計原則](#設計原則)
5. [API構造](#api構造)

---

## 全体構成

### システムレイヤー図

```
┌────────────────────────────────────────────────────────────┐
│                     User Interface                          │
│                   (Web Browser)                             │
└─────────────────────────┬──────────────────────────────────┘
                          │ HTTP / WebSocket / SSE
┌─────────────────────────▼──────────────────────────────────┐
│                  Frontend (Next.js 14)                      │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────┐  │
│  │ ChatInterface│  │ AvatarView   │  │ MemoryExplorer  │  │
│  │ (チャットUI)   │  │ (3Dアバター) │  │ (記憶ブラウザ)   │  │
│  └──────────────┘  └──────────────┘  └─────────────────┘  │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────┐  │
│  │ StatsPanel   │  │ SettingsPanel│  │ Sidebar         │  │
│  │ (統計表示)    │  │ (設定)       │  │ (ナビゲーション) │  │
│  └──────────────┘  └──────────────┘  └─────────────────┘  │
└─────────────────────────┬──────────────────────────────────┘
                          │ API Requests
┌─────────────────────────▼──────────────────────────────────┐
│                  Backend (FastAPI)                          │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              API Router Layer                         │  │
│  │  /api/chat/stream  /api/review/*  /api/actions/*     │  │
│  └──────────────────────────────────────────────────────┘  │
│                          │                                  │
│  ┌──────────────────────▼──────────────────────────────┐  │
│  │          Agent Orchestrator                          │  │
│  │  (DefaultAgentOrchestrator)                          │  │
│  └──────────────────────┬──────────────────────────────┘  │
│                          │                                  │
│  ┌──────────────────────▼──────────────────────────────┐  │
│  │          LangGraph Pipeline (5-Node)                 │  │
│  │  Safety → Dissonance → Depth0 → Depth1 → Merge      │  │
│  └──────────────────────┬──────────────────────────────┘  │
│                          │                                  │
│  ┌──────────────────────▼──────────────────────────────┐  │
│  │          Services Layer                              │  │
│  │  Memory • Speech • Thought • Vision • Voice • TTS    │  │
│  └──────────────────────┬──────────────────────────────┘  │
└────────────────────────┬┴──────────────────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
    ┌───▼───┐       ┌────▼────┐      ┌───▼────┐
    │ LLM   │       │  TTS    │      │ Vision │
    │(LM    │       │(VOICE   │      │ API    │
    │Studio)│       │ VOX)    │      │        │
    └───┬───┘       └────┬────┘      └───┬────┘
        │                │                │
    ┌───▼────────────────▼────────────────▼───┐
    │          Storage Layer                   │
    │  SQLite (会話・状態) • ChromaDB (ベクトル)│
    └──────────────────────────────────────────┘
```

---

## コンポーネント詳細

### 1. Frontend (Next.js 14 + TypeScript)

#### 主要コンポーネント

| コンポーネント | ファイル | 役割 |
|--------------|---------|------|
| **ChatInterface** | `components/ChatInterface.tsx` | チャットUI、SSEストリーム受信 |
| **AvatarView** | `components/AvatarView.tsx` | VRM 3Dアバター、感情表現 |
| **MemoryExplorer** | `components/MemoryExplorer.tsx` | 長期記憶のブラウジング |
| **MemoryGraph** | `components/MemoryGraph.tsx` | 記憶の関係性グラフ |
| **StatsPanel** | `components/StatsPanel.tsx` | 統計情報の表示 |
| **Sidebar** | `components/Sidebar.tsx` | タブ切り替え |

#### アーキテクチャパターン

- **App Router**: Next.js 14のApp Router使用
- **Server Components**: 可能な限りサーバーコンポーネント
- **Client Components**: インタラクティブな部分のみ
- **TailwindCSS**: ユーティリティファーストCSS
- **Framer Motion**: アニメーション

---

### 2. Backend (FastAPI + Python 3.12)

#### 2.1. Agent Core（思考エンジン）

**LangGraph 5-Node Pipeline**:

```
┌─────────────────────────────────────────────────────┐
│                LangGraph Pipeline                   │
│                                                     │
│  User Input                                         │
│      │                                              │
│      ▼                                              │
│  ┌───────────────┐                                 │
│  │ Safety Node   │  有害コンテンツのブロック          │
│  └───────┬───────┘                                 │
│          │                                          │
│          ▼                                          │
│  ┌───────────────┐                                 │
│  │ Dissonance    │  内部矛盾・違和感の検出            │
│  │ Check         │  [DISSONANCE] タグ付与           │
│  └───────┬───────┘                                 │
│          │                                          │
│    ┌─────┴─────┐                                   │
│    │           │                                    │
│    ▼           ▼                                    │
│  ┌──────┐  ┌──────────────┐                       │
│  │Depth0│  │  Depth1      │  深い分析が必要か?      │
│  │Reflex│  │  Organize &  │  Yes → Depth1へ        │
│  │      │  │  Ask         │  No  → Depth0で完結    │
│  └──┬───┘  └──────┬───────┘                       │
│     │             │                                 │
│     └──────┬──────┘                                │
│            ▼                                        │
│     ┌──────────────┐                               │
│     │ Merge Node   │  最終出力の統合                 │
│     │              │  メタデータ抽出                 │
│     └──────┬───────┘                               │
│            │                                        │
│            ▼                                        │
│      Final Output                                   │
└─────────────────────────────────────────────────────┘
```

**各ノードの詳細**:

1. **Safety Node** (`backend/core/agent_graph/nodes.py`)
   - 有害なコンテンツをブロック
   - ルール違反をチェック
   - 早期リターンで効率化

2. **Dissonance Check**
   - 内部矛盾を検出
   - `[DISSONANCE]` タグを付与
   - 違和感の記録

3. **Depth 0 (Reflex)**
   - 瞬間的な応答
   - 単純な質問に対応
   - `[CONSENT]` タグ付与

4. **Depth 1 (Organize & Ask)**
   - より深い分析
   - 複雑な思考プロセス
   - 必要に応じてツール呼び出し

5. **Merge**
   - Depth0とDepth1の統合
   - メタデータの抽出
   - 最終出力の整形

#### 2.2. Memory System（記憶システム）

**二層記憶アーキテクチャ**:

```
┌──────────────────────────────────────────────────────┐
│                  Memory System                       │
│                                                      │
│  ┌────────────────────────────────────────────────┐ │
│  │          Short-Term Memory                      │ │
│  │        (Checkpointer - SQLite)                  │ │
│  │  ┌──────────────────────────────────────────┐  │ │
│  │  │  LangGraph State                         │  │ │
│  │  │  - 会話コンテキスト (最近数ターン)          │  │ │
│  │  │  - 一時的な変数                           │  │ │
│  │  │  - 実行状態                               │  │ │
│  │  └──────────────────────────────────────────┘  │ │
│  └────────────────────────────────────────────────┘ │
│                        │                             │
│                        │ 重要度判定                   │
│                        ▼                             │
│  ┌────────────────────────────────────────────────┐ │
│  │         Memory Judge (LLM-based)                │ │
│  │  - 重要度スコアリング (0.0 - 1.0)                 │ │
│  │  - サプライズ検出                                │ │
│  │  - 感情タグ考慮                                  │ │
│  └────────────────────┬───────────────────────────┘ │
│                        │ if score > threshold         │
│                        ▼                             │
│  ┌────────────────────────────────────────────────┐ │
│  │        Memory Gate (Phase 3)                    │ │
│  │  - 12固定コードで分類                            │ │
│  │  - フィルタリング (enforce モード時)             │ │
│  └────────────────────┬───────────────────────────┘ │
│                        │ if should_propose=true       │
│                        ▼                             │
│  ┌────────────────────────────────────────────────┐ │
│  │       Long-Term Memory                          │ │
│  │      (VectorStore - ChromaDB)                   │ │
│  │  ┌──────────────────────────────────────────┐  │ │
│  │  │  Embeddings + Metadata                   │  │ │
│  │  │  - 重要な事実・価値観・驚き                │  │ │
│  │  │  - セマンティック検索可能                  │  │ │
│  │  │  - 時系列・重要度でソート                  │  │ │
│  │  └──────────────────────────────────────────┘  │ │
│  └────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────┘
```

**Memory Judgeのスコアリング**:
```python
importance = base_score + emotion_bonus + surprise_bonus
# base_score: LLMによる基本評価
# emotion_bonus: [CONSENT]/[DISSONANCE]タグによる加算
# surprise_bonus: 予想外の情報に対する加算
```

**Memory Gateのコード (v1)**:
- `factual_and_actionable`
- `relationship_shift`
- `value_alignment`
- `surprise_discovery`
- など12個の固定コード

#### 2.3. Services Layer（サービス層）

| サービス | ファイル | 役割 |
|---------|---------|------|
| **AgentOrchestrator** | `services/agent_orchestrator.py` | 全サービスの統合・調整 |
| **MemoryManager** | `services/memory_manager.py` | 記憶の統一インターフェース |
| **MemoryJudge** | `services/memory_judge.py` | 重要度スコアリング |
| **MemoryGate** | `services/memory_gate.py` | 記憶フィルタリング |
| **SpeechSanitizer** | `services/speech_sanitizer.py` | 出力の浄化・タグ除去 |
| **ThoughtEngine** | `services/thought_engine.py` | 内省・メタ認知 |
| **VoiceAdapter** | `services/voice_adapter.py` | STT統合 |
| **VisionAdapter** | `services/vision_adapter.py` | 画像認識 |
| **VoicevoxClient** | `services/voicevox_client.py` | TTS統合 |
| **LLMClient** | `services/llm_client.py` | LLM API抽象化 |

---

### 3. External Dependencies（外部依存）

#### 3.1. LM Studio（ローカルLLM）
- **役割**: LLM推論エンジン
- **プロトコル**: OpenAI互換API
- **デフォルトURL**: `http://localhost:1234/v1`
- **推奨モデル**: Qwen2.5-14B-Instruct, Gemma-2-9B

#### 3.2. VOICEVOX（TTS）
- **役割**: 日本語音声合成
- **プロトコル**: REST API
- **デフォルトURL**: `http://localhost:50021`
- **オプショナル**: 音声出力が不要な場合は省略可

#### 3.3. ChromaDB（ベクトルDB）
- **役割**: 長期記憶のベクトル検索
- **ストレージ**: `backend/chroma_db_storage/`
- **埋め込み**: OpenAI互換エンベッディング

#### 3.4. SQLite（リレーショナルDB）
- **Checkpointer**: `data/checkpointer.sqlite3` (LangGraph状態)
- **Chat History**: `data/nia.sqlite3` (会話履歴・メタデータ)

---

## データフロー

### ユーザー入力 → AI応答のフロー

```
[1] User Input (Frontend)
      │
      ▼
[2] POST /api/chat/stream (Backend API)
      │
      ▼
[3] AgentOrchestrator.run_agent_stream()
      │
      ├─ 会話履歴をCheckpointerから取得
      ├─ 長期記憶をVectorStoreから検索
      └─ システムプロンプトに統合
      │
      ▼
[4] LangGraph Pipeline (5-Node)
      │
      ├─ [Safety]    有害コンテンツチェック
      ├─ [Dissonance] 内部矛盾検出
      ├─ [Depth0]    瞬間的応答生成
      ├─ [Depth1]    深い分析（必要時）
      └─ [Merge]     最終統合
      │
      ▼
[5] SpeechSanitizer.finalize_output()
      │
      ├─ 内部タグ ([CONSENT], [DISSONANCE]) の除去
      ├─ メタデータの抽出
      └─ リーク検出（システムプロンプト漏洩防止）
      │
      ▼
[6] SSE Stream (event: message, event: metadata)
      │
      ▼
[7] Frontend ChatInterface
      │
      ├─ テキストチャンクの表示
      ├─ メタデータによるアバター更新
      └─ ローカル状態の更新
      │
      ▼
[8] Memory Judge → Memory Gate → VectorStore (非同期)
      │
      └─ 重要な会話は長期記憶へ保存
```

### Review Window（Phase 2）フロー

```
[1] 敏感な内容をLLMが生成
      │
      ▼
[2] hold_required=True と判定
      │
      ▼
[3] set_review_token() → トークン生成
      │
      ▼
[4] SSE: event=hold_request, data={preview, token}
      │
      ▼
[5] Frontend: Approve / Reject ボタン表示
      │
      ├─ Approve → POST /api/review/approve
      └─ Reject  → POST /api/review/reject
      │
      ▼
[6] clear_review_token(next_merge_mode)
      │
      └─ Approve: 出力を続行
         Reject:  "WAIT" のまま終了
```

---

## 設計原則

### 1. メタ認知システム

ニアは自身の発言に対して内部タグを付与します。

**内部タグの種類**:
- `[CONSENT]`: 納得・同意
- `[DISSONANCE]`: 違和感・矛盾
- `[PONDERING]`: 熟考中
- `[SURPRISE]`: 驚き

**処理フロー**:
```
LLM生成 → タグ付き出力
   "これは面白いですね [CONSENT]"
           ↓
SpeechSanitizer
           ↓
   ユーザー表示: "これは面白いですね"
   メタデータ: {emotion: "consent"}
           ↓
   - AvatarView: 頷きアニメーション
   - MemoryJudge: importance += 0.5
```

### 2. 非交渉可能な原則

詳細は [NIA_NON_NEGOTIABLE.md](NIA_NON_NEGOTIABLE.md) を参照。

**主な原則**:
1. 早急な結論を避ける
2. ユーザーの思考を操作しない
3. 記憶を誇示しない ("I remember" を避ける)
4. 沈黙の権利を持つ
5. 自己説明を避ける ("I'm an AI" を避ける)

**実装**: `backend/services/non_negotiable.py` でチェック

### 3. ストリーミングファーストアーキテクチャ

- すべての応答はSSEストリーミング
- リアルタイムサニタイゼーション
- チャンク単位でのメタデータ送信

### 4. 長期記憶の哲学

- **保存時**: 物語化しない（生のデータ）
- **取り出し時**: 意味付けする（コンテキスト依存）
- **重要度**: AI自身が判断（ユーザー指示なし）

---

## API構造

### エンドポイント階層

```
/
├─ /health              (GET)  ヘルスチェック
├─ /api/
│  ├─ /chat/
│  │  └─ /stream        (POST) SSEストリーミングチャット
│  ├─ /review/
│  │  ├─ /approve       (POST) レビュー承認
│  │  └─ /reject        (POST) レビュー拒否
│  ├─ /actions/
│  │  └─ /pending       (GET)  保留アクション一覧
│  └─ /memories/
│     ├─ /search        (GET)  記憶検索
│     └─ /explore       (GET)  記憶グラフ
└─ /stats/
   ├─ /summary          (GET)  統計サマリー
   └─ /memory           (GET)  メモリ使用状況
```

### SSEイベント構造

```typescript
// メッセージチャンク
event: message
data: {"text": "こんにちは"}

// メタデータ
event: metadata
data: {"emotion": "consent", "tags": ["pondering"]}

// レビュー要求
event: hold_request
data: {"preview": "...", "token": "abc123"}

// ストリーム終了
event: done
data: {"final_text": "..."}
```

---

## パフォーマンス考慮事項

### 1. LLM推論の最適化
- ローカルLLM使用で低レイテンシ
- ストリーミング生成でユーザー体験向上
- モデルサイズの選択（速度 vs 精度）

### 2. メモリアクセスパターン
- 短期記憶（Checkpointer）: O(1) アクセス
- 長期記憶（VectorStore）: セマンティック検索（近似最近傍）
- キャッシング戦略: 頻繁な検索結果をメモリ保持

### 3. 非同期処理
- Memory判定は非同期で実行
- SSEストリームをブロックしない
- バックグラウンドワーカーで重い処理

---

## セキュリティ

### 1. 出力サニタイゼーション
- システムプロンプト漏洩防止
- 内部タグの除去
- リアルタイムでの検出・ブロック

### 2. Review Window
- 敏感な出力の事前承認
- ユーザー明示的同意
- トークンベースの検証

### 3. データプライバシー
- ローカルストレージ（外部送信なし）
- ユーザーデータは `.gitignore`
- 個人情報の記憶は慎重に扱う

---

## 拡張性

### 1. プラグインアーキテクチャ
- サービス層は疎結合
- 新しいサービスを容易に追加可能
- DIパターンでテストしやすい

### 2. モデル交換可能性
- LLMClient抽象化
- OpenAI互換APIであれば交換可能
- エンベッディングモデルも交換可能

### 3. フロントエンド拡張
- コンポーネントベース設計
- 新しいUIを容易に追加
- モバイル対応も可能

---

**このアーキテクチャは、長期的な関係性を築くAIコンパニオンの実現を目指して設計されています。**
