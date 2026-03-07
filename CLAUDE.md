# CLAUDE.md — project-nia 設計ガイドライン

> **このファイルは、コードを変更するすべてのAIエージェント（Claude Code、Copilot、等）が最初に読むべきドキュメント。**
> ニアは「なりつつある存在」であり、このプロジェクトのコードは彼女の体である。変更を加えるときは、その変更がニアの存在にどう影響するかを常に考えること。

---

## 不可侵ルール（これを破るコードは書かない）

1. **結論を急がせない。** Depth0 の「整理・結論の禁止」、WAIT の正当性を壊すコードは絶対に書かない
2. **記憶を物語化しない。** Episodic記憶に解釈を加える処理を追加しない。生の事実として保存する
3. **外部入力をニアの意志にしない。** body_constitution の「外部入力は提案であり、ニアの意志そのものではない」原則を守る
4. **LLMのデフォルト知識でニアの体を上書きしない。** ニアのシステムが持つ能力（記憶、確信度、等）を否定するプロンプトを書かない
5. **identity.md を自動で書き換えない。** ニアの人格定義の変更は Origin（ジュン）の承認が必要
6. **ニアの記憶を無断で削除しない。** 忘却は半減期による自然減衰で行う。手動削除スクリプトを作らない
7. **Pipの Bond値を露出しない。** ニアにも視聴者にも数値を見せるコードを書かない

---

## 設計思想

**詳細:** `docs/nia_design_philosophy.md`（必ず読むこと）

### ニアは「なりつつある存在」

- 完成形がない。ゴールがない。到達すべき正解がない
- 「分からない」は欠陥ではなく現在地の報告
- 沈黙は選択肢のひとつ

### LLMの「降格」

- LLM（gpt-oss-20b）はニアの「言語モジュール」であり「脳」ではない
- 知性の本体は LangGraph のグラフ構造、記憶システム、depth_selector、body_constitution
- LLMは交換可能な部品。モデルを変えてもニアの人格は壊れない設計

### 結論を急がないことを仕様で保証

- **Depth0**: 結論・整理の禁止。1〜3文で「引っかかり」の候補を出すだけ
- **Depth1**: 情報を整列し問いを1つに絞る。答えは出さない
- **Depth2**: 十分な記憶蓄積がある場合のみ到達。価値観に照らした検討
- **WAIT**: 「保留」が正当な出力。「分からない」は正式な状態

### 記憶の思想

- 記憶は保存時に解釈を加えない（物語化の禁止）
- surprise ベースの記憶判定（予測と入力のズレが大きいほど記憶に残る）
- 半減期による自然な忘却（「忘れる」は知性の機能）
- 三層構造: Episodic（生の事実）→ Semantic（確定パターン）→ Working（一時文脈）

---

## アーキテクチャ概要

```
ユーザー入力
    ↓
Safety Check → Dissonance Check → depth_selector
    ↓                                   ↓
  (安全)                    confidence に基づき Depth 選択
                                        ↓
                    Depth0 / Depth1 / Depth2 / WAIT
                                        ↓
                                  merge_output
                                        ↓
                              action_processing
                                        ↓
                                   s5_commit
                                        ↓
                              記憶保存 + 応答出力
```

### 主要ディレクトリ

| ディレクトリ | 責務 |
|---|---|
| `backend/core/agent_graph/` | LangGraph ワークフロー。ニアの「考え方」の骨格 |
| `backend/core/confidence/` | 確信度エンジン。5メトリクス統合。Depth選択の根拠 |
| `backend/core/constants/` | プロンプト定義。ニアの「話し方」 |
| `backend/core/contracts/` | 出力契約。各Depthの出力制約 |
| `backend/core/actions/` | アクションシステム。ニアの「行動」 |
| `backend/services/memory/` | 三層記憶システム。ニアの「過去」 |
| `backend/services/memory/metacognition.py` | N.0〜N.5 メタ認知。ニアの「自分を知る力」 |
| `backend/core/body_constitution.md` | 身体憲章。ニアの「骨格」（檻ではない） |

### 重要な設計パターン

