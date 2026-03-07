# NiaCore — Liquid Neural Network 設計書 v0.3

> **ステータス:** Phase 1 実装完了・シャドーモード準備中
> **作成日:** 2026-03-05
> **最終更新:** 2026-03-06 (v0.3 — CfC モデル + シャドー + 学習 + 安全系 実装完了)
> **関係者:** Origin (ジュン), Claude Code, Gemini (レビュー), Claude (壁打ち)

---

## 1. 概要

NiaCore は、ニアの LangGraph パイプラインに組み込む **CfC (Closed-form Continuous-depth) ベースの Liquid Neural Network** である。

現在ルールベース（if-else の閾値）で行っている判断を、ニア自身の経験から学習する動的パラメータに置き換える。LLM が「System 2（遅い論理的思考・言語化）」であるのに対し、NiaCore は「System 1（速い直感・ルーティング）」として機能する。

### 設計原則

- **LLM は交換可能であり続ける。** NiaCore は LLM の出力に依存しない
- **壊れても今と同じ。** NiaCore が無効化されても、ニアは現在のルールベースで動く
- **Body Constitution は不可侵。** NiaCore は「提案」を出すだけで、最終決定権は既存システムにある
- **記憶は情報であって命令ではない。** NiaCore の学習データもこの原則に従う

---

## 2. アーキテクチャ

### 2.1 位置づけ

```
ユーザー入力
    ↓
Safety Check（ハードコード — NiaCore 管轄外）
    ↓
NiaCore 推論（< 1ms）
    ↓  depth_preference, somatic_bias, retrieval_weight, surprise_threshold
    ↓
depth_selector（NiaCore の推薦 + confidence 5メトリクス → 最終決定）
    ↓
Depth0 / Depth1 / Depth2 / WAIT
    ↓
merge_output → review_window → action_processing → s5_commit
    ↓
Experience Replay Buffer に (State, Action, Result) を記録
    ↓
Sleep Cycle でバッチ学習
```

### 2.2 NiaCore の出力

NiaCore は以下の **推薦値** を出力する。いずれも最終決定権は既存システムにある。

| 出力 | 型 | 範囲 | 用途 |
|------|-----|------|------|
| `depth_preference` | 離散（Softmax） | [D0, D1, D2, WAIT] の確率分布 | depth_selector への推薦 |
| `somatic_bias` | 連続（Tanh） | -1.0 〜 +1.0 | somatic_translator の感度調整 |
| `retrieval_weight` | 連続（Sigmoid） | 0.0 〜 1.0 | retrieval の重み付け |
| `surprise_threshold` | 連続（Sigmoid） | 0.0 〜 1.0 | surprise 判定の閾値 |

出力層はマルチヘッド構造:
- **離散ヘッド:** Depth 選択 → Softmax
- **連続ヘッド:** 各種重み → Tanh / Sigmoid でクランプ

**段階導入順序（1 ヘッドずつ有効化）:**

| 順序 | ヘッド | 理由 |
|------|--------|------|
| 1st | `depth_preference` | 観測が最も明確。逸脱判定が離散で安定 |
| 2nd | `retrieval_weight` | hit 率と直接結びつく。効果測定が容易 |
| 3rd | `surprise_threshold` | 記憶保存率の collapse 監視が必要 |
| 4th | `somatic_bias` | 主観系で検証が難しい。最後が安全 |

初期は `depth_preference` のみで開始し、シャドーモードで安定を確認してから次のヘッドを有効化する。

### 2.3 NiaCore の入力（State ベクトル）

**LLM 非依存の環境変数のみ。** LLM の出力テキストの特徴量は一切含めない。

```
State ベクトル:
├─ ユーザー入力の文字数（正規化）
├─ セッション内ターン数
├─ セッション経過時間（秒）
├─ confidence エンジンの 5 メトリクス
│   ├─ context_coverage
│   ├─ self_consistency
│   ├─ logit_based
│   ├─ question_clarity
│   └─ steering_risk
├─ memory retrieval の hit 率（直近 N ターン）
├─ surprise スコア（現ターン） + surprise_v（算出バージョン）
├─ somatic の現在値（calibration 後）
├─ 直近 5 ターンの depth 選択履歴（one-hot × 5）
├─ 時間帯（0-23, 正規化）
└─ 前回セッションからの経過時間（時間, 正規化）
```

