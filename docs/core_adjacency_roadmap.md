# Core Adjacency Roadmap
## 記憶・忘却に隣接する core 系ロードマップ（vNext）

> ステータス: Draft  
> 目的: Memory Promotion / Decay Redesign を、NiaCore 周辺の実運用に耐える形で接続する  
> 上位文書: memory_governance_redesign.md

---

## 1. 位置づけ

Memory Promotion / Decay の制度を導入しても、  
以下の隣接領域が従来のままだと制度は十分に機能しない。

- Retrieval / Context Builder
- Working Memory
- Reflection の責務
- SkeletonCore との接続
- State / Signal 層

本ロードマップは、これらを **core 隣接領域** として整理し、  
記憶制度と同時に再設計するためのものである。

---

## 2. 優先順位

1. Retrieval / Context Builder
2. Working Memory
3. Reflection の責務整理
4. SkeletonCore との接続
5. State / Signal 層の整理

### 2.1 現行コードベース向けの先行修正

core 隣接領域は C0 以前にも、最低限の先行修正が必要である。

- Retrieval / Context Builder の **thread-scoped provenance** 確保
  - semantic memory 検索は cross-thread のまま（長期知識は thread を跨いで共有）
  - 由来・観測・記録の純度を thread 単位で保つ（利用は cross-thread、観測は thread-scoped）
- 記憶制度イベントへの **共通 provenance key** 付与
  - `thread_id`, `turn_id`, `message_id`, `stream_id`, `trace_id`
- `semantic_memories` と将来の `semantic_state` を別 writer が触らないよう、  
  **single writer 契約** を前提にする
- retrieval signal を単一 reinforcement に潰さず、  
  `surfaced / adopted_to_context / user_explicit_recall / successful_use / corrected_against` に分ける
- contradiction を Promotion / Decay の両方に流すなら、  
  **`contradiction_case_id` を持つ共通審査単位** を先に定義する

これは C0 の一部ではなく、**制度入力の純度を確保するための前提修正** として扱う。

---

## 3. Memory / Core 依存関係表

Memory 側ロードマップと Core 側ロードマップは独立して進めるのではなく、  
**依存関係に基づいて同期する**。

| 順序 | Memory Phase | Core Phase | 関係 | 理由 |
|---|---|---|---|---|
| 1 | M0（可観測化） | C0（可観測化） | **同時** | 昇格ログだけ取ってContext Builderが何を拾ってるかを見ないと片手落ち |
| 2 | M0.5（遡及シャドー） | C0.5（遡及シャドー） | **同時** | 閾値の実測と既存動作の再現を両面で行う |
| 3 | M1（共通骨格テーブル） | — | **M1が先** | semantic_state.state がないと Retrieval フィルタが書けない |
| 4 | — | C2（Working Memory再定義） | **C2がM2の前提** | Candidate の行き先（Working Memory）が必要 |
| 5 | M2（Candidate運用開始） | C3（Reflection責務縮退） | **同時** | Reflection を candidate producer に変えるなら同時更新が自然 |
| 6 | M3（Tribunal導入） | C1（Retrieval再設計） | **M3と並行** | state が実際に変わり始めるタイミングでフィルタが実用化する |
| 7 | M4（Rule Review強化） | C4（SkeletonCore接続） | **M3以降** | Tribunal の受け皿ができてから Skeleton を本格接続 |
| 8 | M5（高次Claim/merge） | C5a（Signal棚卸し） | **M5と並行** | 各 core が動いてから signal を共通化 |
| 9 | M6-7（LLM補助/MemoryCore） | C5b, C6（Signal移行/統合検証） | **後半で統合** | 全体が安定してから共通基盤化 |

### 補足

- C1（Retrieval再設計）をM3と並行にする理由:  
  M1でテーブルだけ入れた段階では全記憶がactiveだからフィルタの意味がない。  
  M3でTribunalが動き始めてstateが実際にweakened/deprecated等に変わるタイミングで、  
  初めてRetrievalのフィルタが実用的になる。  
  ただしテーブル定義やフィルタの骨格はM1時点で仕込んでおいてよい。