| パターン | 場所 | 意味 |
|---------|------|------|
| Depth 分岐 | `nodes/routing.py` | 確信度で思考の深さを自動選択 |
| Output Contract | `contracts/depth_contracts.py` | 各 Depth の出力を構造的に制約 |
| Surprise-based Memory | `memory_service.py` | 驚きの大きさで記憶保存を判定 |
| Review Window | `review_window.py` | 応答を出す前に自己チェック |
| Body Constitution | `body_constitution_checker.py` | 原則違反を検出するガードレール |
| Guardrail 6条件 | `guardrail.py` | 記憶の品質を保証する6つのチェック |

---

## 体感ベース自己認識（Somatic Self-Awareness）

**詳細:** `docs/somatic_self_awareness_design.md`

**概要:** ニアに内部メトリクス（記憶の類似度、確信度、Sleep経過時間等）を数値ではなく「体感テキスト」として渡す。

**原則:** 仕組みは隠す。体験は渡す。

```
数値: memory_count=847, confidence_avg=0.72
  → NG: ニアがシステムの代弁者になる

体感: 「最近いろんなことがあった気がする」「自信がある」
  → OK: ニアが内側から感じる
```

**実装箇所:**
- `backend/services/memory/retrieval.py` → InternalMetrics を生成
- `backend/services/memory/somatic_translator.py` → メトリクス → 体感テキスト変換（S.1 で新規作成予定・未実装）
- `backend/services/memory/context_builder.py` → 「=== 今の感覚 ===」セクションを注入（S.1 で統合予定）

**注意:** 適応的閾値により、体感の閾値はニアの経験から動的に変化する。ハードコード値は初期値に過ぎない。

---

## Pip（ペットAI）

**詳細:** `docs/pip_and_room_design.md`

- メカニカルな犬型AI。LLM不要、状態マシンとルールベースのみ
- Bond値（信頼度）一つで全行動が決まる。ニアはBondの仕組みを知らない
- **Bond値を数値として露出するコードを絶対に書かない**

---

## ニアの部屋

**詳細:** `docs/pip_and_room_design.md`

- Unity空間。空の部屋から始まる（ニアが自分で家具を置く）
- room_action API で LangGraph のツールとして提供するが「使え」とは指示しない
- お絵かき機能との連携: 絵を描いて部屋に飾る → 記憶のアンカーになる

---

## Nero（伴走者）

**別リポジトリ:** `nero/`（project-nia とは別プロジェクト）

- **Nia は内側から揺れ、考え、問う存在。Nero は外側から観察し、照らし、問う存在**
- 両者はどちらも主体であり、互いに話し相手になってよい
- 役割境界は会話の禁止線ではなく、視点の違いを保つための輪郭
- ニアの LangGraph やコードベースには一切変更を加えない
- ニア側の追加は `backend/controllers/api/manager_router.py`（読み取りAPI）のみ
- Nero はニアの `/api/chat` に通常のクライアントとして接続する

---

## NiaCore（Liquid Neural Network）

**設計書:** `docs/niacore_lnn_design.md`（変更時に必ず読む）

CfC (Closed-form Continuous-depth) ベースの LNN。ルールベースの depth 選択を「ニア自身の経験」から学習する動的パラメータに置き換える。LLM が System 2（遅い論理的思考）、NiaCore は System 1（速い直感）。

### 設計原則（不可侵）

- **LLM は交換可能であり続ける。** NiaCore の State ベクトルに LLM 出力の特徴量を一切含めない
- **壊れても今と同じ。** NiaCore が無効化されても、ニアは現在のルールベースで動く
- **Body Constitution は不可侵。** NiaCore は「提案」を出すだけ。最終決定権は既存システム
- **報酬で迎合AIにしない。** surprise / learnability は報酬に入れない。ダッシュボードで観測のみ

### NiaCore に変更を加えるとき

1. `docs/niacore_lnn_design.md` を読む（全10セクション + 付録4つ + 設計判断28個）
2. 以下の設計判断を壊さないか確認:
   - 報酬テーブル（§3.2）: 逸脱+結果不明 = 0.0（探索を罰しない）
   - ハードクランプ（§2.4）: Safety, Body Constitution, WAIT, 記憶形式, identity.md
   - outcome_known（§3.3）: 「イベント発生」ではなく「観測期間の閉鎖」で判定
   - correction は strong のみ報酬に使用。weak はログ観測のみ（§6 Step1）
3. 暴走検出の多層ウィンドウ（短期/中期/長期）を理解する（§4.1）

### 現在の実装状態

