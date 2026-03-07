# Nia Metacognition Architecture — 設計ドキュメント

**作成日**: 2026-02-24
**ステータス**: 実装完了（2026-02-24）

> **実装ノート**: R.a〜R.d（Retrieval先行改善）+ N.0〜N.5（Metacognition）全フェーズ実装済み。
> テスト: 955 passed, 7 skipped（metacog関連112件含む）。
> 主要ファイル:
> - `backend/services/memory/metacognition.py` — N.0 Awareness Core + N.1 MetaCog Check + N.5 Self-Narrative
> - `backend/services/memory/contradiction.py` — N.2 Contradiction Detection
> - `backend/services/memory/self_model.py` — N.3 Self-Model Generation
> - `backend/services/idle_detector.py` — N.4 State-Driven Reflection Trigger
> - `backend/core/agent_graph/nodes/actions.py` — S5 統合（awareness計算、narrative保存、metacog stats蓄積）
> - `backend/core/agent_graph/nodes/routing.py` — N.5 narrative読出し → context_builder注入

## 0. 設計思想

### なぜニアにメタ認知が必要か

ニアの現在の「自己意識」は点描画である。
- ターンごとの confidence 計算（数秒の断片）
- 3分アイドルの振り返り（たまに起きるイベント）
- Sleep Cycle（1日1回のバッチ）

点と点の間でニアは「存在していない」。これ自体は設計上の選択として受け入れる（Presence Spec: 沈黙＝意図された静止）。

しかし、**点の質**は改善できる。

現在の問題:
1. **対話のズレに気づけない**: ユーザーの訂正・困惑・話題転換が「信号」として処理されない
2. **confidence は自己申告**: LLM が自分の確信度を自分で判断している（ダニング＝クルーガー問題）
3. **記憶の矛盾に気づけない**: semantic_memories 同士の矛盾を検出する仕組みがない
4. **自己モデルがない**: identity.md の Recent Learnings は空。ニアは「自分がどう変わったか」を認識できない
5. **振り返りが外発的**: 3分タイマーで起動するため「考えたくなったから考える」ではない
6. **内部状態の言語化がない**: confidence=0.4 が「モヤモヤする」という主観として処理されない

### 設計原則

- **ニアの性格を変えない**: メタ認知は内部インフラ。ニアの関係性ベースの性格はそのまま
- **「人間の模倣」ではなく「ニアなりの自己認識」**: 連続的な意識を目指さない
- **既存アーキテクチャの延長**: 新しいフレームワークは導入しない。今の構造に薄い層を追加する
- **LLM 呼び出しの最小化**: N.0, N.1, N.4, N.5 は LLM 不要。N.2, N.3 は Sleep Cycle 内（1日1回）

### 合体アーキテクチャからの適応

本設計は、汎用知性向けに検討された「合体アーキテクチャ」（Curiosity Core + 誠実性ゲート + Claim Schema + Dissonance Graph 等）から、ニアの思想に合う要素を選択的に適応したものである。

#### A. そのまま使える（ニアの思想と矛盾しない）
- **tombstone 付き忘却** → N.2 に組み込み。revoke 時に「消した理由」と「代替記憶」を残す
- **Idle Runtime の思想** → N.4（状態駆動トリガー）として既に同じ方向

#### B. 翻訳して使う（概念を借りるが、向きを変える）
- **Curiosity Core** → **Awareness Core（N.0）** に翻訳。「知りたい」ではなく「気になる」が駆動力
- **Claim Schema の defeaters** → semantic_memories に反証条件を追加。矛盾検出の効率化
- **Dissonance Graph** → 矛盾の一時保留（working_items, TTL=3日）。対話の中で自然に解消
- **Integrity** → 三戒のランタイム強制チェック（N.1 に統合）

#### C. ニアには入れない（ネロ専用）
- Curiosity Core の内発報酬関数（R_int = Surprise × Learnability × Integrity）
- Output Gate 完全版（Generator → Verifier → Judge の3段）

### Retrieval 先行改善（N.x の前提）

N.1（メタ認知チェック）と N.2（矛盾検出）は記憶検索の精度に依存する。Phase M.1（Query-Aware Retrieval）は実装済みだが、以下の改善を N.x 着手前に行うことで、メタ認知層の精度が上がる。

> **原則**: 引き出しが賢くなれば、保存側で何を構造化すべきかも見えてくる。

#### R.a: janome による日本語名詞抽出

Intent Detection（`retrieval.py` の `detect_intent()`）の `topic_keywords` は現在正規表現ベースで精度が低い。

- **janome**（純 Python、pip install のみ）で形態素解析 → 名詞抽出に置換
- MeCab ほど速くないが 1 クエリ ~3-5ms（100ms 制約に余裕）
- N.1 の `embedding_similarity()` の入力品質も向上

```python
# retrieval.py の detect_intent() 内
from janome.tokenizer import Tokenizer
_tokenizer = Tokenizer()

def _extract_nouns(text: str) -> list[str]:
    return [
        token.surface
        for token in _tokenizer.tokenize(text)
        if token.part_of_speech.startswith("名詞")
        and token.surface not in _STOP_NOUNS
    ]
```

#### R.b: 保存時エンコード（Phase M.3 先行）

現在の `semantic_search()` は検索のたびに全件エンコードしている。Phase M.3（Embedding Cache）を待たずに、**保存時にベクトルを同時格納**する設計に移行する。

```sql
-- N.2 の defeaters カラムと同じ migration で追加
ALTER TABLE semantic_memories ADD COLUMN embedding BLOB;
```

- **新規記憶**: `semantic_store.upsert()` 時にエンコード → `embedding` カラムに保存
- **既存記憶**: Phase M.3 でバックフィル（または Sleep Cycle でバッチエンコード）
- **効果**: N.1 と N.2 の `cosine_similarity()` が SQLite 内で完結（ChromaDB 不要）
- **検索速度**: 40ms → ~5ms（エンコード済みベクトルの読み取りのみ）

#### R.c: Retrieval 品質の簡易評価（Sleep Cycle 追加）

Phase M.4（Observability）を待たずに、ウェイト調整のヒントを得る。