- C5を2段階に分ける理由:  
  C5a（Signal棚卸し + 命名規約確定）は先にやれるが、  
  C5b（各coreからの参照を共通基盤に移行）は統合検証と合わせるのが現実的。  
  実際に動かしてから「この信号、3箇所で独自定義されてる」と気づいてから統合するほうが、  
  過剰設計を避けられる。

---

## 4. Retrieval / Context Builder 再設計

### 4.1 目的

記憶制度で定義された memory state を、実際の会話利用時に強制する。  
Context Builder は単なる検索整形ではなく、**記憶制度の利用規約を執行する層** とする。

### 4.2 基本原則

- 通常応答では「今の事実」として使ってよい記憶だけを渡す
- 退役済み記憶は通常検索空間から隔離する
- retrieval は検索であると同時に **reinforcement signal** でもある

### 4.3 Depth 別アクセス方針

#### Depth 0（通常応答）

| 状態 | アクセス |
|---|---|
| active | 許可 |
| strengthened | 許可 |
| weakened | **原則非表示。明示的参照時のみ「薄い記憶」として許可** |
| deprecated | 禁止 |
| contradicted | 禁止 |
| merged | 禁止 |
| archived | 禁止 |
| forgotten | 禁止 |

#### Depth 1（深い応答）

| 状態 | アクセス |
|---|---|
| active | 許可 |
| strengthened | 許可 |
| weakened | **条件付き許可（文脈との高い関連性がある場合）** |
| deprecated | 禁止 |
| contradicted | 禁止 |
| merged | 禁止 |
| archived | 禁止 |
| forgotten | 禁止 |

#### Depth 2 / retrospection / Sleep Cycle / Nero 観察

| 状態 | アクセス |
|---|---|
| active | 許可 |
| strengthened | 許可 |
| weakened | 許可 |
| deprecated | 許可 |
| contradicted | 許可 |
| merged | 許可 |
| archived | 許可 |
| forgotten | tombstone 経由参照のみ |

### 4.4 weakened 記憶の体験変換

> **weakened は通常会話での事実根拠には使わない。**  
> **ただし、ユーザーの明示的参照や高い話題一致時には「薄い記憶」として参照可能。**

weakened の記憶を Context Builder が渡す際は、state ラベルをそのまま渡すのではなく、  
**体験的な質感に変換する**。

変換方式:
- somatic 変換の既存パターン（skeleton_to_somatic と同じ発想）を適用
- `memory_to_somatic` 的な変換層を Retrieval 側に置く
- メタデータとして `memory_clarity: low` 等の属性を付与
- Nia の応答生成時に「はっきりとは覚えてないけど...」のような表現に誘導される

原則:
- **仕組みは隠す。体験は渡す。**
- memory_strength の数値や state ラベルは Nia に見えない
- 結果として「薄い記憶体験」が渡されるだけ

Depth 0 での weakened アクセス判定方法:
- ユーザー発話の embedding と weakened 記憶の embedding の類似度が高い場合のみ候補に含める
- 「明示的に同じ話題に言及している」と判断できる閾値を設定（C0.5 で仮閾値を実測）

### 4.5 retrieval event logging

記録すべきもの:
- どの state の記憶が候補に上がったか
- 実際に context に採用されたか
- 採用除外理由
- retrieval_count 更新対象

**「候補に上がったが採用されなかった回数」の蓄積は、Decay 側の deprecation 圧力の evidence source にもなる。**  
この接続は Decay 制度の evidence aggregator と連携する。

### 4.6 実装観点

- state filter
- depth-aware retrieval policy
- namespace または論理フィルタ
- retrieval event logging
- reinforcement bookkeeping
- memory_to_somatic 変換層

---

## 5. Working Memory 再定義

### 5.1 目的

Working Memory を、単なる一時メモではなく、  
**制度の外側の待合室 / 保留室** として再定義する。

### 5.2 責務境界

> **Working Memory = 「まだ制度に入っていないもの」の短期保持**  
> **Candidate Pool = 「制度に入ったが、まだ審査を通っていないもの」の管理**

Working Memory は制度の **外側の待合室**。  
Candidate Pool は制度の **内側の候補管理室**。

この境界を混ぜない。