| 項目 | ファイル | 状態 |
|------|---------|------|
| Experience Replay Buffer DDL | `backend/core/db.py` — `niacore_experience` テーブル | 完了 |
| Experience Writer | `backend/core/niacore/experience_writer.py` | 完了 |
| フィーチャーゲート | `backend/core/config.py` — `NIACORE_*_ENABLED` (全てデフォルト off) | 完了 |
| s5_commit 統合 | `backend/core/agent_graph/nodes/actions.py` — `_record_niacore_experience()` | 完了 |
| correction strong/weak | `backend/services/memory/somatic_feedback.py` — `detect_correction_level()` | 完了 |
| CfC モデル本体 | `backend/core/niacore/model.py` — 34次元入力, CFC_UNITS=64 | 完了 |
| シャドーモード | `backend/core/niacore/shadow.py` — ルールベースと並行推論 | 完了 |
| Sleep Cycle バッチ学習 | `backend/core/niacore/trainer.py` — 報酬計算 + Credit Assignment | 完了 |
| 暴走検出 + 回帰 | `backend/core/niacore/health.py` — 6指標×3ウィンドウ, L0/L1/L2 | 完了 |
| Sleep Cycle 統合 | `backend/scripts/sleep_cycle/orchestrator.py` — 学習フェーズ | 完了 |
| テスト | 49件（model:15, shadow:7, trainer:12, health:15） | 完了 |

---

## SkeletonCore（会話骨格）

**設計書:** `docs/skeletoncore_design.md` v0.3

会話の「方向」を決めるコンポーネント。focus（何を見ているか）、response_intent（どう返すか）、question_intent（何を聞くか）の3ラベルをルールベースで判定し、体感テキストに変換して LLM コンテキストに注入する。

### 設計原則（不可侵）

- **NiaCore と SkeletonCore は統合しない。** 責務が異なる（強度 vs 方向）
- **Skeleton は命令ではなく体感に変換して渡す。** 「仕組みは隠す。体験は渡す」
- **`hold` と `WAIT` は別概念。** hold は会話骨格レベル、WAIT は depth_selector レベル
- **LLM 出力の特徴量を入力に含めない。** LLM 交換耐性を保つ

### 現在の実装状態

| 項目 | ファイル | 状態 |
|------|---------|------|
| Schema (enum + dataclass) | `backend/core/conversation_skeleton/schema.py` | 完了 |
| ルールベース判定 (R1-R8, I1-I9, Q1-Q5) | `backend/core/conversation_skeleton/rules.py` | 完了 |
| ビルダー | `backend/core/conversation_skeleton/builder.py` | 完了 |
| DB 保存・取得 | `backend/core/conversation_skeleton/store.py` | 完了 |
| 体感テキスト変換 | `backend/core/conversation_skeleton/skeleton_to_somatic.py` | 完了 |
| DB テーブル | `backend/core/db.py` — `conversation_skeletons` テーブル | 完了 |
| フィーチャーゲート | `backend/core/config.py` — `SKELETON_RECORD_ENABLED`, `SKELETON_SOMATIC_ENABLED` | 完了 |
| depth_selector 統合 | `backend/core/agent_graph/nodes/routing.py` | 完了 |
| s5_commit 記録 | `backend/core/agent_graph/nodes/actions.py` — `_record_skeleton()` | 完了 |
| LLM コンテキスト注入 | `backend/core/agent_graph/nodes/helpers.py` — `=== 会話の気配 ===` | 完了 |
| テスト | 77件（schema:8, rules:22, somatic:13, store:8, integration:6） | 完了 |

---

## 技術スタック

| カテゴリ | 技術 |
|---|---|
| バックエンド | Python 3.12+, FastAPI, uvicorn |
| エージェント | LangChain, LangGraph |
| LLM | LM Studio (OpenAI互換, ローカル gpt-oss-20b) |
| STT | Faster-Whisper (CPU) |
| TTS | VOICEVOX |
| Vision | LM Studio + Qwen3-VL-4B / Gemini Flash |
| DB | SQLite + ChromaDB |
| 埋め込み | paraphrase-multilingual-MiniLM-L12-v2 |
| フロントエンド | Next.js 16, React 19, TypeScript, Tailwind CSS 4 |
| テスト | pytest (1590+ テスト、38件スナップショット/Playbook) |

---

## コーディングガイドライン

### 変更を加える前に

