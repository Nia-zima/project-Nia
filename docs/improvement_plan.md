# AI_Buddy 改善計画表

> 作成日: 2026-02-13
> 最終更新: 2026-02-16
> 基準: 全機能レビュー結果（Agent Graph / Memory v2 / Voice Mode / Frontend / CI+外部連携）

## Context

レビューで抽出した改善項目（高6件 / 中19件 / 低2件 = 計27件）を、
依存関係・工数・影響度を考慮して **4フェーズ** に整理。

**進捗: 26/27 完了（96%）、残り 1件（意図的保留）**

---

## サマリーダッシュボード

```
Phase 1 [安定性・セキュリティ]  ██████████  6/6 完了 ✅
Phase 2 [UX・Voice Mode]       ██████████  6/6 完了 ✅
Phase 3 [精度・パフォーマンス]  █████████░  7/8 完了 (3-7 意図的保留)
Phase 4 [コード品質・将来基盤]  ██████████  7/7 完了 ✅
```

---

## Phase 1: 安定性・セキュリティ基盤 — ✅ 完了

> **目的**: 本番運用で問題になりうるクラッシュ・セキュリティ・データロスを防止

| # | タスク | 状態 | 備考 |
|---|--------|------|------|
| 1-1 | LLMノードのエラーハンドリング統一 | ✅ | depth0/1/2 で try-except + タイムアウト実装済み |
| 1-2 | Identity Manager 秘密鍵の環境変数化 | ✅ | `IDENTITY_SECRET_KEY` を Settings に追加済み |
| 1-3 | System Router に認証追加 | ✅ | `X-System-Token` ヘッダ検証実装済み |
| 1-4 | Public Status のスレッドセーフティ | ✅ | `asyncio.Lock` で排他制御実装済み |
| 1-5 | Semantic extraction 実装確認・補完 | ✅ | Sleep Cycle に `_extract_semantics_from_episodic()` 実装済み (Phase G) |
| 1-6 | S5 Commit のエラー時リトライ | ✅ | exponential backoff 実装済み |

**追加実装** (配信準備スプリント 2026-02-15):
- Checkpointer DB 肥大化対策: `cleanup_old_checkpoints()` + Sleep Cycle 統合
- safety_interrupt: PII検出→ブロック、プロンプトインジェクション検出→ログ
- Diagnostics: `/api/stats/checkpointer` エンドポイント追加

---

## Phase 2: UX改善・Voice Mode強化 — ✅ 完了

> **目的**: ユーザー体験のボトルネック（レイテンシ・再接続・巨大コンポーネント）を解消

| # | タスク | 状態 | 備考 |
|---|--------|------|------|
| 2-1 | TTS センテンスチャンキング | ✅ | `_split_tts_units()` + `TTS_SENTENCE_CHUNKING=True` 実装済み |
| 2-2 | WebSocket 自動再接続 | ✅ | 指数バックオフ(max 3回) 実装済み。stale closure バグも修正済み |
| 2-3 | STT リトライ機構 | ✅ | stt_service.py に実装済み |
| 2-4 | ChatInterface 分割 | ✅ | `chat/ChatMessages.tsx`, `chat/messageNormalization.ts`, `hooks/useVoiceMode.ts` に分離済み |
| 2-5 | Frontend 状態管理集約 (Zustand) | ✅ | `chatStore.ts` (Zustand v5) + ChatInterface/ChatMessages/ChatInput 統合完了。props 15→9 削減 |
| 2-6 | API クライアント層の統一 | ✅ | `apiClient.ts` に全メソッド集約、`api.ts` 削除済み。全16コンポーネント移行完了 |

---

## Phase 3: 精度・パフォーマンス改善 — ⚠️ 7/8 完了

> **目的**: confidence精度向上、メモリシステム最適化、描画パフォーマンス改善

| # | タスク | 状態 | 備考 |
|---|--------|------|------|
| 3-1 | context_coverage を embedding ベースに | ✅ | `ContextCoverageCalculator` に `cosine_similarity` 実装。heuristic フォールバック付き |
| 3-2 | search_active() 重複呼び出し削減 | ✅ | guardrail.py: G1/G2 で search_active 1回に統合。context_builder は元から1回 |
| 3-3 | Guardrail _content_overlap embedding化 | ✅ | G1 で embedding 使用。他チェック(G3-G5)はルールベース設計のため embedding 不要 |
| 3-4 | Semantic半減期の実装 | ✅ | `decay_by_status()` 実装済み (inferred:3日, confirmed:30日)。retention_sweeper 統合済み |
| 3-5 | batch insert の executemany() 化 | ✅ | 全DAO適用済み: semantic_store / commit_executor / working_store |
| 3-6 | MemoryGraph Quad-tree 化 | ✅ | Barnes-Hut quad-tree 完備 (O(n log n)、THETA=0.8) |
| 3-7 | Depth2 プロンプト充実 | 🔒 保留 | **意図的保留**: 記憶データが十分たまるまで設計しない方針（DEPTH2_MIN_TURNS=100 ゲート実装済み） |
| 3-8 | depth_selector decision path 単純化 | ✅ | routing.py にゲート + フォールバック整理済み (Phase F.1) |

