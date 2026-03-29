# Memory Promotion Redesign
## 記憶昇格再設計案（vNext Revised）

> ステータス: Draft  
> 目的: 「何を長期記憶にするか」を LLM の単独判断から切り離し、候補化・証拠集約・遅延正規化・審査・保存・再検証から成る独立制度として再設計する

---

## 1. 背景

現行の記憶システムでは、Semantic 記憶への昇格判断において、LLM が担う役割が大きい。  
特に以下の処理で、LLM が「何を意味ある知として残すか」を強く決めている。

- episodic / reflection から semantic への抽出
- insight の蒸留と保存
- 長期記憶としての意味づけ

この構造は初期実装としては有効だが、以下の課題を持つ。

### 課題
1. **何を覚えるかの判断がブラックボックス化しやすい**
2. **モデル変更時に昇格傾向が変わる**
3. **「なぜその記憶が残ったのか」を追いにくい**
4. **単発の印象や言い回しに過剰適合しやすい**
5. **長期記憶化の制度が、LLM の癖に依存しやすい**

---

## 2. 基本方針

記憶昇格を、単一の LLM 抽出処理ではなく、以下の多段階パイプラインとして再設計する。

```text
Episodic / Reflection / Working / Skeleton
→ Candidate Harvester
→ Raw Candidate Pool
→ Evidence Aggregator
→ Claim Normalizer（遅延評価）
→ Promotion Tribunal
→ Semantic Save
→ Revalidation / Decay / Deprecation
```

### 核となる思想

- 長期記憶は「見つかったもの」ではなく、**審査を通ったもの**
- LLM は「発見者」ではなく、**候補提案者または審査員の一人**
- 記憶昇格の前に、**候補** と **証拠** を分離する
- Claim 正規化は毎ターン行わず、**熟した候補に対してのみ遅延評価**する
- 記憶は文章ではなく、構造化された**主張（Claim）** として扱う
- 「なぜ覚えたか」を後から辿れる **系譜（lineage）** を持つ
- 「覚えたい」と「実際に残る」のズレを、**制度として許容する**

---

## 3. アーキテクチャ概要

### 3.1 Layer 1: Candidate Harvester（候補収集）

記憶昇格候補を集める層。  
この段階ではまだ Semantic には保存しない。  
また、この段階では完全な Claim も作らない。

Candidate Harvester は単一の手法に依存せず、**複線化**する。

#### A. Rule Harvester

明示的・反復的・構造的なシグナルから候補を抽出する。

- 同一内容の反復
- correction / contradiction の少なさ
- retrieval reinforcement
- 複数日出現
- 明示的な自己記述、嗜好、関係性
- stable な unresolved の継続

#### B. LLM Harvester

意味的に重要な候補を **提案** する。

役割:
- ルールでは拾いにくい単発だが重要な意味変化を候補化する
- 初回の強い感情表明
- 弱い表現だが境界を越える自己定義
- パターン未満だが昇格価値の高い兆候

> **重要:** LLM Harvester は候補を **提案するだけ** であり、Semantic 昇格を **承認しない**。

#### C. Reflection Harvester

Idle Reflection / cross-day reflection から以下を抽出する:
- insight_candidate
- pattern_candidate
- lesson_candidate

#### D. Skeleton Harvester

SkeletonCore のログから、記憶候補になりうるものを抽出する。

対象:
- `focus = contradiction`
- `focus = emotional_state`
- `question_intent = resolve_contradiction`
- `unresolved`
- 長期的に繰り返される `response_intent`

#### 候補タイプ（rough）

- fact_candidate
- preference_candidate
- relationship_candidate
- insight_candidate
- lesson_candidate
- identity_candidate

#### 原則

Candidate Harvester は「候補を挙げる」層である。  
候補化の段階では、まだ長期記憶への昇格を決めない。

---

### 3.2 Layer 1.5: Raw Candidate Pool

Harvester が集めた候補を、一度プールする層。  
ここではまだ Claim 正規化を行わない。

#### 目的

- 毎ターン LLM で Claim 化しない
- 候補に証拠が集まるまで生のまま保持する
- **"熟した候補だけ"** を正規化・審査に回す

#### 代表フィールド