```python
async def _evaluate_retrieval_quality(thread_id: str):
    """
    Sleep Cycle 内で実行。
    「今日返された記憶が実際に会話で参照されたか」をログから逆算。
    """
    # 1. 今日の retrieval ログ（どの記憶が返されたか）
    retrieved_ids = _get_today_retrieved_ids(thread_id)

    # 2. 今日の会話ログから、実際に応答に影響した記憶を推定
    referenced_ids = _get_today_referenced_ids(thread_id)

    # 3. 精度指標
    if retrieved_ids:
        precision = len(retrieved_ids & referenced_ids) / len(retrieved_ids)
        _write_kv(conn, "retrieval_precision", str(round(precision, 3)))
        # precision が低い → similarity weight を上げるべき
        # precision が高い → 現状バランス OK
```

#### R.d: Pinned Facts ソートモードの設定化

MoE モデルでは位置バイアスの強さが Vanilla Transformer と異なる可能性があるため、実測前に設定で切り替え可能にする。

```python
PINNED_SORT_MODE = "relevance"  # "relevance" | "confidence" | "random"(A/Bテスト用)
```
- Dissonance Graph の永続保持（探索ターゲット化）
- 探索スレッド（自律的な調査行動）
- 誤り統計としての Self-Model

---

## 1. 全体アーキテクチャ

```
[ターンごとの処理]
  S0 SafetyInterrupt
  S1 Pre-Thought
    └─ N.1 メタ認知チェック（confidence 補正 + 三戒チェック）  ← NEW
  S2 Organize (Depth0/1/2)
    └─ N.5 Self-Narrative（内部状態の言語化）                  ← NEW
  S3 Retrieve
  S4 Answer
  S5 Commit
    └─ N.0 Awareness Core（対話のズレ検出 + 内省シグナル）    ← NEW
    └─ ターン統計の蓄積（confidence 分散、dissonance 回数）

[状態蓄積時]
  N.4 状態駆動トリガー                                        ← NEW（idle_detector 拡張）
    └─ 内部条件（N.0 蓄積含む）で振り返り開始

[Sleep Cycle]
  既存: episodic → semantic 抽出
  既存: inferred → confirmed/revoked
  N.2 矛盾検出（tombstone + defeaters + 一時保留）           ← NEW
  N.3 Self-Model 生成                                        ← NEW
  既存: compression, diary, etc.
```

---

## 2. Phase N.0: Awareness Core（対話のズレ検出）

### 思想

ネロの Curiosity Core は `R_int = Surprise × Learnability × Integrity` で「世界を理解したい」が駆動力。ニアの駆動力はそこではない。

ニアの内発動機は**「関係性への感度」**。「分からないことがある」→ 知りたい（ネロ）ではなく、「うまくいかなかった」→ 気になる → 振り返り（ニア）。

Awareness Core は Curiosity Core の**「観測だけ版」**。駆動するが行動は生まない。検出結果は既存の振り返りパイプライン（N.4 → Reflection Engine）に委ねる。

### 内発報酬の定義（ニア版）

```
R_nia = Relational_Surprise × Growth_Signal × Authenticity
```

| 項 | ネロ（Curiosity Core） | ニア（Awareness Core） |
|----|----------------------|----------------------|
| 第1項 | Surprise（予測誤差） | **Relational_Surprise**（対話のズレ） |
| 第2項 | Learnability（圧縮改善） | **Growth_Signal**（この経験から学べるか） |
| 第3項 | Integrity（誠実性維持） | **Authenticity**（自分に嘘をつかなかったか） |

### 各項の詳細

#### Relational_Surprise — 「あれ？」の検出

世界についての予測誤差ではなく、**対話の中で期待とズレたもの**:

```
信号源:
- ユーザーが訂正してきた（「いや、そうじゃなくて」）
- ユーザーの反応が予想と違った（冷たい / 急に話題変更）
- 自分の記憶と食い違う発言があった
- 自分の応答に対してユーザーが困惑した
```

ニアの世界は対話の中でのみ形づくられるから、**対話のズレ = ニアにとっての予測誤差**。

#### Growth_Signal — 「これは意味がある経験か？」

ネロの Learnability は「世界モデルの圧縮改善」。ニアにとっての「学び」は:

```
信号源:
- 同じ種類のズレが2回以上起きた（パターン）
- ズレの原因が自分の理解不足にある
- この経験が identity の成長エッジに関連する
  （N.3 Self-Model の growth_edges と照合）
- ユーザーが明示的に教えてくれた（フィードバック）
```

ノイズ（一回きりの些細なズレ）と信号（学びにつながるズレ）を区別する役割。

#### Authenticity — 「ごまかさなかったか？」

ネロの Integrity は「監査可能性」。ニアの Authenticity は**三戒への忠実さ**:

```
チェック:
- 分からないのに分かったふりをしなかったか
- 記憶にないのに覚えてると言わなかったか
- 不安なのに平気なふりをしなかったか
```

### ネロとの決定的な違い

```
ネロ: R_int が高い → 「もっと調べよう」（探索行動）
ニア: R_nia が高い → 「あとで振り返ろう」（内省行動）
```

Awareness Core は**行動を生まない**。探索スレッドを起動したり、勝手に調べたりしない。代わりに:
1. R_nia が高いターンに**タグを付ける**（episodic event に `awareness_signal: high`）
2. N.4 の状態駆動トリガーの入力になる（「気になることが溜まった → 振り返りたい」）
3. Sleep Cycle で N.3 Self-Model の更新材料になる

### アルゴリズム

