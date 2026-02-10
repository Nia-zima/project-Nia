# セットアップガイド

このガイドでは、AI_Buddy (Nia) を開発環境でセットアップする手順を説明します。

---

## 📋 前提条件

### 必須ソフトウェア

| ソフトウェア | バージョン | ダウンロード |
|------------|----------|------------|
| Python | 3.12 以上 | [python.org](https://www.python.org/downloads/) |
| Node.js | 18 以上 | [nodejs.org](https://nodejs.org/) |
| Git | 最新版 | [git-scm.com](https://git-scm.com/) |

### 推奨環境

- **OS**: Windows 10/11, macOS 12+, Linux (Ubuntu 20.04+)
- **RAM**: 16GB以上（LLM実行のため）
- **ストレージ**: 10GB以上の空き容量
- **GPU**: CUDA対応GPU（オプション、LLM推論の高速化）

### 外部依存サービス

| サービス | 用途 | 必須 |
|---------|------|-----|
| **LM Studio** | ローカルLLM実行環境 | ✅ 必須 |
| **VOICEVOX** | 日本語TTS | ❌ オプション |

---

## 1. リポジトリのクローン

```bash
# HTTPS経由でクローン
git clone https://github.com/yourusername/AI_Buddy.git
cd AI_Buddy

# または SSH経由
git clone git@github.com:yourusername/AI_Buddy.git
cd AI_Buddy
```

---

## 2. バックエンドのセットアップ

### 2.1. 仮想環境の作成

**Windows (PowerShell)**:
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

**macOS / Linux**:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

仮想環境が有効になると、ターミナルのプロンプトに `(.venv)` が表示されます。

### 2.2. 依存関係のインストール

```bash
# 依存関係のインストール
pip install -r requirements.txt

# インストール確認
pip list
```

**主な依存関係**:
- `fastapi`: Webフレームワーク
- `langchain`, `langgraph`: LLM orchestration
- `chromadb`: ベクトルデータベース
- `aiosqlite`: 非同期SQLite
- `httpx`: HTTPクライアント

### 2.3. 環境変数の設定

プロジェクトルートに `.env` ファイルを作成します。

**.env ファイルの例**:
```env
# ═══════════════════════════════════
# LLM Configuration (LM Studio)
# ═══════════════════════════════════
LLM_BASE_URL=http://localhost:1234/v1
LLM_MODEL_NAME=qwen2.5-14b-instruct
LLM_API_KEY=dummy  # LM Studioでは不要だが、一部のライブラリが要求する場合がある

# ═══════════════════════════════════
# TTS Configuration (VOICEVOX)
# ═══════════════════════════════════
VOICEVOX_URL=http://localhost:50021
VOICEVOX_SPEAKER_ID=1  # デフォルト話者ID

# ═══════════════════════════════════
# Vision API (Optional)
# ═══════════════════════════════════
# VISION_API_KEY=your_api_key_here

# ═══════════════════════════════════
# Logging
# ═══════════════════════════════════
LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR
LOG_MAX_BYTES=5242880  # 5MB
LOG_BACKUP_COUNT=3

# ═══════════════════════════════════
# Memory Gate (Phase 3)
# ═══════════════════════════════════
GATE_MODE=off  # off, log_only, enforce
```

### 2.4. データベースの初期化

データベースは初回起動時に自動的に作成されます。

**手動で初期化する場合**:
```bash
python -m backend.scripts.debug_check_db
```

**データベースファイル**:
- `data/nia.sqlite3`: 会話履歴・記憶メタデータ
- `data/checkpointer.sqlite3`: LangGraph状態管理
- `backend/chroma_db_storage/`: ベクトルデータベース（ChromaDB）

### 2.5. LM Studioのセットアップ

#### インストール
1. [LM Studio公式サイト](https://lmstudio.ai/)からダウンロード
2. インストール後、起動

#### モデルのダウンロード
1. LM Studioで `Search` タブを開く
2. 推奨モデル:
   - **Qwen2.5-14B-Instruct** (高性能)
   - **Gemma-2-9B-Instruct** (軽量)
   - **Phi-3-Medium** (バランス)
3. モデルをダウンロード

#### サーバーの起動
1. LM Studioで `Local Server` タブを開く
2. ダウンロードしたモデルを選択
3. `Start Server` をクリック
4. デフォルトで `http://localhost:1234` で起動

**起動確認**:
```bash
curl http://localhost:1234/v1/models
```

### 2.6. VOICEVOXのセットアップ（オプション）

#### インストール
1. [VOICEVOX公式サイト](https://voicevox.hiroshiba.jp/)からダウンロード
2. インストール後、起動

#### 設定
1. VOICEVOXを起動（デフォルトで `http://localhost:50021` で動作）
2. 話者を選択（デフォルト: ずんだもん）

**起動確認**:
```bash
curl http://localhost:50021/speakers
```

---

## 3. フロントエンドのセットアップ

### 3.1. 依存関係のインストール

```bash
cd frontend
npm install
```

**主な依存関係**:
- `next`: Next.js フレームワーク
- `react`: UIライブラリ
- `tailwindcss`: CSSフレームワーク
- `framer-motion`: アニメーション
- `lucide-react`: アイコン

### 3.2. 環境変数の設定（オプション）

フロントエンドは通常、環境変数を必要としませんが、必要に応じて `frontend/.env.local` を作成できます。

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

---

## 4. 起動

### 4.1. バックエンドの起動

**ターミナル1 (バックエンド)**:
```bash
# プロジェクトルートで
python -m backend.server
```

**起動ログ例**:
```
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

**ヘルスチェック**:
```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

### 4.2. フロントエンドの起動

**ターミナル2 (フロントエンド)**:
```bash
cd frontend
npm run dev
```

**起動ログ例**:
```
  ▲ Next.js 14.x.x
  - Local:        http://localhost:3000
  - Network:      http://192.168.x.x:3000

 ✓ Ready in 2.3s
```

### 4.3. アクセス

ブラウザで `http://localhost:3000` を開きます。

**初回起動時**:
- チャット画面が表示されます
- LM Studioが起動していることを確認してください
- 「こんにちは」などと入力してテスト

---

## 5. トラブルシューティング

### 5.1. バックエンドが起動しない

#### エラー: `ModuleNotFoundError`
**原因**: 依存関係がインストールされていない

**解決策**:
```bash
pip install -r requirements.txt
```

#### エラー: `Address already in use`
**原因**: ポート8000が既に使用されている

**解決策**:
```bash
# Windowsでポートを確認
netstat -ano | findstr :8000

# プロセスを終了
taskkill /PID <プロセスID> /F

# または別のポートで起動
uvicorn backend.server:app --port 8001
```

### 5.2. LM Studioに接続できない

#### エラー: `Connection refused`
**原因**: LM Studioが起動していない、または別のポートで動作している

**解決策**:
1. LM Studioを起動
2. `Local Server` タブで `Start Server` をクリック
3. `.env` の `LLM_BASE_URL` を確認

**接続テスト**:
```bash
curl http://localhost:1234/v1/models
```

### 5.3. フロントエンドが起動しない

#### エラー: `npm ERR! Missing script: "dev"`
**原因**: `package.json` が存在しないか、正しいディレクトリにいない

**解決策**:
```bash
cd frontend
npm install
npm run dev
```

#### エラー: `EADDRINUSE: address already in use`
**原因**: ポート3000が既に使用されている

**解決策**:
```bash
# 別のポートで起動
npm run dev -- -p 3001
```

### 5.4. データベースエラー

#### エラー: `database is locked`
**原因**: 複数のプロセスが同じDBにアクセスしている

**解決策**:
1. 全てのバックエンドプロセスを終了
2. WALファイルを削除:
   ```bash
   rm data/*.sqlite3-wal data/*.sqlite3-shm
   ```
3. 再起動

### 5.5. メモリ不足エラー

#### エラー: `Out of memory` または応答が非常に遅い
**原因**: LLMモデルが大きすぎる

**解決策**:
1. より小さいモデルを使用（例: Phi-3-Mini）
2. LM Studioの設定で `GPU Offload` を調整
3. RAMを増設

### 5.6. CORS エラー

#### エラー: ブラウザコンソールで `CORS policy` エラー
**原因**: フロントエンドとバックエンドのオリジンが異なる

**解決策**:
`backend/server.py` でCORS設定を確認:
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # フロントエンドのURL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## 6. 次のステップ

セットアップが完了したら:

1. **基本的な会話テスト**: チャットインターフェースで会話してみる
2. **メモリ機能の確認**: 重要な情報を伝えて、後で覚えているか確認
3. **ログの確認**: `backend/logs/app.log` でシステムの動作を確認
4. **ドキュメントを読む**: [ARCHITECTURE.md](ARCHITECTURE.md) でシステムの詳細を理解

---

## 7. 開発用コマンド

### テスト実行
```bash
# 全テスト
python -m pytest

# 特定のテスト
python -m pytest tests/test_safety_spec.py -v
```

### データベースのリセット
```bash
# 注意: 全ての会話履歴が削除されます
rm data/nia.sqlite3 data/checkpointer.sqlite3
rm -r backend/chroma_db_storage/
```

### ログの確認
```bash
# リアルタイムでログを確認
tail -f backend/logs/app.log

# Windows (PowerShell)
Get-Content backend/logs/app.log -Wait -Tail 50
```

### デバッグモードで起動
```bash
# 環境変数でログレベルを変更
export LOG_LEVEL=DEBUG  # Windowsは `$env:LOG_LEVEL="DEBUG"`
python -m backend.server
```

---

## 8. 本番デプロイ（参考）

本番環境へのデプロイは、このプロジェクトの範囲外ですが、参考までに:

### 注意事項
- ローカルLLM（LM Studio）は開発環境向けです
- 本番環境では、専用のLLMサーバーまたはクラウドAPIを使用してください
- データベースはSQLiteからPostgreSQLなどに移行を検討
- `.env` ファイルは `.gitignore` に含まれているか確認

---

**セットアップに問題がある場合は、[Issues](https://github.com/yourusername/AI_Buddy/issues) で報告してください。**
