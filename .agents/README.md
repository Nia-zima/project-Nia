# .agents/ — Agent Knowledge Base

このディレクトリは **project-nia 用の外部記憶の入口** です。  
会話メモリに依存せず、ChatGPT / Claude / Codex など別 AI が現在地を短時間で復元するために使います。

## 読む順番

1. `context.md` — 現在地の超要約
2. `current_tasks.md` — 今見るべきタスクだけ
3. `decisions.md` — 重要判断の索引
4. `preferences.md` — ユーザーの好みと進め方
5. `source_of_truth.md` — 正本の場所

必要に応じて:
- `session_log/` — 日ごとの作業要約
- `patterns/` — docs 更新・レビューの定型

## 正本との関係

`.agents/` は入口で、詳細の正本は既存 docs 側です。  
`.agents/` 側に詳細仕様や長い履歴を増やしすぎないこと。

| ファイル | 役割 |
|---------|------|
| `CLAUDE.md` | プロジェクト憲章・不可侵ルール・現在地一覧 |
| `docs/assistant_context.md` | AI 共通の現在地要約（正本） |
| `docs/session_handoff.md` | 最新の停止位置（正本） |
| `docs/decision_log.md` | 重要判断の詳細（正本） |
| `.agents/` | 別 AI が最初に読む薄い index / shortcut layer |

## 更新ルール

- セッション終了時に `context.md` と `current_tasks.md` を短く更新
- 重要判断が増えたら `decisions.md` に「何を見ればよいか」だけ追記
- ユーザーの好みが増えたら `preferences.md` に追記
- 長い作業は `session_log/YYYY-MM-DD.md` に残す

## 原則

- docs の正本を書き換える代わりにしない
- `.agents/` は「最初に読む要約」に徹する
- 詳細な現状、設計、判断理由は docs 側へリンクする
- 履歴の説明コストを減らすのが目的
