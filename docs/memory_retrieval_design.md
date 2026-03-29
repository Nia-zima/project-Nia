# Memory Retrieval Redesign v0.1

> **Status**: Draft
> **Date**: 2026-02-19
> **Scope**: 記憶の「引き出し精度」を改善する設計

---

## 1. 問題の定義

### 1.1 現状

現在の記憶検索は**クエリ非依存**。ユーザーが何を聞いても同じ記憶セットが返る。

```
ユーザー: 「昨日話したゲームの件」
→ confidence が最も高い無関係な記憶 8 件が返る

ユーザー: 「好きな食べ物って何だっけ？」
→ 同じ 8 件が返る
```

#### 検索パスごとの問題

| パス | 方式 | 問題 |
|------|------|------|
| **Pinned Facts** | SQL `confidence DESC` | クエリと無関係に固定表示 |
| **Semantic LT** | SQL `confidence DESC` | `user_query` を受け取るが**未使用** |
| **Working** | SQL `priority ASC` | 設計意図通り（問題なし） |
| **Vector (Legacy)** | ChromaDB L2 距離 | メインパスで呼ばれていない |
| **Hybrid (Legacy)** | 0.65×sim + 0.30×eff + 0.05×rec | **存在するが未使用** |

### 1.2 埋め込みモデルの不整合

| コンポーネント | モデル | 言語 | 使用状況 |
|--------------|--------|------|---------|
| ChromaDB (`vector_store.py`) | `all-MiniLM-L6-v2` | 英語中心 | Legacy パスのみ |
| `embedding_model.py` | `paraphrase-multilingual-MiniLM-L12-v2` | 多言語対応 | failure_memory + guardrail のみ |

日本語主体の会話なのに、英語モデルが使われている（ChromaDB 側）。
多言語モデルは存在するが、メイン検索パスでは一切呼ばれていない。

### 1.3 未使用だが有用な既存コード

- `memory_manager._recency_bonus()`: 半減期 7 日の新鮮度スコア
- `memory_manager._dist_to_sim()`: 距離→類似度変換
- `embedding_model.encode()` / `cosine_similarity()`: 多言語ベクトル演算
- ハイブリッドスコアリング公式: `0.65*sim + 0.30*eff + 0.05*rec`

---

## 2. 設計方針

### 2.1 基本思想

> **広く蓄積 + 賢く引き出す**
>
> 記憶の蓄積側は意図的に緩い（inferred → 24h → confirmed）。
> この方針を維持しつつ、引き出し側の精度を上げることで投資効率を最大化する。

### 2.2 制約

- LLM 呼び出し追加: **0 回/ターン**（検索にLLMを使わない）
- レイテンシ増加: **100ms 以下**（depth0 の 30s タイムアウトを阻害しない）
- 既存の Pinned / Working の仕組みは変更しない（問題がないため）
- Long Term セクションの検索精度のみ改善対象

---

## 3. アーキテクチャ: Query-Aware Retrieval

### 3.1 全体フロー

```
ユーザー入力 (user_query)
        ↓
  ┌─────────────────────────────┐
  │  Step 1: Intent Detection   │  ← ルールベース（LLM不要）
  │  - temporal?  ("昨日", "前") │
  │  - topic?     (名詞抽出)    │
  │  - recall?    ("〜だっけ")   │
  └────────────┬────────────────┘
               ↓
  ┌─────────────────────────────┐
  │  Step 2: Candidate Pool     │  ← SQL + ベクトル検索の並列実行
  │  A) SQL: search_active()    │     confidence DESC, limit=30
  │  B) Vec: semantic_search()  │     cosine_sim(query, memory)
  └────────────┬────────────────┘
               ↓
  ┌─────────────────────────────┐
  │  Step 3: Hybrid Scoring     │  ← 既存公式の拡張
  │  score = w_sim * sim        │
  │        + w_conf * confidence│
  │        + w_rec * recency    │
  │        + w_intent * intent  │
  └────────────┬────────────────┘
               ↓
  ┌─────────────────────────────┐
  │  Step 4: Select Top-K       │  ← CONTEXT_MAX_SEMANTIC (8)
  │  - 重複排除                  │
  │  - 最低スコア閾値            │
  └────────────┬────────────────┘
               ↓
       LLM プロンプトへ注入
```

### 3.2 Step 1: Intent Detection（ルールベース）

LLM を呼ばずに、正規表現 + キーワードマッチでクエリの意図を分類する。

```python
@dataclass
class QueryIntent:
    is_temporal: bool = False     # 時間参照あり（「昨日」「前に」「この間」）
    is_recall: bool = False       # 記憶想起（「〜だっけ」「〜って言ってた」）
    is_topic_specific: bool = False  # 特定トピック（名詞が含まれる）
    temporal_hint: str = ""       # "yesterday", "recent", "old" など
    topic_keywords: list[str] = field(default_factory=list)
```

