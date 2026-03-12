# Memory System Supplementary Design
## 記憶制度 補足設計書

> ステータス: Draft  
> 目的: 記憶制度の Promotion / Decay 接続点、テスト戦略、Phase 0 計装を定める  
> 上位文書: memory_governance_redesign.md  
> 関連文書: memory_promotion_redesign.md, memory_decay_redesign.md, core_adjacency_roadmap.md

---

## 1. seed_retention 算出ロジック

### 1.1 位置づけ

seed_retention は **Promotion 制度と Decay 制度の接続点** である。

- Promotion Tribunal が昇格を承認した時点で算出される
- Semantic Save 時に semantic_state.seed_retention に記録される
- Decay 制度では `memory_strength = seed_retention` を初期値として運用する

### 1.2 三者の関係（再掲）

| 指標 | 意味 | 所属 |
|---|---|---|
| confidence | Claim の妥当性（確からしさ） | Promotion 側 |
| seed_retention | 生存力の初期条件（保持しやすさ） | Promotion → Decay 接続点 |
| memory_strength | 現在の保持力（動的に変動） | Decay 側 |

confidence と seed_retention は別物である。

- confidence が高くても seed_retention が低い場合がある（例: 明確に述べられた一時的な気分）
- confidence が中程度でも seed_retention が高い場合がある（例: 繰り返し確認された inferred preference）

### 1.3 算出式（仮置き）

```text
seed_retention =
  base_retention[claim_type]
  * status_modifier[status]
  * min(1.0, evidence_strength)
  - contradiction_discount
```

> seed_retention は **昇格時点の保持しやすさの初期推定値** である。  
> 正式昇格後の再審査（Sleep Cycle）で再計算されうる。  
> 特に identity 即時パス経由の記憶は、初期 seed_retention が低めに入り、  
> 正式審査後に evidence が積まれてから再計算される。

### 1.4 base_retention（claim_type ごとの基礎保持傾向）

| claim_type | base_retention | 理由 |
|---|---|---|
| identity | 0.85 | 自己定義は最も持続すべき |
| fact (confirmed) | 0.75 | 明示された事実は安定 |
| relationship | 0.70 | 関係性は文脈で変わりうる |
| preference | 0.65 | 好みは変化しやすい |
| lesson | 0.60 | 教訓は状況依存 |
| insight | 0.55 | 傾向は再検証が必要 |

### 1.5 status_modifier

| status | modifier | 理由 |
|---|---|---|
| confirmed | 1.0 | 明示発話はそのまま |
| inferred | 0.85 | 推測は少し割り引く |

### 1.6 evidence_strength（証拠の強さ複合指標）

```text
evidence_strength =
  (evidence_count / expected_count[claim_type])
  * (1 + 0.1 * (unique_dates - 1))
  * (1 + 0.05 * (source_diversity - 1))
```

evidence_count を claim_type ごとの期待値で正規化し、  
日数分散とソース多様性でボーナスを付ける。  
`min(1.0, ...)` でキャップ。

#### expected_count（仮置き）

| claim_type | expected_count | 備考 |
|---|---|---|
| fact (confirmed) | 2 | 明示 1回でも通るが、2回あればフル |
| preference | 3 | 複数回の確認が望ましい |
| relationship | 3 | — |
| insight | 4 | 傾向として成立するには多めの証拠が必要 |
| lesson | 3 | — |
| identity | 2 | 即時パスでは 1回、正式審査で再計算 |

### 1.7 contradiction_discount

```text
contradiction_discount = contradiction_count * 0.10
```

矛盾が 1件あるごとに 0.10 下げる。

### 1.8 算出例

**例1: confirmed fact、evidence 3件、2日分散、source 2種類、矛盾なし**
```text
base = 0.75
status_mod = 1.0
evidence_strength = (3/2) * (1 + 0.1*1) * (1 + 0.05*1) = 1.5 * 1.1 * 1.05 = 1.73 → cap 1.0
contradiction = 0
seed_retention = 0.75 * 1.0 * 1.0 - 0 = 0.75
```

**例2: inferred preference、evidence 2件、1日のみ、source 1種類、矛盾なし**
```text
base = 0.65
status_mod = 0.85
evidence_strength = (2/3) * (1 + 0) * (1 + 0) = 0.67
contradiction = 0
seed_retention = 0.65 * 0.85 * 0.67 - 0 ≈ 0.37
```