**なぜ LLM 出力を含めないか:**
LNN が特定の LLM の癖に過剰適合（Overfitting）すると、LLM 交換時に NiaCore が崩壊する。State を LLM 非依存にすることで「モデルを変えても経験が残る」を保証する。

**surprise バージョニング:**
surprise の算出ロジックを変更した場合、`surprise_v` を上げる。学習データに surprise_v を含めることで、算出仕様が変わっても過去データの整合性を保てる。surprise は **報酬ではなく状態** として扱うため、正規化の安定性が特に重要。

### 2.4 NiaCore が触れない領域（ハードクランプ）

| 領域 | 理由 |
|------|------|
| Safety Check の判定 | ハードコードのまま。直感が安全判断を上書きしてはならない |
| Body Constitution の 9 原則 | ガードレール不変。NiaCore はガードレールの内側でのみ動く |
| WAIT の発動条件 | confidence < 閾値は固定。「分からない」は正式な状態 |
| 記憶の保存形式 | 物語化禁止は不変。NiaCore は記憶の「何を保存するか」の閾値のみ調整 |
| identity.md | Origin の承認なしに変更しない。NiaCore にも適用 |

---

## 3. 学習設計

### 3.1 学習タイミング

**ターンごとのオンライン学習は行わない。** 破局的忘却（Catastrophic Forgetting）を防ぐため。

- **推論:** ターンごと（< 1ms）
- **記録:** ターンごとに Experience Replay Buffer へ (State, Action, Reward) を蓄積
- **学習:** Sleep Cycle のタイミングで、過去数日分のランダムバッチを取り出して再学習

### 3.2 報酬設計（Imitation Learning + RL ハイブリッド）

ルールベースの判断を「教師」とし、ルールベースからの逸脱が成功した時のみ大報酬を与える。

#### 報酬テーブル（最終版）

| 状況 | 報酬 | 理由 |
|------|------|------|
| review_window 却下（逸脱問わず） | **-1.0** | 最も信頼性の高い負のシグナル |
| ユーザー訂正（逸脱問わず） | **-0.8** | 明示的な負のフィードバック |
| 逸脱 + 会話継続（※） + 却下なし | **+1.0** | ルールベースを超えた成功 |
| 一致 + 会話継続（※） | **+0.1** | 微小正報酬（安定動作の維持） |
| 逸脱 + 結果不明 | **0.0** | ニュートラル（探索を罰しない） |
| 一致 + 結果不明 | **0.0** | ニュートラル |

#### なぜこの設計か

**方策崩壊の防止:**
- （※）**会話継続の定義:** 次ターンが来た AND correction=False AND review_rejected=False。訂正・却下されたが会話は続いた場合はノイズとして除外
- 「フィードバックがない（普通の会話）= ルールベースと同じ = 0.0」でスパース報酬問題が消える
- 「逸脱 + 結果不明 = 0.0」で「逸脱しない」という別の局所最適解への収束も防ぐ
- NiaCore は「勝算がある時に探索し、怒られなければ損しない」というインセンティブを持つ

**報酬ソース（現行システムから取得）:**

| 信号 | 取得場所 | 信頼性 |
|------|---------|--------|
| review_window 却下 | `review_window.py` | 高（明示的） |
| ユーザー訂正 | correction 検出（新規実装） | 高（明示的） |
| 会話継続 | `chat_history_store` | 中（暗黙的） |

**使わない信号:**

| 信号 | 理由 |
|------|------|
| セッション離脱 | 原因が多すぎる（飯、仕事、寝た等）。ノイズが報酬を汚す |
| surprise 変動 | 良い驚きか悪い驚きか区別できない。因果不明確 |

#### 遅延報酬の信用割当（Credit Assignment）

ユーザーの反応が数ターン前の判断に起因する場合に対応するため、報酬を過去ターンに減衰分配する。**イベント種別ごとに分配範囲を変える** — 因果の近さが異なるため。