#### パターン例

| パターン | 判定 | 効果 |
|---------|------|------|
| `昨日`, `前に`, `この間`, `さっき` | `is_temporal=True` | recency ボーナス増加 |
| `〜だっけ`, `〜って言ってた`, `覚えてる？` | `is_recall=True` | similarity 重視 |
| 名詞が 1 個以上 | `is_topic_specific=True` | topic キーワードでフィルタリング |
| 上記いずれもなし | デフォルト | 標準ウェイト |

### 3.3 Step 2: Candidate Pool

**2 つの検索を並列実行**し、候補プールをマージする。

#### A) SQL Candidates（既存の `search_active()`）

```sql
SELECT * FROM semantic_memories
WHERE thread_id=? AND status IN ('confirmed', 'inferred')
ORDER BY confidence DESC, created_at DESC
LIMIT 30
```

- 変更なし。confidence 上位を「取りこぼし防止」として確保する。

#### B) Semantic Candidates（新規追加）

```python
def semantic_search(
    query: str,
    thread_id: str,
    *,
    limit: int = 30,
    status_filter: tuple[str, ...] = ("confirmed", "inferred"),
) -> list[ScoredMemory]:
    """
    多言語埋め込みモデルで semantic_memories を類似度検索する。
    """
    # 1. クエリをエンコード
    query_vec = embedding_model.encode([query])  # multilingual model
    if query_vec is None:
        return []

    # 2. 候補の semantic memories を取得（SQL で status + thread_id フィルタ）
    candidates = semantic_store.search_active(thread_id, limit=limit)

    # 3. 各候補をエンコードして cosine similarity を計算
    if not candidates:
        return []

    texts = [m.content for m in candidates]
    mem_vecs = embedding_model.encode(texts)
    if mem_vecs is None:
        return []

    # 4. スコアリング
    scored = []
    for i, mem in enumerate(candidates):
        sim = embedding_model.cosine_similarity(query_vec[0], mem_vecs[i])
        scored.append(ScoredMemory(memory=mem, similarity=sim))

    return sorted(scored, key=lambda x: x.similarity, reverse=True)
```

**注意**: semantic_memories のサイズが大きくなったら、SQLite の全件取得ではなく
ベクトルインデックス（ChromaDB / pgvector）に移行する。
現時点では数十〜数百件規模のため、全件エンコード + cosine sim で十分高速。

#### パフォーマンス見積もり

| 処理 | 所要時間 | 備考 |
|------|---------|------|
| `encode([query])` | ~5ms | 1 テキスト、CPU |
| `search_active()` SQL | ~1ms | SQLite、インデックス済み |
| `encode(30 texts)` | ~30ms | バッチ処理、CPU |
| cosine sim × 30 | <1ms | numpy ドット積 |
| **合計** | **~40ms** | 100ms 制約内 |

### 3.4 Step 3: Hybrid Scoring

2 つの候補プールをマージし、統一スコアで再ランキングする。

```python
def hybrid_score(
    memory: SemanticMemory,
    similarity: float,        # 0.0-1.0（Step 2B）
    intent: QueryIntent,      # Step 1
    now: float,               # time.time()
) -> float:
    """
    4 要素のハイブリッドスコアを算出する。
    """
    # 1. Similarity（クエリとの意味的近さ）
    sim = similarity  # 0.0-1.0

    # 2. Confidence（記憶の確信度）
    conf = memory.confidence  # 0.0-1.0

    # 3. Recency（新鮮度、半減期 7 日）
    age_days = max(0.0, (now - memory.updated_at) / 86400.0)
    rec = 0.5 ** (age_days / 7.0)

    # 4. Intent Bonus（意図マッチ）
    intent_bonus = _compute_intent_bonus(memory, intent)

    # ウェイト（意図によって動的調整）
    if intent.is_recall:
        # 「〜だっけ？」→ 類似度重視
        w = (0.55, 0.20, 0.10, 0.15)
    elif intent.is_temporal:
        # 「昨日の〜」→ 新鮮度重視
        w = (0.35, 0.15, 0.35, 0.15)
    else:
        # デフォルト
        w = (0.45, 0.25, 0.15, 0.15)

    return w[0] * sim + w[1] * conf + w[2] * rec + w[3] * intent_bonus
```

#### Intent Bonus の詳細