**例3: confirmed identity、即時パス、evidence 1件、矛盾なし**
```text
base = 0.85
status_mod = 1.0
evidence_strength = (1/2) * (1 + 0) * (1 + 0) = 0.50
contradiction = 0
seed_retention = 0.85 * 1.0 * 0.50 - 0 = 0.43
→ 即時パスなので初期値は低め。Sleep Cycle 正式審査後に再計算。
```

**例4: inferred insight、evidence 4件、3日分散、source 3種類、矛盾1件**
```text
base = 0.55
status_mod = 0.85
evidence_strength = (4/4) * (1 + 0.1*2) * (1 + 0.05*2) = 1.0 * 1.2 * 1.1 = 1.32 → cap 1.0
contradiction = 1 * 0.10 = 0.10
seed_retention = 0.55 * 0.85 * 1.0 - 0.10 = 0.47 - 0.10 = 0.37
```

### 1.9 再計算のタイミング

- identity 即時パス経由の記憶: Sleep Cycle 正式審査後
- 大きな新 evidence が追加された場合: Sleep Cycle で再評価
- 重大な contradiction が発生した場合: Decay Tribunal が seed_retention ごと再計算を要求することがある

> 通常の Decay（time decay, retrieval reinforcement 等）は memory_strength を変動させるだけであり、  
> seed_retention 自体は原則として昇格時に固定される。  
> 再計算は例外的処理であり、頻繁には行わない。

### 1.10 原則

- seed_retention は昇格時点の初期推定値
- confidence とは独立した指標
- 仮置き値は M0.5 の遡及シャドー分析で再調整する
- 算出式は単純に保ち、複雑化は M0.5 以降の実測に基づいて行う

---

## 2. テスト戦略

### 2.1 方針

NiaCore と同様に **「テスト先、実装後」** のスタイルで進める。  
テスト層を3段 + 1段に分ける。

### 2.2 Layer A: 状態遷移テスト

個々のコンポーネントの状態遷移が正しいかを検証する。

#### Candidate Pool 状態遷移

- pending → accumulating（evidence 追加時）
- accumulating → ready_for_normalization（閾値到達時）
- pending → stale（TTL 超過、evidence なし）
- stale → expired（一定期間経過）
- accumulating → rejected（contradiction 増加時）
- expired 候補の再浮上時に TTL 延長されること

#### semantic_state 状態遷移

- active → weakened（memory_strength < 0.50）
- weakened → deprecated（memory_strength < 0.30 + 条件）
- deprecated → archived（memory_strength < 0.15 + 条件）
- active/strengthened → contradicted（contradiction_score > threshold）
- weakened → active（retrieval/reinforcement で memory_strength >= 0.50）
- deprecated → active（new evidence + tribunal review）
- contradicted → active（tribunal review のみ）

#### 復帰不可の制約

- archived → active が **拒否** されること
- forgotten → active が **拒否** されること
- merged → active が **拒否** されること

#### Working Memory

- active_temp → Harvester 採用で Candidate Pool に移行すること
- identity_hold が Working Memory に仮保持されること
- contradiction_pending が Sleep Cycle で Decay Tribunal に渡ること
- candidate_hold が Working Memory に存在 **しない** こと（Candidate Pool の責務）

### 2.3 Layer B: フロー統合テスト

パイプライン全体の流れが通ることを検証する。

#### Promotion フロー

- 発話 → Harvester → Candidate Pool → Evidence → Claim → Tribunal → Semantic Save
- identity 即時パス: 発話 → Working Memory (identity_hold) → Candidate Pool → Sleep Cycle 正式審査

#### Decay フロー

- Semantic Save → time 経過 → weakened → deprecated → archived → tombstone
- Reinforcement: retrieval → memory_strength 上昇 → weakened から active 復帰

#### 制度間接続

- contradiction_candidate が Reflection から生成され、Decay 側 (contradiction_score 上昇) と Promotion 側 (新 Candidate 生成) の両方に流れること
- seed_retention が Semantic Save 時に正しく算出され、memory_strength の初期値になること
- promotion_path = legacy / tribunal_v1 の並走で同一内容が両経路から来たときに merge_with で吸収されること

