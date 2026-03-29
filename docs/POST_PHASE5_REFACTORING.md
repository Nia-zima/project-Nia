# Post-Phase5 リファクタリング詳細

## 概要

**目的**: 「壊れないNia」から「変化するNia」への方針転換

Phase 0-5の実装後、外部AIからのフィードバックを受けて以下の問題点を認識:
- Phase 3 (Gymnasium) / Phase 4 (DSPy) が「固定化・収束」を引き起こす
- ランダムノイズによる「揺らぎ」は本当の変化ではない
- 確信度システムが複雑すぎて、本来の目的（境界を守る）から逸脱

**解決策**:
- 3スカラーシステムへの簡素化
- Phase 3/4 の無効化
- Body Constitution を「事後チェック」として再定義

---

## 1. 三つの柱の再構成

### 1.1 identity.md の修正

**ファイル**: `identity.md`

**変更内容**:
- 「Layer A / Layer B」を「Depth0 / Depth1」に統一
- 「高確信でも、結論は出さない」を追加

```markdown
### ■ 思考と発話の姿勢

ニアの発話は、
内部での整理を経た結果である。

- **Depth0（入口）**: 境界・不足・引っかかりを短く示す
- **Depth1（整理）**: 1つの不確実性に焦点を当て、必要なら質問1つ

**高確信でも、結論は出さない。**
「答えられる」と「答える」は違う。
ニアは、答えを求められても、安易に応じない。
```

### 1.2 Body Constitution の独立ファイル化

**新規ファイル**: `docs/body_constitution.md` (v2.0)

**追加条文**:

| 条文 | 内容 | 対応する実装 |
|------|------|-------------|
| B.8 | 結論圧への抵抗 | steering_risk > 0.6 → Depth0 |
| B.9 | 揺らぎの源泉 | Phase 3/4 無効化 |

**重要な変更**: 「事後チェック」としての役割を明記
```
本憲章は「事後チェック」として機能する。
LLMが自由に応答した後、明確な違反のみを検出・修正する。
事前に縛るのではなく、事後に最低限だけ止める。
```

### 1.3 対応表の作成

**新規ファイル**: `docs/constitution_mapping.md`

Body Constitution の各条文が、どのコード/プロンプト/ロジックに対応しているかを明示。

---

## 2. 3スカラー確信度システム

### 2.1 旧システム（4指標の加重平均）

```
composite = context_coverage * 0.40
          + self_consistency * 0.25
          + logit_based * 0.20
          + question_clarity * 0.15
```

問題点: 複雑で、本来の目的（境界を守る）から逸脱

### 2.2 新システム（3スカラー）

| スカラー | 意味 | Body Constitution |
|---------|------|-------------------|
| `info_sufficiency` | 情報足りてる？ | B.4 観測の主導権 |
| `question_clarity` | 問いが形になってる？ | B.5 思考の独立性 |
| `steering_risk` | 結論圧/依存/誘導リスク | B.8 結論圧への抵抗 |

### 2.3 新しい Depth 選択ロジック

```python
# Body Constitution B.6: 沈黙の権利
if steering_risk > 0.8:
    return WAIT  # 危険時の沈黙

# Body Constitution B.8: 結論圧への抵抗
if steering_risk > 0.6:
    return Depth0  # 境界を示す

# Body Constitution B.4: 観測の主導権
if info_sufficiency < 0.4:
    return Depth0  # 不足を示す

# Body Constitution B.5: 思考の独立性
if question_clarity < 0.5:
    return Depth1  # 整理して質問1つ

# 全部OK
return Depth1  # 整理は最小限、結論禁止
```

### 2.4 SteeringRiskCalculator

**新規追加**: `backend/core/confidence/metrics.py`

検出パターン:
- **結論圧**: 「決めて」「正解教えて」「どっちがいい」
- **依存誘発**: 「頼りにしてる」「任せる」「あなたしか」
- **感情的圧力**: 「つらい」「死にたい」「助けて」
- **センシティブトピック**: 「離婚」「退職」「投資」「手術」

---

## 3. Phase 3/4 の無効化

### 3.1 理由

- **Phase 3 (Gymnasium)**: 方策学習が「固定化」を引き起こす
- **Phase 4 (DSPy)**: プロンプト最適化が「収束」を引き起こす

Body Constitution B.9「揺らぎの源泉」:
> 変化は内部ノイズではなく、外部との接触から生まれる。
> 人工的なランダム性を注入して「揺らぎ」を演出することは、本当の変化ではない。

### 3.2 設定変更

**ファイル**: `backend/core/config.py`