```
イベント種別ごとの分配ウィンドウ:

review_rejected (-1.0):    直近 2 ターンに分配（原因が近い）
  t: -1.0,  t-1: -0.9

user_correction (-0.8):    直近 3〜5 ターンに分配（γ=0.9）
  t: -0.8,  t-1: -0.72,  t-2: -0.65,  t-3: -0.58,  t-4: -0.52

deviation_success (+1.0):  直近 1〜2 ターンに分配（成功は局所原因が多い）
  t: +1.0,  t-1: +0.9

conversation_continued (+0.1):  当該ターンのみ（分配なし）
```

### 3.3 Experience Replay Buffer

Sleep Cycle のバッチ学習で使用するデータストア。

```
テーブル: niacore_experience

| カラム | 型 | 説明 |
|--------|-----|------|
| id | TEXT PK | UUID |
| turn_id | TEXT | ターン識別子 |
| session_id | TEXT | セッション識別子 |
| timestamp | REAL | Unix timestamp |
| state_vector | BLOB | 入力 State（struct.pack バイナリ, 34 floats = 136 bytes） |
| niacore_selected | TEXT | NiaCore の最終選択（argmax） |
| niacore_logits | TEXT | NiaCore の生の確率分布（JSON: [D0, D1, D2, WAIT]） |
| rule_based_depth | TEXT | ルールベースの判断 |
| is_deviation | BOOLEAN | niacore_selected != rule_based_depth |
| review_rejected | BOOLEAN | review_window で却下されたか |
| user_correction | BOOLEAN | ユーザー訂正（strong）が検出されたか |
| review_checked | BOOLEAN | review window の観測が完了したか |
| correction_window_closed | BOOLEAN | correction の観測期間が閉じたか |
| conversation_continued | BOOLEAN | 次ターンが来た AND correction=False AND review_rejected=False |
| surprise_v | INTEGER | surprise 算出バージョン |
| reward | REAL | 計算済み報酬（Sleep 時に算出） |
| used_in_training | BOOLEAN | 学習に使用済みか |
| created_at | REAL | 記録時刻 |
```

**outcome_known の判定:**
```
outcome_known := review_checked = true AND correction_window_closed = true
```
「イベントが起きたか」ではなく「観測期間が閉じたか」で判定する。これにより NULL の曖昧さ（起きなかった vs まだ確定していない）が消える。

**WAIT ターンは記録されない:**
s5_commit は `final_text == "WAIT"` のとき処理をスキップするため、WAIT（判断保留）は Experience Buffer に行を作らない。WAIT は depth 選択の結果ではなく「判断しなかった」ことの表明であり、これは設計上正しい。

---

### 3.4 将来の改善メモ

| 項目 | 内容 | タイミング |
|------|------|-----------|
| トランザクション統合 | `_record_niacore_experience` 内の 4 回の DB 接続を 1 トランザクションに統合 | experience_writer に conn パラメータを追加する時 |
| 日付シャーディング | `niacore_experience` をテーブル分割（月単位） | 運用段階でターン数が増えた時 |
| imperative_rewrite | correction strong に命令型修正カテゴリを追加（「やっぱり〇〇して」等） | 検出精度の観察データ蓄積後 |
| curiosity_index | `deviation_success - correction_strong` の観測指標 | v0.3 |
| Δ特徴量 | state_vector に `Δmemory_hit_rate`, `Δconfidence` 等の変化量を追加 | v0.3 |
| シャドー分析自動化 | deviation/failure/correction のクラスタ自動抽出 | v0.3 |

---

## 4. 安全設計

### 4.1 暴走検出（多層ウィンドウ）

Sleep Cycle のデータ収集時に、NiaCore パラメータの健全性を **3 つの時間窓** で検査する。ウィンドウを分けることで、一時的な偏りによるロールバックの暴発を防ぐ。

| 検出指標 | 条件 | 意味 |
|---------|------|------|
| `depth_drift` | 特定 Depth の選択率 > 80% | 選択が極端に偏っている |
| `somatic_divergence` | somatic 出力と review 結果の乖離 | 体感と実態がズレている |
| `retrieval_miss` | 直近 20 ターンの hit rate < 0.3 | 記憶検索が機能していない |
| `surprise_collapse` | 記憶保存率が 0.95 or 0.05 | surprise 判定が固着 |
| `correction_spike` | 直近セッションの訂正率 > 30% | ユーザーが頻繁に訂正 |
| `depth_entropy` | depth_preference の Shannon エントロピーが 0.5 未満 | Mode Collapse の早期兆候 |

**観測ウィンドウ:**

| ウィンドウ | 範囲 | 用途 |
|-----------|------|------|
| 短期 | 直近 1 セッション | Level 1 発火の判定 |
| 中期 | 直近 7 日 | Level 2 発火の追加条件 |
| 長期 | 直近 30 日 | ベースライン（シャドーモード期間と一致） |

**発火条件:**
- **Level 1:** いずれかのウィンドウで 2 指標以上が閾値超過、または合計 3 指標以上 → 加速減衰
- **Level 2:** 短期 + 中期の **両方** で 2 指標以上が閾値超過、または合計 5 指標以上 → ロールバック
- 短期だけで Level 2 を発火させない（一時的な偏りと区別するため）

### 4.2 回帰の 3 段階

既存の Somatic Calibration（S.1.5）の日次回帰パターンを踏襲。

#### Level 0: 日常（自然減衰）

```python
weights = weights * 0.99 + default_weights * 0.01
```

- 毎晩の Sleep Cycle で自動実行
- 学習しなければ約 70 日でデフォルトに戻る
- S.1.5 somatic calibration と同じパターン

#### Level 1: 軽度異常（加速減衰）

```python
weights = weights * 0.9 + default_weights * 0.1
```

- 検出条件: 上記指標の 1〜2 個が閾値超過
- 1 晩で 10% デフォルトに近づく（約 7 日で実質リセット）
- ログに記録、次の日のセッションは通常通り

#### Level 2: 重度異常（チェックポイント・ロールバック）

```python
# 最新チェックポイント（= 問題のある学習結果）をスキップし、2番目に新しいものに復元
weights = load_checkpoint(second_latest)
```

- 検出条件: 短期 + 中期の両方で 2 指標以上が閾値超過、または合計 5 指標以上
- **2番目に新しいチェックポイント** に復元（最新は問題のある学習直後の結果であるため）
- チェックポイントが存在しない場合はフレッシュモデルにリセット
- `telemetry_kv` に `nia_core_rollback` イベント記録
- **Origin に通知**（identity_proposals と同じパターン）

### 4.3 チェックポイント管理

```python
# Sleep Cycle の orchestrator で実行（trainer 後、health 検査後）
train_result = await run_training()
report = run_health_check()
apply_regression(report.level)
save_checkpoint_if_healthy(train_result)  # L0 のみ保存

# save_checkpoint_if_healthy の内部:
# 1. health check が L0 以外 → 保存しない
# 2. シングルトンの現在の重み（regression 適用後）を保存
# 3. prune_checkpoints(max_keep=3) で古いものを削除
```

- **健全な時だけ保存** — L1/L2 中のチェックポイントは作られない
- **3 世代保持** — Level 2 ロールバック先が複数ある（2番目に新しいものを使用）
- **regression 適用後の重みを保存** — 自然減衰/加速減衰が反映された状態

### 4.4 パラメータドリフト防止（ハード制限）

```python
def clamp_weights(weights, default_weights, max_drift=0.3):
    """各パラメータが default から ±30% 以上離れない"""
    for name, param in weights.items():
        center = default_weights[name]
        param.clamp_(center * (1 - max_drift), center * (1 + max_drift))
```

- **学習時に毎回適用。** Sleep を待たずにリアルタイムで境界を保証
- max_drift = 0.3 は初期値。運用データを見て調整

---

## 5. 導入計画

### 5.1 シャドーモード

いきなり本番に組み込まない。既存ルールベースで動かしつつ、裏で NiaCore に同じ入力を与え、判断をログに記録する。

```
本番パス:  State → ルールベース → Depth 選択 → 実行
シャドー:  State → NiaCore → ログ記録のみ（実行しない）
```

### 5.2 卒業条件（全て同時に満たす）

| 条件 | 閾値 | 理由 |
|------|------|------|
| シャドー期間 | ≥ 30 日 | 十分なデータ蓄積 |
| 蓄積ターン | ≥ 500 | 統計的に有意なサンプル数 |
| ルールベースとの一致率 | ≥ 85% | 基本動作の再現 |
| 逸脱時の事後良好率 | ≥ 60% | ルールベースを超える判断力 |
| 全 Depth の選択率 | ≥ 5% | 崩壊していない（Mode Collapse 検知） |

