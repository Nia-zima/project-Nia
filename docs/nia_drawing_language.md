# Nia Drawing Language

> 状態: Phase 1 完了 — Dual Ingress アーキテクチャ
> 更新日: 2026-03-30
> 設計書（詳細）: `c:\Users\jk023\Downloads\nia_drawing_language.md`

---

## アーキテクチャ

```
LLM output
  ↓
```draw / ```draw-intent fence 検出
  ↓
┌─ Intent Adapter: YAML → DrawingIntent → intent_to_dsl() → canonical DSL
│  (API model / 手動 / 外部クライアント / test-render)
│
└─ Legacy Adapter: raw DSL → canonicalizer → canonical DSL
   (ローカル LLM — qwen3.5, qwen3-14b 等)
  ↓
Core: parser → scene_graph → renderer → trace → room
```

### Dual Ingress の経緯

Intent Layer（LLM に YAML intent を出力させ、決定論的に DSL に変換する）を設計・実装したが、
ローカル LLM 3モデル（qwen3.5-9b, qwen3-14b-abliterated, gpt-oss-20b）で検証した結果、
いずれも ```draw フェンス内に DSL を出力し、YAML intent に切り替わらなかった。

根本原因: ローカル LLM はフェンス名 `draw` に対してコード的構文を出す学習バイアスが強い。
これは prompt の弱さではなくモデルの出力習性であり、prompt 強化では解決しない。

**結論: Intent を唯一の入口にするのは早すぎた。Core は canonical DSL。手前に model-specific adapter を置く。**
Intent Parser は adapter の一種。Canonicalizer も adapter の一種。

---

## 現在地

### 完了

| 層 | 内容 | テスト |
|---|---|---|
| Core | parser, scene_graph, renderer | 33 |
| Trace/Attempt | 永続化 + trace viewer + debug UI | 20 |
| Intent Adapter | Schema (Pydantic) + Parser (決定論的) | 28 |
| Legacy Adapter | canonicalizer (6種修復) | 含む |
| LLM 接続 | action_processing, prompt injection | 30 |
| Runtime | pipeline orchestration, idempotent replay | 37 |
| Frontend | DrawingCard, SVG preview, error display | — |
| Room | SVG 保存 + hang_art (gate off) | 含む |
| Security | XSS hardening, path traversal, name validation | 含む |
| **合計** | | **151 passed** |

### Canonicalizer 修復一覧

| 修復 | 例 |
|------|---|
| 1行 blob → 宣言前で分割 | `area(...)sky: area(...)` |
| 宣言内 modifier auto-promote | `area(color=cool_1, opacity=faint)` |
| 宣言+配置 同一行 | `area(size=vast) at field because bg` |
| 2語空間参照 | `upper right` → `upper_right` |
| declaration-as-scatter | `star: dot count=50...` → `scatter dot...` |
| modifier 値検証 | `color=banana` → ValueError |

### 明示エラー一覧

| パターン | エラー |
|---------|--------|
| `line from/to` | 未対応文法。専用メッセージ |
| because 後ろ接着 | tag validation で reject |
| placement 後の未知トークン | trailing text error |
| 宣言後の未知 trailing text | trailing text error |

---

## 実装ファイル

| ファイル | 責務 |
|---------|------|
| `backend/core/drawing/schema.py` | AST / data model / vocabulary constants |
| `backend/core/drawing/parser.py` | DSL parser + canonicalizer |
| `backend/core/drawing/scene_graph.py` | 関係解決 → 配置 |
| `backend/core/drawing/renderer.py` | SVG 生成 |
| `backend/core/drawing/trace_store.py` | 成功 trace 永続化 (intent_yaml カラム含む) |
| `backend/core/drawing/attempt_store.py` | 失敗記録永続化 |
| `backend/core/drawing/runtime.py` | パイプライン実行 (dual ingress → core) |
| `backend/core/drawing/intent_schema.py` | Intent Schema (Pydantic model) |
| `backend/core/drawing/intent_parser.py` | Intent → DSL 決定論的変換 |
| `backend/core/drawing/prompt_ref.py` | draw_intent 検出 + LLM context injection |
| `backend/core/agent_graph/nodes/actions.py` | fence 検出 + intent/legacy routing |
| `backend/core/actions/registry.py` | `render_drawing` SAFE アクション |
| `backend/core/actions/executor.py` | `_handle_render_drawing` handler |
| `backend/controllers/api/drawing_router.py` | trace viewer API + test-render API |
| `frontend/components/chat/ChatMessages.tsx` | DrawingCard (SVG 表示) |
| `frontend/components/DrawingViewer.tsx` | Trace viewer UI |

---

## 設計判断

| 判断 | 理由 |
|------|------|
| action_processing 経由（tool_call ではない） | 既存実行経路に載せる。tool_call 基盤が無い |
| ` ```draw ` が統一チャネル | 中身で intent / DSL を自動判定。fence 名でモデルを縛らない |
| 1ターン1ブロック制限 | v0 の制約。複数は pre-gate reject |
| drawing_id = message_id ベース | deterministic key。provenance 無しは reject |
| SAFE リスク | 応答の派生物。gate で弾かれない |
| 失敗は attempt_store に分離 | silent_fallback_masking の補償 |
| 同一 DSL replay は idempotent | temporal_accounting_slip の補償 |
| s5_commit では再パースしない | draw は記憶 commit ではなく response artifact 生成 |
| Intent Layer は捨てない | test-render / API model / 外部クライアント用に温存 |
| legacy DSL + canonicalizer が本番 | ローカル LLM 3モデルで検証済み |
| Core は canonical DSL | adapter は手前に置く。Core を adapter に依存させない |
| DRAWING_INTENT_ONLY gate | canary 用。default off |
| DRAWING_ROOM_ENABLED gate | room 連携。default off |

---

## Feature Gates

| Gate | 目的 | Default |
|------|------|---------|
| `DRAWING_ROOM_ENABLED` | room 壁掛け連携 | off |
| `DRAWING_INTENT_ONLY` | legacy draw を reject し intent のみ受付 | off |

---

## 3-Knot Canary 結果 (2026-03-29)

Drawing 拡張セッションで 9 件の knot hit を検出。
preflight を通した core/runtime は 0 件、通していない拡張部に集中。

| Knot | 件数 | 集中箇所 |
|------|------|---------|
| temporal_accounting_slip | 2 | turn_id 不在, replay wall_art 重複 |
| silent_fallback_masking | 5 | success/error 混同, provenance 衝突, API silent, svg_url 不在 |
| declared_semantics_not_realized | 2 | no-op modifier, registry/executor 不整合 |

**運用則: core 以外の周辺接続にも 3-knot preflight を必須化する。**

---

## 次の一手

1. **canonicalizer 観測継続** — ニアの DSL 出力パターンを蓄積し、修復の安定性を確認
2. **drawing knot 抽出** — because tags の蓄積からパターン発見（trace viewer 基盤あり）
3. **line from/to 正式対応の検討** — ニアが繰り返し使おうとする構文
4. **gpt-oss-20b ストリーミング問題** — 別件として切り出し
5. **モデル比較** — 「YAML を出せるか」ではなく「legacy DSL の壊れ方が少ないか」で比較
