# ニア (Nia) システム仕様書

## 1. 記憶システム (The Brain)

### Memory v2 — 3 層構成

| 層 | テーブル | 寿命 | 用途 |
|----|---------|------|------|
| **Episodic** | `memory_events` | 古いものは圧縮→archive | 生ログ（append-only source of truth） |
| **Semantic** | `semantic_memories` | 半減期で減衰 | 事実・価値観・推論結果 |
| **Working** | `working_items` | TTL / 手動 close | ターン中の作業記憶 |

- **Episodic**: S5 Commit で毎ターン保存。圧縮後は `episodic_summaries` に日単位サマリー。
- **Semantic**: Sleep Cycle で episodic から LLM バッチ抽出。`inferred → confirmed / revoked`。
- **Working**: S5 Commit で open/close。優先度付き、stale 判定あり。

### 忘却ポリシー

| ステータス | 半減期 |
|-----------|--------|
| inferred | 3 日 |
| confirmed | 30 日 |
| revoked | 即アーカイブ |

### Context Builder

Depth ごとに注入するコンテキストを制御:
- **Depth0**: PINNED FACTS のみ（confirmed semantic, confidence ≥ 0.7）
- **Depth1 / Depth2**: フルコンテキスト
  - `=== PINNED FACTS ===` — 確定した高確信度事実
  - `=== PATTERNS ===` — R.4 日横断パターン（`state_tag='insight'`）
  - `=== WORKING ===` — 未解決の作業記憶
  - `=== MEMORY ===` — Short Term + Long Term

## 2. 防御システム (The Shield)

- **Safety Node**: LangGraph パイプラインの先頭で有害入力をブロック
- **Review Window**: Merge が敏感な出力を検出 → Hold → 人間が Approve/Reject
- **SpeechSanitizer**: 内部タグ除去、システムプロンプト漏洩防止、リアルタイム検出
- **Non-Negotiable 原則**: 5 つの不可侵ルール（`NIA_NON_NEGOTIABLE.md` 参照）
- **Guardrail v2**: `memory/guardrail.py` でメモリ書き込みの安全性チェック

## 3. 人格進化 (The Soul)

- **Identity**: `identity.md` に定義。ランタイムで読み込み、Sleep Cycle で更新提案
- **Layer B Guardian**: Sleep Cycle で Identity 変更提案を生成
  - `importance < 0.3`: 自動適用（`LAYER_B_MODE=adaptive` 時）
  - `importance >= 0.3`: DB に保存、人間の承認待ち
- **Identity Proposals UI**: フロントエンドから承認/却下操作可能
- **Chapter Evolution**: 週単位の振り返り（Reflect 機能）
- **Autonomous Reflection (R.1-R.4)**: 自律的な記憶振り返り・パターン抽出
  - R.1 Idle Detection: 3分以上無入力で振り返りトリガー
  - R.2 Daily Log: セッション中の会話をLLMで振り返り → `daily_reflections`
  - R.3 Sleep Cycle 連携: daily_reflections を memory_block として活用
  - R.4 Cross-Day Distillation: 3日以上のデータから日横断パターン抽出 → `semantic_memories` (`state_tag='insight'`)

## 4. インターフェース (The Interface)

- **SSE ストリーミング**: テキスト/メタデータ/Hold/最終結果をリアルタイム配信
- **Voice Mode**: WebSocket 経由の STT → LLM → TTS フルループ
- **VRM アバター**: 感情・ジェスチャー・リップシンク連動
- **配信モード**: LivestreamDashboard でコメント管理

## 三権分立

- **AI**: 考える (Reflection) — Depth0/1/2 で思考、提案を生成
- **人間**: 決める (Decision) — Review Window / Identity Proposals / Actions で承認
- **システム**: 従う (Execution) — Sleep Cycle / S5 Commit / Retention Sweeper