---

## Phase 4: コード品質・将来基盤 — ✅ 完了

> **目的**: デッドコード整理、未完成機能の決着、保守性向上

| # | タスク | 状態 | 備考 |
|---|--------|------|------|
| 4-1 | デッドコード整理 | ✅ | `call_model()` 削除済み。POLICY_MODE learned/hybrid パスも routing.py / helpers.py / config.py から削除済み |
| 4-2 | speech_sanitizer 浄化ルール統一 | ✅ | 14フェーズ処理パイプライン統合済み |
| 4-3 | Vision Client 完成 | ✅ | Ollama + OpenAI/LM Studio 両対応。`VISION_PROVIDER` で切替可能 |
| 4-4 | Action Executor スタブ解消 | ✅ | 全ハンドラに実ロジック実装済み（search_memory, save_memory, see_screen, mc_action 等） |
| 4-5 | Frontend 型安全性向上 | ✅ | `types.ts` に全型定義、`apiClient.ts` ジェネリクス対応。apiClient 統一で `any` 大幅削減 |
| 4-6 | CI Smoke Test 拡充 | ✅ | 11テストファイル + 3層CI (Frontend Build/Lint + Backend Smoke) + タイミングレポート |
| 4-7 | PINNED FACTS 抽出の堅牢化 | ✅ | `extract_section()` 実装済み |

---

## 残タスク一覧

| # | タスク | 難易度 | 備考 |
|---|--------|--------|------|
| 3-7 | Depth2 プロンプト充実 | — | **意図的保留**: 記憶100ターン蓄積後に着手（DEPTH2_MIN_TURNS=100 ゲート実装済み） |

---

## 完了済みタイムライン

```
2026-02-13  Phase 1 全項目完了 (Memory Redesign v2 Phase A-G)
2026-02-15  配信準備スプリント完了
            - Checkpointer cleanup
            - safety_interrupt (PII + injection)
            - WS再接続 stale closure修正
            - Diagnostics (/api/stats/checkpointer)
2026-02-16  Phase 2-6 apiClient統一完了
            - apiClient.ts に全メソッド集約
            - 全16コンポーネント移行
            - api.ts 削除
            - MemoryExplorer 壊れたif/elseブロック修正
            - next build 通過確認
2026-02-16  残タスク完了
            - 4-1: POLICY_MODE dead path 削除 (routing.py/helpers.py/config.py)
            - 3-2: Guardrail search_active 重複削減 (G1/G2 で1回に統合)
            - 3-5: executemany 全DAO適用 (commit_executor/working_store)
            - 3-3: Guardrail embedding → 設計上十分と判断しクローズ
2026-02-16  Phase 2-5 Zustand 状態管理集約完了
            - chatStore.ts: upsertMessage / appendInput アクション追加
            - ChatInterface: 9個の useState → useChatStore に移行
            - ChatMessages: props 全廃 → store 直接参照
            - ChatInput: props 15→9 削減（state は store、callback のみ props）
```

---

## リスクと緩和策

| リスク | 影響 | 緩和策 |
|--------|------|--------|
| ~~sentence-transformers 導入でメモリ増加~~ | ~~Phase 3~~ | ✅ 解決済み: embedding_model.py で遅延ロード実装 |
| ~~ChatInterface 分割で既存動作が壊れる~~ | ~~Phase 2~~ | ✅ 解決済み: 分割完了、ビルド通過 |
| ~~Zustand 導入で学習コスト~~ | ~~Phase 2~~ | ✅ 解決済み: chatStore + ChatInterface/ChatMessages/ChatInput 統合完了 |
| ~~デッドコード削除で将来の Phase II に影響~~ | ~~Phase 4~~ | ✅ call_model 等削除済み。git history で復元可能 |
| ~~AMD GPU で Ollama 未対応~~ | ~~Phase 4~~ | ✅ 解決済み: LM Studio に移行（GPU推論可能） |
