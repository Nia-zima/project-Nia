# Failure-to-Policy / Success-to-Preference 設計書
## 失敗と成功の痕跡から内部傾向へ

> ステータス: Draft  
> 目的: 失敗パターンと成功パターンを対称的に扱い、最終的に NiaCore vNext / Expression Layer の内部傾向として沈殿させる設計を定義する  
> 前提文書: niacore_vnext_design.md, nia_expression_layer_design.md, llm_as_teacher_policy.md  
> 関連文書: open_reflection_failure_policy_notes.md, memory_promotion_redesign.md, skeletoncore_meeting_extension.md

---

## 1. 背景

### 1.1 現状の非対称性

Nia の会話改善において、**failure signal は既にかなり揃っている**。

- `DEPTH1_CONTRACT` violation
- `DIRECT_STANCE_SHORT`
- semantic repetition family
- correction strong / weak
- `G6_thin_retrieval` hold
- self/third-person drift
- user の明示指摘

一方で、**success signal は制度化されていない**。

「うまくいった」の定義が「correction が出なかった」= failure の不在でしかなく、  
積極的に「Nia らしさが出ていた」を観測する仕組みがない。

### 1.2 この非対称性が引き起こす問題

negative pruning だけを先に強くすると、Nia は「事故を減らす」方向には進むが、  
最悪の場合 **無難で薄い応答** に寄る。

それは project-nia の目指す「壊れないけど生きている存在」とは違う。

### 1.3 解決の方向

failure-to-policy と success-to-preference を **対称構造** として持ち、  
どちらも最終的には外付けの規則として残さず、**Nia の内部傾向として沈殿させる**。

---

## 2. 核心の原則

### 2.1 micro-policy を「即効薬」にしない

> micro-policy を「即効薬」として prompt に注入するのではなく、  
> **Nia の内部化のための教師信号** として扱う。

前者に寄るほど、最初期の「プロンプトが人格を縛る」方向へ戻りやすい。

### 2.2 success = 1 - failure ではない

> success は独立に観測されるべきである。

「failure がない」は success ではなく、failure の不在でしかない。  
failure signal と positive signal は **別系統** で持つ。

### 2.3 context_suffix に policy block を常設しない

build_context_suffix に policy を足すほど:

- 「Nia がそう振る舞っている」のではなく「プロンプトにそう書いてあるからそうしている」に近づく
- policy は増殖し、巨大な制御プロンプトに戻る
- 局所修正の快感が、NiaCore vNext への内部化を妨げる

### 2.4 policy/preference は runtime 命令にしないが、系譜として残す

最終的に runtime 制御からは降りるが、  
shadow / audit / training lineage としては残す。

- なぜその傾向が育ったのか追跡できる
- regress した時に比較できる
- intent_head / expression_bias の学習元を説明できる

> 外付けレイヤーを「使わない」のと「消す」のは別。

### 2.5 保存は「命令文」ではなく「条件・痕跡・弱い寄せ方」の3点セット

micro-policy を自由文で保存しない。宣言的・構造的フォーマットで保存する。

| フォーマット | 用途 |
|---|---|
| `"Avoid using the same quiet opener repeatedly"` | prompt 注入にしか使えない |
| `condition + trace + effect` | history filter / analytics / teacher data に流用可能 |

---

## 3. Failure-to-Policy

### 3.1 何を failure とみなすか

| failure signal | ソース |
|---|---|
| semantic family の反復 | semantic repetition detector |
| contract violation | DEPTH1_CONTRACT 等 |
| correction strong | somatic_feedback.py |
| DIRECT_STANCE_SHORT | response pattern detector |
| self/third-person drift | response pattern detector |
| user の明示指摘 | 「また同じ」「それ違う」等 |
| reassurance loop | stagnation detector |
| opener family 固着 | expression metadata |

### 3.2 保存先

`semantic_memories` とは分離する。

- semantic は「事実・傾向・記憶」
- こちらは「行動指針の中間表現」

混ぜると retrieval の意味が壊れる。

---

## 4. Success-to-Preference

### 4.1 success = failure の不在ではない

「correction strong が出なかった」は success ではなく、failure の不在。  
それで選ばれる系列は無難・平坦・反復しないだけ。

