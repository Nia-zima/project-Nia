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
    - `chapter_title.txt`: 今の章タイトル
    - `current_vibe.txt`: 今の気分

### ③ 就寝 (Sleep Cycle)
**★重要: 一日の終わりに必ず実行。**
```bash
python -m backend.scripts.sleep_cycle
```
- **処理内容:**
    - 記憶の整理（Private Memoryへの定着）。
    - 配信ノイズ（Stream Memory）の無視・破棄。
    - 人格の微調整（Guardianによる保護）。

## 🗓️ 2. 週次ルーティン (Weekly Evolution)
**目的:** 過去1週間（1つの章）を振り返り、人格を進化させるか決める。
**推奨:** 週末に手動実行。

### ① 章の生成 (Reflection)
```bash
python -m backend.scripts.chapter_reflection
```
- **結果:** `logs/chapters/` に振り返りデータが生成される。
- **注意:** この時点では人格は変わらない。

### ② 人間による決裁 (Decision) ★最重要
```bash
python -m backend.scripts.chapter_decision
```
- 提案内容を見て判断する。
    - `[a]ccept`: 承認 (人格に反映)
    - `[r]eject`: 却下 (破棄)
    - `[h]old`: 保留 (現状維持)
- **心構え:** 「無理に変える必要はない」。Holdも立派な選択。

## 🛡️ 3. 緊急時の対応
- **変なことを言い出した:**
    - `identity.md` を開き、該当する記述（Recent Learnings等）を手動削除する。
- **章の提案がおかしい:**
    - `chapter_decision.py` で `[r]eject` する。