```python
def _compute_intent_bonus(memory: SemanticMemory, intent: QueryIntent) -> float:
    bonus = 0.0

    # トピックキーワードマッチ
    if intent.topic_keywords:
        content_lower = memory.content.lower()
        matches = sum(1 for kw in intent.topic_keywords if kw.lower() in content_lower)
        bonus += min(1.0, matches / max(1, len(intent.topic_keywords)))

    # 時間ヒント（「昨日」なら 24h 以内のものにボーナス）
    if intent.is_temporal and intent.temporal_hint == "yesterday":
        age_hours = (time.time() - memory.updated_at) / 3600.0
        if age_hours <= 48:
            bonus += 0.5

    return min(1.0, bonus)
```

### 3.5 Step 4: Select Top-K

```python
def select_top_k(
    scored: list[ScoredMemory],
    *,
    k: int = 8,              # CONTEXT_MAX_SEMANTIC
    min_score: float = 0.1,  # 最低スコア閾値
) -> list[ScoredMemory]:
    # 重複排除（同一 ID）
    seen_ids: set[str] = set()
    unique = []
    for sm in scored:
        if sm.memory.id in seen_ids:
            continue
        if sm.score < min_score:
            continue
        seen_ids.add(sm.memory.id)
        unique.append(sm)

    # スコア順で top-K
    unique.sort(key=lambda x: x.score, reverse=True)
    return unique[:k]
```

---

## 4. Pinned Facts の改善

Pinned Facts は「常に表示される基礎情報」なので、クエリ依存にはしない。
ただし、**表示順序**をクエリに応じて並べ替える（内容は同じ、順番だけ変わる）。

```python
def _build_pinned_v2(
    active_memories: list[SemanticMemory],
    user_query: str,
    *,
    limit: int = 5,
) -> str:
    confirmed = [m for m in active_memories if m.status == "confirmed" and m.confidence >= 0.7]
    if not confirmed or not user_query:
        # クエリなし or 候補なし → 既存ロジック
        lines = [f"- {m.content}" for m in confirmed[:limit]]
        return "\n".join(lines)

    # クエリとの類似度でソート（表示順のみ変更、フィルタリングはしない）
    query_vec = embedding_model.encode([user_query])
    if query_vec is None:
        lines = [f"- {m.content}" for m in confirmed[:limit]]
        return "\n".join(lines)

    mem_vecs = embedding_model.encode([m.content for m in confirmed[:limit]])
    if mem_vecs is None:
        lines = [f"- {m.content}" for m in confirmed[:limit]]
        return "\n".join(lines)

    pairs = []
    for i, m in enumerate(confirmed[:limit]):
        sim = embedding_model.cosine_similarity(query_vec[0], mem_vecs[i])
        pairs.append((m, sim))

    # 類似度が高いものを先頭に（LLM は先頭の情報をより重視する傾向）
    pairs.sort(key=lambda x: x[1], reverse=True)
    lines = [f"- {m.content}" for m, _ in pairs]
    return "\n".join(lines)
```

---

## 5. 変更対象ファイル

| ファイル | 変更内容 |
|---------|---------|
| `backend/services/memory/context_builder.py` | `_build_long_term` に semantic_search 統合、`_build_pinned` v2 |
| `backend/services/memory/retrieval.py` | **新規**: QueryIntent, semantic_search, hybrid_score, select_top_k |
| `backend/services/memory/semantic_store.py` | `search_active()` に limit 引数の柔軟化（既存） |
| `backend/core/config.py` | `RETRIEVAL_*` 設定追加 |

### 新規ファイル: `backend/services/memory/retrieval.py`

```
retrieval.py
├── QueryIntent (dataclass)
├── ScoredMemory (dataclass)
├── detect_intent(user_query) → QueryIntent
├── semantic_search(query, thread_id) → list[ScoredMemory]
├── hybrid_rank(sql_candidates, vec_candidates, intent) → list[ScoredMemory]
├── select_top_k(scored, k, min_score) → list[ScoredMemory]
└── retrieve(user_query, thread_id, limit) → list[SemanticMemory]
         ↑ context_builder から呼ばれるエントリーポイント
```

---

## 6. 設定値

```python
# config.py に追加
RETRIEVAL_ENABLED = _env_bool("RETRIEVAL_ENABLED", True)  # False なら既存ロジックにフォールバック
RETRIEVAL_CANDIDATE_N = _env_int("RETRIEVAL_CANDIDATE_N", 30)
RETRIEVAL_MIN_SCORE = _env_float("RETRIEVAL_MIN_SCORE", 0.1)
RETRIEVAL_PINNED_REORDER = _env_bool("RETRIEVAL_PINNED_REORDER", True)

# ウェイトの微調整（env で上書き可能）
RETRIEVAL_W_SIM = _env_float("RETRIEVAL_W_SIM", 0.45)
RETRIEVAL_W_CONF = _env_float("RETRIEVAL_W_CONF", 0.25)
RETRIEVAL_W_REC = _env_float("RETRIEVAL_W_REC", 0.15)
RETRIEVAL_W_INTENT = _env_float("RETRIEVAL_W_INTENT", 0.15)
```

