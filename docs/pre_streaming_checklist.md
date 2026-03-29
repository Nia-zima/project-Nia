# 配信前チェックリスト

> 2026-02-15 コード監査結果に基づく。ニアを外部公開（配信・マルチユーザー）する前に対応すべき項目。

---

## Critical — 配信前に必須

### 1. Safety ゲートの実装
- **現状**: `safety_interrupt` が常に `"safe"` を返す stub 実装
- **リスク**: 第三者入力（視聴者コメント等）に対して危険検出・停止が一切行われない
- **対象**: [nodes.py:661-679](../backend/core/agent_graph/nodes.py#L661-L679), [graph.py:54](../backend/core/agent_graph/graph.py#L54)
- **対応案**:
  - [ ] キーワードベースの即時ブロック（暴力・個人情報要求等）
  - [ ] LLM ベースの意図分類（オプション、レイテンシとのトレードオフ）
  - [ ] ブロック時の応答テンプレート（「その話題は答えられないよ」等）
- **優先度**: 配信開始前に最低限キーワードベースは必須

### 2. Phase2 MED判定の有効化
- **現状**: `review_window.py` に reason_code 定義はあるが、merge_output 内で keyword 系チェックが未実装。`GUARDRAIL_V2_ENABLED=False`
- **リスク**: 配信中にニアが不適切発言をしても HOLD がかからない
- **対象**: [review_window.py:25-49](../backend/core/agent_graph/review_window.py#L25-L49), [nodes.py:1503-1533](../backend/core/agent_graph/nodes.py#L1503-L1533)
- **対応案**:
  - [ ] `GUARDRAIL_V2_ENABLED=True` にして動作検証
  - [ ] keyword 系チェック（`keyword_memory`, `keyword_policy`, `keyword_identity`）の発火ロジック追加
  - [ ] `risk_long_reply` の発火条件実装（配信中の長文独白防止）
  - [ ] HOLD 時のフロントエンド表示確認（配信画面で自然に見えるか）

---

## High — 配信前に強く推奨

### 3. Vision エンドポイントの認可
- **現状**: `/system/vision` にシステムトークン検証なし。`vision_enabled` フラグが実際の画像解析経路を止めていない
- **リスク**: 外部からの不正な画像送信による GPU リソース消費
- **対象**: [system_router.py:82-84](../backend/controllers/api/system_router.py#L82-L84), [vision_client.py:258](../backend/services/vision_client.py#L258)
- **対応案**:
  - [ ] `/system/*` エンドポイントにトークン検証ミドルウェア追加
  - [ ] `vision_enabled=False` 時に画像解析をスキップする分岐を実経路に反映

### 4. Review UI のモバイル対応
- **現状**: Review UI が ChatInterface で無効化、ActionPanel は `xl` 表示のみ
- **リスク**: モバイルから配信管理時に承認/拒否操作ができない
- **対象**: [ChatInterface.tsx:1632](../frontend/components/ChatInterface.tsx#L1632), [page.tsx:79](../frontend/app/page.tsx#L79)
- **対応案**:
  - [ ] モバイルレスポンシブ対応 or モバイル用の簡易承認 UI
  - [ ] あるいは Discord/Telegram bot 経由の承認フロー

### 5. Diagnostics の壊れた API 呼び出し
- **現状**: 存在しない API を呼び出し、例外を握り潰して既定値返却
- **リスク**: 配信中のシステム監視値がサイレントに欠落。異常に気づけない
- **対象**: [livestream_router.py:216](../backend/controllers/api/livestream_router.py#L216), [livestream_router.py:243](../backend/controllers/api/livestream_router.py#L243)
- **対応案**:
  - [ ] 呼び出し先 API の修正 or 削除
  - [ ] 握り潰しを warning ログに変更

---

## Medium — 配信後でも対応可だが早めが望ましい

### 6. 描画停止 API の session_id 未使用
- **現状**: `session_id` を受け取るが無視して現在セッションを無条件停止
- **リスク**: 複数描画セッション時に誤停止
- **対象**: [draw_router.py:28](../backend/controllers/api/draw_router.py#L28), [draw_router.py:65](../backend/controllers/api/draw_router.py#L65)
- **対応案**:
  - [ ] `session_id` による対象セッション特定ロジック追加

### 7. Identity スナップショット / Diff 不整合
- **現状**: スナップショット命名規約と Diff 生成側の期待が不一致
- **リスク**: 日次 Diff が生成されにくく、Identity の変化追跡が困難
- **対象**: [identity_manager.py:39](../backend/services/identity_manager.py#L39), [identity_diff.py:19](../backend/services/identity_diff.py#L19)
- **対応案**:
  - [ ] Diff 生成側を現在のスナップショット命名規約に合わせる
  - [ ] または命名規約を統一

### 8. Context Builder の user_query 未活用
- **現状**: `user_query` を受け取るが、semantic memories は confidence 順のみで取得。クエリ関連性を考慮していない
- **リスク**: 記憶が増えると関係のない事実がコンテキストに注入される
- **対象**: [context_builder.py:52-53](../backend/services/memory/context_builder.py#L52-L53), [context_builder.py:139-151](../backend/services/memory/context_builder.py#L139-L151)
- **対応案**:
  - [ ] `semantic_store.search_active()` に embedding ベースの類似度フィルタを追加
  - [ ] confidence × relevance のハイブリッドスコアリング

### 9. commit_log 形式の不統一
- **現状**: レビュー系と pending-memory 系で commit_log のフォーマットが異なる
- **リスク**: 集計や教師データ整形の複雑化
- **対象**: [review_router.py:102](../backend/controllers/api/review_router.py#L102), [pending_actions_service.py:60](../backend/services/pending_actions_service.py#L60)
- **対応案**:
  - [ ] 共通の commit_log スキーマを定義して統一

---

## 済（2026-02-15 修正完了）

| # | 問題 | 修正内容 |
|:--|:--|:--|
| ~~A~~ | Sleep AUTO_MINOR_UPDATE キー不一致 | `identity_manager.py`: `_auto_minor_key` を追加し、両キーを受け入れ |
| ~~B~~ | STT バッファ上限未適用 | `stt_service.py`: `_bg_read()` に `max_buffer_bytes` 超過時の切り捨て追加 |
| ~~C~~ | final_text フォールバック経路の未浄化 | `agent_orchestrator.py`: DB 保存前に常に `finalize_output()` を通すよう変更 |

---

## 対応方針

- **Critical (1-2)**: 配信開始前に完了必須
- **High (3-5)**: 配信開始前に対応推奨。最低限ログ強化は実施
- **Medium (6-9)**: 配信後に順次対応。運用で致命的にはならないが品質に影響
- 各項目は独立しているため、優先度順に個別対応可能

---

## 5分版・クリック受け入れテスト（UI接続確認）

> 目的: 「UI操作」と「バックエンド機能」が正しく接続されていることを短時間で確認する。

| ID | 目安 | クリック手順 | 期待結果（合格条件） |
|:--|:--:|:--|:--|
| AT-01 | 30秒 | `/` を開く | 画面表示が崩れず、チャットUIとサイドバーが表示される。 |
| AT-02 | 45秒 | サイドバー下部 `Admin Token` に正しい値を入力し `保存` | エラーなく保存でき、以後の管理操作が成功する。 |
| AT-03 | 45秒 | `視覚 (Vision)` をクリック | トグル状態が切り替わる。サーバーログで `POST /api/system/vision` が `200`。 |
| AT-04 | 60秒 | `プロフィール` を開き `bio` を1文字変更して `変更を保存` | 保存成功通知が出る。再読み込み後も値が保持される。`GET /api/profile` と `POST /api/profile` が `200`。 |
| AT-05 | 30秒 | `アイデンティティ` を開く | 401にならず表示される（トークン保存済み前提）。`GET /api/identity/proposals...` が `200`。 |
| AT-06 | 30秒 | `統計` 付近の「失敗/却下」表示を確認 | 件数0なら表示なし。件数がある場合は `失敗/却下: N件` が表示される。 |
| AT-07 | 30秒 | `Admin Token` を `クリア` 後に `視覚 (Vision)` をクリック | 管理操作が失敗し、UI状態が元に戻る。`POST /api/system/vision` が `401`。 |
| AT-08 | 30秒 | 正しいトークンを再入力して `保存` | 管理操作が再び成功する状態に戻る。 |

### 判定
- [ ] AT-01 から AT-08 がすべて期待結果を満たせば受け入れOK

### 実施ログ（任意）
- 実施日:
- 実施者:
- 環境: local / staging / prod
- 補足:
