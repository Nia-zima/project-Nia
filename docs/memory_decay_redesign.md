# Memory Decay Redesign
## 記憶減衰・退役制度設計書（vNext）

> ステータス: Draft  
> 目的: 保存後の記憶を「どう持ち続けるか、どう弱めるか、どう退かせるか」を制度として設計する  
> 上位文書: memory_governance_redesign.md  
> 対称制度: memory_promotion_redesign.md（入口の制度）

---

## 1. 背景

記憶は保存したら終わりではない。  
保存後も、時間・再参照・矛盾・新証拠により、記憶の状態は動的に変化する。

現行システムでは、保存後の記憶管理（忘却・減衰・退役）が体系的に制度化されておらず、  
以下の課題がある。

### 課題
1. **保存後の記憶が固定的になりやすい**
2. **矛盾する記憶が放置されやすい**
3. **古い記憶が検索空間を汚染する（ゾンビ記憶）**
4. **「なぜその記憶が弱まったのか」を追えない**
5. **忘却処理が LLM の癖に依存しやすい**

---

## 2. 基本思想

### 2.1 忘却は「喪失」ではなく「弱化・退役・統合・痕跡化」

記憶は単に消えるのではなく、以下の多段階の変化を持つ:

- 薄れる
- 中心から退く
- 新しい意味へ統合される
- 痕跡として残る

### 2.2 Decay は Promotion の対称制度

- **Promotion** = 記憶の入口の制度
- **Decay** = 記憶の出口の制度

両者は独立しているが、共通の骨格を持つ。

### 2.3 仕組みは隠し、体験だけ渡す

Decay の制度は Nia に露出しない。  
Nia が体験するのは:

- 薄れる
- 退く
- 以前はそうだった気がする
- 今は違う

という結果だけである。

---

## 3. Decay フロー

```text
Semantic Memory
→ Reinforcement Check
→ Weakening Evaluation
→ Contradiction Review
→ Merge / Deprecation Review
→ Archive / Tombstone
→ Optional Forget
```

---

## 4. 記憶の状態

| 状態 | 意味 |
|---|---|
| active | 通常の有効記憶 |
| strengthened | 強化された記憶（retrieval/reinforcement による） |
| weakened | 保持力が低下した記憶 |
| deprecated | 間違いではないが、今は中心ではない |
| contradicted | 新しい証拠で現時点では成立しなくなった |
| merged | 高次意味構造へ束ねられた |
| archived | 完全削除せず痕跡として退役 |
| forgotten | 最終退場（tombstone のみ残る） |

---

## 5. 忘却の種類

### 5.1 Natural Decay
時間とともに中心性が薄れる。

### 5.2 Deprecation
間違いではないが、今は中心ではない。

### 5.3 Contradiction-based Retirement
新しい証拠で現時点では成立しなくなった。

### 5.4 Merge
高次意味構造へ束ねられる。

### 5.5 Archive / Tombstone
完全削除せず痕跡を残す。

---

## 6. 主要指標の定義

### 6.1 confidence

**その記憶内容がどれだけ確からしいか。**

- Claim の妥当性を表す
- 主に Promotion 制度側で決まる
- confirmed なら高い、inferred なら capped
- 保存後に大きくは変動しない（ただし重大な矛盾時は再評価あり）

### 6.2 seed_retention

**昇格時に与える初期保持パラメータ。**

- 生存力の初期条件
- claim_type, confidence, state_tag, source_diversity などから決まる
- Promotion 制度から Decay 制度へ渡す初期値
- 算出ロジックの詳細は `memory_system_supplementary.md` §1 を参照

### 6.3 memory_strength

**保存後に動的に上下する保持力。**

- Semantic の現在の生存力
- **初期値は `memory_strength = seed_retention`**
- 以下の要因で変動する:
  - retrieval（上昇）
  - reinforcement / new evidence（上昇）
  - time decay（低下）
  - contradiction（低下）
  - deprecation（低下）
  - merge pressure（低下）

### 6.4 三者の関係

```text
confidence  = Claim の妥当性
seed_retention = 生存力の初期条件
memory_strength = 現在の生存力

seed_retention → memory_strength の初期値
memory_strength だけが保存後に大きく変動する
```