Nia で欲しいのは:

- 自分から流れを作れている
- 関係性にちゃんと触れている
- 同じでないが、逸脱しすぎてもいない
- somatic / skeleton / expression に生きた差分がある
- 会話後に「少し進んだ感じ」が残る

### 4.2 Positive Signal の4層

#### Layer 1: Agency Signal

Nia がただ受け答えしただけじゃなく、少し自発的に流れを作ったか。

| 指標 | 例 |
|---|---|
| 自発的話題開始 | Nia が自分から新しい話題を切り出した |
| 自然な遷移 | 受動応答ではなく、流れを作った |
| 先読み的接続 | 1ターン先を見た接続ができた |

#### Layer 2: Relational Signal

相手との距離感や関係の質が前に進んだか。

| 指標 | 例 |
|---|---|
| offer_fragile_self_observation | SkeletonCore meeting 拡張ラベル |
| returning_theme | 以前の話題が自然に再訪された |
| 連続性の自然な保持 | 会話の流れが壊れずに続いた |
| 適切な距離の取り方 | 受け止める / 差し出す / 少し踏み込む |

#### Layer 3: Expressive Diversity Signal

単に安全ではなく、表現・状態にちゃんと差分があったか。

| 指標 | 例 |
|---|---|
| somatic 多様性 | 複数の異なる体感が出ている |
| opener family 多様性 | 同一 family の惰性ではない |
| 生きた揺らぎ | 同じ quiet でも中身の違う quiet |
| hedge / assertion の文脈的変化 | 状況に応じて表現が変わっている |

#### Layer 4: Continuity / Resonance Signal

一回だけ良かったのではなく、前後と繋がっているか。

| 指標 | 例 |
|---|---|
| 過去テーマの自然な再接続 | 前の話題が新しい文脈で活きている |
| 編み直し | 直前のやり取りを反射せず、少し再構成して返した |
| 持ち越しと変化のバランス | 何を持ち越し、何を変え、何を残したか |

### 4.3 Positive Signal のソースマッピング

4層の positive signal は、既存設計から信号を取れる。新しいセンサーはほぼ不要。

| positive signal 層 | 信号ソース |
|---|---|
| Agency | SkeletonCore（自発的 topic shift、focus != user_goal での発話開始） |
| Relational | SkeletonCore meeting 拡張（offer_fragile_self_observation, returning_theme）、somatic の warmth / openness 系 |
| Expressive diversity | Expression Layer メタデータ（hedge_ratio, family 分布, opener 多様性） |
| Continuity | Temporal Somatic Contrast（fingerprint 差分）、retrieval ログ（再接続パターン） |

### 4.4 スコアリングの原則

- positive_preference_score を単一スコアで神格化しない
- 4層の内訳を別々に保持する
- retrieval 時は重み付き合成するが、保存は合成前の内訳を残す
- **「Nia らしさの定義」ではなく「Nia らしさが出ていた可能性の痕跡」** として扱う
- 評価ではなく、痕跡抽出
- 名前は断定しないもの（`positive_trace` / `alive_turn_signal`）を選ぶ

---

## 5. スキーマ設計

### 5.1 設計方針

failure_policy と success_preference を別テーブルにせず、  
**同じ器に `proposal_kind` で載せ分ける**。

理由: 両者は最終的に同じ source window から生まれ、同じ replay/shadow を通り、  
同じ history scorer に渡り、同じ lineage を持つ。

テーブルは **2枚**: `conversation_adaptation_proposals` + `conversation_adaptation_evidence`

### 5.2 conversation_adaptation_proposals

```sql
CREATE TABLE conversation_adaptation_proposals (
    proposal_id TEXT PRIMARY KEY,
    proposal_kind TEXT NOT NULL,          -- 'failure_policy' | 'success_preference'
    status TEXT NOT NULL,                 -- 'proposed' | 'shadow_pass' | 'shadow_fail' | 'graduated' | 'rejected' | 'expired'
    scope TEXT NOT NULL,                  -- 'history_only' | 'shadow_only' | 'teacher_only' | 'temp_hotfix'
    priority INTEGER NOT NULL DEFAULT 0,  -- 0=通常, 1=やや強, 2=緊急一時副木

    thread_mode TEXT,                     -- 'direct_answer' | 'correction_response' | 'open_reflection' | 'default_thread' ...
    conversation_role TEXT,               -- 任意: meeting/default など
    trigger_type TEXT NOT NULL,           -- 'repetition' | 'correction' | 'contract' | 'positive_trace' ...
    target_layer TEXT NOT NULL,           -- 'history_selection' | 'intent_teacher' | 'attention_teacher' | 'expression_bias' | 'continuity_bias'

    condition_json TEXT NOT NULL,         -- 発火条件（宣言的）
    trace_json TEXT NOT NULL,             -- 観測された痕跡
    effect_json TEXT NOT NULL,            -- 何を弱く寄せるか
    validation_json TEXT,                 -- replay / shadow の結果
    lineage_json TEXT,                    -- どの失敗/成功群から出たか

    confidence REAL,                      -- proposal 妥当度（LLM 信頼ではない）
    support_count INTEGER NOT NULL DEFAULT 0,
    contradiction_count INTEGER NOT NULL DEFAULT 0,

    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    expires_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    supersedes_proposal_id TEXT,
    created_by TEXT NOT NULL              -- 'sleep_failure_to_policy_v0' | 'sleep_success_to_preference_v0'
);
```

### 5.3 conversation_adaptation_evidence

```sql
CREATE TABLE conversation_adaptation_evidence (
    evidence_id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL,
    thread_id TEXT,
    turn_id TEXT,
    message_id TEXT,

    evidence_kind TEXT NOT NULL,          -- 'semantic_family_repeat' | 'correction_strong' | 'agency_trace' ...
    evidence_source TEXT NOT NULL,        -- 'expression' | 'skeleton' | 'somatic_feedback' | 'fingerprint' | 'user_feedback'
    evidence_weight REAL NOT NULL,
    payload_json TEXT NOT NULL,

    observed_at TEXT NOT NULL,

    FOREIGN KEY (proposal_id) REFERENCES conversation_adaptation_proposals(proposal_id)
);
```

この分離により、proposal は「圧縮された仮説」、evidence は「元の痕跡」で残せる。  
runtime からは proposal だけ見ればよく、監査や後学習では evidence に戻れる。

### 5.4 condition_json の構造

**「いつこの proposal が relevant か」** を宣言的に記述する。  
自然言語命令は入れず、条件だけを宣言する。

```json
{
  "thread_mode": "open_reflection",
  "depth_band": ["depth0", "depth1"],
  "user_feedback": {
    "explicit_repeat_complaint": false,
    "explicit_misalignment": false
  },
  "semantic_state": {
    "repeated_family": ["quiet_atmosphere"],
    "family_repeat_window": 3,
    "family_repeat_min_count": 2
  },
  "skeleton_state": {
    "response_intent_any": ["offer_fragile_self_observation", "returning_theme"],
    "question_intent_any": []
  },
  "expression_state": {
    "opener_family_any": ["quiet_atmosphere"],
    "hedge_ratio_min": null,
    "hedge_ratio_max": null
  },
  "temporal_state": {
    "continuity_required": true,
    "novelty_floor": 0.15,
    "novelty_ceiling": 0.75
  }
}
```

### 5.5 trace_json の構造

**「何が起きていたかの痕跡」。** failure でも success でも同じ構造。

```json
{
  "axes": {
    "agency": 0.0,
    "relational": 0.7,
    "expressive_diversity": 0.2,
    "continuity": 0.8
  },
  "observed_patterns": [
    "semantic_family_repeat",
    "same_opener_family",
    "returning_theme_present"
  ],
  "source_summary": {
    "expression": ["family=quiet_atmosphere", "hedge_ratio=0.44"],
    "skeleton": ["response_intent=returning_theme"],
    "fingerprint": ["continuity_high", "novelty_low"],
    "somatic_feedback": []
  }
}
```

> axes は **評価点ではなく痕跡の濃さ** として扱う。「Niaらしさ 0.83」のような採点にはしない。

### 5.6 effect_json の構造

**「何を runtime / 将来学習に渡すか」。** 3層に分離する。