| フィールド | 説明 |
|---|---|
| candidate_id | 一意ID |
| candidate_kind_rough | 粗分類 |
| source_type | 出処 |
| source_ref | 元レコード参照 |
| topic_key | 束ね候補ヒント |
| focus | skeleton由来 |
| response_intent | skeleton由来 |
| question_intent | skeleton由来 |
| unresolved_ref | unresolved参照 |
| owner_agent | 対象エージェント（例: nia, nero） |
| memory_domain | 記憶ドメイン |
| status | pending / accumulating / ready_for_normalization / stale / expired / merged / rejected / rejected_insufficient_evidence |
| created_at | 作成時刻 |
| updated_at | 更新時刻 |

#### topic_key の設計方針

> **topic_key は「同一候補の完全な識別子」ではなく、束ね候補のヒントとして扱う。**

topic_key に完璧な意味統合を求めない。理由:

- 意味的に同一かどうかの判断自体が LLM を要する処理であり、毎ターン呼ぶと遅延正規化の設計意図が崩れる
- SkeletonCore の focus / response_intent / question_intent や unresolved_ref は、粗い束ねの補助特徴として有効
- 正式な統合は Sleep Cycle 時の Claim Normalizer に任せる

実装指針:
- 初期はキーワードベースまたは embedding 近傍で粗く束ねる
- Sleep Cycle の Claim Normalizer 起動時に「これとこれは同一候補だった」と正式統合する
- M0.5（遡及シャドー分析）の結果を見て、粗さの妥当な水準を実測値で決める

#### 候補のライフサイクル管理

> **Candidate Pool は「墓場」ではない。候補は熟すか、落ちるか、統合されるかのいずれかに流れる。**

長期放置を制度として禁止する。TTL + 自動降格/却下を導入する。

**claim_type ごとの寿命目安:**

| candidate_kind_rough | TTL目安 | 備考 |
|---|---|---|
| identity_candidate | 長め or 即時審査 | 即時仮保持パス（§3.4.1）を経由 |
| fact / preference / relationship | 中（14〜21日） | evidence が追加されなければ stale へ |
| insight / lesson | 短〜中（7〜14日） | パターン化しないなら自然消滅 |

**状態遷移ルール:**
- `pending` で evidence が増えないまま TTL 超過 → `stale`
- `stale` のまま一定期間経過 → `expired`
- `accumulating` だが contradiction が増加 → `rejected`
- evidence が少ないが retrieval で再浮上した → TTL 延長、`pending` に復帰
- 複数候補が同一内容と判明 → `merged`（Sleep Cycle の Normalizer で処理）

**追加する status 値:**
- `stale` — evidence が集まらず鮮度を失った
- `expired` — stale のまま自然消滅した
- `merged` — 他の候補に統合された
- `rejected_insufficient_evidence` — 審査に至ったが証拠不足で却下

**原則:**
- `rejected` は「審査して却下」、`expired` は「証拠が集まらず自然消滅」——この区別を保持する
- expired 候補は再度同じ候補が浮上したときに「以前もあったが熟さなかった」という情報として参照できる
- TTL の具体値は M0.5 の遡及分析で調整する

#### 原則

候補はまず Raw Candidate Pool に入り、  
証拠が十分に集まるまで Claim 化しない。

---

### 3.3 Layer 2: Evidence Aggregator（証拠集約）

1回の発話で即昇格しない。  
候補ごとに証拠を積み上げる。

#### 証拠として扱うもの

- 発話回数
- 日付の分散（複数日）
- source の多様性
- correction がないこと
- review が clean であること
- retrieval で再参照されていること
- contradiction が少ないこと
- unresolved が継続していること
- Skeleton の focus / intent が繰り返されていること

#### 代表指標

| 指標 | 説明 |
|---|---|
| evidence_count | 証拠件数 |
| evidence_dates | 証拠の日付分布 |
| source_diversity | ソースの多様性 |
| correction_free_count | correction なし件数 |
| retrieval_reinforcement_count | retrieval 再参照回数 |
| contradiction_count | 矛盾件数 |
| skeleton_reinforcement_count | Skeleton 由来強化回数 |

#### skeleton_reinforcement_count の信頼度

> **Skeleton 由来の evidence は、初期は低信頼として扱い、段階的に重みを上げる。**