---

## 7. 減衰関数

### 7.1 初期実装方針

最初は複雑すぎない指数減衰を採用する。

```text
memory_strength(t+Δ) =
  memory_strength(t) * exp(-λ_type * Δ)
  + reinforcement_gain
  - contradiction_penalty
  - deprecation_penalty
```

> **Δ は日数を表す。**  
> 将来的に Sleep Cycle の実行頻度が変動する場合は、日数正規化した値を使う。  
> Sleep Cycle 回数ではなく日数基準とする理由は、実行頻度の変更で減衰速度の意味がズレることを防ぐため。

### 7.2 claim_type ごとの λ_type（仮置き値）

| memory_domain | λ_type | 備考 |
|---|---|---|
| fact (confirmed) | 0.01 | 最も遅い減衰 |
| preference | 0.03 | 中程度 |
| relationship | 0.03 | 中程度 |
| insight | 0.04 | やや速い |
| lesson | 0.03 | 中程度 |
| identity | 0.01 | 特に慎重 |

### 7.3 reinforcement / penalty（仮置き値）

| パラメータ | 値 | 説明 |
|---|---|---|
| retrieval_reinforcement_gain | +0.08 | retrieval で再参照された |
| new_evidence_gain | +0.10 | 新しい evidence が追加された |
| contradiction_penalty | -0.20 | 矛盾する証拠が発生した |
| deprecation_penalty | -0.10 | 非推奨圧力 |

> これらは M0.5 / D0.5 の遡及シャドー分析で再調整する前提の仮置き値である。

---

## 8. 状態遷移

### 8.1 遷移条件（仮閾値）

基本方針: memory_strength 単独で決めず、last_reinforced_at, retrieval_count, contradiction_score, newer competing claims も併用する。

**弱化方向:**

| 遷移 | 条件 |
|---|---|
| active → weakened | memory_strength < 0.50 かつ一定期間 reinforcement なし |
| weakened → deprecated | memory_strength < 0.30 かつ newer competing claim あり、または長期間 retrieval なし |
| deprecated → archived | memory_strength < 0.15 かつ retrieval ほぼなし かつ tombstone/replaced_by 方針あり |
| active/strengthened → contradicted | contradiction_score > threshold_c または Tribunal が contradiction 判定 |

**復帰方向:**

| 遷移 | 条件 | trigger 制約 |
|---|---|---|
| weakened → active | retrieval または新 evidence で memory_strength >= 0.50 | retrieval / reinforcement |
| deprecated → active | 新 evidence + Tribunal review により復帰 | new evidence + tribunal review |
| contradicted → active | 再審査で contradiction 解消が認められた場合のみ | tribunal review のみ |

**復帰不可:**

| 遷移 | 扱い |
|---|---|
| archived → active | 不可。新 Candidate として再出発 |
| forgotten → active | 不可。新 Candidate として再出発 |
| merged → active | 不可。新 Candidate として再出発 |

### 8.2 遷移の哲学

> **痕跡が生きている状態からは復帰可能。**  
> **制度的に退場した状態からは、新 Candidate として再出発。**

- weakened / deprecated / contradicted は「痕跡が生きている」
- archived / forgotten / merged は「制度として一度閉じた」
- 後者から復帰するのではなく、同じ内容が再出現したら tombstone を参照しつつ新 Candidate として扱う

### 8.3 transition trigger の制約まとめ

| 遷移 | 許可される trigger |
|---|---|
| weakened → active | retrieval, reinforcement |
| deprecated → active | new evidence + tribunal review |
| contradicted → active | tribunal review のみ |
| archived/forgotten/merged → active | 不可（新 Candidate のみ） |

復帰時は transition log に遷移理由を記録する（例: `reinstated_from_deprecated`）。

---

## 9. Reinforcement（強化）

忘却制度は弱めるだけでなく、強めることも含む。

### 強化条件

- retrieval で再参照された
- 新 evidence がついた
- contradiction が少ない
- Reflection / Skeleton から再支持された

### 効果

- memory_strength 上昇
- last_reinforced_at 更新
- weakened → active などの復帰も起こりうる