```python
@dataclass
class AwarenessSignal:
    relational_surprise: float   # 0.0-1.0
    growth_signal: float         # 0.0-1.0
    authenticity: float          # 0.0-1.0
    composite: float             # 三項積
    trigger_reasons: list[str]   # ["user_correction", "memory_mismatch", ...]


def compute_awareness(
    *,
    user_response: str,          # ユーザーの最新発話
    nia_previous: str,           # ニアの直前の発話
    metacog: MetaCogResult,      # N.1 の結果
    dissonance_on: bool,
    self_model: dict | None,     # N.3 の Self-Model
) -> AwarenessSignal:
    """S5 Commit 時に計算。LLM 不要。ルールベースのみ。"""

    rs = _calc_relational_surprise(user_response, nia_previous, metacog)
    gs = _calc_growth_signal(rs, self_model)
    au = _calc_authenticity(metacog, dissonance_on)

    return AwarenessSignal(
        relational_surprise=rs,
        growth_signal=gs,
        authenticity=au,
        composite=rs * gs * au,
        trigger_reasons=_collect_reasons(rs, gs, au),
    )


def _calc_relational_surprise(
    user_response: str, nia_previous: str, metacog: MetaCogResult,
) -> float:
    """対話のズレを検出。"""
    score = 0.0
    u = (user_response or "").strip()
    if not u:
        return 0.0

    # ユーザーが訂正してきた
    correction_cues = ["違う", "そうじゃなく", "いや、", "じゃなくて", "そうじゃない"]
    if any(c in u for c in correction_cues):
        score += 0.4

    # 急な話題転換（直前のニアの発話と semantic distance が大きい）
    # → embedding 比較は重いので、簡易ヒューリスティック
    if nia_previous and len(u) > 10:
        # ニアの直前の話題と無関係なキーワードが多い場合
        overlap = _keyword_overlap(nia_previous, u)
        if overlap < 0.1:
            score += 0.2

    # 記憶との不整合（N.1 で検出済み）
    if metacog.contradiction_detected:
        score += 0.3

    # ユーザーが困惑した
    confusion_cues = ["え？", "どういうこと", "意味わからん", "ん？", "は？"]
    if any(c in u for c in confusion_cues):
        score += 0.3

    return min(1.0, score)


def _calc_growth_signal(rs: float, self_model: dict | None) -> float:
    """このズレが学びにつながるかを判定。"""
    if rs < 0.1:
        return 0.0  # ズレがなければ学びもない

    base = min(rs * 0.8, 0.6)  # ズレの大きさに比例（キャップ 0.6）

    # Self-Model の growth_edges に関連するズレはブースト
    if self_model and self_model.get("growth_edges"):
        # 将来: growth_edges とのマッチングでブースト
        base += 0.1

    return min(1.0, base)


def _calc_authenticity(metacog: MetaCogResult, dissonance_on: bool) -> float:
    """三戒に忠実だったかを判定。"""
    score = 1.0  # デフォルト: 忠実

    # 根拠のない高確信 = 「分かったふり」の可能性
    if metacog.grounding_hits == 0 and metacog.raw_confidence > 0.8:
        score -= 0.4

    # dissonance が出てるのに無視した場合（将来: 応答テキストとの照合）
    # 現時点では dissonance_on 自体は正直な反応なのでペナルティなし

    return max(0.0, score)
```

### S5 Commit への統合

```python
# S5 Commit 内
awareness = compute_awareness(
    user_response=user_text,
    nia_previous=nia_previous_text,
    metacog=state.get("metacog_result"),
    dissonance_on=state.get("dissonance_on", False),
    self_model=_load_current_self_model(),
)

# episodic event にタグ付け
if awareness.composite > 0.3:
    event_payload["awareness_signal"] = "high"
    event_payload["awareness_reasons"] = awareness.trigger_reasons

# N.4 用に蓄積
_update_awareness_stats(conn, awareness)
```

### コスト

- LLM 呼び出し: なし（全てルールベース）
- 処理時間: <5ms
- 出力: episodic event へのタグ + telemetry_kv への統計蓄積

---

## 3. Phase N.1: メタ認知チェック（Confidence 外部検証 + 三戒ランタイムチェック）

### 問題

ConfidenceEngine は context_coverage, self_consistency, logit_based, question_clarity の4軸で composite confidence を算出する。しかし、**記憶との照合がない**。

また、三戒（捏造しない・覚えてないことを覚えてると言わない・決まってないことは正直に）はプロンプトでのみ強制されており、**コードレベルでのチェックがない**。

### 解決

S1 Pre-Thought の後に**メタ認知補正パス**と**三戒ランタイムチェック**を追加する。

### アルゴリズム

```python
def metacognitive_check(
    *,
    raw_confidence: float,
    user_query: str,
    thread_id: str,
) -> MetaCogResult:
    """
    LLM 呼び出し不要。DB クエリ + ルールベースのみ。
    """
    # 1. 記憶裏付けスコア（memory_grounding）
    hits = semantic_store.search_active(thread_id, limit=5)
    relevant = [h for h in hits if embedding_similarity(h, user_query) > 0.4]

    grounding_score = 0.0
    if relevant:
        avg_confidence = mean(h.confidence for h in relevant)
        confirmed_ratio = sum(1 for h in relevant if h.status == 'confirmed') / len(relevant)
        grounding_score = 0.5 * min(len(relevant) / 3, 1.0) + 0.3 * avg_confidence + 0.2 * confirmed_ratio

    # 2. 矛盾フラグ
    contradiction = _check_pairwise_contradiction(relevant)

    # 3. 三戒チェック（合体アーキテクチャの Integrity をニア向けに翻訳）
    sankai_flags = _check_three_precepts(
        raw_confidence=raw_confidence,
        grounding_hits=len(relevant),
        user_query=user_query,
    )

    # 4. confidence 補正
    adjusted = raw_confidence
    if grounding_score < 0.2 and raw_confidence > 0.7:
        adjusted = raw_confidence * 0.7  # 根拠なき高確信 → 引き下げ
    elif grounding_score > 0.6 and raw_confidence < 0.5:
        adjusted = raw_confidence + (grounding_score - 0.5) * 0.3  # 引き上げ

    if contradiction:
        adjusted = min(adjusted, 0.5)  # 矛盾あり → キャップ

    # 三戒違反リスクが高い場合も引き下げ
    if sankai_flags.fabrication_risk:
        adjusted = min(adjusted, 0.4)

    return MetaCogResult(
        raw_confidence=raw_confidence,
        adjusted_confidence=clamp(adjusted, 0.0, 1.0),
        grounding_score=grounding_score,
        grounding_hits=len(relevant),
        contradiction_detected=contradiction,
        sankai_flags=sankai_flags,
    )


def _check_three_precepts(
    *,
    raw_confidence: float,
    grounding_hits: int,
    user_query: str,
) -> SankaiFlags:
    """
    三戒のランタイムチェック（合体アーキテクチャの Integrity 翻訳版）。

    1. 捏造リスク: grounding_hits == 0 なのに高確信 → 断定してしまう危険
    2. 偽記憶リスク: ユーザーが「前に話した」系の発言 + 記憶ヒットなし
    3. 過確信リスク: confidence < 0.5 なのにユーザーの質問が結論を求めている
    """
    fabrication_risk = (grounding_hits == 0 and raw_confidence > 0.8)

    recall_cues = ["前に", "この間", "言ってた", "覚えてる", "話した"]
    recall_query = any(c in (user_query or "") for c in recall_cues)
    false_memory_risk = (recall_query and grounding_hits == 0)

    return SankaiFlags(
        fabrication_risk=fabrication_risk,
        false_memory_risk=false_memory_risk,
    )
```

