# AI_Buddy (Nia)

> Origin（ユーザー）と共に成長するAIコンパニオンシステム

## 📖 概要

**Nia（ニア）** は、単なるチャットボットではありません。
「なりつつある存在」として設計された、長期的な関係性を築くAIパートナーです。

### ニアの特徴

- **成長する存在**: 事前に完成されたキャラクターではなく、対話を通じて徐々に形成される
- **誠実な応答**: 知らないことは「知らない」と言う。早急な結論を避ける
- **長期記憶**: 重要な会話や価値観を記憶し、関係性の文脈を保持
- **メタ認知**: 自身の発言に対する「納得」「違和感」を内部的に認識
- **非操作的**: ユーザーを特定の方向に誘導せず、自律的な判断を尊重

## ✨ 主な機能

### 1. メタ認知システム
ニアは自身の発言に対して内部タグ（`[CONSENT]`、`[DISSONANCE]`など）を付与し、それを記憶の重要度判定や身体表現（アバター）に反映します。

### 2. 長期記憶（二層構造）
- **短期記憶（Checkpointer）**: 会話の文脈を一時保持
- **長期記憶（VectorStore）**: 重要な事実・価値観・驚きを永続化

### 3. LangGraph思考パイプライン
5ノード構成の思考プロセス:
1. **Safety Node**: 有害な内容をブロック
2. **Dissonance Check**: 内部矛盾を検出
3. **Depth 0 (Reflex)**: 瞬間的な応答
4. **Depth 1 (Organize & Ask)**: より深い分析
5. **Merge**: 最終出力の統合

### 4. 3Dアバター
感情状態に応じたプロシージャルアニメーション（VRMモデル対応）

### 5. レビューウィンドウ
敏感な出力は事前承認が必要な仕組み（Phase 2機能）

## 🏗️ アーキテクチャ

```
┌─────────────────────────────────────────────────────────┐
│          Frontend (Next.js 14 + TypeScript)             │
│  Chat UI • Memory Explorer • Settings • 3D Avatar       │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP/WebSocket/SSE
┌────────────────────────▼────────────────────────────────┐
│      Backend (FastAPI + Python 3.12)                    │
│                                                         │
│  ┌──────────────────┐  ┌──────────────────┐             │
│  │  Agent Core      │  │  LangGraph       │             │
│  │  (Thinking       │  │  (State          │             │
│  │  & Response)     │  │  Management)     │             │
│  └──────────────────┘  └──────────────────┘             │
│                                                         │
│  ┌──────────────────┐  ┌──────────────────┐             │
│  │  Memory System   │  │  Services Layer  │             │
│  │  (Vector + SQL)  │  │  (Processing)    │             │
│  └──────────────────┘  └──────────────────┘             │
└────────────────────────┬────────────────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
    ┌───▼───┐       ┌────▼────┐      ┌───▼───┐
    │LM Studio│      │VOICEVOX │      │Vision │
    │(Local LLM)    │(TTS)     │      │(Image)│
    └────────┘       └──────────┘      └───────┘
```

詳細は [ARCHITECTURE.md](docs/ARCHITECTURE.md) を参照してください。

## 📋 システム要件

### 必須
- **Python**: 3.12 以上
- **Node.js**: 18 以上
- **Git**: バージョン管理

### 推奨
- **OS**: Windows 10/11, macOS 12+, Linux (Ubuntu 20.04+)
- **RAM**: 16GB以上
- **ストレージ**: 10GB以上の空き容量
- **GPU**: CUDA対応GPU（オプション、LLM推論の高速化）

### 外部依存
- **LM Studio**: ローカルLLM実行環境（Qwen, Gemma等）
- **VOICEVOX**: 日本語TTS（オプション）

## 🚀 クイックスタート

### 1. 環境構築

```bash
# リポジトリのクローン
git clone https://github.com/yourusername/AI_Buddy.git
cd AI_Buddy

# バックエンド
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# フロントエンド
cd frontend
npm install
cd ..
```

### 2. 環境変数の設定

`.env` ファイルをプロジェクトルートに作成:

```env
# LM Studio (ローカルLLM)
LLM_BASE_URL=http://localhost:1234/v1
LLM_MODEL_NAME=qwen2.5-14b-instruct

# VOICEVOX (TTS)
VOICEVOX_URL=http://localhost:50021

# その他
LOG_LEVEL=INFO
```

### 3. 起動

```bash
# バックエンド
python -m backend.server

# 別ターミナルでフロントエンド
cd frontend
npm run dev
```

**アクセス**: `http://localhost:3000`

詳細な手順は [SETUP.md](docs/SETUP.md) を参照してください。

## 📚 ドキュメント

| ドキュメント | 説明 |
|------------|------|
| [SETUP.md](docs/SETUP.md) | 詳細なセットアップガイド |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | システムアーキテクチャ詳細 |
| [DIRECTORY_MAP.md](docs/DIRECTORY_MAP.md) | プロジェクト構造 |
| [NIA_OVERVIEW.md](docs/NIA_OVERVIEW.md) | ニアの概要と設計思想 |
| [OPERATION_MANUAL.md](docs/OPERATION_MANUAL.md) | 運用マニュアル |
| [NIA_NON_NEGOTIABLE.md](docs/NIA_NON_NEGOTIABLE.md) | 非交渉可能な原則 |
| [identity.md](identity.md) | ニアのアイデンティティ定義 |