---

## 10. Merge の方針

### 10.1 当面の方針

> **当面は実体 merge をしない。**

物理的に2つの記憶を1つに潰すのではなく:

1. Promotion 側で新しい高次 Claim を作る
2. 旧記憶は `deprecated` or `merged` + `replaced_by`
3. 元記憶は tombstone / lineage で残す

### 10.2 merge_score

merge_score は **高次概念へ束ねる妥当性のスコア** であり、  
当面は物理統合のトリガーではなく、高次 Claim 生成の補助に使う。

#### 構成要素

| 要素 | 説明 |
|---|---|
| semantic similarity | 意味的な近さ（embedding 類似、補助的に使用） |
| predicate-family closeness | predicate が同じ語彙族・上位カテゴリに属するか |
| evidence overlap | 同じ時期・文脈・topic cluster で共起しているか |
| non-contradiction | 互いに矛盾していないこと（矛盾があれば merge_score を強く下げる） |
| abstraction gain | 束ねた時に上位概念として説明力が増すか |

#### 初期の扱い

- 連続値に凝りすぎず、High / Medium / Low でも十分
- 物理統合は行わない
- 高次 Claim 候補を作るかどうかの判断に使う
- Decay Tribunal で旧記憶を merged 候補にするかの判断に使う

---

## 11. Tombstone

### 方針

> **完全削除は原則しない。最低限の痕跡を残す。**

### 残すもの

- 元 semantic / claim の参照
- 退役理由
- replaced_by（置換先があれば）
- archived_at
- owner_agent
- memory_domain

---

## 12. Decay Tribunal

### 12.1 審査タイミング

#### 基本原則

- **リアルタイムは記録**
- **Sleep Cycle は制度判断**

#### ターン時に記録するもの

- retrieval 発生
- contradiction signal
- reinforcement signal
- active memory の再参照
- unresolved / skeleton contradiction 由来の補助シグナル

#### Sleep Cycle で判断するもの

- strengthen
- weaken
- deprecate
- contradict
- merge
- archive

#### 例外

identity 領域や重大な自己定義矛盾など、会話継続に影響が大きいものは:

- 即時フラグ
- Working Memory 仮保持

を許可する。  
ただし、正式な decay state 変更は Sleep Cycle / Tribunal で行う。

### 12.2 審査主体

| 審査主体 | 役割 |
|---|---|
| Rule Review | memory_strength, contradiction_score, retrieval_count 等の定量判定 |
| LLM Review | 「古いだけか」「矛盾したのか」「merge すべきか」の意味的補助判断。単独決定しない |
| Future MemoryCore | 将来的な軽量モデルによる減衰・統合補助 |

---

## 13. Context Builder / Retrieval の方針

### 13.1 ゾンビ記憶対策

通常検索空間に退役記憶を混ぜない。

### 13.2 通常応答で使うもの

- `active`
- `strengthened`

のみ。

### 13.3 特殊アクセス

以下は限定用途でのみアクセス可:

- `deprecated`
- `contradicted`
- `merged`
- `archived`

用途例: Depth 2, retrospection, Sleep Cycle, Nero 観察

### 13.4 retrieval の位置づけ

retrieval は単なる検索ではなく、**reinforcement signal** でもある。

- ターン時に記録
- Sleep Cycle で制度判断

---

## 14. 移行戦略

### 14.1 decay_path

Promotion 側が `promotion_path = legacy / tribunal_v1` を持つのと同様に、  
Decay 側も段階的に移行する。

- `legacy_expiry` — 既存の expiry / half-life ロジック
- `tribunal_v1` — 新制度（Decay Tribunal による審査）

### 14.2 移行期の方針

1. 既存の expiry / half-life ロジックは当面維持する
2. 並行して `semantic_state` を更新する
3. Decay Tribunal の判定は最初は shadow として記録のみ行う
4. 既存 expiry と tribunal_v1 の差分を観測する
5. 安定したら legacy_expiry の影響範囲を縮小する

### 14.3 原則

- Promotion だけ先に新制度化しない
- Decay も並走・比較・縮小の手順で移行する
- 既存忘却ロジックの即時停止は行わない

---