---

## 7. 実装フェーズ

### Phase M.1: Foundation（最小限の改善）

- [ ] **埋め込みモデル統一**: `vector_store.py` の `all-MiniLM-L6-v2` → `paraphrase-multilingual-MiniLM-L12-v2`
  - ChromaDB コレクションを再作成（既存データは Legacy パス未使用のため影響なし）
  - `embedding_model.py` の `_MODEL_NAME` を唯一の正とし、`vector_store.py` から参照
- [ ] `retrieval.py` 新規作成（detect_intent + semantic_search + hybrid_rank）
- [ ] `context_builder._build_long_term()` で `user_query` を活用
- [ ] `RETRIEVAL_ENABLED` フラグでフォールバック可能に
- [ ] 既存テスト通過確認

**期待効果**: 「〜だっけ？」系のクエリで関連記憶が返るようになる + 日本語検索精度向上

### Phase M.2: Pinned Reorder + Intent Detection

- [ ] `_build_pinned_v2()` 実装（表示順のクエリ連動）
- [ ] Intent Detection の正規表現パターン拡充
- [ ] temporal ヒントの時間解析（「昨日」→ 24h, 「先週」→ 7d）
- [ ] ログ出力（検索スコアの可視化）

**期待効果**: 会話の流れに応じて Pinned Facts の並びが変わる

### Phase M.3: Embedding Cache + Vector Index

- [ ] semantic_memories の埋め込みキャッシュ（encode 結果を保存）
  - `semantic_memories` テーブルに `embedding BLOB` カラム追加
  - Sleep Cycle でバッチエンコード（新規/更新分のみ）
  - 検索時は保存済みベクトルを使用（再エンコード不要）
- [ ] 記憶数が 500 件超の場合の性能テスト

**期待効果**: 検索速度 40ms → 5ms（キャッシュヒット時）

### Phase M.4: Observability（将来）

- [ ] 検索クエリ + 返された記憶 + スコアのログ記録
- [ ] ダッシュボードで「どの記憶がよく引き出されるか」を可視化
- [ ] A/B テスト基盤（ウェイト調整の効果測定）

---

## 8. 設計ノート

### 8.1 なぜ LLM を検索に使わないか

LLM ベースのクエリ拡張（HyDE 等）は精度が上がるが、レイテンシとコストが増える。
ニアの depth0 は 30 秒タイムアウトで max_tokens=160 の高速応答が求められるため、
検索パスに LLM を入れるとボトルネックになる。

ルールベースの Intent Detection + 埋め込みモデルの組み合わせで、
LLM コスト 0 でかなりの精度向上が見込める。

### 8.2 全件エンコードは大丈夫か

現在の semantic_memories は数十件規模。Phase M.3 で埋め込みキャッシュを入れれば、
数百件でも問題ない。数千件超えたら ChromaDB / pgvector でインデックスを使う。

段階的に対応する:
- ~100 件: 全件エンコード（~40ms、問題なし）
- ~500 件: 埋め込みキャッシュ（~5ms）
- ~1000 件+: ベクトルインデックス移行

### 8.3 既存のハイブリッドスコアリングとの関係

`chat_history_store.get_memory_context()` のスコアリング（0.65/0.30/0.05）は
**episodic_captures テーブル**を対象としたもので、Legacy パス。

新設計は **semantic_memories テーブル**を対象とし、ウェイトも 4 要素に拡張。
Legacy パスは段階的に廃止する方向（LEGACY_MEMORY_TABLES_ENABLED=False）。

### 8.4 Pinned Facts を検索対象から外さない理由

Pinned は「常に表示」だが、Long Term にも同じ記憶が含まれうる。
重複排除は `select_top_k()` の ID チェックで行うため、
Pinned に出た記憶が Long Term にも重複表示されることはない。

### 8.5 Autonomous Reflection との連携

Autonomous Reflection で生成された insight（`state_tag="insight"`）は
semantic_memories に保存される。この設計により、insight も自動的に
クエリ依存の検索対象になる。特別な処理は不要。

---

## 9. 残課題

1. **名詞抽出の精度**: 日本語の名詞抽出にどこまで力を入れるか（MeCab? 正規表現?）
2. **ウェイトの初期値**: 実データでチューニングが必要（Phase M.4）
3. **Working Items の検索連動**: 現在は priority 順だが、クエリに関連する working item を優先する余地あり