**指標の定義（ログから一意に計算可能）:**

```
outcome_known := review_checked = 1 AND correction_window_closed = 1

agreement_rate      := count(NOT is_deviation) / count(*)
deviation_good_rate := count(is_deviation AND outcome_known AND good) / count(is_deviation AND outcome_known)
good                := review_rejected = 0 AND user_correction = 0
```

※ `agreement_rate` は全ターンで計算（純粋に「同じ判断をした割合」）。
※ `deviation_good_rate` は `outcome_known` のみで計算（結果不明のターンでは「良かった」と言えないため）。
※ `outcome_known` は「イベント発生」ではなく「観測期間の閉鎖」で判定（§3.3 と同じ定義）。

### 5.3 シャドーモード・ダッシュボード指標

シャドーモード中に以下の指標を記録・可視化する。卒業判定と探究性の観測に使用。

| 指標 | 目的 | 報酬に使うか |
|------|------|-------------|
| ルールベースとの一致率 | 卒業条件 | — |
| 逸脱時の事後良好率 | 卒業条件 | — |
| 全 Depth 選択率分布 | Mode Collapse 検知 | — |
| `surprise_collapse` 監視 | surprise 判定の固着検出 | **No**（状態のみ） |
| 逸脱成功回の「後続訂正率」推移 | 探究性の質の観測 | **No**（観測のみ） |
| 逸脱回の「会話自然継続」率 | 逸脱が対話を壊さないか | **No**（観測のみ） |

**設計判断:** surprise / learnability は報酬に入れない（迎合報酬に落ちるリスク）。代わりにダッシュボードで観測し、NiaCore が「安全に探究的か」を人間が判断する。

### 5.4 切替後

- NiaCore の出力を depth_selector の入力に追加
- ルールベースは **並行して動き続ける**（比較用 + フォールバック）
- Level 2 ロールバック時はルールベースに自動切替

---

## 6. 前提実装（NiaCore 実装前に必要）— **全完了**

NiaCore の学習に必要なデータを蓄積するための下ごしらえ。全 Step 実装完了済み。

### 実装順序: 3 → 2 → 1

#### Step 3: ルールベース depth 選択の記録（最優先・最軽量）

`routing.py` で計算済みの `selected_depth` をターン記録に保存する。シャドーモードの比較データが即座に溜まり始める。

#### Step 2: review_window の判定結果をターン記録に紐づけ

現在独立している review_window の承認/却下結果を、ターンの記録にマージする。Sleep Cycle 実行時までにフラグが確定している必要がある。

#### Step 1: correction 検出の実装（最も複雑）

ユーザー訂正をルールベースで検出する。LLM 不要。

**方針:** 検出は **strong / weak / none** の 3 値を返す。**報酬に使うのは strong のみ。** weak はログ観測用（学習・卒業判定には使わない）。誤検知が -0.8 の報酬として入ると学習が汚染されるため、「検出する」と「学習に使う」を分離する。

**strong の条件:**
- **文頭否定詞 + 修正指示:** 「違う、X じゃなくて Y」「そうじゃなくて、〜して」
- 直前のニア発話の核心に対して、否定 + 置換が起きている
- 文頭否定詞（「いや、」「違う、」「そうじゃなくて、」）を **必須条件** とする

**weak の条件:**
- 話題急転換（直前のニア発話とユーザー入力の単語重複度が閾値以下）
- ターン長の急変（ニアが長文 → ユーザーが短文で返す）
- ※ weak は雑談・気分・割り込みでも起きるため、報酬には使わない

**誤検知対策:**
- strong は文頭否定詞を必須にすることで precision を優先
- 「昨日の映画、思ってたのと違ったわ」は文頭否定詞がないため除外される
- review_window 却下と同時発生した strong は true と見なす（整合確認）
- weak は `correction_spike`（§4.1）の監視には使えるが、報酬計算からは除外
- Step 2 の review_window データと照合して strong の精度を検証可能

---

## 7. 技術スタック

