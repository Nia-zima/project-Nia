# Nia 統合ロードマップ

> **目的:** 個別設計書と feature gate 台帳を横断して、「今どこにいて、次に何を有効化し、何を後回しにするか」を一枚で確認できるようにする。  
> **更新タイミング:** gate の stage 変更時、大きな設計追加時、ロードマップの順序変更時。  
> **基準日:** 2026-03-24

---

## 1. この文書の位置づけ

この文書は設計書そのものではない。  
各コンポーネントの仕様は個別設計書を正とし、ここでは **統合順序** と **依存関係** だけを扱う。

優先順位の判断軸は次の 4 つ:

1. 本線を壊さない
2. 観測を先に、制御を後に
3. rollback が簡単なものから有効化する
4. データ量のしきい値を満たしてから次段階へ進む

---

## 2. 現在地

### 2.1 本線

- 会話本線: 稼働中
- `review_window`: 稼働中
- `S5 Commit`: 稼働中
- 品質基盤: gate registry / deferred items / state taxonomy / migration / retention / recovery / review checklist まで整備済み

### 2.2 稼働中の観測系

| 項目 | 状態 | 補足 |
|------|------|------|
| NiaCore Experience | on | `niacore_experience` 蓄積中 |
| NiaCore Shadow | on | depth 決定はまだ rule-based |
| NiaCore vNext Shadow | on | N0 観測専用で `niacore_vnext_shadow` 蓄積中 |
| Skeleton Record | on | record-only |
| Governance Observe / Candidate / Evidence | on | Observe は record-only、Candidate/Evidence は canary |
| Fingerprint Record | on | TS.0 稼働中 |
| Expression Layer E0 | on | record-only |
| RuntimeFacts | on | Phase A 観測中 |

### 2.3 実装済みだが未有効化

| 項目 | Gate | 理由 |
|------|------|------|
| Atmosphere | `ATMOSPHERE_ENABLED` | RuntimeFacts Phase A の観測後に判断 |
| Skeleton Somatic | `SKELETON_SOMATIC_ENABLED` | record-only 観測後 |
| NiaCore Training | `NIACORE_TRAINING_ENABLED` | Shadow 期間・品質条件待ち |

### 2.4 可変データの確認方法

この節の数値は腐りやすい。  
**具体的な行数は常に `python -m backend.scripts.report_gate_status` を正とする。**

このロードマップでは、次の項目だけを確認すればよい:

- `niacore_experience`: Training 判定に十分な蓄積があるか
- `conversation_skeletons`: `SKELETON_SOMATIC_ENABLED` 判定ラインに近いか
- `turn_fingerprints`: TS.1 の前提量に達したか
- `governance_events`: Phase A 観測が十分進んでいるか
- `expression_observations`: E0.5 に進めるだけの分量があるか
- `niacore_vnext_shadow`: N0 の分析を始められるか

---

## 3. 統合順序の原則

### 3.1 一度に進めるのは 1 段階まで

- 同時に複数の gate を有効化すると、挙動変化の原因が分からなくなる
- 特に LLM context を変えるものと、観測専用のものを同日に混ぜない

### 3.2 先に有効化するもの

- fire-and-forget
- rollback が env 1 個で済む
- 既存本線に制御影響を持たない

### 3.3 後に有効化するもの

- LLM prompt / context を変えるもの
- depth 決定や memory policy に影響するもの
- 学習や自動更新を伴うもの

---

## 4. 推奨ロードマップ

## Phase 0: 運用基盤

**状態:** 完了

- gate registry / deferred items / taxonomy
- gate status report
- lightweight migration
- retention policy / prune
- recovery runbook
- review checklist

この段階は完了したので、次は **低リスク観測の拡張** に進む。

---

## Phase 1: 低リスク観測の拡張

**目的:** 本線に影響しない観測レイヤーを先に開ける。

**状態:** 完了（観測継続中）

### 推奨順

1. `EXPRESSION_RECORD_ENABLED`
2. `NIACORE_VNEXT_SHADOW_ENABLED`
3. Chroma 再構築リハーサル（メンテ時）

### 理由

- Expression E0 と vNext Shadow はどちらも fire-and-forget
- rollback は gate を off にするだけ
- 次段階の分析や vNext N1 の前提データになる

### 卒業条件

- `EXPRESSION_RECORD_ENABLED`: `expression_observations >= 100` 行
- `NIACORE_VNEXT_SHADOW_ENABLED`: `niacore_vnext_shadow >= 100` 行
- 観測期間中に writer エラーログ 0 件
- S5 / 本線エラー率に悪影響がない

**補足:** ここでの「100 行」は卒業判定の最小ラインであり、分析開始ラインではない。

---

## Phase 2: Context 注入の段階投入

**目的:** LLM context に影響する要素を 1 つずつ入れる。

**状態:** 進行中（`RUNTIME_FACTS_ENABLED=true`、Phase A 観測中）

### 推奨順

1. `RUNTIME_FACTS_ENABLED`（完了）
2. `SKELETON_SOMATIC_ENABLED`
3. `ATMOSPHERE_ENABLED`

### 理由