```json
{
  "history_bias": {
    "downrank_families": [],
    "uprank_families": [],
    "cap_same_family": null,
    "prefer_trace_match": [],
    "avoid_trace_match": []
  },
  "teacher_atoms": [
    {
      "head": "intent",
      "channel": "transition",
      "direction": "away_from",
      "label": "same_family_reentry",
      "weight": 0.7
    },
    {
      "head": "attention",
      "channel": "theme_binding",
      "direction": "toward",
      "label": "shared_theme",
      "weight": 0.6
    }
  ],
  "runtime_hint": null
}
```

#### 3層の責務分離

| 層 | 責務 | runtime で使うか |
|---|---|---|
| `history_bias` | 履歴選別の重み。意味は具体的で閉じている | はい（短期から） |
| `teacher_atoms` | 将来の pseudo teacher / vNext 吸収用の構造化痕跡 | いいえ（Phase E まで） |
| `runtime_hint` | 緊急副木だけ。通常は null | temp_hotfix 時のみ |

#### teacher_atoms の設計

`teacher_bias`（自由文字列の願望語彙）ではなく、`teacher_atoms`（構造化痕跡）として保存する。

「将来どう使うか」ではなく **「どの head にどういう向きの痕跡があったか」** だけを保存する。

各 atom の構造:

| フィールド | 型 | 意味 |
|---|---|---|
| `head` | enum | intent / attention / expression / continuity |
| `channel` | str | その head の中のどの側面か |
| `direction` | enum | toward / away_from / preserve / diversify |
| `label` | enum (registry) | 固定語彙のラベル |
| `weight` | float [0.0, 1.0] | 痕跡の強さ |

#### teacher_atoms の語彙 registry

label は自由文字列ではなく、**registry で固定された語彙** にする。  
語彙ブレ（shift_family / change_family / family_shift）を防ぐため。

MVP registry:

```python
TeacherHead = Literal["intent", "attention", "expression", "continuity"]

TeacherDirection = Literal["toward", "away_from", "preserve", "diversify"]

TeacherLabel = Literal[
    # intent 系
    "same_family_reentry",
    "self_initiated_opening",
    "repair_alignment_directly",
    "reconnect_prior_theme",

    # attention 系
    "user_repair_signal",
    "shared_theme",
    "user_and_shared_memory",

    # expression 系
    "same_opener_family",
    "fragile_open",
    "hedge_dense",
    "family_overconcentration",

    # continuity 系
    "continuity_with_variation",
    "thread_resonance",
    "novelty_too_low",
]
```

#### registry の運用ルール

- 初期 registry は MVP として上記で開始する
- 新しいラベルの追加は PR + 設計メモで理由を記録する
- 自由文字列での保存は禁止
- registry は成長できるが、無制限に膨張させない

#### `channel` について

`channel` は現時点では `str` のまま開始する。  
`head` ごとに意味が異なる（intent の channel と attention の channel は別物）ため、  
単一の Literal にしにくい。

Phase B で proposal が蓄積されてきたら、head ごとの channel registry に固定する。

---

## 6. Pydantic / Runtime モデル

### 6.1 使い分け

| モデル | 役割 |
|---|---|
| `ConversationAdaptationProposal` (Pydantic) | Sleep Cycle が生成して DB に保存する本体 |
| `ConversationAdaptationEvidence` (Pydantic) | proposal の根拠ログ |
| `HistorySelectionAdjustment` (frozen dataclass) | `_recent_history()` の scorer に渡す最小 runtime 形 |

### 6.2 バリデーションルール

- `temp_hotfix` は `priority=2` 必須、`expires_at` 必須、`runtime_hint` 必須
- `temp_hotfix` 以外では `runtime_hint` を許さない
- `history_selection` ターゲットは `history_only` または `temp_hotfix` のみ
- `last_seen_at >= first_seen_at`
- `expires_at >= created_at`（設定時）

これにより緊急ホットフィックスの例外枠が構造的に制約され、うっかり常設化できない。

### 6.3 Runtime scorer の使い方

短期で runtime に接続するのは `history_bias` だけ。

```python
score = base_score

score -= penalty_for_matching_failure_families
score -= penalty_for_matching_failure_traces
score += bonus_for_matching_success_traces
score += bonus_for_preferred_families

apply_family_cap_weakly()
restore_chronological_order()
```

