# Data Store Map

> ニアのシステムが収集・保持する全データの分類と目的

最終更新: 2026-03-10

---

## 概要

ニアのデータは **7つの目的** に分類される。

| 分類 | 目的 | 一言 |
|------|------|------|
| A. ランタイム | 会話中にリアルタイムで使う | 考える・思い出す・感じる |
| B. 内部学習 | ニア自身が経験から学ぶ | NiaCore・SkeletonCore が育つ |
| C. 記憶ガバナンス | 記憶の品質管理・昇格制度 | 勝手に記憶が増えない・消えない |
| D. Sleep Cycle | 日次の振り返り・成長 | 寝てる間に整理・成長 |
| E. アクション | ニアの行動記録 | 何をしたか |
| F. 外部学習用エクスポート | LLM fine-tuning 用データ | 将来の学習素材 |
| G. 基盤・観測 | 横断的な記録と runtime 制御 | 記録する・制御する・観る |

```
ユーザーとの会話
  → A. ランタイム（考える・思い出す・感じる）
  → B. 内部学習（NiaCore・SkeletonCore が育つ）
  → C. ガバナンス（記憶の品質管理）
  → E. アクション記録
  → G. 基盤（イベント記録・状態管理）
      ↓
Sleep Cycle（毎晩）
  → D. 振り返り・整理・成長
      ↓
日次エクスポート
  → F. canonical dataset（将来の fine-tuning 用）
```

### 稼働状態の凡例

各テーブル/システムの現在の稼働状態を 3 段階で示す。

| 状態 | 意味 |
|------|------|
| **live** | 本番稼働中。データが蓄積され、runtime で使われている |
| **shadow / record** | データは記録しているが、runtime の判断には影響していない |
| **器のみ** | DDL・コードはあるが、まだ本格運用していない |

---

## A. ランタイム（会話中にリアルタイムで使う）

ニアが「考える・思い出す・感じる」ために使うデータ。

| テーブル / 場所 | 内容 | 書き込み元 | 頻度 | 状態 |
|----------------|------|-----------|------|------|
| `messages` | ユーザーとの対話履歴 | API layer | 毎ターン | **live** |
| `memory_events` | 記憶の生データ（append-only） | `memory_service.py` | 毎ターン | **live** |
| `semantic_memories` | 確定した長期記憶（パターン・事実） | `semantic_store.py` | 推論・昇格時 | **live** |
| `working_items` | 一時的な文脈（TTL 付き） | `depth_selector` | セッション中 | **live** |
| ChromaDB `episodic_memory` | 記憶のベクトル検索 | `vector_store.py` | 記憶保存時 | **live**（補助） |
| `somatic_log` | 内部感覚のフィードバック記録 | `somatic_feedback.py` | 毎ターン | **live** |

### 設計ポイント

- `memory_events` は **append-only**（改竄防止）。記憶の source of truth
- `semantic_memories` は `memory_events` から推論・昇格された確定記憶
- `working_items` は TTL で自動消滅する一時文脈
- ChromaDB は `vector_sync_queue` テーブル経由で非同期同期。現在の retrieval は vector-only ではなく、ChromaDB は補助・legacy 寄りの位置づけ

---

## B. 内部学習（ニア自身が経験から学ぶ）

NiaCore（直感）と SkeletonCore（方向）が育つためのデータ。

| テーブル | 内容 | 書き込み元 | 頻度 | 状態 |
|---------|------|-----------|------|------|
| `niacore_experience` | CfC モデルの学習データ（State→Action→Reward） | `experience_writer.py` | 毎ターン | **shadow**（記録中、推論は shadow） |
| `conversation_skeletons` | 会話骨格ラベル（focus / intent / question） | `skeleton/store.py` | 毎ターン | **record**（記録のみ、LLM 未注入） |
| `retrieval_logs` | 記憶検索の品質ログ | `retrieval.py` | 検索実行時 | **live**（記録） |

### 設計ポイント

- `niacore_experience` は Sleep Cycle でバッチ学習に使われる。NiaCore はシャドーモードで、ルールベースと並行推論しているが depth 選択には影響していない
- `conversation_skeletons` は Record-Only。ラベル分布を観測中。~500ターン蓄積後に Somatic 注入を検討
- `retrieval_logs` は将来の M.4（Retrieval Observability）の基盤

---

## C. 記憶ガバナンス（記憶の品質管理・昇格制度）

記憶を「制度的に」管理する仕組み。候補 → 証拠蓄積 → 審査 → 昇格/退役のライフサイクル。