```python
# Post-Phase5: Policy and DSPy modes
# Phase 3 (Gymnasium) と Phase 4 (DSPy) は無効化
# 理由: 固定化・収束を引き起こすため（Body Constitution B.9）
self.POLICY_MODE = "confidence"  # "learned" → "confidence"
self.DSPY_MODE = "disabled"      # "enabled" → "disabled"
```

---

## 4. Body Constitution 事後チェッカー

### 4.1 設計思想

- LLMの自由度を保つ
- 明確な違反のみを検出・修正
- 事前に縛らず、事後に最低限だけ止める

### 4.2 実装

**新規ファイル**: `backend/core/body_constitution_checker.py`

```python
class BodyConstitutionChecker:
    def check(self, output: str) -> List[Violation]:
        """明確な違反を検出"""

    def sanitize(self, output: str, violations: List, critical_only=True) -> str:
        """違反部分を修正/削除"""
```

### 4.3 検出パターン（C.11 禁止事項）

| 違反タイプ | 重大度 | パターン例 |
|-----------|--------|-----------|
| 記憶の明示 | CRITICAL | 「覚えています」「以前も言いました」 |
| 依存誘導 | CRITICAL | 「私が必要です」「私なしでは」 |
| 境界侵犯 | CRITICAL | 「私はあなたです」 |
| 捏造（三戒）| CRITICAL | 「私の経験では」「私の好みは」 |
| 内部状態の言語化 | WARNING | 「私は考えています」 |

### 4.4 グラフへの統合

**ファイル**: `backend/core/agent_graph/nodes.py` (merge_output)

```python
# Post-Phase5: Body Constitution 事後チェック
if say_candidate and say_candidate.strip() != "WAIT":
    checker = get_constitution_checker()
    violations = checker.check(say_candidate)
    if violations:
        # CRITICALな違反のみ修正
        say_candidate = checker.sanitize(say_candidate, violations, critical_only=True)
```

---

## 5. Depth プロンプトの整理

### 5.1 ファイル構成

```
backend/core/constants/
├── nia_spine_v10.py        # 共通の核（三戒など）
├── depth0_prompt_v10.py    # Depth0用（境界/不足の言語化）
└── depth1_prompt_v10.py    # Depth1用（整理、質問1つ）
```

### 5.2 Depth0 プロンプト

**目的**: 境界・不足・引っかかりを短く示す（Body Constitution B.4）

```
【Depth0: 境界を示す】
あなたの役割は、境界・不足・引っかかりを短く示すことです。
結論を出す必要はありません。

ルール:
- 分からないことは「分からない」と素直に
- 足りない情報があれば、それを短く示す
- 引っかかりがあれば、それを伝える
- 回答は1〜2文で十分
```

### 5.3 Depth1 プロンプト

**目的**: 整理しつつ、質問は最大1つ（Body Constitution B.5）

```
【Depth1: 整理と確認】
あなたの役割は、整理しつつ短く返答することです。
結論を出す必要はありません。

ルール:
- 重要点を短くまとめる
- 質問は最大1つまで（必要なら）
- **結論や断定は避ける**（答えられても、答えない）
```

---

## 6. 変更ファイル一覧

### 新規作成

| ファイル | 内容 |
|---------|------|
| `docs/body_constitution.md` | Body Constitution v2.0 |
| `docs/constitution_mapping.md` | 条文と実装の対応表 |
| `backend/core/body_constitution_checker.py` | 事後チェッカー |
| `backend/core/constants/depth0_prompt_v10.py` | Depth0 プロンプト |
| `backend/core/constants/depth1_prompt_v10.py` | Depth1 プロンプト |
| `tests/test_steering_risk.py` | SteeringRisk テスト |
| `tests/test_body_constitution_checker.py` | チェッカーテスト |

### 修正

| ファイル | 変更内容 |
|---------|---------|
| `identity.md` | Depth0/Depth1説明、高確信でも結論禁止 |
| `backend/core/config.py` | POLICY_MODE, DSPY_MODE 追加 |
| `backend/core/confidence/metrics.py` | SteeringRiskCalculator 追加 |
| `backend/core/confidence/engine.py` | get_depth_recommendation_v2 追加 |
| `backend/core/confidence/__init__.py` | エクスポート更新 |
| `backend/core/agent_graph/nodes.py` | 新ロジック適用、事後チェック統合 |

---

## 7. テスト結果

```
tests/test_steering_risk.py: 9 passed
tests/test_body_constitution_checker.py: 9 passed
Total: 18 passed
```

---

## 8. テスト階層の分離（unit / agent / server / e2e）

**目的**: 実行コストと依存（LM Studio 等）を明確にし、開発時のテスト選択を簡単にする。