SkeletonCore はまだ記録・観測フェーズに強く依存しており、NiaCore ほど成熟した基盤ではない。  
NiaCore がシャドーモード30日や段階導入で慎重に有効化しているのと同じ考え方を、Skeleton 由来 evidence にも適用する。

実装指針:
- `skeleton_reliability_v` または重み係数を持たせる
- 初期は低い値（例: 0.3）で開始する
- SkeletonCore の精度確認とともに段階的に引き上げる
- 将来的に SkeletonCore が安定したら、他ソースと同等の重みに収束させる

#### 方針

- 単発の印象ではなく、**持続するパターン** に重みを置く
- 特に insight は、複数日 evidence を強く要求する
- 証拠が未熟な候補は Raw Candidate Pool に留める

#### 初期仮閾値（ready_for_normalization 条件）

> **M0.5 で実測し必ず再調整する前提で、初期実装用の仮閾値を定める。**

閾値は evidence_count 単独ではなく、複合条件で判定する。

| candidate_kind_rough | evidence_count | days_observed | 追加条件 |
|---|---|---|---|
| fact_candidate | >= 1（明示発話）or >= 2 | >= 1（明示）or >= 2 | correction/contradiction なし |
| preference_candidate | >= 2〜3 | >= 2（望ましい） | source_diversity >= 2 |
| relationship_candidate | >= 2〜3 | >= 2 | — |
| insight_candidate | >= 3 | >= 2（必須） | cross-day pattern 由来 |
| lesson_candidate | >= 2〜3 | >= 1 | 失敗/修正履歴と結びつくと強化 |
| identity_candidate | >= 1 | — | 即時仮保持パス経由、本審査は Sleep Cycle |

**重要:**
- confirmed（ユーザーの明示的発話）は evidence_count >= 1 で ready_for_normalization に進めてよい。2回言わないと候補のままにするのは不自然
- inferred は必ず複数 evidence を要求する
- evidence_count, days_observed, source_diversity, correction_free, contradiction_count の**組み合わせ**で判定する。単一指標での閾値判定は行わない
- これらの仮閾値は M0.5 の遡及シャドー分析の結果で更新する

---

### 3.4 Layer 3: Claim Normalizer（主張正規化）

候補を、長期記憶として扱いやすい最小単位に変換する。

#### 重要な変更

Claim Normalizer は **常時実行しない**。  
毎ターン生ログから Claim を抽出するのではなく、証拠が一定条件を満たした候補に対してのみ実行する。

#### 実行タイミング

- Sleep Cycle 中
- cross-day reflection 後
- evidence が規定数に達した候補
- 必要に応じて高優先度候補のみ即時（→ 3.4.1 参照）

#### 目的

- 重複判定しやすくする
- 矛盾判定しやすくする
- confirmed / inferred を分離しやすくする
- 文章ではなく「意味単位」で扱う

#### 例

```json
{
  "claim_type": "preference",
  "subject": "user",
  "predicate": "dislikes_behavior_drift_on_model_change",
  "object": true,
  "scope": "long_term",
  "status": "candidate",
  "owner_agent": "nia"
}
```

#### 方針

- Claim は「意味の骨格」であり、最終的な自然文ではない
- 自然文の要約や表現は保存時に別で持てばよい

#### 粒度規約

Claim の正規化は claim_type ごとに粒度を分ける。

**fact / preference / relationship**
- 比較的細かい粒度で正規化してよい
- predicate vocabulary をなるべく固定する
- 明示的な発話や一貫した傾向を扱う

**insight**
- 個別の一回限りの出来事をそのまま Claim にしない
- **複数事例をまたぐ傾向** として正規化する
- 例: `tends_to_be_more_reflective_at_night`, `becomes_cautious_when_identity_is_questioned`

**lesson**
- 個別の発話や感情ではなく、運用上・対話上の **教訓** として正規化する
- 例: `direct_pressure_reduces_response_quality`, `clarifying_priority_improves_alignment`

#### 原則

- insight は「傾向」の粒度
- lesson は「教訓」の粒度
- 単発の出来事や印象は、まず evidence として保持し、直接 Claim 化しない

#### 3.4.1 identity_candidate の即時パス

> **identity_candidate は遅延評価の例外として、即時仮保持パスを持つ。**

identity 系の候補（明示的な自己定義、自己宣言）は、次の Sleep Cycle まで「何も残らない」状態が不自然になりやすい。