- `RuntimeFacts` は context 注入系の中で最も説明可能性が高い
- `Skeleton Somatic` は `conversation_skeletons` が 500 付近に達してから入れるのが自然
- `Atmosphere` は最も「空気」を変えやすいので最後

### 進め方

- 各 gate ごとに観測期間を設ける
- 1 回の有効化で見るのは 1 コンポーネントだけ
- 観測対象:
  - Depth0 の立ち止まり品質
  - 過剰な即答化が起きないか
  - 不自然な自己言及や説明口調が増えないか

### 観測方法

- **writer 生存確認:** `python -m backend.scripts.report_gate_status`
- **WAIT / spoken バランス:** `expression_observations.event_kind` の分布を見る
- **Depth の偏り:** `expression_observations.selected_depth` と `turn_fingerprints` の増え方を見る
- **品質確認:** 有効化前後で 20 ターン程度を手動レビューする
- **レビュー観点:** 即答化、説明臭さ、自己言及、WAIT の消失、迎合の増加

### 卒業条件

- prompt 変化が「仕組みの露出」になっていない
- WAIT が減りすぎない
- 迎合や説明臭さが増えない

---

## Phase 3: 学習・分析の起動

**目的:** 観測から分析・学習へ進める。

### 推奨順

1. `NIACORE_TRAINING_ENABLED`
2. Expression E0.5 分析
3. TS.1 Contrast Engine

### 理由

- `NIACORE_TRAINING_ENABLED` はもっとも影響が大きいので、日数条件を守る必要がある
- 最短判定日は **2026-04-05**（Shadow 開始 2026-03-06 から 30 日後）
- Expression E0.5 と TS.1 は、観測量が揃ってから分析へ進む

### NiaCore Training の前提条件

- Shadow 期間が 30 日以上
- `niacore_experience` が十分量ある
- 一致率、逸脱後成功率、Depth 分布の条件を満たす
- rollback 手順が明確

### Expression / TS の前提条件

- `expression_observations` の十分な蓄積
- `turn_fingerprints` が 500+ に到達
- strata ごとの分布が読める状態

---

## Phase 4: 制度の本格化（Phase 3 と並行可能）

**目的:** Governance と vNext を次段階へ進める。

### 対象

- Governance Phase B
- Governance Phase C
- NiaCore vNext Phase N1

### 進行条件

- Governance Phase A の candidate / evidence 分布が安定
- vNext Shadow の attention / action 分布が十分見えた
- writer / provenance / taxonomy が崩れていない

### 注意

- この段階からは「観測専用」ではなく、制度そのものが複雑になる
- 先に state / signal 境界を再点検してから進める
- `NIACORE_TRAINING_ENABLED` と Governance Phase B/C は直列依存ではない
- それぞれの前提条件が満たされれば、**並行トラック** として進めてよい

---

## Phase 5: 長期統合トラック

**目的:** 体感・Pip・Unity・配信系を広げる。

### 対象

- S.2 体感 + Pip 統合
- TS.3 Idle Tick
- P.3 お絵かき統合
- P.7 配信
- M.4 Retrieval Observability

### 位置づけ

- これらは本線の安定より後
- Unity / renderer / 外部連携が増えるため、別トラックとして扱うのが安全
- 「ニアの中身」を先に整え、「見せ方」は後から被せる順序を守る

---

## 5. 直近の実行順

2026-03-24 時点での、もっとも自然な順序はこれ。

1. RuntimeFacts Phase A を観測し、説明臭さや即答化の副作用がないか確認する
2. `conversation_skeletons` が 500 超 + 目視確認後、`SKELETON_SOMATIC_ENABLED=true`
3. `ATMOSPHERE_ENABLED=true` は RuntimeFacts 観測後に判断
4. メンテナンス時に Chroma 再構築リハーサルを実施
5. **2026-04-05 以降**に `NIACORE_TRAINING_ENABLED` 判定

---

## 6. 別トラック

### Nero（anti-stagnation / companion）

- Nero は別リポジトリ
- Nia 側の統合ロードマップには直接含めない
- ただし会話品質には影響するため、**Nero 側の変更は別トラックで管理し、Nia 側への影響は `/api/chat` と読み取り API 経由のみ** と明記しておく
- Nia 側で先にやるべきなのは、Nero 依存ではなく Nia 本体の観測・安定化

---

## 7. 今やらないもの

次はやらない方がよいものを明示しておく。

- Governance Phase B/C を先に進めること
- vNext N1 を N0 データなしで始めること
- `ATMOSPHERE_ENABLED` を `RUNTIME_FACTS_ENABLED` より先に入れること
- `NIACORE_TRAINING_ENABLED` を 2026-04-05 より前に入れること
- Unity / 配信系を、内部状態系より先に広げること

---

## 8. 関連文書

- `docs/feature_gate_registry.md`
- `docs/deferred_items.md`
- `docs/state_field_taxonomy.md`
- `docs/nia_expression_layer_design.md`
- `docs/niacore_lnn_design.md`
- `docs/niacore_vnext_design.md`
- `docs/skeletoncore_design.md`
- `docs/temporal_somatic_contrast_design.md`
- `docs/pip_room_temporal_livestream_integration.md`
- `docs/governance_phase_a_status_2026-03-11.md`

この文書を更新するときは、上の台帳類と矛盾しないことを確認する。
