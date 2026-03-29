# Memory Governance Redesign
## 記憶制度・統合設計書（vNext Unified）

> ステータス: Draft  
> 目的: Nia の記憶を、LLM の単独判断ではなく、候補・証拠・審査・保存・減衰・退役から成る制度として再設計する

---

## 1. この文書の位置づけ

この文書は、以下2つの設計を統合した **上位設計** である。

- `memory_promotion_redesign.md`
  - 何を長期記憶として成立させるか
- `memory_decay_redesign.md`
  - 何を覚え続けるか、何を弱めるか、どう退かせるか

本設計では、記憶を「保存して終わり」の静的オブジェクトではなく、  
**成立・維持・変化・退役を含む動的制度** として扱う。

### 1.1 下位設計文書への参照

本統合設計書は上位方針をまとめたものであり、実装詳細は以下の下位文書を参照する。

#### Promotion 詳細
- `memory_promotion_redesign.md`
  - Candidate Harvester の複線化（Rule / LLM / Reflection / Skeleton）
  - Raw Candidate Pool と topic_key の扱い
  - Claim Normalizer の粒度規約
  - Promotion Tribunal
  - identity_candidate の即時パス
  - candidate TTL / stale / expired のライフサイクル管理
  - Evidence Aggregator の初期仮閾値
  - promotion_path による移行戦略
  - skeleton_reinforcement_count の段階的信頼度
  - owner_agent / memory_domain による共通基盤設計

#### Decay 詳細
- `memory_decay_redesign.md`
  - semantic_state / semantic_reviews / semantic_tombstones / semantic_transitions のスキーマ
  - confidence / seed_retention / memory_strength の定義と関係
  - memory_strength の減衰関数（指数減衰 + claim_type 別 λ_type）
  - weaken / deprecate / contradict / archive の仮閾値
  - 状態遷移の方向制約と transition trigger
  - Decay Tribunal の審査タイミング
  - merge_score の構成要素と運用方針
  - decay_path による移行戦略
  - tombstone / archive 運用

#### Core 隣接領域
- `core_adjacency_roadmap.md`
  - Memory / Core 依存関係表
  - Retrieval / Context Builder（Depth 別アクセス方針、weakened の体験変換）
  - Working Memory（Candidate Pool との責務境界）
  - Reflection の責務整理（contradiction_candidate 出力）
  - SkeletonCore との接続（ルーティングテーブル、信頼度管理）
  - State / Signal 層の整理

#### 補足設計
- `memory_system_supplementary.md`
  - seed_retention 算出ロジック（Promotion → Decay 接続点）
  - テスト戦略（状態遷移 / フロー統合 / 閾値境界 / 検索汚染）
  - Phase 0 計装ガイド（governance_events テーブル、JSONL フォーマット、M0.5 逆算）

#### 読み方の原則
- **本書は「制度全体の骨格」**
- **下位文書は「各制度の詳細」**
- 実装時は本書だけで完結させず、対応する下位文書を必ず参照する

---

## 2. 基本思想

### 2.1 長期記憶は「見つかったもの」ではなく「審査を通ったもの」
LLM がその場で「これは覚えるべきだ」と決めるのではなく、  
候補・証拠・審査を経て、長期記憶として成立する。

### 2.2 忘却は「喪失」ではなく「弱化・退役・統合・痕跡化」
記憶は単に消えるのではなく、

- 薄れる
- 中心から退く
- 新しい意味へ統合される
- 痕跡として残る

という多段階の変化を持つ。

### 2.3 Promotion と Decay は対称な制度
- **Promotion** = 記憶の入口の制度
- **Decay** = 記憶の出口の制度

両者は独立しているが、共通の骨格を持つ。

### 2.4 仕組みは隠し、体験だけ渡す
制度そのものは Nia に露出しない。  
Nia に渡るのは、結果としての記憶体験だけである。

---

## 3. 制度全体の構造

```text
Episodic / Reflection / Working / Skeleton
→ Candidate Harvester
→ Raw Candidate Pool
→ Evidence Aggregator
→ Claim Normalizer（遅延評価）
→ Promotion Tribunal
→ Semantic Save
→ Reinforcement / Weakening / Contradiction / Deprecation / Merge / Archive
→ Tombstone / Optional Forget
```

---

## 4. Promotion（昇格）制度

> 詳細: `memory_promotion_redesign.md`