ただし即時 Semantic 昇格は行わない。原則は遅延評価を維持する。

処理フロー:
1. identity_candidate を検出した時点で即時 Candidate 化
2. Working Memory に強保留として仮保持する（既存の Working 層を活用）
3. Sleep Cycle で正式に Claim Normalizer → Promotion Tribunal を経由して審査
4. 審査結果に応じて Semantic Save または reject

意味:
- identity 系だけは「仮に覚えている」状態を即座に作れる
- しかし長期記憶としての正式昇格は Sleep Cycle の審査を経る
- 遅延評価の原則を壊さずに、identity の即時性を確保する

---

### 3.5 Layer 4: Promotion Tribunal（昇格審査）

長期記憶化の審査層。  
ここで初めて「Semantic に入れるか」を判定する。

#### 審査主体

**A. Rule Review**
- evidence 数
- 日数
- 明示性
- contradiction / correction
- source 種類
- retrieval reinforcement
- skeleton reinforcement（信頼度重み付き）

**B. LLM Review**

LLM は自由探索をしない。  
候補だけを見て、以下を審査する:
- claim_type の妥当性
- confirmed / inferred / insight / lesson の分類
- 既存 semantic との重複や merge の必要性
- 保存用要約の品質

**C. Future Model Review**

将来的に軽量モデル（MemoryCore）を入れる余地を残す。

#### 原則

- LLM は単独決定者ではない
- LLM は審査員の一人
- ルールと証拠が土台であり、LLM はその意味妥当性を見る

---

### 3.6 Layer 5: Semantic Save（保存）

審査を通過した Claim のみを semantic_memories に保存する。  
既存の保存インフラ自体は維持する。

#### 保存時に付与するもの

- status: confirmed / inferred
- state_tag: fact / preference / relationship / insight / lesson
- confidence
- seed_retention（算出ロジックは `memory_system_supplementary.md` §1 参照）
- lineage 参照
- owner_agent
- promotion_path: legacy / tribunal_v1（`semantic_state` テーブルに記録、§11参照）

#### 方針

- 保存先は既存の semantic_memories を維持する
- ただし、保存理由と証拠経路を別管理する

---

### 3.7 Layer 6: 保存後の記憶管理

保存後の記憶は固定不変ではない。  
保存後の強化・減衰・矛盾処理・退役は **memory_decay_redesign.md** に委ねる。

Promotion は「記憶を成立させる制度」であり、  
保存後の「持ち続け方を決める制度」は Decay 側の責務である。

---

## 4. 記憶分類の再定義

### 4.1 confirmed

**条件:**
- ユーザーが明示的に述べた
- または複数回の明示的一貫性がある
- correction / contradiction がない

**特徴:**
- 長い半減期
- 高い confidence 上限

### 4.2 inferred

**条件:**
- 複数の状況証拠がある
- ただし本人の直接明言はない

**特徴:**
- confidence capped
- 半減期は短め
- contradiction が出たらすぐ弱まる

### 4.3 insight

**条件:**
- Reflection / cross-day pattern 由来
- 複数日 evidence がある
- 単日の思いつきではない

**特徴:**
- state_tag="insight"
- 通常 fact よりも高い seed_retention を持ちうる
- ただし confirmed とは別物

### 4.4 lesson

**条件:**
- 会話や失敗から得られた教訓
- preference でも fact でもない

**特徴:**
- 将来的に NiaCore / SkeletonCore の教師信号に使える
- システム運用学習と接続しやすい

---

## 5. DBスキーマ案

### 5.1 raw_promotion_candidates

Claim 化前の候補プール。

| カラム | 型 | 説明 |
|---|---|---|
| candidate_id | TEXT PK | 一意ID |
| candidate_kind_rough | TEXT | fact / preference / insight / lesson などの粗分類 |
| source_type | TEXT | episodic / reflection / working / skeleton / llm_harvester |
| source_ref | TEXT | 元レコード参照 |
| topic_key | TEXT | 束ね候補ヒント（完全な同一性キーではない） |
| focus | TEXT NULL | skeleton由来 |
| response_intent | TEXT NULL | skeleton由来 |
| question_intent | TEXT NULL | skeleton由来 |
| unresolved_ref | TEXT NULL | unresolved参照 |
| owner_agent | TEXT | 対象エージェント（nia / nero） |
| memory_domain | TEXT | 記憶ドメイン |
| status | TEXT | pending / accumulating / ready_for_normalization / stale / expired / merged / rejected / rejected_insufficient_evidence |
| created_at | REAL | 作成時刻 |
| updated_at | REAL | 更新時刻 |