### 2.4 Layer C: 閾値境界テスト

仮閾値の境界条件を検証する。

#### Promotion 側

- evidence_count == 1 の confirmed fact が ready_for_normalization に進むこと
- evidence_count == 1 の inferred が ready_for_normalization に **進まない** こと
- TTL 境界: 期限当日の候補が stale に遷移しないこと、翌日に遷移すること

#### Decay 側

- memory_strength == 0.50 で weakened に遷移すること
- memory_strength == 0.51 で weakened に遷移 **しない** こと
- memory_strength == 0.30 で deprecated 条件を満たすこと
- memory_strength == 0.15 で archived 条件を満たすこと

#### seed_retention

- 各算出例（§1.8）の期待値と実際の算出結果が一致すること
- contradiction_discount が正しく適用されること

### 2.5 Layer R: 検索汚染テスト

Context Builder / Retrieval が記憶制度の利用規約を正しく執行しているかを検証する。

#### Depth 0

- deprecated 記憶が context に **入らない** こと
- contradicted 記憶が context に **入らない** こと
- archived 記憶が context に **入らない** こと
- weakened 記憶が明示参照 **なし** では context に **入らない** こと
- weakened 記憶が明示参照 **あり** なら条件付きで context に **入る** こと

#### Depth 1

- weakened 記憶が文脈関連性の高い場合に context に **入る** こと
- deprecated / contradicted が context に **入らない** こと

#### Depth 2+

- weakened, deprecated, contradicted, merged, archived が context に **入る** こと
- forgotten が tombstone 経由参照 **のみ** であること

### 2.6 テストデータ

- M0.5 の遡及分析結果を入力として、新制度での出力が期待通りかを検証する
- 遡及分析は M0.5 の副産物としてテストケースを生む構造

### 2.7 テスト実装タイミング

| Layer | タイミング | 前提 |
|---|---|---|
| Layer A | Phase 1（テーブル作成と同時） | スキーマ確定 |
| Layer B | Phase 2〜3（各フロー稼働時） | Candidate 運用 + Tribunal 導入 |
| Layer C | M0.5 後（閾値仮確定後） | 遡及分析完了 |
| Layer R | Phase C1（Retrieval 再設計時） | semantic_state + Retrieval filter |

---

## 3. Phase 0 計装ガイド

### 3.1 方針

- Phase 0 では **まずログを吐く** ことに集中する
- **primary sink は SQLite**（`governance_events`, `retrieval_logs`, 将来の governance tables）
- `governance_events` は記憶制度専用のイベントテーブル（汎用 `events` とは分離）
- JSONL は offline analysis / export 用の副次表現として扱う
- テーブル化は Phase 1 で行う
- スキーマを先に固定しすぎない
- M0.5 で何が必要かを見てから構造化する

#### なぜ DB-first か

現行の project-nia では、すでに以下が DB 中心で動いている。

- `decision_event.v2`
- canonical dataset exporter
- stats / audit / snapshot

このため、Memory 制度の観測も DB 側に寄せた方が、

- `thread_id`
- `turn_id`
- `message_id`
- `stream_id`

の join を保ちやすい。  
JSONL は「あとで見るための書き出し」としては有効だが、
**制度観測の source of truth にはしない**。

#### なぜ governance_events を events と分離するか

記憶制度イベントは汎用 `events` テーブルとは以下の点で異なる:

1. **量**: candidate_created / evidence_added / retrieval_surfaced 等は高頻度。汎用テーブルに混ぜると膨れる
2. **クエリ軸**: `candidate_id`, `claim_id`, `semantic_id`, `contradiction_case_id` での絞り込みが頻出。汎用テーブルでは JSON 内検索になり遅い
3. **join 先**: `memory_claims`, `semantic_state`, `raw_promotion_candidates` との直接 join が必要
4. **ライフサイクル**: 制度テーブルと一緒に vacuum / archive できる

汎用 `events` テーブルには引き続き cross-domain イベント（`decision_event`, `commit_log`, 粗い `governance_summary`）を記録する。

#### governance_events テーブルスキーマ