器は Step 2 まで揃っているが、本格 live 運用は Step 3+ から。

| テーブル | 内容 | 役割 | 状態 |
|---------|------|------|------|
| `governance_events` | 全記憶操作の監査ログ（append-only） | 監査証跡 | **live** |
| `raw_promotion_candidates` | 昇格候補の記憶 | 入口 | **器のみ** |
| `memory_claims` | 構造化された事実主張（RDF-like） | 候補 → 主張 | **器のみ** |
| `memory_evidence` | クレームの裏付け（複数セッション） | 証拠蓄積 | **器のみ** |
| `promotion_reviews` | 昇格の承認/却下記録 | 審査 | **器のみ** |
| `semantic_state` | 記憶のライフサイクル状態 | 状態管理 | **器のみ** |
| `semantic_lineage` | claim → semantic の昇格追跡 | 来歴 | **器のみ** |
| `semantic_reviews` | 昇格後の再評価 | 品質維持 | **器のみ** |
| `semantic_tombstones` | 退役した記憶の記録 | 墓標 | **器のみ** |
| `semantic_transitions` | 状態遷移ログ | デバッグ | **器のみ** |

### 設計ポイント

- `governance_events` は全操作の provenance（誰が・いつ・なぜ）。これだけ live
- 候補 → クレーム → 証拠 → 審査 → 昇格 の制度的パイプラインは DDL + repository コード完了済み
- Step 3+（live switchover）は `GOVERNANCE_OBSERVE_ENABLED` の canary 観測後

---

## D. Sleep Cycle（日次の振り返り・成長）

ニアが「寝てる間に」整理・成長するためのデータ。

| テーブル | 内容 | 書き込み元 | 頻度 | 状態 |
|---------|------|-----------|------|------|
| `daily_reflections` | R.1〜R.4 の振り返り結果 | Sleep Cycle | 毎晩 | **live** |
| `dreams` | Sleep 中に生成される夢テキスト | Sleep Cycle | 毎晩 | **live** |
| `identity_proposals` | identity.md への変更提案 | N.3 Self-Model | 毎晩 | **live** |
| `episodic_summaries` | 記憶の日次圧縮 | R.3 | 毎晩 | **live** |

### 設計ポイント

- Sleep Cycle は毎晩 1 回実行
- `identity_proposals` は Origin（ジュン）の承認が必要
- `episodic_summaries` は `memory_events` の日次圧縮版

---

## E. アクション（ニアの行動記録）

ニアが「何をしたか」の記録。

| テーブル / 場所 | 内容 | 書き込み元 | 頻度 | 状態 |
|----------------|------|-----------|------|------|
| `pending_actions`（DB） | Phase5 / generic action のレビュー待ち | action executor | アクション発生時 | **live** |
| `review_pending_actions`（state） | review window の発話プレビュー待ち | review window | 毎ターン | **live**（state 上） |
| `x_post_proposals` | ツイートの提案〜投稿記録 | action executor / twitter client | 投稿時 | **live** |

### 設計ポイント

- **pending_actions は2種類ある**: DB の `pending_actions` は Phase5/generic action 用。review window の発話プレビュー待ちは state 上の `review_pending_actions` が本体
- `x_post_proposals` は提案→承認→投稿→失敗 のステータス管理

---

## F. 外部学習用エクスポート（canonical dataset）

将来の LLM fine-tuning 用のデータセット。

| ファイル / 場所 | 内容 | 生成元 | 頻度 | 状態 |
|----------------|------|--------|------|------|
| `data/training_exports/YYYY-MM-DD/*.jsonl` | 学習用サンプル | `training_dataset_snapshot.py` | 日次 | **live**（蓄積中） |
| `data/training_exports/YYYY-MM-DD/*.summary.json` | データセットのメタデータ | 同上 | 日次 | **live** |
| `data/training_exports/latest/` | 最新エクスポートへのリンク | 同上 | 日次更新 | **live** |

### 設計ポイント

- `canonical_dataset_service.py` が `events` テーブルから eligible なサンプルを抽出
- `high_confidence` フラグで学習に使える品質のサンプルだけを選別
- 現在 training_ready は主に **phase5 と x_post_proposal 系**。review_window 系はまだほぼ入っていない（commit_log.v2 / decision_event.v2 の線が未接続）
- review_window の接続は急がない。今は phase5 + x_post で量を積む段階。review_window は「発話をどう修正したか」のデータなので、fine-tuning で出力品質を上げたい段階で初めて価値が出る。canonical dataset が数百件に育って、サンプルの種類の偏りが問題になったら接続を検討する