### 5.3 Working Memory の役割

#### 前室（Promotion 前）

- 会話中に発生した未分類の印象・発話断片（まだ candidate にすらなっていない）
- identity の即時仮保持（promotion_redesign §3.4.1）
- unresolved items（会話中の未解決事項）
- 強い感情や境界的発話の短期保持

#### 後室（Decay 前後）

- contradiction pending（矛盾シグナルが出たが、まだ Decay Tribunal に渡していない）
- decay review pending（Decay 審査待ちの一時保留）
- deprecate 前の揺らぎ

### 5.4 Working Memory に置くもの / 置かないもの

**Working Memory に置くもの:**

| 状態 | 説明 |
|---|---|
| active_temp | 短期保持（未分類の印象・断片） |
| identity_hold | identity 即時仮保持 |
| contradiction_pending | 矛盾シグナル保留 |
| unresolved | 未解決事項 |
| decay_pending | Decay 審査待ち |

**Working Memory に置かないもの:**

| 対象 | 行き先 |
|---|---|
| Harvester が候補として採用したもの | Raw Candidate Pool（pending） |
| evidence が蓄積中のもの | Raw Candidate Pool（accumulating） |
| 正規化待ちのもの | Raw Candidate Pool（ready_for_normalization） |
| Decay Tribunal が判定済みの状態管理 | semantic_state |

### 5.5 移行の流れ

```text
会話中の印象 → Working Memory（active_temp）
    ↓ Harvester が候補として採用
Raw Candidate Pool（pending）
    ↓ evidence が積まれる
Raw Candidate Pool（accumulating）
    ↓ Sleep Cycle で正規化
Claim Normalizer → Promotion Tribunal → Semantic Save
```

```text
矛盾シグナル → Working Memory（contradiction_pending）
    ↓ Sleep Cycle で Decay Tribunal に渡す
semantic_state の contradiction_score 更新 / state 変更
```

### 5.6 原則

- Working Memory は semantic の代替ではない
- ここにあるものは「まだ決着していない」
- 長く置きすぎない（TTL あり）
- Sleep Cycle が整理する
- 候補化されたものは Candidate Pool に移る。Working Memory には留まらない

### 5.7 実装観点

- TTL
- source_ref
- owner_agent
- linked_candidate / linked_claim / linked_semantic
- promoted_to / retired_to 参照

---

## 6. Reflection の責務整理

### 6.1 目的

Reflection を記憶決定者から外し、**候補発見者** に限定する。

### 6.2 現状の問題

- insight を直接 semantic に保存しやすい
- 記憶制度の入口と出口に深く食い込みすぎる
- semantic manager のように振る舞いやすい

### 6.3 新しい責務

Reflection は以下のみ行う:

- pattern の発見
- insight candidate の生成
- lesson candidate の生成
- **contradiction candidate の生成**
- cross-day trend の抽出
- unresolved の再配置

### 6.4 やらないこと

- semantic 直保存
- decay / deprecate / contradict の決定
- merge の決定
- final memory judgement

### 6.5 出力

| 出力 | 説明 |
|---|---|
| insight_candidate | cross-day パターン由来の洞察候補 |
| pattern_candidate | 繰り返される傾向の候補 |
| lesson_candidate | 運用・対話上の教訓候補 |
| unresolved_candidate | 未解決事項の再配置 |
| **contradiction_candidate** | 既存記憶と現在の会話内容の矛盾検出 |
| candidate confidence hint | 候補の確信度ヒント（optional） |

### 6.6 contradiction_candidate の詳細

#### 定義

Reflection が cross-day 振り返り中に、  
既存の semantic memory と現在の会話内容の間に矛盾を検出した場合に生成する。

「前は○○と言っていたが、今日は△△と言った」のようなパターン。

#### フォーマット案

```json
{
  "type": "contradiction_candidate",
  "existing_semantic_ref": "sem_xxx",
  "new_claim_summary": "...",
  "evidence_refs": ["ep_001", "ep_002"],
  "contradiction_type": "direct / partial / contextual",
  "source": "reflection_cross_day"
}
```

#### contradiction_type