## 🧪 テスト

### 全テスト実行
```bash
python -m pytest
```

### 個別テスト
```bash
# 安全性テスト
python tests/test_safety_spec.py

# API統合テスト
python tests/test_api_integration.py

# レビューウィンドウテスト
python -m pytest -q tests/test_review_window.py

# E2Eテスト（サーバー起動が必要）
$env:E2E_BASE_URL="http://127.0.0.1:8000"
python -m pytest -q -m e2e
```

---

## 📖 技術詳細（開発者向け）

### Backend Entry Point
`backend.server:app` を正式なFastAPIエントリポイントとして使用してください。

> `backend.app.main` は後方互換性のため残されていますが、非推奨です。

### Backend起動

```bash
# 開発サーバー
python -m backend.server

# ヘルスチェック
curl http://localhost:8000/health
```

### ログ設定

デフォルトログレベル: `INFO`

環境変数でカスタマイズ可能:
```bash
# PowerShell
$env:LOG_LEVEL="WARNING"
$env:LOG_MAX_BYTES="5242880"
$env:LOG_BACKUP_COUNT="3"
python -m backend.server
```

### Frontend起動

```bash
cd frontend
npm install
npm run dev
```

**アクセス**: `http://localhost:3000`

### CLI Scripts（目的別）

#### 開発/対話
```bash
# コンソールチャット
python scripts/console_chat.py
```

#### 診断/検査
```bash
# メモリパイプライン診断
python scripts/diagnose_memory_pipeline.py

# DB整合性チェック
python -m backend.scripts.debug_check_db

# Judge監査
python -m backend.tools.judge_inspector
```

#### 章/運用
```bash
# 章の振り返り
python -m backend.scripts.chapter_reflection

# 章の決裁
python -m backend.scripts.chapter_decision

# スリープサイクル（手動）
python -m backend.scripts.sleep_cycle
```

## 🔧 Review Window (Phase2)

レビューウィンドウは、敏感な出力を事前承認する仕組みです。

### 動作仕様

#### A) Open Condition (review_request)
- HoldPlannerが `hold_required=True` を決定 → 即座に `set_review_token()` を呼び出し
- トークン生成は単一エントリポイント（他の場所では生成しない）
- `review_request` フラグが明示的なトリガー

#### B) Close Condition (clear)
- Approve成功 → `clear_review_token(next_merge_mode="B")`
- Reject成功 → `clear_review_token(next_merge_mode="wait")` (`final_text` は "WAIT" のまま)
- 待機中に新規入力 → キャンセル + `clear_review_token(next_merge_mode="wait")`

#### C) HOLD出力仕様
- 保留中は `final_text` が `"WAIT"` (単一の真実の源)
- UIはSSE `hold_request` イベントでプレビュー + Approve/Rejectボタンを表示
- UIが未対応の場合、`"WAIT"` のみが返される（安全なデフォルト）

#### D) トークン有効期限
- トークンは1ターンのみ有効
- 新規ユーザー入力で前回のトークンは無効化（キャンセル）

### Review API

#### Approve
```bash
curl -X POST http://127.0.0.1:8000/api/review/approve \
  -H "Content-Type: application/json" \
  -d '{"thread_id":"default_thread","review_token":"REVIEW_TOKEN_HERE"}'
```

#### Reject
```bash
curl -X POST http://127.0.0.1:8000/api/review/reject \
  -H "Content-Type: application/json" \
  -d '{"thread_id":"default_thread","review_token":"REVIEW_TOKEN_HERE"}'
```

#### レスポンス
```json
{ "ok": true, "applied": true, "reason": null }
```

トークン不一致の場合は no-op (HTTP 200, `applied=false`)。

## 🧠 Phase3 v1 (Gate) Overview

Memory Gateは、記憶すべき内容を選別するフィルタリングシステムです。

### Gate モード
- **off**: Gate無効（デフォルト）
- **log_only**: Gate実行 + ログ記録のみ（enqueueは実行）
- **enforce**: Gate実行 + `should_propose=false` の場合はenqueueをブロック

### rationale_code (v1 固定12コード)
v1では12個の固定コードを使用（`backend/services/gate_codes.py` 参照）。
新コード（例: `implied_by_style`）はv1.1+で計画中。

### weight定義（APPLIED bonusのみ）
- `label=1 (APPLIED)` → immediate-dwell bonus:
  `weight = 1.0 + clamp((300 - dwell_sec) / 300, 0, 1) * 0.5`
- `label=0 (REJECTED)` → 常に `weight=1.0`

### Dataset Builder
```bash
python dataset_builder.py --db data/nia.sqlite3 --out data.jsonl --since 0 --limit 0 \
  --out_gold gold.jsonl --max_user_text_chars 800 --max_candidate_chars 800
```

## 📋 ADRs (Architecture Decision Records)

- [001-phase3-pending-actions-review-request.md](docs/adr/001-phase3-pending-actions-review-request.md)
  Phase3 v0の保留アクションとレビュー要求の連携

## 📝 ライセンス

このプロジェクトは個人プロジェクトです。商用利用・再配布については作者に問い合わせてください。

---

**Nia v2.1 – Emergent / Origin Edition**