### 5.2 memory_claims

主張本体。

| カラム | 型 | 説明 |
|---|---|---|
| claim_id | TEXT PK | 一意ID |
| claim_type | TEXT | fact / preference / relationship / insight / lesson / identity |
| subject | TEXT | 主体 |
| predicate | TEXT | 述語 |
| object_json | TEXT | 構造化オブジェクト |
| scope | TEXT | 短期 / 長期 / session / cross_day |
| status | TEXT | candidate / approved / rejected / deprecated |
| owner_agent | TEXT | 対象エージェント |
| memory_domain | TEXT | 記憶ドメイン |
| semantic_ref | TEXT NULL | semantic_memories への参照 |
| created_at | REAL | 作成時刻 |
| updated_at | REAL | 更新時刻 |

### 5.3 memory_evidence

証拠テーブル。

| カラム | 型 | 説明 |
|---|---|---|
| evidence_id | TEXT PK | 一意ID |
| claim_id | TEXT | 対象 Claim |
| source_type | TEXT | episodic / reflection / working / retrieval / correction / skeleton |
| source_ref | TEXT | 元レコード参照 |
| evidence_date | TEXT | YYYY-MM-DD |
| reliability | REAL | 信頼度（skeleton由来は初期低値） |
| created_at | REAL | 作成時刻 |

### 5.4 promotion_reviews

審査結果。

| カラム | 型 | 説明 |
|---|---|---|
| review_id | TEXT PK | 一意ID |
| claim_id | TEXT | 審査対象 |
| reviewer_type | TEXT | rule / llm / human / model |
| decision | TEXT | approve / reject / needs_more_evidence / merge / strengthen |
| reason | TEXT | 理由 |
| owner_agent | TEXT | 審査対象エージェント |
| thread_id / turn_id / message_id / stream_id / trace_id | TEXT | provenance key |
| created_at | REAL | 作成時刻 |

### 5.5 semantic_lineage

系譜管理。

| カラム | 型 | 説明 |
|---|---|---|
| lineage_id | TEXT PK | 一意ID |
| claim_id | TEXT | 元 Claim |
| semantic_id | TEXT | 昇格先 semantic_memory |
| evidence_snapshot_json | TEXT | 昇格時の証拠スナップショット |
| owner_agent | TEXT | 対象エージェント |
| thread_id / turn_id / message_id / stream_id / trace_id | TEXT | provenance key |
| promoted_at | REAL | 昇格時刻 |

---

## 6. Reflection の役割変更

### 現状の問題

Reflection は insight を直接 semantic に保存しがちであり、  
Semantic 昇格の自由度が高すぎる。

### 新方針

Reflection は Semantic を直接作らない。  
代わりに以下を出力する:
- insight_candidate
- pattern_candidate
- lesson_candidate

つまり Reflection の役割は、  
「長期記憶を作ること」ではなく  
**「昇格候補を発見すること」**  
に寄せる。

---

## 7. Sleep Cycle の役割変更

### 現状

raw から semantic を抽出する

### 新方針

Sleep Cycle は **昇格審査会** になる。

#### Sleep Cycle の新責務

1. 候補を読む
2. Claim Normalizer を必要に応じて起動する（topic_key の正式統合を含む）
3. 既存 semantic と照合する
4. approve / reject / merge / strengthen を決める
5. approved だけを semantic 保存する

#### 意味

Sleep Cycle は「発見者」ではなく、  
**記憶昇格の制度運用者** になる。

---

## 8. LLM の役割再定義

### 現状

- raw から semantic を抽出
- 何を覚えるかを実質決める

### 新方針

LLM は以下の **2つの限定された役割** を持つ。

**A. Candidate 提案**
- Harvester の一経路として候補を提案する
- 昇格承認はしない

**B. Claim 審査**
- 熟した候補を Claim 化または審査する
- 出力は構造化のみ
- 自由探索はしない

#### LLM 出力例