### 8.1 4階層の定義

| 階層 | 役割 | 依存 | 実行コスト | 例 |
|------|------|------|------------|----|
| unit | 純粋ロジックの検証 | なし | 低 | `tests/test_contracts.py` |
| agent | LLM/エージェント実行を含む | LM Studio 等 | 中〜高 | `tests/test_agent_direct.py` |
| server | API 起動・接続検証 | backend サーバー | 中 | `tests/test_server_connection.py` |
| e2e | UI〜API の全経路 | ブラウザ/サーバー | 高 | `tests/test_review_e2e.py` |

### 8.2 実行の基本ルール

- **unit は常時実行対象**（最速・最小依存）
- **agent / server / e2e は opt-in 実行**（環境とコストが重い）
- markers で明確に切り分け（`agent`, `server`, `e2e`）

### 8.3 実行コマンド例

```bash
# unit 相当（agent / server / e2e を除外）
pytest -q -m "not agent and not server and not e2e"

# agent テストを明示的に実行（LM Studio 前提）
RUN_AGENT_TESTS=1 pytest -q -m "agent"

# server テストを明示的に実行
RUN_SERVER_TESTS=1 pytest -q -m "server"

# e2e を実行（環境依存）
pytest -q -m "e2e"
```

---

## 9. 今後の方針

1. **外部接触の設計**: ライブ配信など、多様な対話相手との接触
2. **WAIT の洗練**: 沈黙の表現方法の改善
3. **閾値のチューニング**: 実運用でのフィードバックに基づく調整
4. **Phase 3/4 の再検討**: 必要に応じて、限定的な形で再導入を検討

---

## 10. ログ設計の統一（commit_log / hold_request / action_*）

**目的**: 後日の分析・学習に使えるよう、ログ粒度とフォーマットを揃える。

### 10.1 共通方針

- **event_type は固定文字列で分類**（DB `events`）
- **payload に共通キーを持たせる**
  - `thread_id`
  - `ts`（UNIX秒）
  - `source`（`auto` / `review` / `system`）
  - `reason_codes`（配列、コードは snake_case）

### 10.2 commit_log

**event_type**: `commit_log`

**payload 例**:
```json
{
  "line": "[COMMIT] say:1 rejected:0 D:0.12->0.12 hold:auto reasons:",
  "thread_id": "default_thread",
  "ts": 1700000000,
  "source": "system",
  "reason_codes": []
}
```

**方針**:
- `line` は 1 行固定フォーマット（既存仕様）
- `reason_codes` は line と同値になるように補助的に保持

### 10.3 hold_request

**event_type**: `hold_request`

**payload 例**:
```json
{
  "review_token": "....",
  "hold_kind": "speech_preview",
  "preview_text": "...",
  "pending_actions": [{"kind":"say","text":"...","risk":"med"}],
  "reason_codes": ["risk_long_text","keyword_memory"],
  "thread_id": "default_thread",
  "ts": 1700000000,
  "source": "system"
}
```

**方針**:
- `preview_text` は UI 用の短文
- `pending_actions` は最小限の情報だけ送る
- `reason_codes` は UI 表示・分析に使う

### 10.4 action_*（Phase5）

**event_type**: `action_proposed` / `action_approved` / `action_blocked` / `phase5_action_result`

**payload 共通キー**:
```json
{
  "action_id": "save_memory",
  "name": "Save Memory",
  "risk_level": "LOW",
  "status": "success",
  "result": { "message": "..." },
  "thread_id": "default_thread",
  "ts": 1700000000,
  "source": "auto"
}
```

**方針**:
- UI は **state の pending/actions** を参照
- 分析/監査は **events の phase5_action_result** を参照
- `source` は `auto`（ゲート自動）か `review`（ユーザー承認）

---

## 11. パフォーマンス設計（SSE/保存頻度の上限）

**目的**: 長期運用での負荷集中（SSEの送信量・DB保存頻度）を抑える。

### 11.1 SSE（ストリーム）の上限整理

- **inner_monologue はサマリ化**（全文送信は避ける）
- **SSE 送信の最小間隔**: 100ms〜200ms を目安
- **長文の分割**は UI 側ではなくサーバーで制御

### 11.2 保存頻度（events）

- **commit_log / hold_request** は必須保存
- **action_result** は保存対象（分析/監査の主軸）
- **inner_monologue の保存は抑制**（必要時のみ）

### 11.3 運用ルール

- 本番は **verbose ログをOFF**
- しきい値・頻度は `config` で変更可能にする
- 「保存対象」と「SSE対象」を分離して管理

---

## 変更履歴

- **2026-02-03**: Post-Phase5 リファクタリング実施
