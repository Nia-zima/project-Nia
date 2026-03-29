# 📘 ニア(Near) 運用マニュアル

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