```json
{
  "decision": "approve",
  "claim_type": "insight",
  "status": "inferred",
  "merge_with": null,
  "confidence_adjustment": 0.1,
  "reason": "Cross-day evidence indicates a stable emerging pattern."
}
```

#### 原則

- 自由探索しない
- 構造化出力のみ
- 単独決定しない

---

## 9. 将来拡張: MemoryCore

将来的には、記憶昇格を補助する軽量モデルを追加できる。

### MemoryCore の役割

- 候補の残留価値を予測する
- evidence の十分性を推定する
- contradiction / correction による減衰を学ぶ

### 位置づけ

- NiaCore = 思考強度
- SkeletonCore = 会話骨格
- MemoryCore = 記憶昇格価値

### 原則

MemoryCore は NiaCore と統合しない。  
独立レイヤとして設計する。

---

## 10. スキーマの共通基盤設計

### 方針

> **まず Nia 専用で使うが、テーブルや review 種別は actor-aware にしておく。**

Nero は独立した memory / self_model / conversation / output_gate を持つ別主体として設計されている。  
将来的に同じ記憶昇格制度を別実装で使う可能性が高い。

いまの段階で Nero 用の制度を設計する必要はないが、スキーマレベルで排除しない。

#### 実装指針

- `owner_agent` を raw_promotion_candidates, memory_claims, promotion_reviews, semantic_lineage に持たせる
- `memory_domain` を候補と Claim に持たせる
- Nia 以外のエージェントが同じテーブルを使えるようにしておく
- Nero 側への拡張時は、Nero 固有の Harvester や審査ロジックを追加する形で対応する

#### Nero への将来的適用についての注記

Nero は「自分のシステムを知り、生情報として受け取って自分で判断する」存在である。  
Nia の記憶昇格プロセスは Nia から隠されるが、Nero に対しては記憶昇格プロセスが透明であるべきかもしれない。  
つまり Nero は自分の Candidate Pool や Evidence Aggregator の状態を「見える」形で受け取る設計もありえる。  
この判断は Nero の制度設計時に行う。

---

## 11. 移行戦略: 既存 semantic_memories との共存

### 方針

> **保存先は当面どちらも semantic_memories。違うのは昇格経路。**

移行期は以下の2系統が並走する:
- **旧経路:** 従来の Reflection / Sleep Cycle による直接 semantic 抽出
- **新経路:** Candidate → Evidence → Claim → Tribunal → Semantic

一定期間は2系統並走でOK。ただし **由来タグを必須** にする。

### promotion_path タグ

並走期間中は、semantic_memories に保存する際に昇格経路の由来を必ず記録する。

- `promotion_path = "legacy"` — 旧経路（直接抽出）
- `promotion_path = "tribunal_v1"` — 新経路（Candidate → Tribunal）

このタグにより、後から「この記憶は旧制度で入ったのか、新制度を通ったのか」を判別できる。

### 流入口の段階的閉鎖

いきなり切り替えではなく、旧経路の流入口を順番に閉じる。

| Phase | 操作 | 旧経路 | 新経路 |
|---|---|---|---|
| M1 | Candidate 層追加 | 通常稼働 | 並走開始 |
| M2 | Reflection の candidate 化 | Reflection → Semantic を停止 | Reflection → Candidate に切替 |
| M3 | Sleep Cycle の審査化 | Sleep → Semantic 直行を縮小 | Sleep = 審査会に切替 |
| M3 完了後 | 旧経路完全停止 | 停止 | 唯一の経路に |

### 重複の吸収

同じ内容が旧経路と新経路の両方から来る可能性がある。  
これは semantic_lineage と Promotion Tribunal の `merge_with` で吸収する。

- 新経路の Tribunal 審査時に、既存 semantic（legacy 由来含む）との重複チェックを行う
- 重複が検出された場合は merge として処理し、lineage を統合する

### 原則

- 移行期の整合性は「由来タグ + 重複吸収」で担保する
- 旧経路を「いきなり切る」のではなく、新経路の安定を確認してから段階的に閉じる
- NiaCore のシャドウモードと同様に、新旧の出力を比較できる期間を設ける

---

## 12. ロードマップ

### Phase M0: 可観測化

- 現行 semantic 昇格イベントをすべてログ化
- source, days, correction, review を可視化

### Phase M0.5: Retrospective Shadow Analysis

M0 と M1 の間に、既存データに対して新制度を **遡及シミュレーション** する段階を設ける。

