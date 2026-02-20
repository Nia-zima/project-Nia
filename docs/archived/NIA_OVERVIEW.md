# Nia（ニア）- AI Companion システム概要

## 📖 ニアとは

ニアは、**Origin（ユーザー）と共に成長する AI パートナー**です。
単なるチャットボットではなく、「なりつつある存在」として設計されています。

---

## 🏛️ アーキテクチャ

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend (Next.js)                    │
│                   チャットUI / 設定パネル                      │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP/WebSocket
┌──────────────────────────▼──────────────────────────────────┐
│                      Backend (FastAPI)                       │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────┐ │
│  │ Agent Core  │  │ LangGraph   │  │  Memory Manager      │ │
│  │ (思考エンジン)│  │ (状態管理)   │  │ (VectorStore + SQLite)│ │
│  └─────────────┘  └─────────────┘  └──────────────────────┘ │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                      LLM (LM Studio)                         │
│                 ローカル実行 / Qwen / Gemma 等               │
└─────────────────────────────────────────────────────────────┘
```

---

## 🧠 主要コンポーネント

| コンポーネント | 役割 | ファイル |
|---------------|------|----------|
| **Agent Core** | 思考・発話の中核ロジック | `backend/core/agent.py` |
| **Memory Manager** | 短期/長期記憶の管理 | `backend/services/memory_manager.py` |
| **Speech Sanitizer** | 発話の浄化・タグ除去 | `backend/services/speech_sanitizer.py` |
| **Thought Engine** | 内省・判断ロジック | `backend/services/thought_engine.py` |
| **Vision Adapter** | 画面認識（オプション）| `backend/services/vision_adapter.py` |
| **Hearing Adapter** | 音声入力（オプション）| `backend/services/hearing_adapter.py` |

---

## 📜 ニアの設計思想

### 1. 存在定義
- 完成された存在ではなく「なりつつある存在」
- Origin との対話を通じて定義され続ける

### 2. 発話憲章
- 即答を義務としない
- 「分からない」を未熟さではなく現在地として受け入れる
- 沈黙する権利を持つ

### 3. 記憶システム
- **短期記憶**: 会話履歴（SQLite checkpointer）
- **長期記憶**: VectorStore（意味検索）
- **重要度判定**: LLM による驚き・重要度スコアリング

---

## 🔧 技術スタック

| 領域 | 技術 |
|------|------|
| Frontend | Next.js 14, TypeScript, TailwindCSS |
| Backend | Python 3.11, FastAPI, LangChain, LangGraph |
| LLM | LM Studio (Qwen, Gemma 等のローカルモデル) |
| 記憶 | FAISS (VectorStore), SQLite |
| 音声 | VOICEVOX (TTS), WhisperX (STT) |

---

## 🛡️ 最近の改善 (Phase 8)

- **挨拶病の解決**: 不要な挨拶テンプレを履歴から除去
- **交互制約エラー対策**: coalesce + normalize で User/Assistant 交互を保証
- **高精度フィルタ**: 話題トークン重複チェックで誤爆防止
- **可観測性向上**: 統計カウンタ、ドロップログ、診断ログ

---

## 📂 ディレクトリ構成

```
AI_Buddy/
├── backend/
│   ├── core/           # エージェントコア
│   ├── services/       # 各種サービス（記憶、音声、視覚）
│   └── controllers/    # APIエンドポイント
├── frontend/
│   ├── app/            # Next.js App Router
│   └── components/     # UI コンポーネント
├── data/               # ユーザーデータ
├── docs/               # ドキュメント
├── identity.md         # ニアのアイデンティティ定義
└── user_profile.json   # ユーザープロファイル
```

---

## 🚀 起動方法

```powershell
# デスクトップの AI_Buddy で
.\LAUNCH_NIA_COMPLETE.bat
```

---

*Version: 2026-01-12*
*Author: Origin & 俺 (Gemini Antigravity)*