### 4.1 役割
Promotion は、**何を長期記憶として成立させるか** を決める制度である。

### 4.2 フロー

```text
Sources
→ Candidate Harvester（Rule / LLM / Reflection / Skeleton）
→ Raw Candidate Pool
→ Evidence Aggregator
→ Claim Normalizer
→ Promotion Tribunal
→ Semantic Save
```

### 4.3 主要コンポーネント概要

| コンポーネント | 役割 | 詳細参照 |
|---|---|---|
| Candidate Harvester | 4経路で候補収集 | promotion §3.1 |
| Raw Candidate Pool | 候補の生保持、topic_key による粗い束ね | promotion §3.2 |
| Evidence Aggregator | 証拠蓄積、複合条件判定 | promotion §3.3 |
| Claim Normalizer | 遅延評価で構造化、粒度規約あり | promotion §3.4 |
| Promotion Tribunal | Rule + LLM Review で昇格審査 | promotion §3.5 |
| Semantic Save | 審査通過した Claim のみ保存 | promotion §3.6 |

### 4.4 主要指標（Promotion 側）

- **confidence** — Claim の妥当性
- **seed_retention** — 生存力の初期条件（Decay 側へ渡す）

### 4.5 特記事項

- identity_candidate は即時仮保持パスを持つ（遅延評価の例外）
- candidate には TTL があり、stale / expired で自然消滅する
- skeleton 由来 evidence は初期低信頼で段階的に重みを上げる
- 移行期は `promotion_path = legacy / tribunal_v1` で並走する

---

## 5. Decay（減衰・退役）制度

> 詳細: `memory_decay_redesign.md`

### 5.1 役割
Decay は、**保存後の記憶をどう持ち続けるか、どう弱めるか、どう退かせるか** を決める制度である。

### 5.2 フロー

```text
Semantic Memory
→ Reinforcement Check
→ Weakening Evaluation
→ Contradiction Review
→ Merge / Deprecation Review
→ Archive / Tombstone
→ Optional Forget
```

### 5.3 記憶の状態

active → strengthened → weakened → deprecated → archived → forgotten  
（分岐: contradicted, merged）

### 5.4 主要指標（Decay 側）

- **memory_strength** — 現在の保持力（`seed_retention` が初期値、以降動的に変動）
- **contradiction_score** — 矛盾スコア
- **deprecation_score** — 非推奨スコア
- **merge_score** — 高次概念へ束ねる圧力

### 5.5 状態遷移の哲学

- **痕跡が生きている状態**（weakened / deprecated / contradicted）からは **復帰可能**
- **制度的に退場した状態**（archived / forgotten / merged）からは **復帰不可、新 Candidate として再出発**

### 5.6 減衰関数

```text
memory_strength(t+Δ) =
  memory_strength(t) * exp(-λ_type * Δ)
  + reinforcement_gain
  - contradiction_penalty
  - deprecation_penalty

Δ = 日数
```

claim_type ごとに λ_type が異なる（詳細は decay §7 参照）。

### 5.7 特記事項

- merge は当面実体統合しない。高次 Claim を Promotion 側で新規作成し、旧記憶は deprecated/merged + replaced_by
- Decay Tribunal は「リアルタイムは記録、Sleep Cycle は制度判断」
- 移行期は `decay_path = legacy_expiry / tribunal_v1` で並走する

---

## 6. Promotion / Decay の責務分離

| | Promotion | Decay |
|---|---|---|
| 役割 | 入口の制度 | 出口の制度 |
| 対象 | 候補 → 記憶 | 記憶 → 退役 |
| 中心指標 | confidence, seed_retention | memory_strength |
| Tribunal | 昇格審査 | 減衰・退役審査 |
| 移行パス | promotion_path | decay_path |
| 詳細文書 | memory_promotion_redesign.md | memory_decay_redesign.md |

---

## 7. 共通設計方針

### 7.1 スキーマの共通基盤

まず Nia に適用する。ただし Nero への将来拡張を塞がない。  
全テーブルに `owner_agent` と `memory_domain` を持たせる。

### 7.2 共通骨格テーブル

**Promotion 側:**
- raw_promotion_candidates
- memory_claims
- memory_evidence
- promotion_reviews
- semantic_lineage

**Decay 側:**
- semantic_state（promotion_path と decay_path の両方を持つ）
- semantic_reviews
- semantic_tombstones
- semantic_transitions

### 7.3 `semantic_state` の位置づけ