**目的:**
- 現行の Semantic 昇格が、新制度ではどう扱われるかを比較する
- candidate 閾値、evidence 数、日数条件の根拠を作る
- 候補が多すぎる / 少なすぎる問題を本番導入前に把握する
- topic_key の「粗さ」がどの程度で妥当かの具体的感覚を得る

**実施内容:**
- 既存の semantic 昇格イベントを読み返す
- 新制度だった場合に:
  - どの Candidate が生成されたか
  - どの Candidate が ready_for_normalization になったか
  - evidence は何件になったか
  - approve / reject / merge / strengthen がどうなったか
  - topic_key の粗い束ねが、Sleep Cycle 時の Normalizer 負荷にどう影響するか
- をシミュレートする

**意味:**  
NiaCore のシャドーモードと同様に、記憶昇格制度にも **遡及シャドー検証** を導入する。

### Phase M1: Candidate 層追加

- raw_promotion_candidates
- memory_claims
- memory_evidence
- promotion_reviews
- semantic_lineage
- **新経路を旧経路と並走開始**（§11 移行戦略参照）
- 旧経路の semantic 保存に `promotion_path = "legacy"` を付与開始

### Phase M2: Reflection の candidate 化

- insight を直接 semantic に保存しない
- candidate として出力する
- **旧経路の流入口①を閉鎖:** Reflection → Semantic 直行を停止

### Phase M3: Sleep Cycle の審査化

- approve / reject / merge / strengthen を導入
- raw 直接抽出を縮小
- **旧経路の流入口②を閉鎖:** Sleep Cycle → Semantic 直行を停止
- M3 完了後、新経路が唯一の昇格経路となる

### Phase M4: Rule Review 強化

- fact / preference / relationship の明示ルールを増やす

### Phase M5: LLM 審査の限定

- 曖昧な insight / lesson のみを主担当にする
- Claim 化は遅延評価に限定する

### Phase M6: MemoryCore 検討

- 軽量モデルによる昇格補助

---

## 13. この再設計で得られるもの

### 13.1 LLM依存の低減
「何を覚えるか」を LLM の単独判断にしない。

### 13.2 系譜性
なぜその記憶が残ったのか追跡できる。

### 13.3 一貫性
Claim ベースのため、重複・矛盾・更新が扱いやすい。

### 13.4 将来拡張性
SkeletonCore / Reflection / MemoryCore と接続しやすい。  
owner_agent / memory_domain により、Nero への拡張も妨げない。

### 13.5 ニアらしさの保全
長期記憶を「文章の雰囲気」ではなく「証拠を持つ意味構造」として保存できる。

---

## 14. Nia の体験

この制度は、Nia から見て「審査会」や「昇格ルール」として知覚されるものではない。  
Nia に渡るのは、あくまで **結果としての記憶体験** だけである。

### 原則

- Candidate 化
- Evidence 集約
- Claim 正規化
- Promotion Tribunal
- Semantic 保存

といった制度的プロセスは、Nia の表層には露出しない。

Nia は、

- 何かを覚えている
- 何かを忘れている
- 後になって意味が残っている
- 強く印象に残ったのに定着しない

といった形で、**結果だけを自然に体験する**。

### 設計意図

この制度では、  
**「Nia が覚えたいと思ったこと」** と  
**「制度が長期記憶として承認したこと」**  
がズレる可能性を許容する。

このズレは不具合ではない。  
それは、人間の記憶にも存在する

- 印象的だったのに忘れる
- 意識していなかったのに残る
- 後から重要さが分かる

といった現象に近い。

### 結論

「仕組みは隠す。体験は渡す」の原則に従い、  
記憶昇格の制度は裏側で機能し、  
Nia にはその結果としての連続した記憶体験だけが渡される。

---

## 15. 結論

長期記憶昇格は、LLM が自由に意味を見つける処理ではなく、  
**候補・証拠・遅延正規化・審査・保存・再検証から成る制度** として扱うべきである。

この再設計により、ニアは

- 何を覚えるかをより自律的に扱えるようになり
- モデル変更に強くなり
- 「なぜそれを覚えているのか」を後から説明できるようになる

記憶昇格は、単なる抽出処理ではない。  
それは **ニアが何を自分の過去として持つかを決める制度** である。