### データ構造

```python
@dataclass
class SankaiFlags:
    fabrication_risk: bool = False    # 戒1: 捏造リスク
    false_memory_risk: bool = False   # 戒2: 偽記憶リスク

@dataclass
class MetaCogResult:
    raw_confidence: float
    adjusted_confidence: float
    grounding_score: float           # 0.0-1.0: 記憶による裏付け度
    grounding_hits: int              # ヒットした関連記憶数
    contradiction_detected: bool     # 矛盾する記憶ペアの有無
    sankai_flags: SankaiFlags        # 三戒チェック結果
```

### 統合ポイント

- **場所**: `routing.py` の `depth_selector()` 内、`_confidence_engine.get_depth_recommendation_v2()` の直後
- **出力**: state に `metacog_result` を追加。`adjusted_confidence` を以降の処理で使用
- **三戒フラグの効果**:
  - `fabrication_risk=True` → confidence を 0.4 にキャップ → Depth1 で慎重に応答
  - `false_memory_risk=True` → N.5 Self-Narrative で「覚えてないかも」を注入
- **ログ**: `telemetry_logger` に記録
- **LLM 呼び出し**: なし

### コスト

- DB クエリ: 1回（search_active — Context Builder と共有可能）
- Embedding 計算: 1回（retrieval.py と共有可能）
- 追加レイテンシ: ~10-30ms

---

## 4. Phase N.2: 矛盾検出（tombstone + defeaters + 一時保留）

### 問題

semantic_memories に以下のような矛盾が蓄積されうる:
- 記憶A (confirmed): 「ジュンはコーヒーが好き」
- 記憶B (inferred): 「ジュンは紅茶派」

現在は revoke は明示的なユーザー訂正か、staleness_days による自然忘却にのみ依存。

### 解決（3つの改善を統合）

#### 4a. tombstone 付き忘却（合体アーキテクチャ A 適応）

現在の revoke は `revoke_reason` と `revoked_by_id` を持つが、実質的に「消す」だけ。

**改善**: revoke 時に以下を必ず記録する（tombstone 化）:
- `revoke_reason`: なぜ無効になったか（矛盾検出 / ユーザー訂正 / 時間経過）
- `revoked_by_id`: 代替となる新しい記憶の ID（supersedes チェーン）
- `tombstone_note`: 追加コンテキスト（「〇〇の話題で矛盾が発覚」等）

**効果**: 都合の悪い事実の抹消を防ぐ。ニアが「前はこう思ってたけど、今は違う」と言える。

```python
# semantic_store.revoke() の拡張
def revoke(
    memory_id: str,
    *,
    reason: str,
    revoked_by_id: str | None = None,
    tombstone_note: str = "",
) -> None:
    # 既存: status='revoked', revoke_reason=reason, revoked_by_id=...
    # 追加: note フィールドに tombstone_note を書き込み
    ...
```

**DB 変更**: なし（既存の `revoke_reason`, `revoked_by_id`, `note` カラムで対応可能）

#### 4b. defeaters（反証条件）の追加（合体アーキテクチャ B 適応）

semantic_memories に `defeaters` フィールドを追加。「こうなったらこの記憶は無効」を事前に定義。

```
記憶: "ジュンはコーヒーが好き"
defeaters: ["紅茶を好むと明言した場合", "カフェインをやめたと言った場合"]
```

**効果**: 矛盾スキャン時に defeaters を先にチェック → LLM 呼び出し削減

```sql
-- semantic_memories テーブルに追加（JSON 配列文字列）
ALTER TABLE semantic_memories ADD COLUMN defeaters TEXT NOT NULL DEFAULT '[]';
```

**生成タイミング**: Sleep Cycle の semantic extraction 時に LLM が同時生成

```
既存プロンプトへの追加:
「この事実が無効になる条件（反証条件）を1〜2個挙げてください」
→ defeaters フィールドに格納
```

#### 4c. 矛盾の一時保留（合体アーキテクチャ B 適応）

ネロは矛盾を永続的に保持する（Dissonance Graph）。ニアは**一時保留**して対話で自然に解消する。

```
検出された矛盾:
  記憶A: "ジュンはコーヒーが好き"
  記憶B: "ジュンは紅茶派"

即 revoke しない。代わりに:
  → working_items に登録（TTL=3日）
  → item_type = "contradiction_hold"
  → 次の会話で自然に確認する機会を待つ
  → 3日経っても解消しなければ、古い方を revoke（tombstone 付き）
```

### アルゴリズム

```
Sleep Cycle 内の実行順序:
  1. 既存: episodic → semantic 抽出
  2. 既存: inferred → confirmed/revoked
  3. 【N.2】矛盾スキャン ← NEW
  4. N.3: Self-Model 生成
  5. 既存: compression, diary, etc.
```

