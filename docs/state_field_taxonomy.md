# State Field Taxonomy（AgentState フィールド分類）

> **目的:** AgentState の全フィールドを寿命・用途で分類し、「誰が書き、誰が読み、どこに残るか」を明示する。
> **フィールド数:** 65（2026-03-17 時点）
> **参照元:** `backend/core/agent_graph/state.py`
> **更新タイミング:** state フィールドの追加・変更時。

---

## 分類定義

| 分類 | 略称 | 意味 | 例 |
|------|------|------|-----|
| **turn-local** | TL | 1ターン内で生成・消費。DB に残らない | `draft`, `memory_context` |
| **cross-turn** | CT | ターンをまたいで持続する（DB, telemetry_kv, 状態蓄積） | `messages`, `review_rejected_actions` |
| **observation-only** | OB | 分析用に記録するが、制御フローに影響しない | `surprise_reasons`, `depth2_gate_met` |
| **control-path** | CP | ルーティング・depth 選択・hold 判定等に直接影響する | `confidence`, `selected_depth`, `hold_required` |

フィールドは複数の分類を持ちうる（例: `surprise_score` は CP + OB）。

---

## フィールド一覧

### Core Messages

| フィールド | 分類 | Writer | Reader | 永続化 |
|-----------|------|--------|--------|--------|
| `messages` | CT | safety, merge (AIMessage 追加) | 全ノード | LangGraph checkpoint |
| `has_user_text` | TL | orchestrator | safety | なし |
| `user_text` | TL | safety | depth_selector, 全 depth ノード | なし |
| `thread_id` | CT | orchestrator | 全ノード | パラメータ |
| `turn_id` | OB | orchestrator (agent_stream 経由) | commit_helpers | telemetry_kv |

### Safety & Tracing

| フィールド | 分類 | Writer | Reader | 永続化 |
|-----------|------|--------|--------|--------|
| `message_id` | CT | orchestrator | expression, governance | トレースID |
| `stream_id` | CT | orchestrator | expression, governance | トレースID |
| `trace_id` | CT | orchestrator | somatic, retrieval | トレースID |
| `test_mode` | CP | orchestrator | s5_commit (早期リターン) | なし |
| `safety_route` | CP | safety_interrupt | グラフルーティング | なし |
| `safety_text` | TL | safety_interrupt | — | なし |

### Dissonance & Surprise

| フィールド | 分類 | Writer | Reader | 永続化 |
|-----------|------|--------|--------|--------|
| `dissonance` | CP | dissonance_check | depth_selector, merge | なし |
| `dissonance_on` | CP | routing | merge (hold ロジック) | なし |
| `surprise_score` | CP+OB | dissonance_check | niacore, fingerprint, evidence | なし |
| `surprise_reasons` | OB | dissonance_check | ログのみ | なし |

### Depth Selection

| フィールド | 分類 | Writer | Reader | 永続化 |
|-----------|------|--------|--------|--------|
| `need_depth1` | CP | routing | depth ノード dispatch | なし |
| `need_depth2` | CP | routing | depth2 gate | なし |
| `selected_depth` | CP+OB | routing | merge, action, expression, experience | なし |
| `depth_action` | CP | routing | expression, ログ | なし |
| `depth_recommendation_reason` | OB | routing | ログ | なし |
| `depth2_gate_met` | OB | routing | ログ | なし |
| `depth2_mode` | CP | routing | merge, depth2, motion, vnext | なし |
| `self_scope` | CP | dissonance_check | routing (reflective), skeleton | なし |
| `force_ab_followup` | CP | routing | merge (depth2_text 上書き) | なし |

### Confidence

| フィールド | 分類 | Writer | Reader | 永続化 |
|-----------|------|--------|--------|--------|
| `confidence` | CP | routing (engine + metacog 調整) | action_gate, expression, experience | なし |
| `confidence_metrics` | OB | routing | skeleton, niacore, expression | なし |
| `reason_codes` | CP+OB | dissonance, routing, merge, review | hold/review 判定（50+ 参照） | なし |

### Draft & Output

| フィールド | 分類 | Writer | Reader | 永続化 |
|-----------|------|--------|--------|--------|
| `draft` | TL | depth0, depth1 | merge, review_window | なし |
| `depth1_text` | TL | depth1 | merge (fallback) | なし |
| `depth2_text` | TL | depth2 | merge | なし |
| `depth2_fallback_used` | OB | depth2 | expression | なし |
| `final_text` | TL→CT | merge | s5_commit, action_processing | episodic DB |
| `merge_mode` | TL | merge | review_router | なし |

### Review Window

| フィールド | 分類 | Writer | Reader | 永続化 |
|-----------|------|--------|--------|--------|
| `hold_required` | CP | merge, review_window | action, s5_commit (スキップ) | なし |
| `hold_kind` | OB | merge | expression | なし |
| `review_token` | CP | merge, review_window | review_router | なし |
| `review_pending_actions` | CP | review_window, review_router | action_processing | なし |
| `review_rejected_actions` | CT | review_router (蓄積) | s5_commit | **クリアされない** |
| `suppressed_actions` | CT | review_window.set_review_token | ログ | **クリアされない** |

### Action System

| フィールド | 分類 | Writer | Reader | 永続化 |
|-----------|------|--------|--------|--------|
| `proposed_actions` | TL | action_processing | action_gate | なし |
| `approved_actions` | TL | action_gate | action_executor | なし |
| `pending_actions` | CT | action_processing | review_window | なし |
| `rejected_actions` | CT | action_gate | governance evidence | なし |
| `action_results` | TL | action_executor | Pip interaction 検出 | なし |

### External Data

| フィールド | 分類 | Writer | Reader | 永続化 |
|-----------|------|--------|--------|--------|
| `external_reason` | OB | merge (external_pipeline) | ログ | なし |
| `external_used` | CP+OB | merge | expression | なし |
| `external_confidence` | OB | merge | expression | なし |
| `contradiction_flag` | OB | merge | ログ | なし |

### Memory & Context

| フィールド | 分類 | Writer | Reader | 永続化 |
|-----------|------|--------|--------|--------|
| `memory_context` | TL | routing | depth ノード (LLM prompt) | なし |
| `memory_sections` | TL | routing | — | なし |
| `cumulative_turn_count` | OB | routing (DB 問い合わせ) | depth2 gate | なし |

### Orchestrator

| フィールド | 分類 | Writer | Reader | 永続化 |
|-----------|------|--------|--------|--------|
| `orchestrator_stage` | OB | s5_commit | ログ | なし |
| `commit_result` | OB | s5_commit | ログ | なし |
| `pre_thought_action` | CP | dissonance_check | S0 ルーティング | なし |

### Game

| フィールド | 分類 | Writer | Reader | 永続化 |
|-----------|------|--------|--------|--------|
| `game_context` | TL | routing | depth ノード (LLM prompt) | なし |
| `game_active` | OB | routing | ログ | なし |

### Metacognition

| フィールド | 分類 | Writer | Reader | 永続化 |
|-----------|------|--------|--------|--------|
| `metacog_result` | OB+CP | routing (_run_metacognition) | s5_commit (awareness 計算) | telemetry_kv (統計) |
| `awareness_signal` | OB | s5_commit | ログ | telemetry_kv (ring buffer) |

### Somatic

| フィールド | 分類 | Writer | Reader | 永続化 |
|-----------|------|--------|--------|--------|
| `somatic_senses` | OB | routing (_collect_somatic) | skeleton, niacore, LLM context | somatic_log |
| `retrieval_top_similarity` | OB | routing | vnext, expression, fingerprint | turn_fingerprints |

### NiaCore Shadow

| フィールド | 分類 | Writer | Reader | 永続化 |
|-----------|------|--------|--------|--------|
| `niacore_shadow` | OB | routing | experience_writer, vnext | niacore_experience |
| `niacore_vnext_shadow` | OB | routing | vnext_writer | niacore_vnext_shadow |

### SkeletonCore

| フィールド | 分類 | Writer | Reader | 永続化 |
|-----------|------|--------|--------|--------|
| `conversation_skeleton` | OB | routing (_run_skeleton_build) | expression, fingerprint, governance, LLM context | conversation_skeletons |

### Contract 1/2/3

| フィールド | 分類 | Writer | Reader | 永続化 |
|-----------|------|--------|--------|--------|
| `runtime_facts_text` | TL+OB | routing | LLM context, motion | turn_fingerprints |
| `atmosphere_text` | TL+OB | routing | LLM context, motion | turn_fingerprints |

---

## 集計

| 分類 | 件数 | 備考 |
|------|------|------|
| turn-local (TL) | 23 | 1ターン内で消費 |
| cross-turn (CT) | 9 | DB or 暗黙蓄積 |
| observation-only (OB) | 20 | 分析専用 |
| control-path (CP) | 18 | 制御フローに影響 |

※複数分類を持つフィールドは主分類でカウント。

---

## 設計上の注意点

### `False` と「未配線」を混ぜない

観測フィールドで「まだ producer がない」場合、state 側は `None` を推奨する。
`False` は「判定した結果、該当しなかった」を意味し、`None` は「まだ判定する仕組みがない」を意味する。
この区別が E0.5 以降のパターン分析で重要になる。

**例外:** DB schema が `NOT NULL DEFAULT 0` や `TEXT NOT NULL` で定義されている列は、
`None` を INSERT できない。この場合は fixed sentinel（`False`/`"none"`）を使い、
コメントで「no state producer yet」と明記する。
現行の Expression Layer E0 がこのパターンを採用している（`commit_helpers.py` L567-579）。

### cross-turn フィールドの寿命

`review_rejected_actions` と `suppressed_actions` はターン間でクリアされず蓄積する。
これは意図的な設計かもしれないが、長期セッションでのメモリ成長リスクがある。
各 cross-turn フィールドに明示的な寿命定義（ターン数上限、セッションスコープ等）を持たせることを推奨。

### observation-only フィールドが control-path に昇格するとき

`surprise_score` のように、当初 observation-only として追加されたフィールドが
後から depth gating に使われるケースがある。
昇格時には、このドキュメントの分類を更新し、テストを追加すること。