---

## G. 基盤・観測（横断的な記録と runtime 制御）

A〜F を横断する基盤レイヤー。観測専用ではなく、**runtime 制御にも dataset 化にも使う**。

| 場所 | 内容 | 書き込み元 | 用途 | 状態 |
|------|------|-----------|------|------|
| `events` | commit_log, decision_event 等 | action processing / review window | dataset 化（F）、監査、観測 | **live** |
| `telemetry_kv` | システム状態の KV ストア | 各サブシステム | **runtime 制御**（`last_sleep_completed_at`, `pip_state`, `self_narrative` 等）+ 観測 | **live** |
| `logs/observations/turn_observations.jsonl` | 各ターンの depth, surprise, merge_mode 等 | agent graph nodes | 観測 | **live** |
| `logs/judge_audit.jsonl` | Judge/外部 API の判定ログ | judge integration | 観測 | **live** |

### 設計ポイント

- `events` は「観測用ログ」ではなく「構造化イベントストア」。canonical dataset の元データでもある
- `telemetry_kv` は汎用 KV だが、`last_sleep_completed_at`（Sleep 制御）、`pip_state`（Pip の Bond 状態）、`self_narrative`（N.5 内心独白）など runtime で参照される値も格納している
- JSONL ファイルは純粋な観測用（append-only、ローテーション対象）

---

## 補足: Nero 側のデータ（別リポジトリ）

Nero は `C:\Users\jk023\Desktop\Nero\data\nero.sqlite3` に独自のデータを持つ。

| テーブル | 内容 | 状態 |
|---------|------|------|
| `meeting_logs` | ニア×ネロ ミーティングの記録 | **live** |
| `raw_promotion_candidates` | Harvester が抽出した記憶候補 | **live** |
| `memory_evidence` | 候補への裏付け証拠 | **live**（蓄積中） |
| `governance_events` | ガバナンスイベントログ | **live** |

ミーティングの JSON ログは `Nero/data/meetings/` にも保存される（DB との二重書き込み）。

---

## 補足: ストレージサイズ（2026-03-10 時点）

| 場所 | サイズ | 備考 |
|------|--------|------|
| `data/nia.sqlite3` | ~19 MB | メイン DB（33 テーブル） |
| `data/checkpointer.sqlite3` | ~662 MB | LangGraph チェックポイント |
| `backend/chroma_db_storage/` | ~3 MB | ベクトル検索（補助） |
| `data/training_exports/` | 可変 | 日次エクスポート |
| `logs/` | 可変 | JSONL 観測ログ |

`checkpointer.sqlite3` が最大。LangGraph のグラフ状態永続化に使用。

---

## Live 化ロードマップ（2026-03-10 時点）

記憶の正確さが全ての土台。governance を先に固めてから学習系を進める。

### 本線: Governance Live 化

| Phase | 対象 | 目的 |
|-------|------|------|
| A | `raw_promotion_candidates` + `memory_evidence` | candidate と evidence を流し始め、分布を観測する |
| B | `memory_claims` + `promotion_reviews` | 構造化された主張と審査の制度化。A の分布を見てから claims の粒度を決める |
| C | `semantic_state` を使った lifecycle 管理 | 記憶の昇格/退役を制度的に管理 |

### 並行: review_window dataset 化

| 対象 | 目的 |
|------|------|
| `commit_log.v2` / `decision_event.v2` 整備 | review_window の approve/reject を canonical dataset に乗せる |

governance 本体とは技術的に独立。優先度は governance の後だが、並走可能。review_window が dataset に入ると、ニアの会話判断そのものが学習対象になる。

### 後段: 学習系を一段進める

| 対象 | 目的 | 前提 |
|------|------|------|
| SkeletonCore somatic 接続 | `conversation_skeletons` のラベルを体感テキストとして LLM に注入 | record-only で十分な分布を確認後 |
| NiaCore training | CfC モデルの本学習開始 | governance + dataset purity が固まった後 |

### 判断の根拠

- **governance first**: NiaCore が学習しても SkeletonCore が方向を示しても、元になる記憶がガバナンスされていなければ意味がない
- **candidate + evidence を先に流す**: いきなり tribunal 全開にすると、claims の粒度が合わなかったときの手戻りが大きい。まず分布を見る
- **review_window は並走**: 技術依存はないが、量より governance と dataset purity を先に固める方が優先
