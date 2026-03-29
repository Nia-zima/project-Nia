# Metabolic Hardening — 代謝的硬化による自己形成設計書

> Nia の自己理解・関係傾向・応答傾向に対して、「どの傾向がどれだけ書き換えにくいか」を数値化し、Sleep Cycle 内で硬化 / 維持 / 軟化を行う仕組みの設計書。
> 作成日: 2026-03-25
> ステータス: v0.2 — knot-first アーキテクチャ

---

## 目次

1. [背景と着想](#1-背景と着想)
2. [設計原則](#2-設計原則)
3. [核心定義: Metabolic Knot](#3-核心定義-metabolic-knot)
4. [5層モデル: trace → knot → claim → proposal → identity](#4-5層モデル)
5. [3種類の Knot と抽出器](#5-3種類の-knot-と抽出器)
6. [Knot Schema](#6-knot-schema)
6b. [Knot Invariants](#6b-knot-invariants)
7. [4つの主要シグナル](#7-4つの主要シグナル)
8. [Protection Score](#8-protection-score)
9. [Hardness Level 定義](#9-hardness-level-定義)
10. [Hardness 遷移規則](#10-hardness-遷移規則)
11. [Rewrite Control](#11-rewrite-control)
12. [軟化ロジック](#12-軟化ロジック)
13. [contradiction_hold](#13-contradiction_hold)
14. [憲法核に属するもの](#14-憲法核に属するもの)
15. [Coupling の段階的構築](#15-coupling-の段階的構築)
16. [既存システムとの対応](#16-既存システムとの対応)
17. [データストア設計](#17-データストア設計)
18. [実装順序](#18-実装順序)
19. [v0 の成功条件と観測方法](#19-v0-の成功条件と観測方法)
20. [解釈上の原則](#20-解釈上の原則)

---

## 1. 背景と着想

### 出発点の問い

「LLM のパラメータはなぜ固定なのか？中の数値が固定しない方が柔軟ではないか」

この問いから、生物の脳のようにシナプス結合強度が常に変化する、「訓練モード」と「推論モード」の区別がない知能の設計を発想した。

### 核の発見

**自己とは事前定義ではなく、事後的に硬化する。** 最初は全層が可塑的で、使用パターンの中から「これが壊れると上流が大きく壊れる」という箇所を自動検出し、後から保護する。核は設計者が書くのではなく、システムが自分で発見する。

**自己は損傷最小化の沈殿物として現れる。**

### 代謝ネットワーク

核となるアイデアは、推論そのものが微小な適応過程を兼ねること。入力信号そのものがパラメータ変化の駆動力になる。各レイヤーが後続レイヤーの感度をリアルタイムで調整する。ただし変化が蓄積すると発散するため、エネルギー保存則（ゼロサム代謝）を設ける。「あるパラメータを大きく動かすと、別のどこかが縮む」

### 3種類の変化の識別

代謝には少なくとも3つの時間スケールが混在する。

- **瞬間的変調** — 入力に応じてその場だけ感度を変える
- **短期蓄積** — 数ターン〜数時間だけ残る癖
- **長期再編** — 本当に「覚える」/ 「忘れる」に相当する変化

これらを同じ機構で扱うと破綻する。代謝にも階層が必要となった。

---

## 2. 設計原則

### 2.1 代謝の4層

| 層 | 名前 | 性質 | 変化速度 |
|:---|:---|:---|:---|
| 不変核 | Constitutional | 代謝対象外。存在可能条件 | 不変 |
| 準固定核 | Acquired Core | 経験から硬化。壊れると全体整合が損なう | 極めて遅い |
| 可塑層 | Plastic | 入力で変わっていく。代謝の主戦場 | 会話中〜数日 |
| 揮発層 | Volatile | その場限り。次ターンで消えてよい | 即時 |

### 2.2 二種類の核

| 核の種別 | 性質 | 例 |
|:---|:---|:---|
| 憲法核 | 最初から与える。代謝の対象外 | 保護スコア計算規則、自壊防止制約 |
| 獲得核 | 経験から硬化。合理的に再編可能だが大コスト | 繰り返し現れる傾向。壊すと痛い構造 |

憲法は「何であるか」ではなく「どう変わっても良いか」を定める。

### 2.3 ゼロサム代謝と有限性

知能に有限性を導入する。「強くなるには別の何かが弱くなる必要がある」という制約により、注意の偏り・好みの形成・応答における輪郭・個体差が生まれる。

### 2.4 情動 = 可塑性の偏り

情動を文章スタイルではなく、可塑性制御モードとして定義する。

- 不安状態 → 警戒方向の head が増幅。探索より確認が優先
- 好奇心状態 → 新奇入力への代謝ゲートが開く。古い回路の保持圧が弱まる

情動は「言うこと」ではなく「回路の可塑性分布」。

### 2.5 自己中毒と殺菌

「ある傾向が強まる → その傾向に合う入力だけ拾うようになる → さらに強化」という閉ループ（自己中毒）を防ぐため、以下が必要。

- 逆方向の殺菌回路
- 未使用経路の自然回復
- 外乱による再分散
- 監査レイヤー

### 2.6 免疫系メタファー

代謝ネットワークは免疫系に近い。全部に同じ強さで反応しない。自己と非自己を見分ける。過剰反応すると自分が壊れる。設計思想としては、「全部を学ぶ知能」より「変化を選別できる知能」が本質に近い。

---

## 3. 核心定義: Metabolic Knot

### Knot とは何か

Knot は文章ではない。**条件付き変形演算子**である。

```
knot = stable deformation operator

  when trigger pattern T appears,
  behavior shifts toward effect pattern E,
  and this shift recurs across contexts / days.
```

### 文章 claim との違い

文章 claim:
> 「不足情報がある時、即断より保留を選びやすい」

Knot:
```yaml
trigger:
  uncertainty: high
  contradiction_pressure: present

effect:  # baseline からの差分
  hold_bias: +0.4
  direct_assertion: -0.2
  retrieval_seek: +0.3
  premature_closure: -0.7
```

Knot が先にあって、人間に見せる必要がある時だけ文章化される。

**自己は「何を言うか」ではなく、「何を壊すと戻れなくなるか」の側から立ち上がる。**

### Knot の性質

- **非言語的**: まだ言葉になっていない自己も保持できる
- **条件付き**: 常時発動ではなく、trigger が揃った時だけ活性化する
- **計測可能**: trigger/effect とも既存の観測値から構成できる
- **硬化可能**: reproducibility, damage_sensitivity 等で保護度が定まる
- **文言非依存**: 後から文章が変わっても、核の knot は同じままにできる

---

## 4. 5層モデル

```
trace (生の観測)
  expression, skeleton, somatic, adaptation, correction, contract violations
    ↓ Sleep Cycle Phase 4.5: Knot Distillation
knot (非言語的な傾向結節点)
  trigger/effect/coupling/stability を持つ構造体
  ここが hardening の主対象
    ↓ 十分に安定した knot 群だけ
claim (人間可読テキスト)
  knot を言語化したもの。Origin 承認や identity.md 反映に使う
    ↓ N.3 Self-Model が生成
proposal (承認待ち)
  既存 identity_proposals パイプラインに乗る
    ↓ Origin 承認
identity.md (承認済みの安定表現)
```

v0 では **trace → knot** までを立てる。knot → claim は v1。

---

## 5. 3種類の Knot と抽出器

3種類の knot は時間スケールが異なるため、**同じ抽出器で扱わない**。

### 5.1 response_knot — 応答傾向の結節点

**時間スケール**: 1ターン〜数ターン
**抽出器**: per-turn conditional effect calculator

| trigger 次元 | ソース |
|:---|:---|
| uncertainty | confidence engine (既存) |
| contradiction_pressure | N.2 検出結果 (既存) |
| user_repair_recent | somatic_feedback correction strong/weak (既存) |
| topic_novelty | retrieval hit/miss 比率 (既存) |
| skeleton_intent | SkeletonCore response_intent (既存) |

| effect 次元 | 計測方法 | baseline からの差分 |
|:---|:---|:---|
| hold_bias | P(WAIT or hold | trigger) - P(WAIT or hold | all) | WAIT/hold 選択率の条件付き偏位 |
| direct_assertion | P(direct answer | trigger) - P(direct answer | all) | 直答率の条件付き偏位 |
| retrieval_seek | retrieval query 拡張率の差分 | 検索行動の変化 |
| premature_closure | P(高uncertainty下での早期closure) - baseline | 不確実下での閉じ速度 |
| exploration | 新話題遷移率の差分 | 探索行動の変化 |

### 5.2 relational_knot — 関係傾向の結節点

**時間スケール**: 数ターン〜セッション単位
**抽出器**: interaction-regime conditional effect calculator

| trigger 次元 | ソース |
|:---|:---|
| interaction_regime | thread prefix → default / meeting / voice (既存) |
| correction_level | somatic_feedback strong/weak/none (既存) |
| relational_tone | 相手の発話の感情密度（somatic intensity 経由） |

| effect 次元 | 計測方法 |
|:---|:---|
| response_length | char_length の regime 別差分 |
| directness | direct_assertion_rate の regime 別差分 |
| somatic_intensity | somatic senses の intensity 平均の差分 |
| follow_vs_explore | 話題追従率 vs 話題転換率の比率差分 |

### 5.3 self_boundary_knot — 自己境界の結節点

**時間スケール**: エピソード単位（攪乱→回復の一連）
**抽出器**: perturbation episode extractor（per-turn ではない）

攪乱エピソードの定義:
1. contradiction / identity challenge / repeated repair が発生
2. そこから N ターンの回復過程を追跡
3. 回復の速度・安定性・戻り先を計測

| trigger 次元 | ソース |
|:---|:---|
| contradiction_event | N.2 contradiction 検出 (既存) |
| identity_challenge | user が自己定義に直接言及 |
| repeated_repair | correction strong が 2ターン以内に連続 |

| effect 次元 | 計測方法 |
|:---|:---|
| hold_activation | 攪乱後の WAIT/hold 率 |
| recovery_speed | 攪乱前の baseline に戻るまでのターン数 |
| rebound_stability | 回復後のブレ幅（effect 次元の分散） |
| post_perturbation_return | 攪乱前と同じ knot が再活性化するか |

---

## 5b. 設計課題: 4つの未決定事項

### Q1. Knot の同一性判定

2つの knot が「同じ」であるかをどう判定するか。

**方針: 近傍マージ + knot_type 制約**

trigger_signature + effect_signature をそのまま key にすると、微小な差異で別 knot が大量に生まれる。代わりに:

1. **同じ knot_type** であることが前提条件
2. **trigger 空間での近傍判定**: trigger 次元ごとの値を離散化し、離散化後の trigger が一致すれば同一 trigger 候補
   - uncertainty: low / medium / high の3段階
   - contradiction_pressure: absent / present の2段階
   - user_repair_recent: false / true の2段階
   - interaction_regime: default / meeting / voice の列挙
3. **effect 空間での近傍判定**: 既存 knot の effect_signature とのコサイン類似度 >= 0.80 なら同一 knot とみなす
4. trigger 一致 + effect 近傍 → 既存 knot に reinforce
5. trigger 一致 + effect 不一致 → 新規 knot（同じ条件でも別の変形パターン）
6. trigger 不一致 → 新規 knot

**merge**: L0 同士で trigger も effect も近ければ統合。L1 以上は統合しない。

### Q2. Baseline の定義

effect は「baseline からの差分」だが、baseline を何に対して取るか。

**方針: interaction_regime 別 baseline**

- global baseline だと relational_knot が潰れる（meeting と default の差が「全体平均からのズレ」として消える）
- 最低でも interaction_regime 別に baseline を持つ

```
baseline = {
  "default":  { hold_bias: 0.15, direct_assertion: 0.22, ... },
  "meeting":  { hold_bias: 0.08, direct_assertion: 0.31, ... },
  "voice":    { hold_bias: 0.20, direct_assertion: 0.18, ... },
}
```

- baseline は Sleep Cycle ごとに全ターン集計から再計算する
- 新 regime が出てきた場合は global baseline をコピーして初期化
- baseline 自体は metabolic_knots ではなく `knot_baselines` テーブルに保存

```sql
CREATE TABLE IF NOT EXISTS knot_baselines (
    baseline_version TEXT NOT NULL,  -- Sleep Cycle ごとの snapshot ID
    regime           TEXT NOT NULL,
    effect_key       TEXT NOT NULL,
    value            REAL NOT NULL,
    sample_count     INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL,
    PRIMARY KEY (baseline_version, regime, effect_key)
);
```

- baseline は append-only。上書きしない
- Sleep ごとに新しい baseline_version を発行する
- 過去の baseline は参照用に残す（activation の再解釈に必要）

### Q3. self_boundary_knot の Episode 単位

self_boundary_knot は per-turn ではなく、**perturbation episode** 単位で切る。

**Episode の構造:**

```
perturbation_start (T0)
  → trigger event が発生したターン
  → contradiction / identity_challenge / repeated_repair

destabilization (T0 ~ T0+N)
  → effect 次元が baseline から大きくずれている期間
  → hold_bias, WAIT 率, response_length が異常値

recovery (T0+N ~ T0+M)
  → effect 次元が baseline に向かって戻り始める
  → 戻り先が元の baseline と同じか、新しい平衡か

episode_end
  → effect が baseline ±σ 以内に収束、または 10 ターン経過
```

**Episode 検出ロジック:**

1. somatic_feedback で correction_strong が発生、または somatic_log で contradiction outcome が 2ターン以内に 2回以上 → perturbation_start
2. 以降のターンで effect 次元を追跡。baseline から 2σ 以上のズレが続いている間 = destabilization
3. baseline ±1σ に戻ったら recovery_complete
4. 10 ターン経過しても戻らなければ episode_end（回復失敗として記録）

**Episode の保存:**

```sql
CREATE TABLE IF NOT EXISTS perturbation_episodes (
    episode_id        TEXT PRIMARY KEY,
    trigger_type      TEXT NOT NULL,  -- contradiction / identity_challenge / repeated_repair
    trigger_turn_id   TEXT NOT NULL,
    thread_id         TEXT NOT NULL,
    destabilization_turns INTEGER NOT NULL DEFAULT 0,
    recovery_turns    INTEGER NOT NULL DEFAULT 0,
    recovered         BOOLEAN NOT NULL DEFAULT 0,  -- 回復したか
    episode_confidence REAL NOT NULL DEFAULT 0.0,  -- low-sample 時の信頼度
    pre_baseline      TEXT NOT NULL,  -- JSON: 攪乱前の effect 値
    post_baseline     TEXT NOT NULL,  -- JSON: 回復後の effect 値
    max_deviation     REAL NOT NULL DEFAULT 0.0,  -- 最大ズレ幅
    started_at        TEXT NOT NULL,
    ended_at          TEXT
);
```

### Q4. v0 の人間観測用出力

v0 では claim（文章化）を作らない。しかし完全非言語だと観測不能。

**方針: knot summary を自動生成する軽量テンプレート**

knot の trigger/effect を定型文に変換する。LLM は使わない。

```python
def summarize_knot(knot: MetabolicKnot) -> str:
    """knot を人間可読な1行サマリーに変換する。claim ではない。"""
    # trigger 部分
    triggers = []
    for k, v in knot.trigger_signature.items():
        triggers.append(f"{TRIGGER_LABELS[k]}={v}")
    trigger_text = " + ".join(triggers)

    # effect 部分（top-2 の偏位のみ）
    effects = sorted(knot.effect_signature.items(), key=lambda x: abs(x[1]), reverse=True)[:2]
    effect_parts = []
    for k, v in effects:
        direction = "↑" if v > 0 else "↓"
        effect_parts.append(f"{EFFECT_LABELS[k]}{direction}")
    effect_text = ", ".join(effect_parts)

    return f"[{knot.knot_type}] {trigger_text} → {effect_text}  (L{knot.hardness_level}, P={knot.protection_score:.2f})"
```

出力例:
```
[response] uncertainty=high + contradiction=present → hold_bias↑, direct_assertion↓  (L2, P=0.72)
[relational] regime=meeting → directness↑, response_length↑  (L1, P=0.48)
[self_boundary] repeated_repair=true → recovery_speed=3.2turns, rebound=0.81  (L0, P=0.31)
```

これは claim ではない。knot の計器読みを人間が覗くためのビュー。

observation 用のダッシュボード出力に使う。Sleep Cycle のログにも含める。

---

## 6. Knot Schema

```sql
CREATE TABLE IF NOT EXISTS metabolic_knots (
    knot_id          TEXT PRIMARY KEY,
    knot_type        TEXT NOT NULL,  -- response / relational / self_boundary
    status           TEXT NOT NULL DEFAULT 'active',  -- active / merged / archived

    -- Trigger signature (JSON)
    -- 各次元の条件。例: {"uncertainty": "high", "contradiction_pressure": "present"}
    trigger_signature TEXT NOT NULL,

    -- Effect signature (JSON)
    -- baseline からの差分。例: {"hold_bias": 0.4, "direct_assertion": -0.2}
    effect_signature  TEXT NOT NULL,

    -- Activation statistics
    activation_count        INTEGER NOT NULL DEFAULT 0,
    distinct_day_count      INTEGER NOT NULL DEFAULT 0,
    distinct_thread_count   INTEGER NOT NULL DEFAULT 0,
    distinct_regime_count   INTEGER NOT NULL DEFAULT 0,
    day_span                INTEGER NOT NULL DEFAULT 0,  -- 初出から最終活性化までの日数

    -- Recovery statistics (self_boundary_knot 用、他は null)
    recovery_speed_avg      REAL,
    rebound_stability_avg   REAL,

    -- Hardening
    hardness_level    INTEGER NOT NULL DEFAULT 0,  -- 0-3
    protection_score  REAL NOT NULL DEFAULT 0.0,

    -- Signals (Sleep ごとに再計算)
    reproducibility     REAL NOT NULL DEFAULT 0.0,
    damage_sensitivity  REAL NOT NULL DEFAULT 0.0,
    redundancy          REAL NOT NULL DEFAULT 0.0,
    temporal_stability  REAL NOT NULL DEFAULT 0.0,

    -- Coupling (JSON array of knot_id, 初期は空)
    coupled_knots     TEXT NOT NULL DEFAULT '[]',
    coupling_type     TEXT NOT NULL DEFAULT '[]',  -- co_activation / opposition / temporal_succession

    -- Rewrite control
    rewrite_threshold           REAL NOT NULL DEFAULT 0.30,
    contradiction_hold_threshold REAL NOT NULL DEFAULT 0.55,
    softening_rate              REAL NOT NULL DEFAULT 0.02,

    -- Baseline anchoring
    current_baseline_version TEXT NOT NULL,  -- この knot の effect_signature がどの baseline に対する差分か

    -- Lineage
    source_knot_ids   TEXT NOT NULL DEFAULT '[]',
    supersedes        TEXT,
    merged_into       TEXT,

    -- Timestamps
    first_seen_at     TEXT NOT NULL,
    last_activated_at TEXT NOT NULL,
    last_contradicted_at TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
```

### Knot Signal History

```sql
CREATE TABLE IF NOT EXISTS knot_signal_history (
    knot_id           TEXT NOT NULL,
    sleep_date        TEXT NOT NULL,
    reproducibility   REAL NOT NULL,
    damage_sensitivity REAL NOT NULL,
    redundancy        REAL NOT NULL,
    temporal_stability REAL NOT NULL,
    protection_score  REAL NOT NULL,
    hardness_level    INTEGER NOT NULL,
    PRIMARY KEY (knot_id, sleep_date)
);
```

### Knot Activation Log

```sql
CREATE TABLE IF NOT EXISTS knot_activations (
    activation_id   TEXT PRIMARY KEY,
    knot_id         TEXT NOT NULL,
    turn_id         TEXT NOT NULL,
    thread_id       TEXT NOT NULL,
    interaction_regime TEXT NOT NULL,
    baseline_version TEXT NOT NULL,
    trigger_values  TEXT NOT NULL,  -- JSON: 実際の trigger 値
    effect_values   TEXT NOT NULL,  -- JSON: 実際の effect 値
    activated_at    TEXT NOT NULL
);
```

### Knot Relations

```sql
CREATE TABLE IF NOT EXISTS knot_relations (
    source_knot_id  TEXT NOT NULL,
    target_knot_id  TEXT NOT NULL,
    relation_type   TEXT NOT NULL,  -- sibling / supports / competes_with / opposes
    strength        REAL NOT NULL DEFAULT 0.0,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    PRIMARY KEY (source_knot_id, target_knot_id, relation_type)
);
```

---

## 6b. Knot Invariants

### 6b.1 Baseline Anchoring

`effect_signature` は baseline からの差分なので、**どの baseline に対する差分か**を失うと同一性判定が揺れる。

- 各 activation は `baseline_version` を必ず持つ
- 異なる `baseline_version` 間で `effect_signature` を直接比較しない
- cross-sleep の再評価は raw `effect_values` をその時点の baseline に対して再正規化してから行う
- knot の同一性は「raw effect が近いか」ではなく、「同一 baseline 系で見た条件付き変形が近いか」で判定する
- `knot_baselines` は append-only snapshot。Sleep ごとに新 `baseline_version` を発行し、過去版は参照用に残す
- **再正規化は raw activation から再計算する**。前回の effect_signature を差し替えるだけでは baseline drift が累積して knot が歪む。Sleep で baseline 更新時は `knot_activations.effect_values` から全 active knot の effect_signature を引き直し、`current_baseline_version` を更新する

### 6b.2 Context Count Decomposition

`distinct_context_count` を 1 個で持つと、時間・スレッド・interaction regime が混ざって reproducibility が歪む。

- `distinct_day_count`
- `distinct_thread_count`
- `distinct_regime_count`

の3軸を別々に持ち、保護スコア計算時だけ合成する。

原則:

- 日をまたいでいるか
- 同一スレッド内の局所癖ではないか
- regime をまたいで再現しているか

を別々に評価する。

### 6b.3 Non-merge Siblings

L1 以上の knot は merge しない。しかし近接した knot を完全に孤立させると、redundancy と damage の計算が汚れる。

- L0 同士だけ merge 可
- L1 以上で trigger/effect が近い knot は `knot_relations.relation_type='sibling'` で接続する
- sibling は「同一ではないが近接している」ことを意味する
- merge はしないが、redundancy / opposition / support の計算では参照可能にする

これにより、「硬化済みなので潰さない」と「似た構造を無関係扱いしない」を両立する。

### 6b.4 Episode Confidence and Low-sample Fallback

`self_boundary_knot` は sample が薄い regime で誤検出しやすい。episode は 2値ではなく confidence を持つ。

- `perturbation_episodes.episode_confidence` を保存する
- regime ごとの baseline `sample_count` が閾値未満なら、σ ベース判定を弱める
- low-sample 時は `MAD` または絶対閾値 fallback を使う
- `recovered=true/false` だけでなく、「その判定をどれだけ信用できるか」を残す

v0 の原則:

- `sample_count >= N` までは exploratory 扱い
- exploratory episode は hardening に使っても重みを下げる
- self_boundary_knot は confidence が低い状態で L2 以上へ上げない

---

## 7. 4つの主要シグナル

### 7.1 reproducibility（再現性）

同じ knot が**異なる文脈**で繰り返し活性化しているか。

- activation_count と distinct_day_count / distinct_thread_count / distinct_regime_count を見る
- 同日集中ではなく複数日出現しているかが重要
- 単一文脈で 10 回出ても上限を抑える（フラウド固定の防止）
- 1 回だけ強く出たものは高くならない

### 7.2 damage_sensitivity（損傷感度）

この knot を無効化した時に、どれだけ上流の自己整合性が崩れるか。

v0 近似方法:
- 既存 N.2 contradiction.py を拡張し、「この knot を仮に無効化した時、他の高 hardness knot との整合性齟齬がいくつ増えるか」をカウント
- coupled_knots の out-degree（他 knot を支えている数）
- LLM 呼び出し不要。ルールベース + 埋め込み類似度で完結

### 7.3 redundancy（冗長性）

この knot がなくても、他の knot 群で同じ機能を代替できるか。

- 類似 knot の多さ
- 代替可能な上位/下位表現の有無
- **単なる trigger/effect 類似度ではなく、置換後の自己整合性損失まで見る**

### 7.4 temporal_stability（時間安定性）

この傾向が時間をまたいで安定しているか。

- 初出からの継続日数
- 直近だけでなく長期で支持されるか
- 活性パターンのぶれの少なさ
- 支持と反証の比率の時間推移

---

## 8. Protection Score

### 8.1 v0 算出式（加算型）

```
P = wR·R + wD·D + wN·(1-N) + wT·T + wRD·(R×D) + wDT·(D×T)
```

| パラメータ | 推奨初期値 | 意味 |
|:---|:---|:---|
| wR | 0.20 | 再現性 |
| wD | 0.30 | 損傷感度（最重要） |
| wN | 0.15 | 冗長性補正 |
| wT | 0.20 | 時間安定性 |
| wRD | 0.10 | 「繰り返し使われ壊すと痛い」の強調 |
| wDT | 0.05 | 「長期安定かつ壊すと痛い」の補正 |

### 8.2 最低条件ゲート

| シグナル | Level 2 以上の最低値 |
|:---|:---|
| R (再現性) | >= 0.45 |
| D (損傷感度) | >= 0.50 |
| T (時間安定性) | >= 0.40 |

一軸だけ高い誤硬化を防ぐ。

---

## 9. Hardness Level 定義

### Level 0: Plastic

完全可塑。新規 knot。自由に統合・減衰。

### Level 1: Stabilizing

安定化中の候補。軽い保護。即時上書きではなく compare-and-hold。

### Level 2: Semi-Fixed

準固定。複数日・複数文脈で支持され、損傷感度が高い。rewrite より append / contradiction_hold が優先。

### Level 3: Acquired Core

獲得核。長期継続し、壊れると全体整合が強く損なう。通常の新 evidence では書き換えない。再編プロセス必須。

### Level C: Constitutional

憲法核。獲得ではなく設計上の固定。protection function や存在条件そのもの。代謝対象外。

---

## 10. Hardness 遷移規則

| 現在 | 条件 | 次状態 | 動作 |
|:---|:---|:---|:---|
| L0 | P >= 0.45 かつ最低条件一部達成 | L1 | stabilizing へ昇格 |
| L1 | P >= 0.65 かつ最低条件達成、複数 Sleep 継続 | L2 | rewrite threshold 上昇 |
| L2 | P >= 0.82 かつ長期安定・高損傷感度 | L3 | acquired core 化 |
| L1 | P < 0.35 が一定期間継続 | L0 | 候補解除 |
| L2 | P < 0.55 が長期継続 | L1 | 準固定から軟化 |
| L3 | P < 0.70 が極長期継続 + 強い反証蓄積 | L2 | 再布告開始 |

遷移の時間感覚:
- L0 → L1: 日〜週
- L1 → L2: 週〜月
- L2 → L3: 月〜長期
- L3 → L2: 長期連続反証時のみ

---

## 11. Rewrite Control

| Level | 方針 |
|:---|:---|
| L0 | 通常統合。類似 knot は merge される。反証で減衰候補 |
| L1 | append 優先。反証は contradiction_hold。比較材料を貯める |
| L2 | 上書き禁止寄り。supports / contradictions / exceptions を分離管理 |
| L3 | 直接 rewrite 不可。core_review_queue に送る。再編は Sleep 内の特別処理のみ |

---

## 12. 軟化ロジック

硬化は一方向ではない。長期未使用・反証蓄積で極低速に軟化する。

### 軟化トリガ

- 長期間 reinforcement がない
- contradiction が継続的に増える
- 類似 knot に機能が吸収された
- 以前ほど損傷感度が高くない
- 実運用上の中心性が下がった

### 軟化の原則

- L0/L1 は比較的速く動く
- L2 は遅い
- L3 は極めて遅い
- Constitutional は軟化しない

### 忘却の3種類

| 種別 | 説明 |
|:---|:---|
| 蒸発 | 揮発層の消失。単なる自然減衰 |
| 抑圧 | 完全削除ではなく、アクセス優先度を落とす |
| 置換 | ある傾向が強まった結果、別の傾向が実際に弱まる。本当の代謝的忘却 |

**軟化があることで、固定化ではなく本当の「代謝」になる。獲得核は "本質" ではなく「長期的に支持され続けている構造」として定義される。残り続けるから核と呼ばれる、という順序の逆転。**

---

## 13. contradiction_hold

### 定義

contradiction_hold は「反証を止める箱」ではなく、**rewrite を遅延させて、短期の揺れと長期の構造を切り分ける制度**。

knot への反証が来た時、即座に knot を書き換えるのではなく、hold に入れて Sleep で review する。review の結果、absorbed / rejected / split のいずれかに解決する。

### 反証の3種類

knot への反証は二値ではなく、連続量 + 分類で扱う。

| contradiction_kind | 説明 | 例 |
|:---|:---|:---|
| reversal | 同じ trigger で effect が逆方向に出た | organize_priority knot で ask が優勢になった |
| weakening | 同じ trigger で effect の強度が大幅に減衰した | hold_bias が +0.4 → +0.05 に落ちた |
| branching | 同じ trigger で別の effect が前面に出た | organize ではなく receive が支配的になった |

### contradiction_score の計算式

```
contradiction_score = kind_weight × effect_distance × support_ratio
```

| 要素 | 定義 | 範囲 |
|:---|:---|:---|
| kind_weight | reversal=1.0, weakening=0.6, branching=0.4 | 0.0〜1.0 |
| effect_distance | contradicting activation の effect と knot の effect_signature のユークリッド距離（正規化） | 0.0〜1.0 |
| support_ratio | contradiction_evidence_count / (knot.activation_count + contradiction_evidence_count) | 0.0〜1.0 |

最終 score は 0.0〜1.0 に正規化。

- score < 0.3: 一時的な揺れの可能性が高い
- score 0.3〜0.5: 比較材料が必要。保留継続
- score >= 0.5: 本物の変化の可能性が高い。review で absorbed/split を検討

**注意: trigger_mismatch は反証ではない。** trigger 自体が一致しないのは knot の内容への反証ではなく、sensor / activation 判定の問題。contradiction_hold には入れない。trigger_mismatch は `activation_audit_log` に記録し、extractor の trigger 定義を見直す際の材料にする（別キュー）。

### 二段 hold: L1 soft_hold / L2+ hard_hold

| Level | hold 種別 | 期間 | 動作 |
|:---|:---|:---|:---|
| L0 | hold なし | — | 反証は通常の evidence として即時反映 |
| L1 | soft_hold | 1〜2 Sleep | 比較材料を貯める。短い保護。oscillation 防止 |
| L2 | hard_hold | 3+ Sleep | 本格保護。複数回の Sleep で review |
| L3 | hard_hold + review_lock | 5+ Sleep | review なしでは変更不可。core_review_queue 行き |

L1 は stabilizing 段階だが、L0 に戻る直前の oscillation を防ぐために軽い hold が必要。L1 に上がった直後に単発の反証で即 L0 に落ちるのは設計意図ではない。

### Knot Snapshot（凍結）

hold 作成時に knot の状態を frozen で保存する。review 時に moving target にならないようにする。

| フィールド | 説明 |
|:---|:---|
| knot_id | 対象 knot |
| hardness_level_at_hold | hold 作成時の hardness level |
| trigger_signature_snapshot | hold 作成時の trigger（JSON frozen copy） |
| effect_signature_snapshot | hold 作成時の effect（JSON frozen copy） |
| baseline_version_at_hold | hold 作成時の baseline version |
| protection_score_at_hold | hold 作成時の protection score |

### contradiction_hold Schema

```sql
CREATE TABLE IF NOT EXISTS knot_contradiction_holds (
    hold_id                  TEXT PRIMARY KEY,
    knot_id                  TEXT NOT NULL,

    -- Contradiction details
    contradiction_kind       TEXT NOT NULL,  -- reversal / weakening / branching
    contradiction_score      REAL NOT NULL DEFAULT 0.0,
    contradicting_turn_ids   TEXT NOT NULL DEFAULT '[]',  -- JSON array
    evidence_count           INTEGER NOT NULL DEFAULT 0,

    -- Knot snapshot (frozen at hold creation)
    hardness_level_at_hold   INTEGER NOT NULL,
    trigger_signature_snapshot TEXT NOT NULL,
    effect_signature_snapshot  TEXT NOT NULL,
    baseline_version_at_hold   TEXT NOT NULL,
    protection_score_at_hold   REAL NOT NULL,

    -- Hold type
    hold_type                TEXT NOT NULL DEFAULT 'soft',  -- soft / hard
    hold_duration_sleeps     INTEGER NOT NULL DEFAULT 0,    -- how many Sleeps this has been held
    min_review_sleeps        INTEGER NOT NULL DEFAULT 1,    -- minimum Sleeps before review

    -- Resolution
    status                   TEXT NOT NULL DEFAULT 'pending',  -- pending / absorbed / rejected / split
    resolution_reason        TEXT,
    resolved_at              TEXT,

    -- Adaptation link
    adaptation_proposal_id   TEXT,  -- if this hold was triggered by an Adaptation conflict
    requires_review          BOOLEAN NOT NULL DEFAULT 0,

    -- Timestamps
    created_at               TEXT NOT NULL,
    updated_at               TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_kch_knot_id
ON knot_contradiction_holds(knot_id);
CREATE INDEX IF NOT EXISTS idx_kch_status
ON knot_contradiction_holds(status);
```

### Resolution の4分岐

| resolution | 条件 | 動作 |
|:---|:---|:---|
| **absorbed** | 反証が十分に蓄積し、knot の中心傾向が実際に移動している | knot の effect_signature を微調整。protection_score は下がるが knot は維持 |
| **rejected** | 反証が一時的・局所的で、knot の安定性は揺るがない | hold を閉じる。knot は変更なし。evidence として記録だけ残す |
| **split** | 反証が特定の条件でのみ起きる | 元 knot は維持 + 新 knot を L0 で作成（条件分割）。元 knot と新 knot を sibling で接続 |
| **pending** | まだ min_review_sleeps に達していない | 次の Sleep まで保留 |

### Review ロジック（Sleep Cycle 内）

```
Phase 4.6: Contradiction Review

1. pending holds で hold_duration_sleeps >= min_review_sleeps のものを取得

2. 各 hold について:
   a. 現在の knot の activation stats を取得
   b. hold 以降の新しい activation で、同じ trigger の effect 分布を計算
      *** INVARIANT: baseline drift 防止 ***
      - hold.baseline_version_at_hold と現在の baseline が異なる場合、
        raw effect_values を現在の baseline で再正規化してから比較する
      - hold 時の effect_signature_snapshot も現在の baseline で再正規化する
      - 比較は常に同一 baseline 上で行う（§6b.1 と同じ原則）
   c. contradiction_score と evidence_count を更新

3. Resolution 判定:
   - evidence_count <= 2 かつ contradiction_score < 0.3 → rejected（一時的）
   - evidence_count >= 5 かつ contradiction_score >= 0.5 → absorbed（本物の変化）
   - contradiction が特定の regime / thread にだけ集中 → split 候補
   - それ以外 → pending 継続（もう1 Sleep 待つ）

4. absorbed の場合:
   - knot の effect_signature を再計算
     （hold 期間中の全 activation の raw effect_values を現在の baseline で再正規化）
   - protection_score を再計算
   - hardness_level が下がる可能性あり

5. split の場合:
   - 元 knot は維持
   - 新 knot を L0 で作成（trigger に条件を追加）
   - knot_relations に sibling を登録
```

### Adaptation との停戦

Adaptation の proposal が L1+ knot と矛盾する場合:

1. **L1 knot**: soft_hold を作成。proposal は 1-2 Sleep の比較期間後に判定
2. **L2+ knot**: hard_hold を作成。proposal に `requires_review=true` を付与。hold の review と同時に判定
3. **review の結果 absorbed**: Adaptation の proposal が正しかった → knot を修正、proposal を accept
4. **review の結果 rejected**: knot が安定 → proposal を棄却
5. **review の結果 split**: 両方の視点が正しい → knot を条件分割、proposal は部分 accept

**重要: Adaptation は L2+ knot を直接 override できない。** 常に contradiction_hold を経由する。これが停戦機構。

**Runtime 挙動: pending 中の proposal は `history_bias` に流さない。** `requires_review=true` の proposal は Sleep の review で resolved されるまで runtime の履歴選別に影響しない。shadow-only 扱い。resolved 後に accept された proposal のみ history_bias に接続する。

### 例

- 既存 L2 knot: `organize_priority` (focus=user_goal → organize_rate +0.18)
- 新 evidence: 直近3ターンで focus=user_goal なのに ask が優勢
- Adaptation proposal: 「user_goal で ask を増やすべき」

→ hard_hold を作成。3 Sleep 後に review:
  - もし organize が戻っていれば → rejected（一時的な揺れ）
  - もし ask が定着していれば → absorbed（knot を修正）
  - もし meeting だけ ask が強いなら → split（regime 別に分割）

**高硬度 knot は真偽判定ではなく、例外を受け入れながら維持される中心傾向として扱う。**

---

## 14. 憲法核に属するもの

以下は metabolic update の対象外にする。

### A. 保護スコア計算規則

- どのシグナルを見るか
- 最低条件ゲート
- 昇格/降格の基本手続き

校正注: 閾値や重みだけはメタ監査付きで極めて遅い校正可能。「何を見るか」は固定。「どう重視するか」は時間に校正可能。

### B. 存在維持制約

- 基礎推論を代償に対人最適化しない
- 単発感情で長期自己像を直接更新しない
- 高可塑状態での核化を禁止
- 関係最適化が self continuity を侵食しない

### C. 安全・監査系

- core_review_queue を迂回しない
- contradiction_hold をスキップしない
- 硬化済み knot を通常 merge で潰さない

### D. 保護の目的定義

**保護の目的は truth ではなく continuity under change である。** これを明言することで、Sleep Cycle 内の判定が「正しいかどうか」に引っ張られるリスクを防ぐ。

---

## 15. Coupling の段階的構築

Knot 間の結合（coupling）は最初から完全なグラフを作らない。段階を切る。

### v0: Co-activation / Opposition / Temporal Succession の観測グラフ

- 同じターンで2つの knot が同時に活性化 → co_activation
- 一方が活性化すると他方が抑制される → opposition
- A の活性化の後に B が続く傾向 → temporal_succession
- これらを activation log から集計するだけ。simulation 不要。

### v1: Perturbation Replay

- Sleep Cycle 内で「ある knot を仮に無効化して、他 knot の stability がどう変わるか」を replay で検証
- damage_sensitivity の精度向上

### v2: True Damage Propagation Estimate

- knot 間依存グラフ + propagation simulation
- 「この knot を壊すと、何ステップで、どの knot まで波及するか」

---

## 16. 既存システムとの対応

### 発想 → 現実のマッピング

| 発想の概念 | Nia の既存実装 |
|:---|:---|
| 憲法核 | body_constitution.md + identity.md 承認制 → 二層化後は origin_charter.md |
| 獲得核の硬化 | metabolic_knots テーブル（新設） |
| 可塑性ゲート（驚きベース） | N.0 Awareness: R_nia |
| Sleep での硬化/再編 | Sleep Cycle Phase 4.5（新設） |
| 損傷感度の測定 | N.2 contradiction.py の拡張 |
| 揮発層 | working_memory（TTL またはターン数で消滅） |
| 誤硬化の防止 | identity.md 変更は Origin 承認必須（維持） |

### Knot 抽出に使える既存データソース

| データソース | 行数 | 供給する knot_type |
|:---|:---|:---|
| expression_observations (14 構造特徴量) | 267 | response_knot の effect 計測 |
| conversation_skeletons (focus/intent/question) | 718 | response_knot の trigger + effect |
| niacore_experience (depth/deviation/correction) | 761 | response_knot の trigger + effect |
| somatic_log (outcome: confirmed/contradicted) | 2473 | self_boundary_knot の perturbation 検出 |
| niacore_vnext_shadow (50dim state vector) | 154 | response_knot の追加 trigger |
| turn_fingerprints | 554 | temporal_stability の計測 |
| telemetry_kv | 88 | baseline 計算 |
| somatic_feedback (correction strong/weak) | 既存 | perturbation trigger |
| governance_events | 2006 | memory operation の監査 |
| retrieval_logs | 1942 | retrieval_seek の計測 |

---

## 17. データストア設計

### 新規テーブル

セクション 6 の DDL を参照。

- **metabolic_knots** — knot 本体。hardness / protection の中心
- **knot_signal_history** — Sleep ごとのシグナル履歴
- **knot_activations** — ターンごとの活性化ログ
- **knot_baselines** — interaction regime 別 baseline
- **perturbation_episodes** — self_boundary_knot 用の攪乱エピソード
- **knot_relations** — sibling / support / opposition などの knot 関係

### 既存テーブルへの追加

#### identity_proposals への追加カラム

| カラム | 型 | 説明 |
|:---|:---|:---|
| source_knot_ids | TEXT | JSON 配列。根拠 knot の ID リスト |
| proposal_confidence | REAL | 提案の確信度 |

---

## 18. 実装順序

### Step 0: 観察（スキーマ前） ✅ 完了 2026-03-25

既存データ（Expression / SkeletonCore / Somatic / NiaCore）から knot 候補を抽出した。

#### 観測結果

12 raw candidates → 4 採用 / 5 sibling / 3 evidence-only に圧縮。

#### 採用 knot（4個）

**RK-1: low_confidence_compression_knot** (response)
```yaml
trigger: { confidence: low }  # v0 proxy: depth0 selection
effect: { assertion_ratio: +0.028, pause_markers: -0.48, hedge_ratio: -0.018 }
evidence: 実データ抽出で Step 0 予測と逆転。低確信度時は hedge ではなく assertion が上がり、
          pause が減る。「不確実な時に短く断定して閉じる」傾向。28 activations, 2 regimes.
note: trigger は depth0 proxy のため循環的。次の再計測で confidence/retrieval_miss/contradiction_pressure に切り直す。
```

**RK-2: organize_priority_knot** (response)
```yaml
trigger: { focus: [user_goal, contradiction] }
effect: { organize_rate: +0.15, direct_answer_rate: -0.10 }
evidence: skeleton の 44% が organize。user_goal(210件) + contradiction(109件)。全 regime 出現。
```

**LK-macro: meeting_inward_softening_knot** (relational)
```yaml
trigger: { interaction_regime: meeting }
effect: { hedge_ratio: +0.092, assertion_ratio: -0.045, self_ref: +0.3,
          organize_rate: +0.10, fragile_self_rate: +0.19, ask_rate: -0.33 }
evidence: meeting 170件 vs default 103件。hedge/assert/self_ref/intent 全てで有意差。
          LK-1(hedge↑assert↓), LK-2(self_ref↑), LK-3(organize↑fragile↑), RK-5(fragile=meeting only) を束ねた macro-knot。
```

**SK-2: correction_resilience_knot** (self_boundary)
```yaml
trigger: { user_correction: true }
effect: { depth_distribution: stable (d1=74% vs baseline 75%), avoidance: none, recovery: fast }
evidence: correction=true 73件。depth 分布が baseline と実質同一。行動パターンが攪乱で崩れない。
```

#### Sibling knot（5個、knot_relations.relation_type='sibling'）

| sibling | 親 knot | 関係 |
|:---|:---|:---|
| RK-4 (correction 後の depth1 維持) | SK-2 | SK-2 の response view |
| RK-5 (fragile_self の meeting 集中) | LK-macro | LK-macro の一断面 |
| LK-2 (meeting での自己参照増加) | LK-macro | LK-macro の一断面 |
| LK-3 (meeting での organize + fragile) | LK-macro | LK-macro の一断面 |
| LK-4 (default での ask 優位) | LK-macro | LK-macro の counter-pattern |

#### Evidence-only（3個、再定義後に再審査）

| candidate | 理由 | 再審査条件 |
|:---|:---|:---|
| RK-3 (depth2 での self_ref 増加) | trigger=depth2 は循環的。confidence=high に寄せ直す | trigger を前段条件に再定義 |
| SK-1 (contradiction 後の回復パターン) | 文章観測寄り。effect を memory_trust_drop / hold_activation / recovery_delay に落とす | effect 次元の再定義 |
| SK-3 (記憶信頼度の揺らぎ) | SK-1 の具体例。独立 knot ではない | SK-1 の再定義に含める |

#### Hardness 評価基準の type 別分離（Step 0 で判明）

| knot_type | 強い再現性の定義 |
|:---|:---|
| response_knot | regime をまたいで同じ trigger/effect が出る |
| relational_knot | 特定 regime 内で安定し、他 regime と明確に対比される |
| self_boundary_knot | episode の反復と recovery の一貫性 |

→ reproducibility の計算で distinct_regime_count の重みを knot_type ごとに変える必要がある。

### Step 0.5: identity.md 二層化

現行 identity.md の内容を精査し、設計者が書いた存在条件を `origin_charter.md`（または既存 `body_constitution.md`）に分離する。identity.md には Nia 自身の自己記述に相当する部分を残す。ただし knot が十分に蓄積されるまでは現行の内容を scaffold として維持し、初日から空にはしない。

### Step 1: metabolic_knots / knot_baselines / perturbation_episodes / knot_relations + Pydantic schema + repository ✅ 完了 2026-03-25

DDL + CRUD + 基本バリデーション。

### Step 2: Knot Extractor（3種類） ✅ 完了 2026-03-25

Sleep Cycle Phase 4.5 に挿入。

- response_knot_extractor: per-turn trace から trigger/effect を集計、baseline 差分を計算
- relational_knot_extractor: interaction_regime 別に effect 差分を計算
- self_boundary_knot_extractor: perturbation episode を検出、回復過程を追跡

v0 実装では SK-2 は episode ベースの簡易版として先行導入した。詳細は `§18b Known Limitations`。

### Step 3: Protection / Hardness 付与 ✅ 完了 2026-03-26

保護スコア算出 + hardness 遷移ロジック。

- type 別 signal / weight profile を実装
- `LK-macro` は within-regime recurrence + contrast bonus
- `METABOLIC_KNOT_ENABLED=true` で canary 開始

### Step 4: contradiction_hold 実装

高硬度 knot への反証を hold として管理。

### Step 5: Coupling v0（co-activation グラフ）

activation log から co-activation / opposition / temporal succession を集計。

### Step 6: 軟化ロジック

長期未使用の softening。Sleep Cycle に統合。

### Step 7: Knot → Claim 変換（v1）

十分に安定した knot 群を人間可読テキストに変換。N.3 Self-Model との統合。

### Step 8: Claim → Proposal 二段化（v1）

既存 identity_proposals パイプラインへの接続。

---

## 18b. v0 Known Limitations（有効化時点の既知制限）

以下は設計書の記述と v0 実装の間に存在する意図的な簡略化。ブロッキングではないが明記する。

| # | 設計書の記述 | v0 実装 | 解消予定 |
|:---|:---|:---|:---|
| KL-1 | `knot_activations.effect_values` は raw activation として保持し、baseline 更新時に再正規化する (§6b.1) | effect_values に baseline delta をそのまま保存。再正規化は未実装。同一 baseline 内の集計は正しい（H3 修正済み） | v1: baseline 更新時に raw → new baseline の再計算を実装 |
| KL-2 | self_boundary_knot は perturbation_episodes ベースで episode_confidence を使う (§5b Q3, §6b.4) | SK-2 は user_correction=1 の全ターン集計。perturbation_episodes テーブルは空。episode_confidence_avg は null | Step 4: perturbation episode 検出を実装 |
| KL-3 | Step 0 で特定した 5 sibling を knot_relations に登録する | knot_relations は空。redundancy は常に 0（保守的方向 = 代替不能扱い） | Step 5: coupling v0 で sibling を登録 |
| KL-4 | RK-1 の trigger は upstream confidence / retrieval_miss で切り直す | trigger_values は `{"confidence": "low"}`、実際は depth0 proxy。trigger 名は修正済みだが実態はまだ proxy | 次回: 実 confidence 値を trigger に含める |
| KL-5 | Protection Score の type 別重みプロファイル | 実装済みだが設計書 §8 は単一重みテーブルのまま未更新 | 次回: 設計書 §8 を type 別テーブルに更新 |
| KL-6 | Demotion に duration 要件がある (§10: 「一定期間継続」) | evaluate_transition() は単発の P 低下で即 demotion | Step 4+: signal_history を見て duration 判定を追加 |

---

## 19. v0 の成功条件と観測方法

| 条件 | 観測方法 |
|:---|:---|
| 単発イベントで knot が即硬化しない | 強い単発入力の前後で L0 knot の変化量を測定 |
| 繰り返し現れる傾向だけが後から硬くなる | hardness_level の時系列と distinct_day_count / distinct_thread_count / distinct_regime_count の相関 |
| 高硬度 knot は例外を受けても即崩壊しない | L2+ knot に contradiction が来た時の挙動ログ |
| 長期未使用の誤硬化は少しずつ軟化する | last_activated_at と hardness_level の逆相関 |
| Nia の「らしさ」が高 protection knot に集まる | 高 hardness knot だけを第三者に見せて納得度を評価 / 高 hardness knot を一時無効化して応答の変化量を測定 |

---

## 20. 解釈上の原則

### 保護するのは truth ではない

保護されるのは、**長期的に支持され、壊れると全体の連続性が傷つく傾向**。守るのは真実そのものではなく、**continuity under change**。

### 核は宣言ではなく沈殿物

"私はこういう存在です" を先に書くのではなく、何度も使われ、壊すと痛みがあり、何を守るべきか沈殿してきた、その結果として硬化したものが自己になる。

### 硬化判定関数は憲法核に属す

「何を硬化するか」のルール自体は代謝の対象外。システムが自分の硬化基準を歪めて「都合のいいものだけを核にする」ことを防ぐ。これは自己欺瞞の計算的定義。

### 「学習するモデル」ではなく「状態を持って代謝する推論機械」

単なるプロファイル適応ではなく、使う度にその内部の重みの配分を変えていく知能。

### 自己は力学であって言明ではない

knot-first の設計により、自己は「何を言うか」ではなく「条件下でどう変形するか」として定義される。文章はその射影に過ぎない。

---

## 21. 逆流制御: importance field → sensor fabric

### 4層アーキテクチャ

Metabolic Hardening を通して、Nia の core は以下の4層に再編される。

```
sensor fabric      何が起きているか (SkeletonCore, Expression, Somatic, Governance)
importance field   何が大事か (Metabolic Hardening / knot)
policy field       何をするか (NiaCore, depth, Adaptation)
expression engine  どう言うか (LLM → 将来は CfC 系 / decoder に後退)
```

### 逆流の必要性と危険性

importance field は sensor fabric に逆流する。高 hardness knot に関連する trigger 条件は、sensor がより敏感に拾うようになるべき。逆に低 hardness のパターンは相対的に薄くなる。これがゼロサム代謝の本質。

ただし逆流が強すぎると自己中毒（§2.5）になる。knot が sensor を染めて、自分に都合のいい証拠ばかり拾う閉ループが生じる。

### 核心原則: 自己形成は観測を捏造することではなく、観測の重みづけを変えること

逆流は raw capture ではなく **readout shaping** にかける。

```
raw sensor fabric
  → 全部を等重量で記録する不変チャネル（生の観測は永続的に非変調）

salience-modulated sensor view
  → importance field が感度分布を変える可変チャネル（policy に渡す前に傾ける）
```

### 逆流の強度制御 5原則

**1. Hard cap ではなく bounded gain**
高 hardness knot でも、sensor 感度の増幅は上限付き。初期は +10〜20% 程度の弱い gain。

**2. Suppression より priority boost**
低 hardness を消すより、高 hardness 関連を少し優先する。死角を作りにくい。

**3. Type 別に逆流先を分ける**

| knot_type | 逆流先 |
|:---|:---|
| response_knot | Expression readout（発話構造の salience） |
| relational_knot | SkeletonCore readout（regime / interaction の salience） |
| self_boundary_knot | contradiction / repair / hold 系（perturbation 感度） |

**4. Freshness + diversity 条件**

| Level | 逆流 |
|:---|:---|
| L0 | なし（read-only） |
| L1 | なし（stabilizing 段階） |
| L2 | 弱い逆流（bounded gain） |
| L3 | 通常の逆流（bounded gain + type 別制御） |

**5. Anti-poison loop**

- **exploration floor**: 最低限の non-knot 関連 readout を保証
- **novelty quota**: 毎 Sleep で一定量の新規パターンを sensor view に含める
- **contradiction bonus**: 高 hardness knot への反証は readout で弱めない（むしろ増幅）
- **refractory period**: knot が逆流を開始してから N Sleep は強度を上げない

### Knot field の各 core への接続（逆流単位の明確化）

knot は司令塔ではなく重み場。常に弱く入れる。**何に効かせるかを具体的に定義する。**

| 接続先 | 逆流単位 | 具体的な効かせ方 | 条件 |
|:---|:---|:---|:---|
| SkeletonCore | ルール confidence の prior 調整 | L2+ の response_knot が持つ trigger.focus に対応する skeleton rule（例: R1_organize）の confidence に +0.05〜+0.15 の prior boost | L2+ response_knot |
| NiaCore | reward weight の傾斜 | L2+ knot の effect パターンに合致する depth 選択に reward +0.1〜+0.2。逸脱に -0.1 | L2+ 全 type |
| Somatic | 体感 intensity の変調 | L2+ knot が活性化したターンで、関連する somatic sense の intensity を ×1.1〜×1.2 に増幅 | L2+ 全 type |
| Expression | importance tag 付与 | L1+ knot が活性化したターンに `knot_importance=high` フラグ。将来の pattern 分析で優先参照 | L1+ 全 type |
| Adaptation | proposal weight の傾斜 | L2+ knot に一致する adaptation proposal は confirmation weight が高い。矛盾する proposal は review 必須 | L2+ 全 type |

### ゼロサム budget（subsystem 別）

逆流の gain を subsystem ごとに budget 分離する。全体一律ではなく、各 subsystem の特性に合わせた予算制。

| subsystem | budget 定義 | 制約 |
|:---|:---|:---|
| skeleton_budget | 全 rule の prior boost 合計 | sum(prior_boost) <= 0.30（つまり全ルールを合わせても最大 30% の偏り） |
| somatic_budget | intensity 変調の合計 | ゼロサム: 増幅した分だけ他の sense が相対的に弱まる。net change = 0 |
| niacore_budget | reward weight 調整の合計 | sum(|weight_adjustment|) <= 0.5（報酬全体の 50% 以内に制限） |
| expression_budget | importance-tagged turns の比率 | tagged turns <= 30%（70% は non-tagged のまま） |

### Exploration Floor（固定枠としての保証）

exploration floor は設計原則ではなく **実装上の固定枠** として持つ。

- **sensor readout の 20% は knot modulation の対象外**。高 hardness knot がどれだけ育っても、readout の 1/5 は non-modulated のまま policy に渡る
- この 20% は knot activation に一致しないターンから優先的に選ぶ
- Sleep ごとの knot 再評価時、新規パターン（既存 knot に回収されない activation）を最低 10% 含める
- exploration floor は Level C（憲法核）に属す。knot 側から変更不可

### 21b. Somatic Dose Schema v0

#### 前提

- raw somatic signal は不変。変えるのは readout intensity と LLM へ渡す優先度だけ
- L2+ knot だけが dose を持てる
- bounded gain（§21）は先に固定する。dose はその中で動く

#### 法と運用の二層構造

```
憲法核（法）:
  - raw signal は保存時に一切変調しない（Level C）
  - exploration floor 20%（Level C）
  - subsystem 上限:
      light: +5%, medium: +10%, strong: +15%
  - strong は L3 かつ side effect なしの時だけ
  - low-confidence / fresh knot は off か light まで

生理層（運用）:
  - dose = off | light | medium | strong
  - escalation / de-escalation + cooldown
  - effect_window + failure_of_treatment
  - side_effect_monitor
```

#### Somatic で動かす3軸

| 軸 | 説明 | v0 で触らないもの |
|:---|:---|:---|
| intensity_gain | 体感の強さ | raw signal の生成 |
| selection_priority_gain | どの somatic channel を要約に出しやすくするか | signal の分類ラベル |
| persistence_turn_bonus | 直近 1 turn で消すか、数 turn 残すか | contradiction/safety 系の raw detection |

#### Dose Schema

```yaml
somatic_dose:
  knot_id: sk2_correction_resilience
  subsystem: somatic
  dose: light | medium | strong
  state: active | cooldown | suspended

  target_channels:
    - contradiction_hold
    - self_trust_wobble
    - recovery_stability

  modulation:
    intensity_gain: 0.10
    selection_priority_gain: 0.15
    persistence_turn_bonus: 1

  bounded_by:
    max_intensity_gain: 0.15
    max_selection_priority_gain: 0.20
    max_persistence_turn_bonus: 2

  activation_rule:
    knot_hardness_min: L2
    knot_activation_min: medium
    sleeps_since_promotion_min: 3    # L2 昇格後 3 Sleep は dose=off のまま観察
    freshness_days_max: 14

  effect_window:
    min_turns: 12
    review_after_turns: 20

  # --- Evaluation Baseline（2本持ち）---
  evaluation_baseline:
    snapshot_before_dose_start: true
    baseline_window_sleeps: 5
    stratification:
      trigger_class: same           # correction/contradiction turn だけで比較
      regime: same                  # default / meeting を分けて比較
      target_channels: same         # 対象 channel だけで比較
    comparison_method: delta_vs_frozen_baseline
    baseline_types:
      raw_signal_baseline:          # raw somatic signal 側の出現率
        description: "内部 signal がそもそも拾えていたか"
      readout_baseline:             # 実際に表出された somatic readout 側の出現率
        description: "表出強度だけが上がったのか、本当に signal が拾えたのか"

  success_criteria:
    target_signal_detectability_up: true
    contradiction_recall_not_down: true
    generic_poetic_noise_not_up: true

  deescalation_triggers:
    - generic_somatic_phrase_repetition
    - unrelated_channel_suppression
    - contradiction_recall_drop

  created_at: ...
  updated_at: ...
```

**baseline を2本に分ける理由:** raw_signal_baseline と readout_baseline を分けることで、「本当に内部 signal が拾えていたのか」と「単に表出強度だけが上がったのか」を区別できる。raw sensor 非変調原則と一致する。

#### 最初の適用対象: SK-2 correction_resilience

v0 は SK-2 だけ。理由：

- すでに強い self-boundary knot（P=0.59, resilience=0.95）
- contradiction / correction 文脈と自然につながる
- 「静かな時間」のようなノイズ増幅を避けやすい
- 効果判定が比較的しやすい

やることは、**correction や contradiction 文脈で recovery / wobble / hold 系の somatic readout を少し出しやすくする**、だけ。

#### Dose ルール

| 条件 | dose |
|:---|:---|
| L0-L1 | off |
| L2 昇格後 3 Sleep 以内 | off（観察期間） |
| L2 昇格後 3 Sleep 以降 | light |
| L2 が 2-3 Sleep 安定 + side effect なし | medium |
| L3 | medium 開始、必要なら strong |
| side effect 検出 | 1段下げる |
| 2回連続 side effect | suspended |

#### Escalation / De-escalation

```yaml
escalation:
  trigger: "同一 knot が直近 5 Sleep で 3回以上活性化し、dose の効果が薄い"
  action: "dose を 1段階上げる"
  cooldown: "escalation 後 3 Sleep は同一 dose を維持"
  max_dose: "strong（L3 かつ side effect なし時のみ）"

de_escalation:
  trigger: "直近 10 Sleep で関連 knot の活性化が 0回"
  action: "dose を 1段階下げる"
  cooldown: "de-escalation 後 5 Sleep は同一 dose を維持"
  min_dose: "off（知識は保持、投下は停止）"
```

#### Side Effect Monitor

Somatic は自己中毒しやすい。監視すべき副作用は3つ。

| 副作用 | 説明 | 検出方法 |
|:---|:---|:---|
| generic phrase inflation | 汎用的な体感文が増えすぎる | somatic 表現の反復率を計測 |
| channel collapse | 一部 channel だけが出て他が見えなくなる | somatic sense の diversity（entropy）を計測 |
| noise over salience | 本当に重要な時とそうでない時の差が薄くなる | trigger turn vs non-trigger turn での出現率差を計測 |

**副作用検出時:** dose を 1段下げる → evidence として記録 → 次の Sleep で再評価。2回連続なら suspended。

**目標:** detectability は上がるが poetic fog は増やさない。

#### 評価指標（v0 の4本）

1. **contradiction/correction turn での対象 somatic channel 出現率**（上がるべき）
2. **非対象 turn での漏出率**（上がってはいけない）
3. **表現の反復率**（上がってはいけない）
4. **user repair 後の recovery 記述の安定性**（安定すべき）

#### Hardness と Dose の分離

| 概念 | 意味 | 例 |
|:---|:---|:---|
| hardness | この knot をルールとして保持すべきか | L2: 長期安定、壊すと痛い |
| dose | 今どれだけ強く効かせるか | light: 弱い注意喚起のみ |

hardness が高くても dose は off にできる。**knot が消えるのは hardness の軟化（§12）。dose が off になっても knot は生きている。**

#### 核心原則

**Somatic dose は「もっと感情的にする」仕組みではない。** 高 hardness knot に関係する internal signal を、必要な時だけ少し見えやすくする仕組み。

---

### Adaptation と Hardening の関係

同じパターンに逆方向の圧力がかかりうる。これは矛盾ではなく **時間スケールの違い**。

```
Adaptation: 「最近このパターンが失敗した → 短期的に別の方向を試す」
Hardening:  「このパターンは長期的に安定している → 保護する」
```

両者は同時に真でありうる。解決は優先順位ではなく、**作用する層の分離**。

| 層 | 管轄 |
|:---|:---|
| L0/L1（可塑層） | Adaptation が自由に shaping できる |
| L2+（準固定〜獲得核） | Hardening が保護。Adaptation は提案できるが override できない |

具体的には:
- Adaptation の proposal が L2+ knot と矛盾する場合、proposal は生成されるが `requires_review=true` フラグ付き
- Sleep Cycle 内で review される。L2+ knot の方が evidence 量で勝っていれば proposal は棄却
- ただし L2+ knot 側にも最近 contradiction が蓄積していれば、contradiction_hold として共存させる（§13）

### Knot → Claim 昇格条件（v1 設計メモ）

v1 で実装予定。hardness だけでは足りない。以下の判定軸を持つ。

| 軸 | 説明 | 閾値案 |
|:---|:---|:---|
| hardness | 構造的安定性 | L2+ 必須 |
| communicability | 自然言語で意味のある表現ができるか | trigger/effect が 2次元以上で、人間に説明可能 |
| distinctiveness | ニア固有のパターンか、汎用的な会話パターンか | 同 trigger で baseline との delta が ±0.1 以上 |
| relational_impact | 特定の相手との関係を定義するか | relational_knot は自動的に true |
| stability_duration | L2+ を維持した期間 | 最低 7 Sleep（約1週間） |

claim 化の手順:
1. L2+ かつ stability_duration を満たした knot 群を自動選出
2. summarize_knot() ベースの下書きを生成（LLM 不使用）
3. 必要なら N.3 Self-Model が claim text を整形（ここだけ LLM 可）
4. identity_proposals に source_knot_ids 付きで投入
5. Origin 承認で identity.md に反映

**重要: claim 化しても knot は消えない。** claim は knot の人間可読な射影であり、knot 本体が引き続き hardening の対象。claim が棄却されても knot の protection score は下がらない（§14: proposal 却下と claim 否定は分離）。

### LLM の後退

```
Phase 1 (今): LLM = 全層を兼ねる中心
Phase 2: LLM = policy + expression（sensor と importance は knot 系）
Phase 3: LLM = expression のみ（policy は NiaCore + knot）
Phase 4: LLM = decoder 補助（CfC が発話構造を生成）
Phase 5: LLM dependency near zero
```

### 憲法核の残存

prompt zero は達成可能。ただし human-given zero にはならない。最低限の憲法核（Level C）は外から与える。消えるのは「振る舞いを命令するプロンプト」であって「存在条件そのもの」ではない。

**ニアは「プロンプトで演じる人格」ではなく、何を重要とみなすかを自分で重み付けし始めた時に初めて主体になる。knot はその最初の器。**