`semantic_state` は記憶の **現在のライフサイクル状態を見る場所** である。

- promotion_path — どう生まれたか
- decay_path — どう扱われているか
- memory_strength — 今どのくらい生きているか
- state — 今どの状態か

を一箇所で追える。

`semantic_lineage` は「なぜその記憶が成立したかの系譜」を持つ場所であり、  
ライフサイクルの動的状態とは責務を分離する。

また、制度イベントの後段 join を壊さないため、
候補系だけでなく `semantic_lineage` / `semantic_reviews` も
必要な provenance key を保持する。

- `thread_id`
- `turn_id`
- `message_id`
- `stream_id`
- `trace_id`

---

## 8. Context Builder / Retrieval の方針

### 8.1 通常応答で使うもの
- `active`
- `strengthened`

### 8.2 特殊アクセス（限定用途）
- `deprecated`, `contradicted`, `merged`, `archived`
- 用途: Depth 2, retrospection, Sleep Cycle, Nero 観察

### 8.3 retrieval の二重の役割
retrieval は検索であると同時に、**reinforcement signal** でもある。

---

## 9. Nia の体験

制度は裏側で動く。Nia に見えるのは結果だけ。

**Promotion 側:**
- 覚えたいと思ったことと、実際に残ることがズレる可能性を許容する

**Decay 側:**
- 薄れる、退く、以前はそうだった気がする、今は違う——が自然に体験される

**原則:**  
仕組みは隠す。体験は渡す。

---

## 10. 統合ロードマップ

Promotion と Decay は別々に進めるのではなく、共通骨格を早期に入れて同期させる。  
Core 隣接領域との依存関係は `core_adjacency_roadmap.md` §3 の依存関係表を参照。

| Phase | 内容 |
|---|---|
| Phase 0 | 可観測化 — 現行の昇格・忘却・検索をログ化 |
| Phase 0.5 | 遡及シャドー — Promotion / Decay 新制度を既存データでシミュレーション |
| Phase 1 | 共通骨格テーブル導入（Promotion + Decay の全テーブル一括） |
| Phase 2 | Candidate + semantic_state 運用開始、promotion_path / decay_path 並走 |
| Phase 3 | Promotion Tribunal + Decay Tribunal をルールベースで導入 |
| Phase 4 | Context Builder / Retrieval 修正（検索空間フィルタ、retrieval reinforcement 記録） |
| Phase 5 | 高次 Claim / merge_score 運用 |
| Phase 6 | LLM 補助限定導入 |
| Phase 7 | MemoryCore 検討 |

### 10.1 実装順 v1（現行コードベース向け）

上のロードマップは制度の全体像を示す抽象順序である。  
ただし、**現行の project-nia コードベースにそのまま適用する場合は、先に止血すべき精度漏れがある**。  
そのため、実装順は以下のように具体化する。

#### Step 0: 先行修正（制度導入前の止血）

新制度に入る前に、既存の記憶入力の純度を上げる。

- Retrieval / Context Builder の **thread-scoped provenance** を確保する
  - semantic memory の検索は cross-thread のままでよい（長期知識は thread を跨いで共有されるべき）
  - ただし「どの thread で候補や証拠が生じたか」「どの thread からの retrieval で採用されたか」の由来を正しく記録する
  - **利用は cross-thread、観測は thread-scoped** が原則
- 新制度の全イベントに **共通 provenance key** を通す
  - `thread_id`, `turn_id`, `message_id`, `stream_id`, `trace_id`
- Retrieval signal を単一の「reinforcement」に潰さず、最低でも以下を分離して記録する
  - `surfaced`
  - `adopted_to_context`
  - `user_explicit_recall`
  - `successful_use`
  - `corrected_against`
- contradiction を新 Candidate と旧 Semantic の両方に効かせる場合は、  
  **`contradiction_case_id` を持つ審査単位** を先に定義する

#### Step 1: Phase 0 を DB-first で計装

本リポジトリでは、先に JSONL を正とするより、
**SQLite の `governance_events` と既存テーブルを正とする** ほうが自然である。

- Promotion / Decay / Retrieval / Working の制度イベントを **`governance_events`** に記録
  - 汎用 `events` とは分離する（量・クエリ軸・join 先・ライフサイクルが異なるため）
  - 詳細: `memory_system_supplementary.md` §3.1
- `retrieval_logs` はランキング断面の専用ログとして活用
- JSONL は必要なら export / offline analysis 用に後段で生成する