```sql
CREATE TABLE IF NOT EXISTS governance_events (
    id TEXT PRIMARY KEY,
    ts REAL NOT NULL,
    schema_version TEXT NOT NULL DEFAULT 'governance_event.v1',
    event_name TEXT NOT NULL,
    -- provenance keys
    thread_id TEXT,
    turn_id TEXT,
    message_id TEXT,
    stream_id TEXT,
    trace_id TEXT,
    -- ownership
    owner_agent TEXT NOT NULL DEFAULT 'nia',
    memory_domain TEXT NOT NULL DEFAULT 'default',
    -- governance entity references
    candidate_id TEXT,
    claim_id TEXT,
    semantic_id TEXT,
    contradiction_case_id TEXT,
    -- harvester provenance
    source_harvester TEXT,  -- rule / llm / reflection / skeleton
    -- flexible payload
    payload_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_ge_event ON governance_events(event_name, ts);
CREATE INDEX IF NOT EXISTS idx_ge_thread ON governance_events(thread_id, ts);
CREATE INDEX IF NOT EXISTS idx_ge_candidate ON governance_events(candidate_id);
CREATE INDEX IF NOT EXISTS idx_ge_claim ON governance_events(claim_id);
CREATE INDEX IF NOT EXISTS idx_ge_semantic ON governance_events(semantic_id);
CREATE INDEX IF NOT EXISTS idx_ge_contradiction ON governance_events(contradiction_case_id);
CREATE INDEX IF NOT EXISTS idx_ge_trace ON governance_events(trace_id);
```

#### ストレージ分割方針

| テーブル | 役割 | 主なイベント |
|---------|------|------------|
| `events` | cross-domain 汎用イベント | decision_event, commit_log, governance_summary |
| `governance_events` | 記憶制度 source of truth | candidate_created, evidence_added, claim_normalized, promotion_reviewed, semantic_state_changed, contradiction_case_opened, decay_reviewed |
| `retrieval_logs` | 検索ランキング断面 | retrieval_candidate, retrieval_excluded, context_build |

#### Phase 0 で最低限そろえる provenance key

- `thread_id`
- `turn_id`
- `message_id`
- `stream_id`
- `trace_id`
- `candidate_id`（Candidate 発生後）
- `claim_id`（Claim 化後）
- `semantic_id`（Semantic 化後）
- `contradiction_case_id`（矛盾ケース導入後）

> 計装初期にすべての値が埋まらなくてもよい。  
> ただし schema 上の置き場は最初から確保し、後付け join を避ける。

Step 2 の共通骨格テーブルでも同じ原則を守る。

- `raw_promotion_candidates`
- `memory_claims`
- `memory_evidence`
- `promotion_reviews`
- `semantic_lineage`
- `semantic_reviews`

は provenance key を保持し、`semantic_lineage` / `semantic_reviews` も
後段の監査・dataset export で turn join 可能にしておく。

### 3.2 計装対象

#### Promotion 系

| 対象 | 記録するもの | 主記録先 |
|---|---|---|
| Semantic 昇格イベント | 昇格した記憶の source、元の episodic/reflection 参照、昇格日時、claim_type、confidence | `governance_events`（必要なら後で JSONL export） |
| Reflection 出力 | 生成した insight/pattern/lesson、そのうち何が semantic 化されたか、何が候補止まりか | `governance_events` または `daily_reflections` + export |
| Working Memory 滞留 | 各アイテムの滞留時間、最終参照日時、行き先（候補化/消滅/Decay移管） | `governance_events` + `working_items` |
| 意思決定スナップショット | Promotion 判定時に「何が見えていたか」の断面（少量） | `governance_events` |

#### Decay 系

| 対象 | 記録するもの | 主記録先 |
|---|---|---|
| 既存 expiry/half-life | どの記憶がいつ expire したか、expire 時の retrieval_count | `governance_events`（将来は `semantic_transitions` / `semantic_reviews`） |
| Retrieval | どの記憶が候補に上がったか、採用/除外、state、除外理由 | `retrieval_logs` + `governance_events` |
| 意思決定スナップショット | Decay 判定時の断面（少量） | `governance_events` |

#### Core 系

| 対象 | 記録するもの | 主記録先 |
|---|---|---|
| Context Builder | context に入った記憶一覧、除外された記憶一覧、除外理由 | `governance_events` |
| SkeletonCore | focus, intent, unresolved の分布 | 既存 DB / event log の拡張 |