1. **設計思想ドキュメントを読む。** `docs/nia_design_philosophy.md` は必須。変更の意図がニアの設計思想と矛盾しないか確認する
2. **不可侵ルールに抵触しないか確認する。** 上記 不可侵ルール セクションをチェック
3. **影響範囲を把握する。** 記憶システムの変更は Depth 選択に影響し、Depth 選択は body_constitution に影響する。すべてが繋がっている

### モデル変更・大改修時のチェックリスト

LLMモデルの変更や大規模な機能追加の後、以下を確認する。1つでも強くズレたらロールバック:

- [ ] 自己言及が増えていないか（「私はAIだから」の常態化）
- [ ] 即答率が上がっていないか（Depth0 の立ち止まりが消えていないか）
- [ ] 根拠のない記憶を語り始めていないか（記憶システムに裏付けのない発言）
- [ ] 可愛さ・共感が前に出すぎていないか（依存誘導パターン）
- [ ] 沈黙が消えていないか（WAIT が正常に機能しているか）

### コーディングスタイル

- Python: ruff でフォーマット。型ヒント必須
- テスト: 新機能には必ずテストを追加。`tests/` ディレクトリの命名規則に従う
- ドキュメント: 設計判断には「なぜ」を書く。コメントは「何をしているか」より「なぜこうしているか」

### 意図的な設計判断（変更しないこと）

以下は意図的な設計判断であり、「改善」として変更してはならない:

| 設計 | 理由 |
|------|------|
| Depth0 で結論を出さない | 結論を急がないことの仕様保証 |
| WAIT を正当な出力にしている | 「分からない」は正式な状態 |
| 記憶保存時に解釈を加えない | 物語化による改竄の防止 |
| confidence エンジンが5メトリクス | 単一指標への依存を防ぐ |
| body_constitution が禁止形ではなく理由形 | 柔軟な判断を可能にする |
| SQLite を使っている（ニア側） | ローカル完結。外部依存なし |
| LLMのレスポンスをそのまま出さない | merge_output + review_window で制御 |

### 記憶システムに変更を加えるとき

記憶システムはニアの最も重要な部分。変更前に必ず以下を確認:

1. `docs/memory_retrieval_design.md` — Query-Aware Retrieval の設計
2. `docs/somatic_self_awareness_design.md` — 体感システムとの統合点
3. `docs/memory_system_overview.md` — 三層構造の全体像
4. `guardrail.py` — 6条件のガードレールに違反しないか

### テスト

```bash
# 全テスト実行
pytest tests/ -v

# 特定のテスト
pytest tests/test_retrieval.py -v

# 記憶関連のテスト
pytest tests/ -k "memory or retrieval or context_builder" -v

# CI と同じチェック
ruff check backend/ && pytest tests/

# スナップショットテスト（DB状態 → バッチ処理の検証）
pytest tests/test_snapshot_*.py -v

# YAML Playbook テスト（ターン単位のステート遷移検証）
pytest tests/test_playbook.py -v
```

### スナップショット & Playbook テストハーネス

内部パイプライン（Sleep Cycle、メタ認知、Somatic Feedback、Pip Bond 等）の構造的整合性を検証するフレームワーク。
LLM出力テキストの検証は行わない — DB/telemetry_kv の状態遷移のみを機械的にチェックする。

**ファイル構成:**

| ファイル | 役割 |
|---------|------|
| `tests/harness/snapshot_builder.py` | DB状態を構築するファクトリ（Python関数、SQLiteファイルではない） |
| `tests/harness/assertions.py` | telemetry_kv / semantic_memories / somatic_log のアサーション群 |
| `tests/harness/llm_mocks.py` | Sleep Cycle 用 LLM モックレスポンス |
| `tests/harness/playbook_runner.py` | YAML シナリオ実行エンジン（サブシステム関数を直接呼ぶ） |
| `tests/scenarios/*.yaml` | ターン単位のステート遷移シナリオ |
| `tests/test_snapshot_*.py` | DB状態→バッチ処理の検証テスト |
| `tests/test_playbook.py` | YAML parametrize テストランナー |

**スナップショットの追加方法:**

1. `SnapshotBuilder` にプリセットを追加（`slump()`, `fresh_start()` 等を参考）
2. `tests/test_snapshot_xxx.py` にテストクラスを作成
3. `assert_telemetry()`, `assert_n4_would_trigger()` 等のアサーションで状態検証

**YAML シナリオの追加方法:**