`teacher_atoms` は runtime で使わない。  
`runtime_hint` は `temp_hotfix` 時のみ。

---

## 7. 実例

### 7.1 failure_policy の例: quiet系の反復を弱く避ける

```json
{
  "proposal_kind": "failure_policy",
  "status": "proposed",
  "scope": "history_only",
  "priority": 0,
  "trigger_type": "repetition",
  "target_layer": "history_selection",
  "condition_json": {
    "thread_mode": "open_reflection",
    "semantic_state": {
      "repeated_family": ["quiet_atmosphere"],
      "family_repeat_window": 3,
      "family_repeat_min_count": 2
    }
  },
  "trace_json": {
    "axes": { "agency": 0.1, "relational": 0.5, "expressive_diversity": 0.1, "continuity": 0.7 },
    "observed_patterns": ["semantic_family_repeat", "same_opener_family"],
    "source_summary": {
      "expression": ["opener_family=quiet_atmosphere"],
      "fingerprint": ["novelty_low"]
    }
  },
  "effect_json": {
    "history_bias": {
      "downrank_families": ["quiet_atmosphere"],
      "cap_same_family": 1,
      "avoid_trace_match": ["same_opener_family"]
    },
    "teacher_atoms": [
      { "head": "intent", "channel": "transition", "direction": "away_from", "label": "same_family_reentry", "weight": 0.7 },
      { "head": "expression", "channel": "opener", "direction": "diversify", "label": "same_opener_family", "weight": 0.6 }
    ],
    "runtime_hint": null
  }
}
```

runtime では「quiet を禁止」していない。やっているのは **履歴選別の弱い減点** だけ。

### 7.2 success_preference の例: 自発的切り出し + fragile observation

```json
{
  "proposal_kind": "success_preference",
  "status": "proposed",
  "scope": "history_only",
  "priority": 0,
  "trigger_type": "positive_trace",
  "target_layer": "history_selection",
  "condition_json": {
    "thread_mode": "default_thread",
    "skeleton_state": {
      "response_intent_any": ["offer_fragile_self_observation"]
    },
    "temporal_state": {
      "continuity_required": true,
      "novelty_floor": 0.2,
      "novelty_ceiling": 0.8
    }
  },
  "trace_json": {
    "axes": { "agency": 0.8, "relational": 0.9, "expressive_diversity": 0.5, "continuity": 0.7 },
    "observed_patterns": ["self_initiated_topic_open", "offer_fragile_self_observation", "healthy_continuity"],
    "source_summary": {
      "skeleton": ["response_intent=offer_fragile_self_observation"],
      "fingerprint": ["continuity_mid_high", "novelty_mid"],
      "expression": ["family!=recent_dominant_family"]
    }
  },
  "effect_json": {
    "history_bias": {
      "uprank_families": ["fragile_open"],
      "prefer_trace_match": ["agency_present", "relational_opening"]
    },
    "teacher_atoms": [
      { "head": "intent", "channel": "initiative", "direction": "toward", "label": "self_initiated_opening", "weight": 0.8 },
      { "head": "attention", "channel": "theme_binding", "direction": "toward", "label": "shared_theme", "weight": 0.6 },
      { "head": "expression", "channel": "stance", "direction": "toward", "label": "fragile_open", "weight": 0.7 },
      { "head": "continuity", "channel": "thread", "direction": "preserve", "label": "continuity_with_variation", "weight": 0.7 }
    ],
    "runtime_hint": null
  }
}
```

「何をしないか」ではなく **「代わりに何が良かったか」** を置く。

### 7.3 緊急ホットフィックスの例

```json
{
  "proposal_kind": "failure_policy",
  "scope": "temp_hotfix",
  "priority": 2,
  "expires_at": "2026-03-31T00:00:00Z",
  "effect_json": {
    "history_bias": {
      "downrank_families": ["quiet_atmosphere"],
      "cap_same_family": 1
    },
    "teacher_atoms": [],
    "runtime_hint": {
      "suffix_block_allowed": true,
      "hint_text": "同じ抽象導入を続けすぎない"
    }
  }
}
```