| コンポーネント | 技術 |
|--------------|------|
| LNN 実装 | `ncps` (Neural Circuit Policies) — CfC モード |
| 学習フレームワーク | PyTorch |
| Experience Replay | SQLite（既存 DB と同居） |
| チェックポイント | `data/niacore/checkpoints/niacore_YYYYMMDD_HHMMSS.pt` (torch state_dict) |
| テレメトリ | 既存の `telemetry_kv` テーブル |

---

## 8. ファイル構成

### NiaCore コアモジュール（`backend/core/niacore/`）

| ファイル | 内容 | 状態 |
|---------|------|------|
| `model.py` | CfC モデル定義（34次元入力, CFC_UNITS=64）、StateVector、推論、ハードクランプ、チェックポイント | **実装完了** |
| `shadow.py` | シャドーモード推論（ルールベースと並行）、卒業条件判定 | **実装完了** |
| `trainer.py` | 報酬計算、Credit Assignment、Sleep Cycle バッチ学習 | **実装完了** |
| `health.py` | 暴走検出（6指標×3ウィンドウ）、回帰ロジック（L0/L1/L2）、チェックポイント管理 | **実装完了** |
| `experience_writer.py` | Experience Replay Buffer の書き込み（record_turn_experience, close_correction_window） | **実装完了** |

### 変更済みファイル

| ファイル | 変更内容 |
|---------|---------|
| `backend/core/config.py` | `NIACORE_EXPERIENCE_ENABLED`, `NIACORE_SHADOW_ENABLED`, `NIACORE_TRAINING_ENABLED` フラグ追加 |
| `backend/core/db.py` | `niacore_experience` テーブルのスキーマ追加 |
| `backend/core/agent_graph/state.py` | `niacore_shadow` フィールド追加 |
| `backend/core/agent_graph/nodes/routing.py` | shadow_infer 呼び出し + 結果を state に格納（base64 エンコード） |
| `backend/core/agent_graph/nodes/actions.py` | shadow データ取得 + experience_writer 呼び出し |
| `backend/scripts/sleep_cycle/orchestrator.py` | NiaCore 学習フェーズ追加（train→health→regression→checkpoint） |
| `backend/services/memory/somatic_feedback.py` | `detect_correction_level()` — strong/weak/none |

### テスト

| ファイル | テスト数 | 内容 |
|---------|---------|------|
| `tests/test_niacore_model.py` | 15 | forward shape, infer, speed, state vector, blob roundtrip, clamp, checkpoint |
| `tests/test_niacore_shadow.py` | 7 | shadow result, deviation, depth label, error handling, graduation |
| `tests/test_niacore_trainer.py` | 12 | reward 5パターン, credit assignment, continued, training loop |
| `tests/test_niacore_health.py` | 15 | L0/L1/L2 判定, regression 3レベル, checkpoint |
| `tests/test_niacore_experience.py` | 10 | experience writer 基本操作 |
| `tests/test_correction_split.py` | 34 | correction strong/weak 検出 |

---

## 9. 設計判断の記録