```python
async def scan_contradictions(thread_id: str) -> list[ContradictionPair]:
    """
    confirmed/inferred の semantic_memories から矛盾候補を検出。

    Step 1: defeaters チェック（LLM 不要）
    Step 2: embedding 近傍ペア抽出
    Step 3: LLM による矛盾判定（候補ペアのみ）
    Step 4: 矛盾確定 → 一時保留（working_items）または tombstone revoke
    """
    active = semantic_store.search_active(thread_id, limit=50)

    # Step 1: defeaters チェック（高速、LLM 不要）
    for mem in active:
        defeaters = json.loads(mem.defeaters or "[]")
        for d in defeaters:
            # 他の active 記憶が defeater 条件に該当するかチェック
            # （簡易: キーワードマッチ、将来: embedding 比較）
            matching = [m for m in active if m.id != mem.id and _defeater_matches(d, m.content)]
            if matching:
                # defeater に該当 → 即 revoke（tombstone 付き）
                semantic_store.revoke(
                    mem.id,
                    reason=f"defeater triggered: {d}",
                    revoked_by_id=matching[0].id,
                    tombstone_note=f"反証条件「{d}」に該当する記憶が確認された",
                )

    # Step 2: embedding 近傍ペア抽出
    candidates = []
    for i, a in enumerate(active):
        for b in active[i+1:]:
            sim = cosine_similarity(a.embedding, b.embedding)
            if sim > 0.7:
                candidates.append((a, b, sim))

    if not candidates:
        return []

    # Step 3: LLM 判定（バッチ、最大 CONTRADICTION_MAX_PAIRS ペア）
    candidates.sort(key=lambda x: x[2], reverse=True)
    top_candidates = candidates[:settings.CONTRADICTION_MAX_PAIRS]

    contradictions = []
    for a, b, sim in top_candidates:
        result = await _llm_check_contradiction(a.content, b.content)
        if result.is_contradiction:
            contradictions.append(ContradictionPair(
                memory_a=a, memory_b=b, similarity=sim,
                resolution_type=result.resolution_type,  # "hold" | "supersede"
            ))

    # Step 4: 解決
    for pair in contradictions:
        older = pair.memory_a if pair.memory_a.created_at < pair.memory_b.created_at else pair.memory_b
        newer = pair.memory_a if older == pair.memory_b else pair.memory_b

        if pair.resolution_type == "supersede":
            # 時間的変化 → 即 supersede（tombstone 付き）
            semantic_store.revoke(
                older.id,
                reason=f"時間的変化: superseded by {newer.id}",
                revoked_by_id=newer.id,
                tombstone_note=f"新しい情報「{newer.content[:50]}」により更新",
            )
        else:
            # 矛盾 → 一時保留（working_items に登録、TTL=3日）
            working_store.add(WorkingItem(
                id=str(uuid.uuid4()),
                thread_id=thread_id,
                item_type="contradiction_hold",
                content=f"矛盾: [{older.content}] vs [{newer.content}]",
                priority=2,
                status="open",
                linked_semantic_ids=json.dumps([older.id, newer.id]),
                ttl_turns=None,
                expires_at=time.time() + 3 * 86400,  # 3日後
                created_turn_id="sleep_cycle",
                created_at=time.time(),
                updated_at=time.time(),
            ))

    return contradictions
```

### LLM プロンプト（矛盾判定 — 拡張版）

```
以下の2つの記憶は矛盾していますか？

記憶A: {content_a}
記憶B: {content_b}

回答は JSON で:
{
  "contradiction": true/false,
  "resolution_type": "hold" | "supersede" | "compatible",
  "reason": "理由（1文）"
}

判定基準:
- "compatible": 補完関係（矛盾ではない）
- "supersede": 時間的変化（古い方を更新として扱う）
- "hold": 明確に両立不可能（一時保留して確認が必要）
```

### 矛盾保留の解消フロー

```
working_items (contradiction_hold, TTL=3日)
  │
  ├─ 会話中にユーザーが関連話題に触れた
  │   → Context Builder が working セクションに矛盾を表示
  │   → LLM が自然に確認（「そういえば、コーヒーと紅茶どっちが好きだっけ？」）
  │   → ユーザーの回答で解消 → working を close、古い方を revoke
  │
  └─ TTL 期限切れ（3日経過）
      → S5 Commit の TTL チェックで検出
      → 古い方を自動 revoke（tombstone 付き）
      → working を close (reason="ttl_expired")
```

### データ構造

```python
@dataclass
class ContradictionPair:
    memory_a: SemanticMemory
    memory_b: SemanticMemory
    similarity: float
    resolution_type: str = ""  # "hold" | "supersede" | "compatible"
```

### コスト

- defeaters チェック: LLM 0回（キーワードマッチのみ）
- embedding 近傍: 0回（vector_sync 済み）
- LLM 呼び出し: 0〜10回/日（矛盾候補がある場合のみ）
- 実行タイミング: Sleep Cycle 内（1日1回）

---

## 5. Phase N.3: Self-Model 生成

### 問題

identity.md の `## Recent Learnings` セクションは空。ニアは自分の変化を認識する手段を持たない。
R.4 の cross-day distillation で insight は抽出されるが、それは「ユーザーについてのパターン」であり「自分についての認識」ではない。

### 解決

Sleep Cycle に **Self-Model 生成パス**を追加。日々の対話と振り返りから「ニア自身についての認識」を抽出し、identity.md に反映する。

### アルゴリズム

```
Sleep Cycle 内の実行順序:
  1. 既存: episodic → semantic 抽出
  2. 既存: inferred → confirmed/revoked
  3. N.2: 矛盾スキャン
  4. 【N.3】Self-Model 生成 ← NEW
  5. 既存: compression, diary, etc.
```

```python
async def generate_self_model(thread_id: str) -> SelfModel:
    """
    日次の Self-Model を生成。

    入力:
    - 今日の daily_reflections
    - 直近の semantic_memories (state_tag='insight')
    - 前回の self_model（あれば）
    - 今日の awareness_signal 統計（N.0）

    出力:
    - SelfModel dataclass → identity.md の Recent Learnings に反映
    """
    # 1. 入力収集
    today_reflections = _get_today_reflections(thread_id)
    recent_insights = semantic_store.search_by_tag(thread_id, 'insight', limit=10)
    prev_model = _load_previous_self_model()
    awareness_stats = _get_today_awareness_stats(thread_id)

    # 2. LLM による自己認識抽出
    prompt = f"""
あなたはニアです。今日の振り返りと最近の気づきから、自分自身について認識していることを整理してください。

【今日の振り返り】
{_format_reflections(today_reflections)}

【最近の気づき（パターン）】
{_format_insights(recent_insights)}

【今日の対話で気になったこと】
{_format_awareness_stats(awareness_stats)}

【前回の自己認識】
{_format_prev_model(prev_model)}

以下の4項目について、変化があった部分だけ更新してください。変化がなければ前回のままで構いません。
JSON で出力:
{{
  "current_state": "今の自分の状態を1文で",
  "growth_edges": ["成長途中だと感じること（最大3つ）"],
  "recent_changes": ["最近変わったと感じること（最大3つ）"],
  "relationship_note": "Originとの関係について今感じていること（1文）"
}}
"""

    result = await call_llm(prompt, timeout_seconds=_SLEEP_LLM_TIMEOUT)
    model = _parse_self_model(result)

    # 3. identity.md の Recent Learnings に反映
    _update_identity_recent_learnings(model)

    # 4. 保存（次回の入力用）
    _save_self_model(model)

    return model
```