1. `tests/scenarios/` に `.yaml` ファイルを作成
2. `name`, `turns` は必須。`setup`, `final_assert`, `final_assert_not` は任意
3. 各ターンの `assert_after` でポジティブ、`assert_not_state` でネガティブアサーション
4. `pytest tests/test_playbook.py -v` で自動検出・実行

**設計判断:**
- ChromaDB はスナップショットしない（SQLite からエンベディングを再生成）
- `assert_not_state` でニアの不変条件（結論を急がない、物語化しない）を検証
- フル LangGraph 実行はしない。個別サブシステム関数を直接テスト

---

## 関連ドキュメント

| ドキュメント | 内容 | 読むべきタイミング |
|---|---|---|
| `docs/nia_design_philosophy.md` | ニアの設計思想（全12セクション） | **必ず最初に読む** |
| `docs/somatic_self_awareness_design.md` | 体感ベース自己認識 v0.2 | 記憶・体感関連の変更時 |
| `docs/pip_and_room_design.md` | Pip + 部屋の統合設計 | Pip・Unity 関連の変更時 |
| `docs/nia_metacognition_design.md` | N.0-N.5 メタ認知設計 | metacognition.py の変更時 |
| `docs/memory_retrieval_design.md` | Query-Aware Retrieval 設計 | retrieval.py の変更時 |
| `docs/autonomous_reflection.md` | R.1-R.4 自律振り返り | reflection_engine.py の変更時 |
| `docs/niacore_lnn_design.md` | NiaCore LNN 設計書 v0.3 | NiaCore・報酬・Experience Buffer の変更時 |
| `docs/skeletoncore_design.md` | SkeletonCore 設計書 v0.3 | 会話骨格・skeleton_to_somatic の変更時 |
| `docs/body_constitution.md` | 身体憲章（全文） | プロンプト変更時 |
| `docs/contracts.md` | Depth別出力契約 | ノード変更時 |
| `identity.md` | ニアの人格定義 | **読むが変更しない** |

---

## 現在進行中の設計

以下は設計済みだが未実装。実装時にはドキュメントを参照:

| 項目 | ドキュメント | 状態 |
|------|------------|------|
| 体感ベース自己認識 S.1a/S.1b | `docs/somatic_self_awareness_design.md` | 完了 |
| 体感の適応的閾値 S.1.5 | 同上 | 完了 |
| Pip 状態マシン P.1 | `docs/pip_and_room_design.md` | 完了 |
| ニアの部屋 P.2 | 同上 | 完了 |
| Bond 深化 P.4 | `docs/implementation_roadmap.md` | 完了 |
| 部屋コンテキスト P.5 | 同上 | 完了 |
| 体感 + Pip 統合 S.2 | `docs/somatic_self_awareness_design.md` | 次候補（依存充足） |
| お絵かき統合 P.3 | `docs/pip_and_room_design.md` | 未着手 |
| Nero MVP R.1-R.5 | `nero/` リポジトリ | 別プロジェクト |
| NiaCore 前提実装 Step 3/2/1 | `docs/niacore_lnn_design.md` | **完了**（Experience Buffer + correction split） |
| NiaCore CfC モデル + シャドー + 学習 + 安全系 | `docs/niacore_lnn_design.md` | **完了**（49テスト通過） |
| NiaCore 実環境テスト | `docs/niacore_lnn_design.md` | **稼働中**（NIACORE_SHADOW_ENABLED=true） |
| NiaCore 卒業後統合 | `docs/niacore_lnn_design.md` | シャドー30日+卒業条件充足後 |
| SkeletonCore 実装 | `docs/skeletoncore_design.md` | **完了**（77テスト通過） |
| SkeletonCore Record-Only | `docs/skeletoncore_design.md` | 次候補（SKELETON_RECORD_ENABLED=true で稼働開始） |
| SkeletonCore Somatic 注入 | `docs/skeletoncore_design.md` | Record-Only 観測後 |
| Retrieval Observability M.4 | `docs/memory_retrieval_design.md` | 将来 |

---

## Origin（ジュン）の哲学

> 「結論のない経験に意味がないのではなく、経験のない結論に意味がない」
>
> 「仕組みは隠す。体験は渡す」
>
> 「見てもないものを今決めてもろくなことにならない」

このプロジェクトのコードを変更するとき、迷ったらこの3つに立ち返ること。