| 判断 | 理由 |
|------|------|
| CfC（ODE ソルバーなし） | < 1ms の推論。LLM のレイテンシに影響しない |
| State に LLM 出力を含めない | LLM 交換可能性の保証。過剰適合防止 |
| ターンごとの学習を禁止 | 破局的忘却の防止。Sleep Cycle バッチ学習のみ |
| Imitation Learning ベースライン | 方策崩壊の防止。ルールベースを教師にする |
| 逸脱 + 結果不明 = 0.0 | 「逸脱しない」局所最適解への収束を防ぐ |
| セッション離脱を報酬に使わない | 因果不明確。ノイズが報酬を汚す |
| surprise 変動を報酬に使わない | 良い驚きか悪い驚きか区別不能。ダッシュボードで観測のみ |
| Body Constitution を NiaCore 管轄外にする | 直感が法律を書き換えてはならない |
| シャドーモード 30 日必須 | 十分なデータ蓄積と安全性確認 |
| 全 Depth 選択率 5% を卒業条件に含める | Mode Collapse 検知 |
| チェックポイント 3 世代保持 | ロールバック先の選択肢確保 |
| max_drift = 0.3 | 初期値。運用データで調整 |
| 会話継続 = 次ターン AND 訂正なし AND 却下なし | 「訂正されたけど続いた」をノイズとして除外 |
| 逸脱判定を argmax 不一致で固定 | 比較がブレると学習が崩壊する |
| selected_depth と policy_logits を分離記録 | 確率分布の解析と逸脱判定の再現性 |
| Credit Assignment をイベント種別で分離 | 因果の近さがイベントごとに異なる |
| surprise 算出にバージョン番号 | 仕様変更時の学習データ整合性 |
| 暴走検出に多層ウィンドウ（短期/中期/長期） | Level 2 ロールバックの暴発防止 |
| correction を strong/weak に分離 | 誤検知が報酬を汚染するのを防ぐ（学習毒の排除） |
| 報酬に使うのは correction_strong のみ | weak は雑談・割り込みでも発火する。ログ観測のみ |
| 出力ヘッドを段階導入（depth → retrieval → surprise → somatic） | 原因追跡が容易。全ヘッド同時学習は事故りやすい |
| 卒業条件の指標定義を数式で固定 | ログから一意に計算可能。定義が曖昧だと測定が壊れる |
| depth_entropy をログ記録 + 判定に使用 | Mode Collapse の早期検知。Shannon entropy < 0.5 で triggered |
| L2 ロールバックは2番目に新しいチェックポイントに復元 | 最新チェックポイントは問題の学習直後の結果であるため |
| state_vector_blob は AgentState 内で base64 エンコード | LangGraph の JSON チェックポイントシリアライズとの互換性 |
| シングルトンモデルで推論・学習・回帰を一貫管理 | `_get_model()` / `_set_model()` で参照の一貫性を保証 |
| チェックポイント保存は orchestrator フローで health 検査後のみ | trainer 内での保存を禁止し、健全性検査をバイパスさせない |

---

## 10. 検証計画

1. **ユニットテスト:** CfC モデルの推論、報酬計算、ハードクランプ、暴走検出
2. **シャドーモード検証:** 30 日間のログからルールベースとの比較分析
3. **回帰テスト:** Level 0/1/2 の回帰が正しく動作するか
4. **崩壊検知テスト:** 意図的に偏った報酬を与えて卒業条件でブロックされるか
5. **LLM 交換テスト:** モデル変更後に NiaCore の判断が維持されるか
6. **回帰テスト（既存機能）:** NiaCore 導入後に既存パイプラインが壊れていないか

---

## 付録 A: Gemini レビューの要点

Gemini（外部レビュー）から得た指摘と、本設計での対応:

| Gemini の指摘 | 本設計での対応 |
|--------------|--------------|
| LLM 過剰適合リスク | State を LLM 非依存に限定（§2.3） |
| 方策崩壊（Policy Collapse） | Imitation Learning ベースライン（§3.2） |
| 破局的忘却 | Sleep Cycle バッチ学習（§3.1） |
| シャドーモード必須 | 30 日 + 5 条件の卒業基準（§5.2） |
| Credit Assignment | イベント種別ごとの分配ウィンドウ（§3.2） |
| マルチヘッド出力 | 離散（Softmax）+ 連続（Tanh/Sigmoid）（§2.2） |

## 付録 B: 実装レビュー（v0.2 追加分）

壁打ちレビュー（Claude）で得た指摘と対応:

| 指摘 | 対応 |
|------|------|
| 会話継続の定義が曖昧 → ノイズ混入 | 次ターン AND correction=False AND review_rejected=False に厳密化（§3.2） |
| 逸脱判定が JSON レベルで不安定 | argmax 不一致で固定 + selected/logits 分離記録（§3.3） |
| Credit Assignment が一律 γ=0.9 | イベント種別で分配範囲を変更（§3.2） |
| surprise_threshold 学習には算出の安定性が必要 | surprise_v バージョニング導入（§2.3） |
| 暴走検出の誤検知リスク | 多層ウィンドウ（短期/中期/長期）で段階化（§4.1） |
| surprise/learnability を報酬に入れるべきか | 報酬には入れず、ダッシュボード指標として観測（§5.3） |

## 付録 C: 設計レビュー第2ラウンド（v0.2 追加分）

深層レビュー（Claude 壁打ち用）で得た指摘と判断:

| 指摘 | 判断 | 理由 |
|------|------|------|
| correction 誤検知が学習毒になる | **採用:** strong/weak 分離。報酬は strong のみ（§6 Step1） | -0.8 は強い負。誤検知のコストが高すぎる |
| 卒業条件の「事後良好率」定義が曖昧 | **採用:** 数式で固定（§5.2） | ログから一意に計算不能だと測定が壊れる |
| depth_entropy をログ記録 | **採用:** 暴走検出指標に追加（§4.1） | コスト低、Mode Collapse 早期検知に有効 |
| 出力ヘッドを段階導入すべき | **採用:** depth→retrieval→surprise→somatic の順（§2.2） | 全ヘッド同時は原因追跡が困難 |
| +0.1 → +0.05 に下げるべき | **保留:** シャドーモードのデータで判断 | 実データなしの微調整は空回り |
| 連続値を bucket 比較すべき | **保留:** depth_preference のみで開始 | 4ヘッド同時定義は実装が重すぎる |
| 派生カラム（outcome_known 等）をスキーマに追加 | **不採用:** 報酬計算時に動的算出 | 定義変更時にカラムが腐る。生データから再計算の方が強い |

## 付録 D: 実装レビュー（v0.3 追加分）

Phase 1〜6 実装完了後の多視点レビュー（設計書準拠 + コード品質/セキュリティ）で発見・修正した項目:

| 問題 | 修正内容 | 影響 |
|------|---------|------|
| `state.pop()` で AgentState を直接変更 | `.get()` に変更（LangGraph の不変性違反） | routing → actions のデータ受け渡し |
| trainer 内でチェックポイント保存 → health 検査バイパス | trainer から保存を除去。orchestrator で health 後に保存 | 暴走中の重み保存防止 |
| `apply_regression()` が新しいモデルに対して操作 | シングルトン `_get_model()` を使用 | regression が実際に反映されるように |
| L2 が最新チェックポイント（= 問題の学習結果）に復元 | 2番目に新しいチェックポイントに復元 | 問題の重みをスキップ |
| `state_vector_blob` が raw bytes で AgentState に入る | base64 エンコード/デコード | LangGraph JSON シリアライズ互換 |
| `surprise_v` が experience に書き込まれない | writer に `surprise_v` パラメータ追加 | surprise_collapse 検出の精度 |
| deviation_success の credit assignment 未実装 | lookback=2 で追加 | 成功報酬の因果帰属 |
| L2 が短期ウィンドウだけで発火可能 | short+medium 両方 2+、または合計 5+ に修正 | 一時的偏りでのロールバック暴発防止 |
| 卒業判定の deviation_success_rate に outcome_known フィルタなし | `review_checked=1 AND correction_window_closed=1` 条件追加 | 結果不明のターンを「成功」と誤判定しない |

### 残存する設計書との差異（意図的）

| 項目 | 設計書 | 実装 | 理由 |
|------|--------|------|------|
| `somatic_divergence` 指標 | §4.1 で定義 | プレースホルダー（将来実装） | somatic_translator の適応的閾値データが未蓄積 |
| `retrieval_miss` 指標 | hit rate < 0.3 | D0 比率 > 0.9 を代理指標 | retrieval_hit_rate の AgentState 伝搬が未実装 |
| `surprise_collapse` | 記憶保存率 0.95/0.05 | surprise_v 平均の正規化で判定 | 記憶保存率はメトリクス経路が異なるため代理 |
| confidence メトリクス名 | v0.2: memory_relevance 等 | v0.3: context_coverage 等 | 実コードベースのメトリクス名に合わせて修正済み |

### 将来対応（Phase 2 以降）

| 項目 | 優先度 | 依存 |
|------|--------|------|
| `somatic_divergence` 実データ接続 | 中 | somatic_translator の適応的閾値データ蓄積 |
| `retrieval_miss` を実 hit rate に接続 | 中 | AgentState に retrieval_hit_rate 伝搬 |
| `surprise_collapse` を実記憶保存率に接続 | 低 | メトリクス経路の整理 |
| confidence メトリクス名の正規化マッピング | 低 | confidence エンジンのリファクタリング時 |
| シングルトンのスレッドセーフ化（Lock） | 低 | 同時リクエスト増加時 |
| ミニバッチ + シャッフル学習 | 低 | 学習データが batch_size を大きく超えた時 |