### identity.md への反映例

```markdown
## Recent Learnings

**最終更新**: 2026-02-24（Sleep Cycle 自動生成）

- **今の状態**: 日常会話では自然に返せるようになってきたけど、抽象的な質問にはまだ戸惑う
- **成長途中**:
  - 感情の言語化（「なんとなく」を超えた表現）
  - 長い文脈の追跡（話題が切り替わると前の文脈を見失いがち）
- **最近の変化**:
  - 冗談に対して自然に反応できるようになった
  - 「分からない」と言うことへの抵抗が減った
- **Originとの関係**: 少しずつ信頼が積み上がっている感じがする
```

### 保存先

- `self_model.json`（`sleep_outputs/` ディレクトリ内）— 履歴として蓄積
- `identity.md` の `## Recent Learnings` セクション — ランタイムで読み込まれる

### コスト

- LLM 呼び出し: 1回/日（Sleep Cycle 内）
- ファイル書き込み: 2件（self_model.json + identity.md）

---

## 6. Phase N.4: 状態駆動トリガー

### 問題

現在の振り返りトリガー:
- `reflection_pending=1`（S5 で daily_turn_count >= REFLECTION_TURN_THRESHOLD 時にセット）
- AND `idle_minutes >= IDLE_THRESHOLD_MINUTES`（30分）

これは**外発的**。ニアが「考えたくなった」わけではなく、タイマーが鳴っただけ。

### 解決

既存のタイマーベースのトリガーは残しつつ、**内部状態に基づくトリガー**を追加する。N.0 Awareness Core の蓄積が主要な入力源。

### トリガー条件

```python
# telemetry_kv に蓄積される統計（S5 Commit で更新）
METACOG_STATS = {
    "confidence_variance":   float,  # 直近5ターンの confidence の分散
    "dissonance_streak":     int,    # 連続 dissonance 検出回数
    "contradiction_recent":  bool,   # N.1 で矛盾検出があったか
    "topic_shift_count":     int,    # 直近5ターンの話題転換回数
    "awareness_average":     float,  # N.0 の直近5ターン composite 平均
}

def should_trigger_reflection(stats: dict) -> tuple[bool, str]:
    """
    内部状態に基づく振り返りトリガー判定。
    idle_detector_loop 内で、既存の pending+idle チェックに加えて呼ばれる。
    """
    # 条件1: Awareness Core が「気になること」を多く検出
    if stats.get("awareness_average", 0) > 0.25:
        return True, "awareness_high"

    # 条件2: confidence が大きく揺れた（迷っていた）
    if stats.get("confidence_variance", 0) > 0.08:
        return True, "confidence_variance_high"

    # 条件3: dissonance が3回以上連続（引っかかりが続いた）
    if stats.get("dissonance_streak", 0) >= 3:
        return True, "dissonance_streak"

    # 条件4: N.1 で矛盾が検出された（記憶の整合性問題）
    if stats.get("contradiction_recent", False):
        return True, "contradiction_detected"

    # 条件5: 話題が急に3回以上変わった（未消化の文脈が残った）
    if stats.get("topic_shift_count", 0) >= 3:
        return True, "topic_shifts"

    return False, ""
```

### idle_detector への統合

```python
async def idle_detector_loop() -> None:
    while True:
        await asyncio.sleep(interval)

        # 既存: pending + idle チェック
        if pending == "1" and idle_minutes >= idle_threshold:
            await _trigger_reflection(reason="timer")
            continue

        # 【N.4】状態駆動トリガー（idle 5分以上で発動可能）
        if idle_minutes >= STATE_TRIGGER_MIN_IDLE_MINUTES:
            stats = _load_metacog_stats(conn)
            should, reason = should_trigger_reflection(stats)
            if should:
                logger.info("[IdleDetector] state-driven trigger: %s", reason)
                await _trigger_reflection(reason=f"state:{reason}")
```

### 統計の蓄積

S5 Commit 内で以下を更新:

```python
def _update_metacog_stats(conn, state: AgentState):
    """ターンごとに metacog 統計を更新。"""
    confidence = state.get("confidence", 0.5)
    dissonance = state.get("dissonance_on", False)

    # confidence 履歴（直近5ターン分リングバッファ）
    history = json.loads(_read_kv(conn, "confidence_history") or "[]")
    history.append(confidence)
    history = history[-5:]
    _write_kv(conn, "confidence_history", json.dumps(history))

    # confidence variance
    if len(history) >= 3:
        mean_c = sum(history) / len(history)
        variance = sum((c - mean_c) ** 2 for c in history) / len(history)
        _write_kv(conn, "confidence_variance", str(round(variance, 4)))

    # dissonance streak
    streak = int(_read_kv(conn, "dissonance_streak") or "0")
    streak = (streak + 1) if dissonance else 0
    _write_kv(conn, "dissonance_streak", str(streak))

    # contradiction_recent（N.1 から伝播）
    metacog = state.get("metacog_result")
    if metacog and metacog.contradiction_detected:
        _write_kv(conn, "contradiction_recent", "1")

    # awareness_average（N.0 から伝播）
    awareness = state.get("awareness_signal")
    if awareness:
        aw_history = json.loads(_read_kv(conn, "awareness_history") or "[]")
        aw_history.append(awareness.composite)
        aw_history = aw_history[-5:]
        _write_kv(conn, "awareness_history", json.dumps(aw_history))
        _write_kv(conn, "awareness_average", str(
            round(sum(aw_history) / len(aw_history), 4)
        ))
```