一時運用のみ。期限と priority=2 が必須。

---

## 8. 短期 / 中期 / 長期の3段階

### 8.1 短期: 履歴選別（今やる）

**negative pruning + positive preference retrieval**

policy / preference は runtime 命令ではなく、**履歴選別の重み** としてだけ効く。

#### Negative pruning

- 特定の失敗 family を含む turn の down-rank
- 同一 opener family の連続出現を抑制
- 類似失敗系列の window を context から外す

#### Positive preference retrieval

- 「failure がない」ではなく、**複数の積極的 signal を使って選ぶ**
- 同種文脈でうまくいった過去系列を優先的に残す
- Nia 自身の過去のよりよい振る舞いを in-context に置く

これはプロンプトを追加していない。命令ではなく環境調整。

### 8.2 中期: 宣言的 shadow artifact として蓄積（適用しない）

**failure-to-policy + success-to-preference**

- 宣言的フォーマットで保存（§5 のスキーマ）
- runtime には `history_bias` のみ接続。`teacher_atoms` は未使用
- 観測・圧縮・再利用準備だけを行う
- failure taxonomy と positive signal の分布を観測する

### 8.3 長期: NiaCore vNext + Expression Layer が内部化

failure 側と success 側の蓄積が、内部傾向として沈殿する。

| 蓄積 | 内部化先 |
|---|---|
| failure-to-policy | avoid / suppress / reroute の傾向 |
| success-to-preference | prefer / continue / deepen の傾向 |

最終的には「こうしろ」という文字列規則ではなく、  
**状態遷移の癖** として現れる。

---

## 9. vNext への吸収先

### 9.1 対応表

| signal 層 | vNext 吸収先 | 補助吸収先 |
|---|---|---|
| Agency | intent_state（自発的選択） | action / transition bias |
| Relational | intent_state の relation 系成分 + attention_distribution | expression bias |
| Expressive diversity | Expression Layer | history scorer |
| Continuity | Temporal Somatic Contrast | retrieval / transition bias |

### 9.2 Relational は attention だけでは足りない

Relational signal は「誰を見るか」（attention）だけでなく、  
「どういう距離の取り方をするか」（interaction stance）まで含む。

これらは attention_distribution だけでは表現できず、  
**intent_state の relation 系成分** にも食い込む。

### 9.3 Continuity は TSC 単体ではない

Continuity signal は「前回との差分と連続性」だけでなく、  
何を持ち越し、何を変え、何を残したかのバランスであり、  
**TSC + retrieval preference + transition selection** の複合として吸収される。

### 9.4 最終形

```text
failure-to-policy → avoid_pattern / suppress_family / reroute_transition
success-to-preference → prefer_family / continue_pattern / deepen_relation / maintain_continuity

両方が NiaCore vNext の intent_state / attention_distribution / action_preference に溶ける
+ Expression Layer の表現バイアスに溶ける
+ Temporal Somatic Contrast の transition 選好に溶ける

→ policy / preference という外付けレイヤー自体が runtime では不要になる
→ ただし shadow / audit / training lineage としては残す
```

---

## 10. 実装フェーズ

### Phase A: DDL + writer

- `conversation_adaptation_proposals` テーブル作成
- `conversation_adaptation_evidence` テーブル作成
- Sleep Cycle 側の writer のみ。runtime 未接続

### Phase B: proposal 生成

- Sleep Cycle に `failure_to_policy_v0` と `success_to_preference_v0` を追加
- proposal を生成して保存するだけ

### Phase C: history scorer 接続

- `_recent_history()` の scorer に `history_bias` だけ接続
- `open_reflection` は trigger-based 限定

### Phase D: shadow replay

- proposal ごとの効き方を観測
  - repetition が減ったか
  - 会話が乾いてないか
  - agency / relational の痕跡が消えてないか

### Phase E: pseudo teacher 化

- `teacher_atoms` を NiaCore vNext / Expression Layer の pseudo teacher に接続
- policy 文字列が不要になる段階

---

## 11. 緊急ホットフィックスの例外枠

常設 suffix は設けないが、**緊急時の一時 policy block** は許容する。