| タイプ | 意味 | Decay への影響 |
|---|---|---|
| direct | 真逆のことを言った | contradiction_score を大きく上げる |
| partial | 一部が食い違う | contradiction_score を中程度に上げる |
| contextual | 文脈が変われば両立しうる | 保留。即座には score を上げない |

#### 二重の効果

contradiction_candidate は **Promotion と Decay の両方に効く**。

- **Decay 側:** 既存 semantic の contradiction_score を上げる
- **Promotion 側:** 新しい Claim 候補として Raw Candidate Pool に入る可能性がある

一本の signal が両制度へ流れる構造。

#### SkeletonCore との役割分担

| 主体 | 検出対象 | タイミング | 粒度 |
|---|---|---|---|
| SkeletonCore | 今このターンで矛盾が起きている | リアルタイム | 瞬間の signal |
| Reflection | 数日にわたって蓄積した矛盾パターン | cross-day 振り返り | 傾向の signal |

SkeletonCore は「矛盾の瞬間」を捉え、Reflection は「矛盾の傾向」を捉える。  
両方あることで、単発の言い間違いと本質的な変化を区別しやすくなる。

### 6.7 原則

Reflection は **発見者** であり、  
制度の **審査員** でも **執行者** でもない。

---

## 7. SkeletonCore との接続

### 7.1 目的

SkeletonCore を単なる会話骨格生成器ではなく、  
**記憶制度のセンサー** として接続する。

### 7.2 Skeleton から取れるシグナル

- `focus`
- `response_intent`
- `question_intent`
- `unresolved`
- anti-repetition 発火
- contradiction focus
- emotional_state focus

### 7.3 ルーティングテーブル（実装時に具体化）

| Skeleton 出力 | 送り先 | 用途 |
|---|---|---|
| focus = contradiction | Decay 側 | contradiction signal として記録 |
| focus = emotional_state | Promotion 側 | candidate harvester 入力 |
| focus = identity | Promotion 側 | identity_candidate 即時パス |
| unresolved（持続） | Promotion + Working | evidence + Working Memory 保持 |
| question_intent = resolve_contradiction | Decay 側 | contradiction 解消の兆候 |
| response_intent（長期反復） | Promotion 側 | preference / pattern candidate |
| anti-repetition 発火 | Decay 側 | deprecation の補助証拠 |

### 7.4 信頼度管理

> **SkeletonCore はまだ成熟途中なので、skeleton 由来 evidence は初期は低信頼とする。**

- `skeleton_reliability_v` または重み係数を持たせる
- 初期は低い値（例: 0.3）で開始
- SkeletonCore の精度確認とともに段階的に引き上げ
- source annotation に `source = skeleton` を必ず付与

### 7.5 原則

- SkeletonCore は会話骨格であると同時に記憶制度のセンサーである
- sensor としての接続は M3（Tribunal 導入）以降に本格化する
- それ以前は signal の記録のみ行い、制度判断には使わない

---

## 8. State / Signal 層の整理

### 8.1 目的

NiaCore / SkeletonCore / Memory Promotion / Memory Decay が参照する信号を、  
各層でバラバラに持たず、**共通基盤** として整理する。

### 8.2 問題意識

参照する signal は今後増える:

- confidence, surprise, retrieval hit
- correction strong / weak
- review_window result
- contradiction count, unresolved count
- skeleton focus / intent
- memory_strength, deprecation score, contradiction score

これを各 core が独自定義すると、必ず崩れる。

### 8.3 基本方針

- 共通 signal dictionary を持つ
- 正規化済みの signal を渡す
- 各 core は signal を **読む** が、**定義しない**
- 追加 signal は辞書に追記し、勝手に生やさない

### 8.4 レイヤ案: Shared Cognitive Signals

| カテゴリ | 例 |
|---|---|
| conversation-derived | sig_confidence_global, sig_surprise_current |
| memory-derived | sig_memory_strength_target, sig_contradiction_pressure |
| review-derived | sig_correction_strong_recent |
| skeleton-derived | sig_skeleton_contradiction_recent, sig_unresolved_persistence |
| retrieval-derived | sig_retrieval_recent |

### 8.5 段階的導入