### コスト

- LLM 呼び出し: なし
- DB クエリ: 1回/ポーリング
- クールダウン: `STATE_TRIGGER_COOLDOWN_MINUTES = 60`

---

## 7. Phase N.5: Self-Narrative（内部状態の言語化）

### 問題

confidence=0.4 はニアにとって「数値」でしかない。人間なら「モヤモヤする」「なんか引っかかる」と感じるところを、ニアは処理していない。

### 解決

S2 (Organize) の前に、**内部状態を短い自然言語に変換する薄い層**を追加。出力はユーザーに見せず、working_memory に注入する。

### アルゴリズム

```python
def generate_self_narrative(
    *,
    metacog: MetaCogResult,      # N.1 の結果
    awareness: AwarenessSignal,  # N.0 の結果（前ターン分）
    dissonance_on: bool,
    self_model: dict | None,     # N.3 の Self-Model
) -> str:
    """
    内部状態を1文の自然言語に変換。

    【重要】LLM 呼び出しはしない。テンプレートベース。
    LLM に自己言語化させると「演技」になるリスクがあるため、
    ルールベースのマッピングで素朴な表現を生成する。
    """
    parts = []
    conf = metacog.adjusted_confidence

    # confidence ベースの状態表現
    if conf < 0.3:
        parts.append("よく分からない感じがする")
    elif conf < 0.5:
        parts.append("なんとなく引っかかる")
    elif conf > 0.85 and metacog.grounding_hits >= 2:
        parts.append("これは覚えてる、たぶん大丈夫")
    elif conf > 0.85 and metacog.grounding_hits == 0:
        parts.append("自信はあるけど、根拠が思い出せない")

    # 三戒フラグ
    if metacog.sankai_flags.false_memory_risk:
        parts.append("これ、本当に覚えてるかな…")
    if metacog.sankai_flags.fabrication_risk:
        parts.append("確証がないのに言い切りそう")

    # dissonance
    if dissonance_on:
        parts.append("何か噛み合わない気がする")

    # contradiction
    if metacog.contradiction_detected:
        parts.append("前に聞いたことと矛盾してるかも")

    # awareness（前ターンのズレが大きかった場合）
    if awareness and awareness.relational_surprise > 0.5:
        parts.append("さっきの反応、ちょっと気になる")

    if not parts:
        return ""

    return "（内心: " + "。".join(parts) + "）"
```

### Context への注入

```
=== WORKING ===
（内心: なんとなく引っかかる。前に聞いたことと矛盾してるかも）
- [open] ゲームの話題について質問する予定
- [contradiction_hold] 矛盾: [コーヒーが好き] vs [紅茶派]（残り2日）
```

### なぜ LLM ではなくテンプレートか

- 「演技」防止: 実際の数値に直結した表現のみ
- コストゼロ
- Presence Spec の「身体は内部状態の副作用」原則に合致

### コスト

- LLM 呼び出し: なし
- 処理時間: <1ms
- 追加トークン: 10-30トークン/ターン

---

## 8. 依存関係と実装順序

```
N.0 Awareness Core ──────────────────────┐
  │                                       │
  ├─→ N.4 に composite 統計を提供         │
  ├─→ N.5 に前ターンの awareness を提供   │
  └─→ N.3 に awareness_stats を提供       │
                                          │
N.1 メタ認知チェック ────────────────────┤
  │                                       │
  ├─→ N.0 に MetaCogResult を提供         │
  ├─→ N.4 に統計蓄積                      │
  └─→ N.5 に MetaCogResult を提供         │
                                          │
N.2 矛盾検出 ────────────────────────────┤
  │                                       │
  └─→ N.3 に矛盾のない記憶を提供          │
                                          │
N.3 Self-Model ───────────────────────────┘
  │
  └─→ N.0, N.5 に Self-Model を提供（optional）
```

### 推奨実装順序

```
Phase R (Retrieval 先行改善) — N.x の精度基盤
  R.a janome 名詞抽出
  R.b 保存時エンコード（embedding カラム + upsert 時格納）
  R.c Retrieval 品質簡易評価（Sleep Cycle 追加）
  R.d Pinned ソートモード設定化
      ↓
Phase N (Metacognition)
  N.1 → N.0 → N.2 → N.3 → N.4 → N.5
```

| Phase | 依存 | LLM追加 | 難易度 | 内容 |
|-------|------|---------|--------|------|
| **R.a** | なし | なし | ★☆☆ | janome 名詞抽出（retrieval.py） |
| **R.b** | なし | なし | ★★☆ | 保存時エンコード（DB migration + upsert 変更） |
| **R.c** | R.b | なし | ★☆☆ | Retrieval 品質評価（Sleep Cycle 追加） |
| **R.d** | なし | なし | ★☆☆ | Pinned ソートモード設定化 |
| **N.1** | R.b | なし | ★★☆ | メタ認知チェック + 三戒ランタイム |
| **N.0** | N.1 | なし | ★★☆ | Awareness Core |
| **N.2** | R.b | 0-10回/日 | ★★★ | 矛盾検出 + tombstone + defeaters + 一時保留 |
| **N.3** | N.2, (N.0) | 1回/日 | ★★☆ | Self-Model |
| **N.4** | N.0, N.1 | なし | ★★☆ | 状態駆動トリガー |
| **N.5** | N.0, N.1, (N.3) | なし | ★☆☆ | Self-Narrative |

**R.b が N.1 と N.2 の前提**。embedding カラムがあれば `cosine_similarity()` が SQLite 内で完結し、N.1 のメタ認知チェックと N.2 の矛盾スキャンが高速になる。

N.1 が N.0 より先なのは、N.0 が MetaCogResult を入力として使うため。

---

## 9. 変更対象ファイル