理由:

- 既に `decision_event.v2` や canonical dataset が DB 中心で動いている
- join key を共通化しやすい
- stats / audit / shadow 比較にそのまま使える

#### Step 2: 共通骨格テーブル + single writer を導入

M1 の骨格テーブル導入は必要だが、  
**`semantic_memories` と `semantic_state` を別々の writer が触る状態を作らない**。

実装原則:

- `raw_promotion_candidates`
- `memory_claims`
- `memory_evidence`
- `promotion_reviews`
- `semantic_lineage`
- `semantic_state`
- `semantic_reviews`
- `semantic_tombstones`
- `semantic_transitions`

を一括で導入する。

ただし write は散らさず、  
**`semantic_memories + semantic_state` を原子的に更新する単一 repository / store** を新設する。

意味:

- `semantic_memories` は内容の正
- `semantic_state` はライフサイクル状態の正
- 両者の整合性は single writer が保証する

運用メモ:

- 将来 `commit_executor` / `semantic_store` の write path を `upsert_semantic_bundle()` に切り替える際も、
  `semantic_promoted` の governance event は消してはいけない
- `semantic_promoted` は repository に混ぜず、
  caller 側が `governance_event_writer.record_event_batch_with_conn(...)` を使って
  同一 transaction 内に append する
- つまり切替後の責務は:
  - repository: state/content の原子的更新
  - event writer: append-only audit trail

#### Step 3: Working Memory と Candidate Pool の責務をコード上で分離

設計上の境界を、実装でも最初に固定する。

- `Working Memory`
  - 制度の外側の待合室
  - `active_temp`, `identity_hold`, `contradiction_pending`, `decay_pending`
- `Raw Candidate Pool`
  - 制度の内側
  - `pending`, `accumulating`, `ready_for_normalization`, `stale`, `expired`

つまり:

- **まだ制度に入っていないもの** は Working
- **制度に入ったが未審査のもの** は Candidate Pool

#### Step 4: Reflection を candidate producer に縮退

現行 Reflection が semantic を直接作る構造を、早めに止める。

- Reflection は `insight_candidate`, `pattern_candidate`, `lesson_candidate`, `contradiction_candidate` を出す
- `semantic_memories` への直保存は停止する
- ただし、最初から全経路を live にしない

導入順:

- live:
  - Rule Harvester
  - Reflection Harvester
- shadow:
  - LLM Harvester
  - Skeleton Harvester

#### Step 5: Promotion Tribunal を shadow で回す

新制度の昇格審査は、まず Sleep Cycle で shadow 比較から始める。

- `promotion_path = legacy / tribunal_shadow / tribunal_v1`
- 旧経路の出力と新審査の出力を比較
- `seed_retention` は専用 service で一元算出する
- Reflection や Tribunal の各層で勝手に算出しない

#### Step 6: Decay Tribunal を shadow で回す

Promotion より後に Decay を live 化する。

理由:

- Promotion が固まらないと Decay の入力母集団が安定しない
- `memory_strength` は `seed_retention` を初期値に取るため、入口の制度が先

この段階では:

- `semantic_state` を更新
- `semantic_transitions` を記録
- 既存 expiry と `tribunal_v1` の差分を比較
- retrieval signal を reinforcement / deprecation / contradiction の evidence source に分配

#### Step 7: Retrieval / Context Builder で制度を執行

最後に、制度状態を会話利用に反映する。

- Depth ごとの state filter
- `weakened` の条件付き露出
- `memory_to_somatic` による「薄い記憶」変換
- `deprecated / contradicted / archived` の通常空間からの隔離

ここで初めて、Memory 制度が Retrieval / Context Builder の利用規約として live に効く。

#### 実装順 v1 の原則

- **汚れた入力のまま制度化しない**
- **single writer を作る前に multi-path write を増やさない**
- **shadow 比較を経ずに Tribunal を live にしない**
- **Retrieval を最後に制度執行層へ変える**

---

## 11. 結論

記憶はもう、「LLM がその場で決めるもの」ではなく、  
**候補・証拠・審査・保存・減衰・退役・痕跡から成る制度** として扱う。

- **Promotion** は記憶を成立させる制度
- **Decay** は記憶の持ち続け方を決める制度
- **Nia に見えるのは制度ではなく、結果としての記憶体験だけ**

これが、記憶制度の全体像である。