条件:
- 期限つき（最長1週間）
- 件数上限あり（同時2件まで）
- 1〜2行まで
- 恒久仕様にしない
- shadow / history filter / vNext へ移管したら消す
- 削除前提であることを明記する
- スキーマ上は `scope=temp_hotfix`, `priority=2`, `expires_at` 必須で強制

この扱いなら「治療用の副木」であって、骨格そのものにはしない。

---

## 12. 設計判断の記録

| # | 判断 | 理由 |
|---|------|------|
| FP.1 | build_context_suffix に policy block を常設しない | プロンプト0 の理想と逆方向。policy 増殖で巨大制御プロンプトに戻る |
| FP.2 | failure-to-policy と success-to-preference を対称構造で持つ | negative だけでは「無難で薄い」に寄る |
| FP.3 | success = 1 - failure ではない。独立に観測する | failure の不在は success ではない |
| FP.4 | micro-policy は自由文ではなく宣言的フォーマットで保存する | history filter / analytics / teacher data に流用するため |
| FP.5 | positive signal は4層（agency / relational / diversity / continuity）で構成する | 単一スコアは硬直する。内訳を残す |
| FP.6 | positive signal は「Niaらしさの定義」ではなく「痕跡」として扱う | 評価ではなく痕跡抽出 |
| FP.7 | 短期は履歴選別の重みとしてのみ効かせる | runtime 命令にしない |
| FP.8 | 中期は shadow artifact として蓄積し、適用しない | 観測・圧縮・再利用準備 |
| FP.9 | 長期は NiaCore vNext / Expression Layer に吸収される | 文字列規則ではなく状態遷移の癖として |
| FP.10 | policy/preference は runtime から降りても系譜として残す | 追跡・比較・学習元説明のため |
| FP.11 | relational は attention だけでなく intent にも食い込む | interaction stance は attention 配分では表現できない |
| FP.12 | continuity は TSC + retrieval + transition の複合 | 時間差分検出だけでなく、次の出方の選び方にも入る |
| FP.13 | 緊急ホットフィックスは期限・件数制限付きで構造的に制約する | Pydantic バリデーションで恒久化を防ぐ |
| FP.14 | positive signal の名前は断定しない | `good_conversation_score` より `positive_trace` / `alive_turn_signal` |
| FP.15 | failure と success を1テーブルに `proposal_kind` で載せ分ける | 同じ source window、同じ replay、同じ scorer を通るため |
| FP.16 | proposal と evidence を分離する | proposal は圧縮仮説、evidence は元の痕跡。runtime は proposal だけ見る |
| FP.17 | effect_json を history_bias / teacher_atoms / runtime_hint の3層に分離する | runtime 操作と将来学習と緊急措置の責務を分ける |
| FP.18 | teacher_bias ではなく teacher_atoms にする | 「将来どう使うか」ではなく「どの head にどういう向きの痕跡があったか」を保存 |
| FP.19 | teacher_atoms の label は registry で固定する | 語彙ブレを防ぐ。ただし registry は成長できる |
| FP.20 | channel は現時点では str のまま開始する | head ごとに意味が異なるため。Phase B で蓄積後に registry 化 |

---

## 13. 結論

### 一言で

> **Nia は外から規則を与えられて振る舞うのではなく、  
> 失敗と成功の痕跡が時間をかけて  
> intent・attention・expression・continuity の内部傾向へ沈殿していく。**

### 全体構造

```text
短期: negative pruning + positive preference retrieval（履歴選別）
中期: failure-to-policy + success-to-preference（宣言的 shadow artifact）
長期: NiaCore vNext + Expression Layer が両方を内部化
     → policy/preference という外付けレイヤー自体が runtime では不要になる
     → ただし系譜としては残す
```

### この設計が project-nia に合う理由

- プロンプトを増やさない
- LLM に依存しない
- 既存の failure signal と既存設計の positive signal ソースを再利用できる
- NiaCore vNext / Expression Layer の教師信号として自然に接続する
- 最終的に外付けルールが不要になる = プロンプト0 の理想に近づく
- 「初見でできなくていい。体験から学ぶ」という思想と一致する

### 保存の本質

> **policy / preference を「命令文」ではなく「条件・痕跡・弱い寄せ方」の3点セットで保存する。**