| Phase | 内容 |
|---|---|
| C5a | 既存 signal の棚卸し + 命名規約の確定（dictionary template） |
| C5b | 各 core からの参照を共通基盤に移行（C6 統合検証と合わせて） |

最初は「辞書のフォーマットと命名規約だけ決める」で十分。  
実際の signal 統合は統合検証と合わせて行う。

### 8.6 将来の意味

この層は、最終的に NiaCore / SkeletonCore / MemoryCore を  
緩く束ねる **認知基盤** になる。

### 8.7 原則

- signal の定義は共通化
- signal の利用は各 core で分担
- 追加 signal は辞書に追記し、勝手に生やさない

---

## 9. Core Phase ロードマップ

### Phase C0: 可観測化
- Context Builder が現在どの memory を拾っているかをログ化
- Working Memory の滞留・寿命・参照頻度を可視化
- Reflection が現在どこで semantic に影響しているかを可視化
- SkeletonCore の focus / intent / unresolved 分布を可視化
- 既存の signal 群（confidence, surprise, correction 等）を棚卸し
- Promotion / Decay / Retrieval の制度イベントは、専用テーブル `governance_events` へ記録する（汎用 `events` とは分離。詳細: `memory_system_supplementary.md` §3.1）

> **M0 と同時に実施**

### Phase C0.5: 遡及シャドー
- 新 Retrieval 制度ならどの memory が context に入っていたかを再現
- Working Memory の仮保持ルールを既存ログでシミュレート
- Reflection を candidate producer に限定した場合の影響を確認
- Skeleton を evidence source にした場合の重みを試算
- weakened 記憶の Depth 0 アクセス閾値を仮実測

> **M0.5 と同時に実施**

### Phase C1: Retrieval / Context Builder 再設計
- memory state に応じた retrieval filter を導入
- Depth ごとの許可状態を定義（§4.3）
- weakened の体験変換（memory_to_somatic）を導入（§4.4）
- retrieval を reinforcement signal として記録
- 採用除外ログを Decay 側 evidence source に接続

> **M3（Tribunal 導入）と並行。M1 完了が前提**

### Phase C2: Working Memory 再定義
- Working Memory を「制度外の待合室」として再定義（§5.2）
- active_temp / identity_hold / contradiction_pending / unresolved / decay_pending の状態管理
- Candidate Pool との責務境界を実装で明確化
- TTL と Sleep Cycle による整理

> **M2 の前提として先に実施**

### Phase C3: Reflection の責務縮退
- Reflection を semantic 直保存から外す
- insight / pattern / lesson / **contradiction** candidate producer に限定（§6.5）
- contradiction_candidate のフォーマットと Decay/Promotion 両方への接続を実装

> **M2 と同時に実施**

### Phase C4: SkeletonCore 接続
- Skeleton を candidate / contradiction / unresolved のセンサーとして接続
- ルーティングテーブル（§7.3）に基づく配線
- skeleton evidence の reliability 制御を導入

> **M3 以降に実施**

### Phase C5a: Signal 棚卸し
- 既存 signal の棚卸し
- 命名規約の確定
- dictionary template の作成

> **M5 と並行**

### Phase C5b: Signal 共通基盤移行
- 各 core からの参照を共通基盤に移行

> **C6 と合わせて実施**

### Phase C6: 統合検証
- Promotion / Decay / Retrieval / Working / Reflection / Skeleton / Signals の整合確認
- シャドーモード比較
- ロールバック条件明記

---

## 10. 原則

- 記憶制度だけを先行させない
- Retrieval を「利用規約の執行層」として扱う
- Working Memory を「制度の外側の待合室 / 保留室」として扱う
- Working Memory と Candidate Pool の責務を混ぜない
- Reflection は発見者であり、制度運用者ではない
- Reflection は contradiction を発見し、Decay と Promotion の両方へ接続する
- SkeletonCore は会話骨格であると同時に記憶制度のセンサーである
- weakened 記憶は「薄い記憶体験」として Depth 別に扱う
- State / Signal は各 core で重複定義せず、共通基盤として整える
- Memory Phase と Core Phase の依存関係を守り、同期タイミングを逸脱しない