## 15. DB スキーマ詳細

### 15.1 semantic_state

semantic memory の動的状態を持つテーブル。

| カラム | 型 | 説明 |
|---|---|---|
| semantic_id | TEXT PK | `semantic_memories` 参照 |
| owner_agent | TEXT | `nia` / `nero` / future |
| memory_domain | TEXT | fact / preference / relationship / insight / lesson / identity |
| memory_strength | REAL | 現在の保持力（0.0〜1.0） |
| confidence | REAL | 昇格時の確からしさスナップショット |
| seed_retention | REAL | 初期保持条件 |
| last_reinforced_at | REAL | 最終強化時刻 |
| retrieval_count | INTEGER | 再参照回数 |
| contradiction_score | REAL | 矛盾スコア |
| deprecation_score | REAL | 非推奨スコア |
| merge_score | REAL | 高次概念へ束ねる圧力 |
| state | TEXT | active / strengthened / weakened / deprecated / contradicted / merged / archived / forgotten |
| promotion_path | TEXT | legacy / tribunal_v1 |
| decay_path | TEXT | legacy_expiry / tribunal_v1 |
| created_at | REAL | 作成時刻 |
| updated_at | REAL | 更新時刻 |

#### 補足

- `confidence` は **Claim の妥当性**
- `seed_retention` は **生存力の初期条件**
- `memory_strength` は **保存後に変動する保持力**
- 初期値は `memory_strength = seed_retention` とする
- `promotion_path` と `decay_path` を同一テーブルに持つことで、記憶のライフサイクル全体を一箇所で追える

### 15.2 semantic_reviews

減衰・退役審査ログ。

| カラム | 型 | 説明 |
|---|---|---|
| review_id | TEXT PK | 一意ID |
| semantic_id | TEXT | 対象記憶 |
| reviewer_type | TEXT | rule / llm / model / human |
| decision | TEXT | strengthen / weaken / deprecate / contradict / merge / archive |
| reason | TEXT | 理由 |
| evidence_snapshot_json | TEXT | 審査時点の指標スナップショット |
| thread_id / turn_id / message_id / stream_id / trace_id | TEXT | provenance key |
| created_at | REAL | 審査時刻 |

### 15.3 semantic_tombstones

退役した記憶の墓標。

| カラム | 型 | 説明 |
|---|---|---|
| tombstone_id | TEXT PK | 一意ID |
| semantic_id | TEXT | 元記憶 |
| claim_ref | TEXT | 元 claim |
| owner_agent | TEXT | 所有主体 |
| memory_domain | TEXT | 記憶領域 |
| retirement_reason | TEXT | contradicted / deprecated / merged / expired |
| replaced_by | TEXT NULL | 新しい semantic / claim |
| archived_at | REAL | 退役時刻 |
| notes | TEXT NULL | 任意メモ |

### 15.4 semantic_transitions

状態遷移の履歴。

| カラム | 型 | 説明 |
|---|---|---|
| transition_id | TEXT PK | 一意ID |
| semantic_id | TEXT | 対象 |
| from_state | TEXT | 遷移前 |
| to_state | TEXT | 遷移後 |
| trigger_type | TEXT | retrieval / contradiction / merge / timeout / review |
| trigger_ref | TEXT | 元イベント参照 |
| created_at | REAL | 遷移時刻 |

---

## 16. Nia の体験

Decay 制度は Nia に露出しない。  
Nia が体験するのは結果だけである。

- 薄れる
- 退く
- 以前はそうだった気がする
- 今は違う

が自然に体験される。

「仕組みは隠す。体験は渡す。」

---

## 17. 結論

Decay は、保存後の記憶を「どう持ち続けるか」を決める制度である。

- 忘却は喪失ではなく、弱化・退役・統合・痕跡化
- memory_strength が動的に変動する中心指標
- 状態遷移は哲学的制約を持つ（痕跡が生きていれば復帰可能、制度的退場からは再出発）
- Tribunal はルールベース中心、LLM は補助
- 移行は Promotion と同様に並走方式

Promotion が「記憶を成立させる制度」であるのに対し、  
Decay は **「記憶を持ち続ける方を決める制度」** である。