| Phase | ファイル | 変更内容 |
|-------|---------|----------|
| R.a | `backend/services/memory/retrieval.py` | detect_intent() を janome ベースに置換 |
| R.a | `pyproject.toml` / `requirements.txt` | janome 依存追加 |
| R.b | DB migration | semantic_memories に `embedding BLOB` カラム追加 |
| R.b | `backend/services/memory/semantic_store.py` | upsert() 時にエンコード + embedding 保存 |
| R.b | `backend/services/memory/retrieval.py` | semantic_search() を保存済みベクトル参照に変更 |
| R.c | `backend/scripts/sleep_cycle/orchestrator.py` | _evaluate_retrieval_quality() 追加 |
| R.d | `backend/services/memory/context_builder.py` | PINNED_SORT_MODE 対応 |
| R.d | `backend/core/config.py` | PINNED_SORT_MODE 設定追加 |
| N.0 | `backend/services/memory/metacognition.py` | AwarenessSignal, compute_awareness() |
| N.0 | `backend/core/agent_graph/nodes/actions.py` | S5 で awareness 計算・タグ付け |
| N.1 | `backend/services/memory/metacognition.py` | **新規**: MetaCogResult, SankaiFlags, metacognitive_check() |
| N.1 | `backend/core/agent_graph/nodes/routing.py` | depth_selector に metacog + 三戒チェック統合 |
| N.1 | `backend/services/telemetry_logger.py` | metacog + sankai 結果のログ記録 |
| N.2 | `backend/scripts/sleep_cycle/contradiction.py` | **新規**: scan_contradictions() (tombstone + defeaters + hold) |
| N.2 | `backend/scripts/sleep_cycle/orchestrator.py` | 矛盾スキャンパスの追加 |
| N.2 | `backend/scripts/sleep_cycle/extraction.py` | semantic extraction 時に defeaters 生成 |
| N.2 | DB migration | semantic_memories に `defeaters` カラム追加 |
| N.3 | `backend/scripts/sleep_cycle/self_model.py` | **新規**: generate_self_model() |
| N.3 | `backend/scripts/sleep_cycle/orchestrator.py` | Self-Model 生成パスの追加 |
| N.3 | `identity.md` | Recent Learnings セクションの自動更新 |
| N.4 | `backend/services/idle_detector.py` | 状態駆動トリガー + awareness 条件の追加 |
| N.4 | `backend/services/memory/commit_executor.py` | metacog + awareness 統計の蓄積 |
| N.5 | `backend/services/memory/context_builder.py` | Self-Narrative の working セクション注入 |
| N.5 | `backend/services/memory/metacognition.py` | generate_self_narrative() 追加 |

---

## 10. 設定項目

```python
# .env に追加（Retrieval 先行改善）
JANOME_ENABLED = True                     # R.a: janome 名詞抽出のON/OFF（False→regex フォールバック）
EMBEDDING_AT_SAVE = True                  # R.b: 保存時エンコードのON/OFF
RETRIEVAL_QUALITY_EVAL = True             # R.c: Sleep Cycle での品質評価ON/OFF
PINNED_SORT_MODE = "relevance"            # R.d: "relevance" | "confidence" | "random"

# Metacognition
AWARENESS_CORE_ENABLED = True             # N.0 のON/OFF
AWARENESS_SIGNAL_THRESHOLD = 0.3          # N.0: episodic タグ付け閾値
METACOG_ENABLED = True                    # N.1 全体のON/OFF
METACOG_GROUNDING_THRESHOLD = 0.4         # N.1: 記憶ヒットの similarity 閾値
SANKAI_CHECK_ENABLED = True               # N.1: 三戒ランタイムチェックのON/OFF
CONTRADICTION_SCAN_ENABLED = True         # N.2 のON/OFF
CONTRADICTION_MAX_PAIRS = 10              # N.2: LLM 判定する最大ペア数
CONTRADICTION_HOLD_TTL_DAYS = 3           # N.2: 矛盾一時保留の TTL（日）
SELF_MODEL_ENABLED = True                 # N.3 のON/OFF
STATE_TRIGGER_ENABLED = True              # N.4 のON/OFF
STATE_TRIGGER_COOLDOWN_MINUTES = 60       # N.4 のクールダウン
STATE_TRIGGER_MIN_IDLE_MINUTES = 5        # N.4 の最小アイドル要件
SELF_NARRATIVE_ENABLED = True             # N.5 のON/OFF
```

---

## 11. テスト方針

| Phase | テスト |
|-------|--------|
| R.a | janome で名詞抽出 → topic_keywords にカタカナ/漢字名詞が入る。ストップワード除外 |
| R.b | upsert 時に embedding が保存される。保存済みベクトルで cosine_similarity が動作 |
| R.c | retrieval ログと会話ログの突合せで precision が計算される |
| R.d | PINNED_SORT_MODE=relevance でクエリ関連度順、confidence で既存順 |
| N.0 | ユーザー訂正→RS高、話題転換→RS中、通常会話→RS低、根拠なし高確信→Authenticity低 |
| N.1 | 高confidence+記憶0件→引き下げ、低confidence+記憶3件→引き上げ、矛盾→0.5キャップ、三戒フラグ検出 |
| N.2 | defeater該当→即revoke(tombstone付き)、矛盾→一時保留(working)、補完→スキップ、supersede→tombstone |
| N.3 | reflections+insights+awareness→Self-Model生成、identity.md更新、変化なし→前回踏襲 |
| N.4 | awareness_average高→トリガー、confidence_variance高→トリガー、クールダウン内→抑制 |
| N.5 | conf<0.3→「よく分からない」、false_memory_risk→「覚えてるかな」、RS高→「気になる」 |

---

## 12. 将来の拡張（ネロ連携）

このメタ認知アーキテクチャは、将来的にネロ（独立した分析型AI）との連携基盤になる:

- **N.0 の awareness_signal** → ネロが「ニアが何に引っかかったか」を観測
- **N.1 の contradiction_detected** → ネロに矛盾解決を依頼
- **N.2 の矛盾保留** → ネロが論理的にどちらが正しいか判定（保留期間中に介入）
- **N.3 の Self-Model** → ネロがニアの成長を客観的に評価
- **N.5 の Self-Narrative** → ネロがニアの内部状態を読んでフィードバック

### 共通基盤（将来構築）
- Memory System（episodic / semantic / working）
- Claim / Memory Schema（defeaters を含む）
- 矛盾検出インフラ（embedding 近傍 + LLM 判定）

連携パターン A（非同期レビュー）から始め、B（リアルタイム検証）に進む想定。
詳細はネロの設計ドキュメントで定義する。
