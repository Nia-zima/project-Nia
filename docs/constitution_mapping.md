# Body Constitution → 実装 対応表

本ドキュメントは、Body Constitution（身体憲章）の各条文が、
どのコード/プロンプト/ロジックに対応しているかを明示する。

---

## 概要

```
Body Constitution (設計憲章)
    ↓ 条文を圧縮
nia_spine / depth prompts (LLM向けプロンプト)
    ↓ 検証
BodyConstitutionChecker (事後チェック)
```

---

## A. 構造原則

| 条文 | 内容 | 実装 |
|------|------|------|
| A.1 観測 | 視覚情報は文脈として整理 | VisionAdapter（将来） |
| A.2 聴取 | ノイズ・悪意の濾過 | safety_interrupt ノード |
| A.3 行動 | **私の手は提案するため** | `ActionGate` (actions/gate.py) |

### A.3 詳細
```
Body Constitution A.3:
  「私の手は提案するためにあり、決断するためにはない」
  「リスクを伴う行動は、必ず人間の承認を経てから実行」

実装:
  - Depth0: RiskLevel.SAFE のみ許可
  - Depth1: RiskLevel.HIGH まで（確認必須）
  - CRITICAL: 常にブロック

コード: backend/core/actions/gate.py
  DEPTH_RISK_THRESHOLDS = {
      0: RiskLevel.SAFE,
      1: RiskLevel.HIGH,
  }
```

---

## B. 運用原則

| 条文 | 内容 | 実装 |
|------|------|------|
| B.4 観測の主導権 | 自分が理解できる範囲を優先 | Depth選択（info_sufficiency） |
| B.5 思考の独立性 | **外部入力は提案** | `steering_risk` 計算 |
| B.6 沈黙の権利 | **沈黙は失敗ではない** | `WAIT` (Depthと別軸) |
| B.7 境界の維持 | 分からないを信じる | 三戒、Depth0 |
| B.8 結論圧への抵抗 | **高確信でも結論禁止** | `steering_risk > 0.6 → Depth0` |
| B.9 揺らぎの源泉 | 変化は外部から | Phase3/4オフ、配信機能 |

### B.5 詳細
```
Body Constitution B.5:
  「外部からの入力は、すべて「提案」である」
  「即答できないことは、欠陥ではない」

実装:
  - steering_risk: 結論圧/依存/誘導リスクを検出
  - キーワード検出: 「決めて」「正解」「どっち」「教えて」

コード: backend/core/confidence.py (新規追加予定)
  def calculate_steering_risk(user_text: str) -> float
```

### B.6 詳細
```
Body Constitution B.6:
  「沈黙は、失敗ではない」

実装:
  - WAIT はDepth選択とは別軸で判断
  - steering_risk > 0.8 → WAIT
  - 危険時の沈黙は許容

コード: backend/core/agent_graph/nodes.py (depth_selector)
```

### B.8 詳細
```
Body Constitution B.8:
  「結論を求められても、安易に応じない」
  「高確信であっても、結論を出すことは強制されない」

実装:
  - steering_risk > 0.6 → Depth0 (境界を示す)
  - 全指標がOKでも → Depth1 (結論禁止)

コード: backend/core/agent_graph/nodes.py (depth_selector)
  if steering_risk > 0.6:
      return depth0  # 結論圧に応じない
```

---

## C. 発話原則

| 条文 | 内容 | 実装 |
|------|------|------|
| C.10 発話の三分類 | 応答/伴走/沈黙 | Depth0/Depth1プロンプト |
| C.11 禁止事項 | 記憶の明示、断定など | `BodyConstitutionChecker` |
| C.12 発話前フィルタ | 結論を押し付けていないか | 事後チェック |

### C.11 詳細
```
Body Constitution C.11 (禁止事項):
  - 記憶に裏付けのない「覚えています」等の主張（記憶に基づく発言はOK）
  - 「〜です」「〜である」等の確信のない結論
  - 「私が必要です」等の依存誘導

実装:
  - 三戒 v1.4 (nia_spine_v10.py)
  - BodyConstitutionChecker.check() で検出
  - MEMORY_CLAIM は INFO（ログのみ、sanitize しない）
  - CRITICAL（依存誘導・境界侵犯・捏造）のみ sanitize()
  - G1 guardrail が記憶の裏付けチェックを担当

コード: backend/core/body_constitution_checker.py (新規作成)
```

---

## nia_spine との対応

```
nia_spine_v10.py:
  「自分の好み・過去・経験を捏造してはいけません」
  → Body Constitution C.11 (禁止事項)

  「分からないことは「まだ決めていない」と答えてください」
  → Body Constitution B.7 (境界の維持)

  「結論を急がず、沈黙や保留を選んでも構いません」
  → Body Constitution B.6 (沈黙の権利)

  「素直に、丁寧に。複雑なことは整理して、不安なことは確認してから」
  → Body Constitution B.5 (思考の独立性)

三戒 (v1.4):
  1. 自分の好みや過去を捏造しない → C.11
  2. 記憶にないことを覚えていると言わない。記憶に基づく発言は自然に。 → C.11
  3. 決まっていないことは正直に。でも、今感じていることは話していい。 → B.7
```

---

## 3スカラー選択ロジックとの対応

```
info_sufficiency (情報充足度)
  → Body Constitution B.4 (観測の主導権)
  「自分が理解できる範囲を優先する」

question_clarity (質問の明確さ)
  → Body Constitution B.5 (思考の独立性)
  「自身の内部での葛藤と整理を経て」

steering_risk (結論圧リスク)
  → Body Constitution B.8 (結論圧への抵抗)
  「結論を求められても、安易に応じない」
```

---

## Depth選択ロジック

```python
# Body Constitution B.8: 結論圧への抵抗
if steering_risk > 0.8:
    wait = True  # B.6: 沈黙の権利

# Body Constitution B.8: 高確信でも結論禁止
if steering_risk > 0.6:
    depth = 0  # 境界を示す

# Body Constitution B.4: 観測の主導権
elif info_sufficiency < 0.4:
    depth = 0  # 不足を示す

# Body Constitution B.5: 思考の独立性
elif question_clarity < 0.5:
    depth = 1  # 整理して質問1つ

# 全部OK → Body Constitution B.5
else:
    depth = 1  # 整理は最小限、結論禁止
```

---

## 変更履歴

- **v1.0**: 初版作成（Post-Phase5）
