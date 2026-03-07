from pathlib import Path

from backend.core.config import settings

# プロジェクトルートの特定
PROJECT_ROOT = settings.PROJECT_ROOT
DOCS_DIR = PROJECT_ROOT / "docs"

# 1. 運用マニュアル (OPERATION_MANUAL.md)
MANUAL_TEXT = """# 📘 ニア(Near) 運用マニュアル

## 📅 1. 日次ルーティン (Daily Loop)
**目的:** ニアと話し、配信し、一日の終わりに記憶を整理する。

### ① 起動 (Start)
1. **LLMサーバー起動:** LM Studio / Ollama 等を起動。
2. **広報官 (OBS連携) 起動:**
   ```bash
   python -m backend.scripts.obs_writer
   ```
3. **ニア本体 起動:**
   ```bash
   python -m backend.core.agent
   ```

### ② 活動中 (Activity)
- **会話:** 普通に話しかける。
- **配信:** OBSに `obs_output/` 内のテキストファイルを表示。

### ③ 就寝 (Sleep Cycle)
**★重要: 一日の終わりに必ず実行。**
```bash
python -m backend.scripts.sleep_cycle
```
- **処理内容:**
    - 記憶の整理（Private Memoryへの定着）。
    - 配信ノイズ（Stream Memory）の無視・破棄。
    - 人格の微調整（Guardianによる保護）。
    - R.4 日横断パターン抽出（3日+の蓄積で自動実行）。
    - N.3 Self-Model 更新（identity.md Recent Learnings）。

## 🛡️ 2. 緊急時の対応
- **変なことを言い出した:**
    - `identity.md` を開き、該当する記述（Recent Learnings等）を手動削除する。
- **Identity提案がおかしい:**
    - フロントエンドのアイデンティティパネルから却下する。
"""

# 2. システム仕様書 (SYSTEM_SPEC.md)
SPEC_TEXT = """# ⚙️ ニア(Near) システム仕様書

## 1. 記憶システム (The Brain)
- **Private Memory:** 信頼度100%。あなたとの会話・約束を永久保存。
- **Stream Memory:** 信頼度減衰。配信コメント等は時間が経つと自動消滅(GC)。
- **Fail-Safe:** 配信メタデータ欠損時は自動で最大警戒モードになり汚染を防ぐ。

## 2. 防御システム (The Shield)
- **Audience Safety Layer v2:** 群衆の「数」「悪意」を検知し影響力を弱める。
- **Stream Digest (Phase 4.5):** 配信記憶は物理削除され、「抽象的な雰囲気（天気図）」だけが外伝として残る。
- **Allow List:** 「学習許可」がない記憶は、寝ている間に夢に見ることすら許されない。

## 3. 人格進化 (The Soul)
- **Guardian (Layer B):** 人格の管理者。急激な変化や性格の改変をブロックする。
- **R.4 CrossDay Distillation:** 日横断パターンを自動抽出し semantic_memories に保存。
- **Identity Proposals:** 重要な変更は identity_proposals テーブルで承認待ち。フロントエンドから承認/却下。

## 4. インターフェース (The Interface)
- **OBS連携 (Phase 6):** `obs_writer` が人格回路と絶縁された状態でテキストを出力。

## 三権分立:
- **AI:** 考える (Reflection)
- **人間:** 決める (Decision)
- **システム:** 従う (Sleep Cycle)
"""

# 3. ディレクトリ構造 (DIRECTORY_MAP.md)
DIR_TEXT = """# 📂 ディレクトリマップ

| パス | 説明 | 重要度 |
| :--- | :--- | :--- |
| `identity.md` | ニアの魂。 ここが変わると性格が変わる。 | ★★★ |
| `backend/core/config.py` | 設定ファイル。APIキーやURLはここ。 | ★★★ |
| `sleep_outputs/` | Sleep Cycle 出力（日記、自己モデル等）。 | ★★☆ |
| `logs/judge_audit.jsonl` | 会話ログ。全ての記憶判断の記録。 | ★★☆ |
| `logs/world_context/` | 外伝ダイジェスト。配信の空気感。 | ★☆☆ |
| `obs_output/` | 配信表示用テキスト。OBSはここを見る。 | ★☆☆ |
| `chroma_db/` | 記憶データベース（ベクトルストア）。 | ★★★ |
"""

def generate():
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Manual
    with open(DOCS_DIR / "OPERATION_MANUAL.md", "w", encoding="utf-8") as f:
        f.write(MANUAL_TEXT)
    
    # Specs
    with open(DOCS_DIR / "SYSTEM_SPEC.md", "w", encoding="utf-8") as f:
        f.write(SPEC_TEXT)
    
    # Dir Map
    with open(DOCS_DIR / "DIRECTORY_MAP.md", "w", encoding="utf-8") as f:
        f.write(DIR_TEXT)
    
    print(f"✅ Documentation generated in: {DOCS_DIR}")
    print("   - OPERATION_MANUAL.md")
    print("   - SYSTEM_SPEC.md")
    print("   - DIRECTORY_MAP.md")

if __name__ == "__main__":
    generate()