### 3.3 JSONL フォーマット例

#### promotion_events.jsonl

```json
{
  "timestamp": "2025-01-15T03:00:00Z",
  "event_type": "semantic_promotion",
  "semantic_id": "sem_xxx",
  "source_type": "reflection",
  "source_ref": "refl_yyy",
  "claim_type": "insight",
  "confidence": 0.72,
  "evidence_count": 3,
  "evidence_dates": ["2025-01-13", "2025-01-14", "2025-01-15"]
}
```

#### retrieval_events.jsonl

```json
{
  "timestamp": "2025-01-15T14:30:00Z",
  "event_type": "retrieval_candidate",
  "semantic_id": "sem_zzz",
  "state": "active",
  "adopted": true,
  "depth": 0,
  "retrieval_score": 0.85
}
```

```json
{
  "timestamp": "2025-01-15T14:30:00Z",
  "event_type": "retrieval_excluded",
  "semantic_id": "sem_aaa",
  "state": "deprecated",
  "adopted": false,
  "depth": 0,
  "exclusion_reason": "state_filter:deprecated_not_allowed_at_depth0"
}
```

#### context_builder.jsonl

```json
{
  "timestamp": "2025-01-15T14:30:00Z",
  "event_type": "context_build",
  "included": ["sem_xxx", "sem_yyy"],
  "excluded": [
    {"semantic_id": "sem_aaa", "reason": "state_filter:deprecated"},
    {"semantic_id": "sem_bbb", "reason": "low_relevance"}
  ],
  "depth": 0,
  "total_candidates": 15,
  "total_included": 5
}
```

### 3.4 意思決定スナップショット

> **全件でなくてよい。後から「この時点で何が見えていたか」が分かれば十分。**

promotion_snapshots.jsonl:
```json
{
  "timestamp": "2025-01-15T03:00:00Z",
  "event_type": "promotion_decision_snapshot",
  "candidate_id": "cand_xxx",
  "visible_evidence_count": 3,
  "visible_semantic_count": 42,
  "existing_similar_claims": ["claim_yyy"],
  "decision": "approve",
  "reason": "cross_day_evidence_sufficient"
}
```

decay_snapshots.jsonl:
```json
{
  "timestamp": "2025-01-15T03:00:00Z",
  "event_type": "decay_decision_snapshot",
  "semantic_id": "sem_zzz",
  "memory_strength": 0.48,
  "last_reinforced_at": "2025-01-10T00:00:00Z",
  "retrieval_count": 2,
  "contradiction_score": 0.0,
  "decision": "weaken",
  "reason": "memory_strength_below_threshold"
}
```

### 3.5 M0.5 で必要になるデータの逆算

Phase 0.5 の遡及シャドー分析で必要になるデータを逆算して、Phase 0 で確実に取る。

| M0.5 での分析 | 必要なログ |
|---|---|
| 「この記憶は新制度だったら evidence 何件で昇格したか」 | promotion_events（source_ref、evidence_count） |
| 「この記憶は新制度だったらいつ weakened になったか」 | retrieval_events（retrieval 履歴）+ decay_events（time 経過） |
| 「Reflection が candidate producer だけだったら何が変わるか」 | reflection_outputs（全出力ログ） |
| 「Context Builder がゾンビ記憶を拾っていないか」 | context_builder（除外理由ログ） |
| 「seed_retention の仮算出式が妥当か」 | promotion_events（claim_type, confidence, evidence_count, evidence_dates） |
| 「weakened の Depth0 アクセス閾値はどのくらいか」 | retrieval_events（state, depth, adopted） |
| 「candidate の TTL はどのくらいが妥当か」 | working_memory（滞留時間、行き先） |

### 3.6 原則

- Phase 0 は「観測」に集中する。制度変更は行わない
- primary sink は `governance_events` テーブルに置き、必要なら JSONL export を後段で行う
- 汎用 `events` には cross-domain イベントのみ。記憶制度イベントは `governance_events` に集約
- 「M0.5 で必要になるデータ」を逆算して計装する
- 全件ログではなく、制度判断に関わるイベントに絞る
- 意思決定スナップショットは少量でよいが、ゼロにはしない
