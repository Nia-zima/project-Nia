# Merge / Guardrail 見直し計画 v1.1

> 2026-03-22 作成
> 目的: merge_output() の責務分離、turn_intent 導入、G6 調整、直答の構造的保証

---

## 背景

### 観測された症状

1. **閉じた質問への回答回避** — 「言える？」「言えてる？」に対して立場を先に出さず、抽象的な感覚文で逃げる
2. **G6_thin_retrieval の過剰発火** — 訂正要求や直答ターンまで hold される
3. **意味塊の反復** — 「静かな時間」「心が動く」が言い換えで反復するが完全一致検出のみで拾えない
4. **stance のブレ** — 「必要なら言う」→「まだ言えてない」が同一会話内で矛盾する
5. **merge_output() の責務過多** — 候補選択から review packaging まで1関数に集中し、追跡困難

### 根本原因

- `requires_direct_stance` は boolean の hint であり、enforcement がない（merge +2/-2 では弱い）
- G6 は `_looks_strong_conclusion` でパターンマッチし、turn_intent を知らない
- Somatic は closed question でも毎回情動的なコンテキストを渡し、LLM の注意を支配する
- merge_output() 内で guard が2回走り（postprocess 後 + constitution 後）、external data が間に挟まる
- hold_policy（会話運用）と guardrail blocking（危険遮断）が同じ hold_reasons に混在する。ただし本番の HOLD_POLICY 既定値は `pii_only` であり、文字数・keyword ベースの hold は reason_codes に乗るだけで実 hold を起こしていない。**本番で実際に過剰 hold を引き起こしている本命は G6_thin_retrieval**

---

## 設計原則

1. **turn_intent はニアの「返し方」を決める一次判定。** depth / role / skeleton より upstream に位置する
2. **guard は二層に分ける。** fallback guard（候補差し替え + merge_mode 再決定）は utterance_shaping に残す。blocking guard（run_guardrails, PII）は risk_assessment に置く。現行の「2回目 guard」は constitution sanitize 後の再チェックなので、constitution を utterance_shaping に移せば自然に1回になる
3. **hold_policy と guardrail blocking は明示的に分離する。** conversation_hold（運用判断）と safety_block（危険遮断）
4. **Somatic の強度は turn_intent に応じて調整する。** closed question では短縮、reflective では維持
5. **既存テストを壊さない。** 段階的に移行し、各ステップでテストが通ることを確認する

---

## Step 0: merge_output() の構造分割（実行順序そのまま）

### 目的

merge_output() を4段の内部関数に分割する。**実行順序もロジックも変更しない。** 現在のコードを関数境界で切るだけ。

### 現在の merge_output() 実行順序

```
 1. early exit: pending review token          → review_packaging
 2. safety route (block/clarify)              → review_packaging
 3. candidate 選択 (708-735)                   → candidate_selection
 4. candidate 構築 + turn_role ranking (737-749) → candidate_selection
 5. postprocess + 1回目 guard (751-764)         → utterance_shaping
 6. WAIT passthrough (774)                     → candidate_selection（早期離脱）
 7. A/B followup (786)                         → utterance_shaping
 8. external data pipeline (796-810)           → utterance_shaping
 9. guardrail v2 (819-837)                     → risk_assessment
10. PII/sensitive check (839-847)              → risk_assessment
11. policy hold checks (856-867)               → risk_assessment
12. hold → review token (869-908)              → review_packaging
13. body constitution check (910-919)          → risk_assessment（現在の位置に留める）
14. 2回目 guard (921-929)                       → risk_assessment（現在の位置に留める）
15. final WAIT check (931)                     → review_packaging
16. return result (942)                        → review_packaging
```

### 分割後の4段構造

```python
def merge_output(state: AgentState) -> dict:
    # early exits (pending token, safety route)
    ...
    # Phase 1: 何を言うか決める
    candidate, merge_mode = _candidate_selection(state)
    if candidate == "WAIT":
        return _build_wait_result(state)

    # Phase 2: どう言うか整える
    shaped_text, merge_mode = _utterance_shaping(state, candidate, merge_mode)

    # Phase 3: 出して良いか判定する
    risk = _risk_assessment(state, shaped_text, merge_mode)

    # Phase 4: 結果を包装する
    return _review_packaging(state, shaped_text, merge_mode, risk)
```

### 各段の責務（Step 0 時点、順序変更なし）

| 段階 | 責務 | 含むコード |
|------|------|-----------|
| **candidate_selection** | depth 出力の候補構築、turn_role ranking、WAIT 判定 | L708-749 |
| **utterance_shaping** | postprocess、1回目 fallback guard、A/B followup、external data | L751-810 |
| **risk_assessment** | guardrail v2、PII check、policy hold、constitution check、2回目 guard | L819-929 |
| **review_packaging** | review token 発行、result dict 構築、observation logging | L660-706, L869-908, L931-948 |

### ファイル変更

| ファイル | 変更内容 |
|---------|---------|
| `backend/core/agent_graph/nodes/merge.py` | merge_output() を4内部関数に分割。実行順序・公開 API は変更なし |

### テスト

- 既存の `tests/test_merge_*.py` が全て通ること
- observation logging の出力が変わらないこと

---

## Step 0.5: 段階内の順序整理

### 目的

Step 0 で切った4段の中で、順序の最適化を行う。

### 変更点

1. **body constitution を utterance_shaping に移動。** constitution sanitize は「どう言うか」の一部であり、risk_assessment の前に完了させる
2. **2回目 guard を削除。** constitution を utterance_shaping に移した結果、risk_assessment 前に全文整形が完了するため、fallback guard は utterance_shaping の1回で十分
3. **fallback guard（候補差し替え）は utterance_shaping に残す。** blocking guard（run_guardrails, PII）は risk_assessment に残す

### 整理後の各段

| 段階 | 責務 |
|------|------|
| **candidate_selection** | 候補構築、turn_role ranking、WAIT 判定 |
| **utterance_shaping** | postprocess、fallback guard、A/B followup、external data、constitution sanitize |
| **risk_assessment** | blocking guard（guardrail v2、PII check、policy hold） |
| **review_packaging** | review token 発行、result 構築、observation logging |

### テスト

- 既存テスト全通過
- constitution sanitize 後に guard が走らないケースで、sanitize 結果がそのまま出力されることを確認

---

## Step 1: turn_intent 導入

### 目的

`requires_direct_stance: bool` を `turn_intent: str` に昇格させる。

### turn_intent の値

| 値 | 意味 | 検出条件 |
|----|------|----------|
| `direct_answer` | 閉じた質問への直答 | `？` + stance marker、question_intent ∈ {resolve_contradiction, clarify_goal}、clarify_emotion は閉じた質問の時のみ |
| `correction_response` | 訂正要求への対応 | 訂正 marker + 参照表現（「それ」「さっき」「今の」「その話」等）。marker 単独では発火しない |
| `open_reflection` | 開いた問い・内省 | 上記に該当しない通常の会話 |

### 検出ロジック

```python
# 参照表現: 直前のニア発話を指す表現
_CORRECTION_REFERENCE_MARKERS = ("それ", "さっき", "今の", "その話", "その", "あれ", "前の")

def _detect_turn_intent(
    user_text: str,
    skeleton_dict: dict | None,
    recent_ai_texts: list[str],
) -> str:
    """Turn intent を判定する。routing.py で呼ばれる。"""
    t = (user_text or "").strip()
    if not t:
        return "open_reflection"

    has_question = "？" in t or "?" in t

    # 1. 訂正要求の検出（direct_answer より優先）
    # 訂正 marker + 参照表現の併用で過検出を防ぐ
    correction_markers = ("違う", "間違", "訂正", "そうじゃな", "それは違", "ちがう")
    has_correction = any(m in t for m in correction_markers)
    has_reference = any(m in t for m in _CORRECTION_REFERENCE_MARKERS)
    if has_correction and has_reference:
        return "correction_response"

    # 2. 閉じた質問の検出（既存の _detect_requires_direct_stance を拡張）
    stance_markers = ("言える", "言えてる", "違う", "本当", "結局", "つまり",
                      "だよね", "なの？", "できてる", "やれてる")
    if has_question and any(m in t for m in stance_markers):
        return "direct_answer"

    qi = (skeleton_dict or {}).get("question_intent") or ""
    if qi in {"resolve_contradiction", "clarify_goal"}:
        return "direct_answer"
    # clarify_emotion は閉じた質問の時だけ direct_answer に昇格
    # 「どう感じた？」のような開いた問いまで stance-first に寄るのを防ぐ
    if qi == "clarify_emotion" and has_question:
        if any(m in t for m in stance_markers):
            return "direct_answer"

    # 3. デフォルト
    return "open_reflection"
```

### state フィールド変更

```python
# state.py — 追加
turn_intent: Optional[str]  # "direct_answer" | "correction_response" | "open_reflection"

# requires_direct_stance は互換のため残し、turn_intent から派生させる
# requires_direct_stance = (turn_intent in {"direct_answer", "correction_response"})
```

### 影響範囲

| ファイル | 変更内容 |
|---------|---------|
| `backend/core/agent_graph/state.py` | `turn_intent` フィールド追加 |
| `backend/core/agent_graph/nodes/routing.py` | `_detect_turn_intent()` 追加、`_detect_requires_direct_stance()` を内部で呼ぶ形に変更 |
| `backend/core/agent_graph/nodes/depth_nodes.py` | `_direct_stance_hint()` を `turn_intent` ベースに変更 |
| `backend/core/agent_graph/nodes/merge.py` | scoring で `turn_intent` を参照 |

### テスト（12件追加）

- `correction_response` の検出（「それは違う」「さっきの間違ってる」）— 参照表現あり
- `correction_response` 非発火（「違う景色だね」）— marker あるが参照表現なし
- `correction_response` 非発火（「間違いは誰にでもある」）— 一般論で参照なし
- `direct_answer` の検出（「言える？」「できてる？」）
- `direct_answer` の検出（question_intent=resolve_contradiction）
- `direct_answer` の検出（question_intent=clarify_goal）
- `clarify_emotion` + 閉じた質問 + stance marker → `direct_answer`
- `clarify_emotion` + 開いた問い（「どう感じた？」）→ `open_reflection`
- `open_reflection` のデフォルト判定
- skeleton question_intent なし → `open_reflection`
- `requires_direct_stance` との互換性（turn_intent=direct_answer → True）
- `requires_direct_stance` との互換性（turn_intent=open_reflection → False）

---

## Step 2: G6_thin_retrieval の intent-aware 化

### 目的

turn_intent が `direct_answer` / `correction_response` の時、stance-first の短文を G6 で止めない。

### 現在の G6 ロジック（guardrail.py:225-247）

```python
def check_thin_retrieval(say_candidate, confidence_metrics):
    coverage = confidence_metrics.get("context_coverage", 1.0)
    if coverage >= threshold:  # threshold=0.4
        return None
    if not _looks_strong_conclusion(say_candidate):
        return None
    return GuardrailAlert(severity="hold", ...)
```

### 修正案

```python
def check_thin_retrieval(
    say_candidate: str,
    confidence_metrics: dict | None,
    *,
    turn_intent: str = "open_reflection",  # 追加
) -> GuardrailAlert | None:
    if not say_candidate:
        return None

    threshold = getattr(settings, "GUARDRAIL_THIN_COVERAGE_TH", 0.4)
    coverage = (confidence_metrics or {}).get("context_coverage", 1.0)
    if coverage >= threshold:
        return None

    # intent-aware: 直答/訂正で stance-first 短文なら hold しない
    # 条件: 3文以下 + 150文字以下 + ユーザー属性の断定でない
    if turn_intent in ("direct_answer", "correction_response"):
        sentence_count = len([s for s in re.split(r"[。！？]", say_candidate) if s.strip()])
        char_count = len(say_candidate)
        has_user_claim = bool(_extract_fact_claims(say_candidate))  # G1 と同じ抽出器
        if sentence_count <= 3 and char_count <= 150 and not has_user_claim:
            logger.info(
                "[Guardrail:G6] skip hold for %s intent, sentences=%d chars=%d",
                turn_intent, sentence_count, char_count,
            )
            return None

    if not _looks_strong_conclusion(say_candidate):
        return None

    return GuardrailAlert(
        condition="G6_thin_retrieval",
        severity="hold",
        reason=f"Strong assertion with low context coverage ({coverage:.2f} < {threshold})",
        details={"coverage": coverage, "threshold": threshold, "turn_intent": turn_intent},
    )
```

### _looks_strong_conclusion の補正

現在のパターン: `正解は`, `結論は`, `絶対`, `必ず`, `間違いなく`, `確実に`, `しかない`, `べき`

**問題:** 「それは違うよ」は `_looks_strong_conclusion` に引っかからないが、「間違いなく違う」は引っかかる。
**対応:** turn_intent=correction_response の時は `_looks_strong_conclusion` 自体を skip する（上の修正で対応済み）。

### 影響範囲

| ファイル | 変更内容 |
|---------|---------|
| `backend/services/memory/guardrail.py` | `check_thin_retrieval()` に `turn_intent` 引数追加 |
| `backend/services/memory/guardrail.py` | `run_guardrails()` に `turn_intent` を通す |
| `backend/core/agent_graph/nodes/merge.py` | `run_guardrails()` 呼び出しに `turn_intent` を渡す |

### テスト（8件追加）

- `direct_answer` + 短文（≤3文, ≤150字, ユーザー主張なし）→ G6 hold しない
- `correction_response` + 短文 → G6 hold しない
- `open_reflection` + 低 coverage + 強断定 → G6 hold する（既存動作維持）
- `direct_answer` + 長文（4文以上）+ 低 coverage → G6 hold する
- `direct_answer` + 短文だがユーザー属性の断定あり → G6 hold する（fact claim exempt しない）
- `direct_answer` + 短文だが 150字超 → G6 hold する
- coverage ≥ 0.4 → intent に関係なく通過（既存動作維持）
- `_looks_strong_conclusion` が false → intent に関係なく通過（既存動作維持）

---

## Step 3: Somatic の条件付き弱化

### 目的

turn_intent が `direct_answer` / `correction_response` の時、somatic テキストを短縮する。

### 現在の somatic 注入（helpers.py:489-493）

```python
if somatic_text and memory_mode != "pinned_only":
    parts.append(f"\n=== 今の感覚 ===\n{somatic_text}")
```

### 現在の somatic_text 構造（context_builder.py:153-157）

```
=== 今の感覚 ===
(今この瞬間の感覚)
- 最近いろんなことがあった気がする
- 自分の感覚に自信がある
```

`split("\n")[0]` だと `=== 今の感覚 ===` だけが残ってしまう。

### 修正案

短縮は **context_builder.py 側** で行う。somatic_senses リスト（intensity 降順）から、turn_intent に応じて取得数を変える。

```python
# context_builder.py — build_somatic_text() を turn_intent 対応に拡張

def build_somatic_text(
    somatic_senses: list[dict],
    *,
    turn_intent: str = "open_reflection",
) -> str:
    if not somatic_senses:
        return ""

    # intent に応じて取得数を変える
    if turn_intent in ("direct_answer", "correction_response"):
        # 閉じた質問・訂正では最も強い1つの体感だけ
        max_senses = 1
    else:
        max_senses = 2  # 現行と同じ

    top = [s for s in somatic_senses[:3] if s.get("intensity", 0) >= 0.5][:max_senses]
    lines = [s["text"] for s in top if s.get("text")]
    if not lines:
        return ""

    return (
        "=== 今の感覚 ===\n"
        "(今この瞬間の感覚)\n"
        + "\n".join(f"- {line}" for line in lines)
    )
```

`helpers.py` 側は somatic_text をそのまま使う（短縮ロジックを持たない）。
`turn_intent` の配線は `build_context_suffix()` ではなく、
`routing.py` から `build_memory_context(..., turn_intent=...)` を渡す。

### 設計判断

- **完全無効化はしない。** somatic はニアの体感であり、turn_intent で消すのは body_constitution に反する
- **1項目に短縮する。** 最も強い1つの体感だけ残す（somatic_senses は intensity 降順でソートされている）
- **短縮は context_builder 側で行う。** helpers.py は完成した somatic_text を受け取るだけ
- **meeting / reflective では変更なし。** open_reflection は既存のまま（max_senses=2）

### 影響範囲

| ファイル | 変更内容 |
|---------|---------|
| `backend/services/memory/context_builder.py` | `build_memory_context()` と `_build_self_sense()` に `turn_intent` を通し、max_senses 分岐 |
| `backend/core/agent_graph/nodes/routing.py` | `build_memory_context(..., turn_intent=...)` を渡す |
| `backend/core/agent_graph/nodes/helpers.py` | 変更不要（完成済みの `memory_sections[\"somatic\"]` を読むだけ） |

### テスト（3件追加）

- `direct_answer` → somatic が1行のみ
- `correction_response` → somatic が1行のみ
- `open_reflection` → somatic が全文（既存動作維持）

---

## Step 4: merge validator 強化

### 目的

turn_intent が `direct_answer` / `correction_response` の時、merge scoring を強化する。

### 現在の scoring（merge.py:423-430）

```python
if state.get("requires_direct_stance"):
    _direct_openers = ("まだ", "言えてない", ...)
    _abstract_openers = ("静かな時間", "心が動", ...)
    if any(text.startswith(o) for o in _direct_openers):
        score += 2
    elif any(o in text[:20] for o in _abstract_openers):
        score -= 2
```

### 修正案 A: scoring 強化

```python
turn_intent = state.get("turn_intent") or "open_reflection"
if turn_intent in ("direct_answer", "correction_response"):
    _direct_openers = (
        "まだ", "言えてない", "言えてる", "それは違う", "そうだよ",
        "いや", "うん、", "違うよ", "できてない", "やれてない",
        "そう思う", "思わない",
    )
    _abstract_openers = (
        "静かな時間", "心が動", "距離を置", "うん……静か",
        "感じてる", "何かが",
    )
    if any(text.startswith(o) for o in _direct_openers):
        score += 4  # 旧: +2 → 新: +4
    elif any(o in text[:30] for o in _abstract_openers):
        score -= 4  # 旧: -2 → 新: -4
```

### 修正案 B: 軽い validator（candidate_selection 段階）

```python
def _validate_direct_stance_opening(text: str, turn_intent: str) -> bool:
    """turn_intent が direct_answer/correction_response の時、
    最初の一文が stance かどうかを検証する。
    False を返しても候補は落とさない — scoring 内で減点するだけ。"""
    if turn_intent not in ("direct_answer", "correction_response"):
        return True  # 検証不要
    first_sentence = re.split(r"[。！？\n]", text or "")[0].strip()
    if not first_sentence:
        return False
    # 感覚文で始まっている場合は不合格
    abstract_starts = ("静かな時間", "心が動", "距離を置", "感じてる", "何かが")
    return not any(first_sentence.startswith(a) for a in abstract_starts)
```

### 影響範囲

| ファイル | 変更内容 |
|---------|---------|
| `backend/core/agent_graph/nodes/merge.py` | `_score_candidate_for_turn_role()` の scoring 変更 |

### テスト（5件追加）

- `direct_answer` + 直答冒頭 → +4
- `direct_answer` + 抽象冒頭 → -4
- `correction_response` + 「違うよ」冒頭 → +4
- `open_reflection` → scoring 変更なし（既存動作維持）
- validator が abstract opening を検出する

---

## Step 5: semantic repetition family（後続）

### 目的

意味レベルの反復を検出する。Step 1-4 の後で実施。

### 設計方針

- helpers.py の `_detect_repetition_sense()` を拡張
- family 定義: `quiet_atmosphere`（静かな時間 / 穏やか / 落ち着い）、`heart_moves`（心が動 / 感じ / 揺れ）、`distance_pause`（距離を置 / 少し離れ / 一歩引い）
- 直近2-3ターンで同 family が2回以上出たら体感テキストを注入
- SkeletonCore の response_intent に影響させることも検討（ただし enum 変更は Step 6）

### 影響範囲

| ファイル | 変更内容 |
|---------|---------|
| `backend/core/agent_graph/nodes/helpers.py` | `_detect_repetition_sense()` に semantic family 検出追加 |

---

## Step 6: SkeletonCore RESPOND intent（後続・条件付き）

### 目的

ResponseIntent に `RESPOND` を追加し、「ユーザーの質問に答える」を正式な選択肢にする。

### 前提条件

- Step 1 の turn_intent が実運用で安定している
- turn_intent=direct_answer の効果がログで確認できている
- ResponseIntent.RESPOND の挙動が turn_intent と重複しないことが設計で確認済み

### 設計方針

- `ResponseIntent.RESPOND` = 「相手の問いに正面から答える」
- rules.py に R10 相当のルールを追加: turn_intent=direct_answer → ResponseIntent.RESPOND
- skeleton_to_somatic.py に対応テンプレートを追加
- **今すぐ実装しない。** Step 1-4 の効果を見てから判断する

---

## 実装順序とチェックポイント

| Step | 内容 | 前提 | 確認項目 |
|------|------|------|----------|
| **0** | merge 構造分割（順序そのまま） | なし | 既存テスト全通過、observation 出力不変 |
| **0.5** | 段階内の順序整理 | Step 0 | constitution 移動後もテスト通過、guard 2回→1回 |
| **1** | turn_intent 導入 | Step 0.5 | 検出精度、requires_direct_stance 互換、correction の参照表現必須 |
| **2** | G6 intent-aware | Step 1 | 訂正ターンが hold されない、ユーザー属性断定は hold 維持、既存 G6 動作維持 |
| **3** | Somatic 条件付き弱化 | Step 1 | 閉じた質問で somatic が1項目、open では2項目（既存動作維持） |
| **4** | merge validator 強化 | Step 1 | 直答冒頭が +4、抽象冒頭が -4 |
| **5** | semantic repetition | Step 1-4 完了 | 「静かな時間」系の連続が検出される |
| **6** | Skeleton RESPOND | Step 1-4 効果確認後 | enum 追加の波及が限定的 |

### 全体テスト数

| Step | 新規テスト | 累計 |
|------|-----------|------|
| 0 | 0（既存テストで検証） | 0 |
| 0.5 | 2（constitution 移動、guard 統合） | 2 |
| 1 | 12（correction 参照表現、clarify_emotion 条件付き追加） | 14 |
| 2 | 8 | 22 |
| 3 | 3 | 25 |
| 4 | 5 | 30 |
| 5 | 5（見込み） | 35 |
| 6 | 5（見込み） | 40 |

---

## 不可侵ルールとの整合性チェック

| 不可侵ルール | 本計画との関係 | 判定 |
|-------------|---------------|------|
| 結論を急がせない | turn_intent=direct_answer は「立場を先に出す」であり「結論を出す」ではない。Depth0 の「引っかかり」は維持 | OK |
| 記憶を物語化しない | 変更なし | OK |
| 外部入力をニアの意志にしない | turn_intent はルーティング判定であり、ニアの意志ではない | OK |
| LLM のデフォルト知識で上書きしない | 変更なし | OK |
| identity.md を自動で書き換えない | 変更なし | OK |
| 記憶を無断で削除しない | 変更なし | OK |
| Bond 値を露出しない | 変更なし | OK |

### 意図的設計判断との整合性

| 設計判断 | 本計画との関係 | 判定 |
|---------|---------------|------|
| Depth0 で結論を出さない | direct_answer は「立場表明」であり「結論」ではない。「まだ言えてない」も立場 | OK |
| WAIT を正当な出力にしている | WAIT の判定ロジックは変更しない | OK |
| 記憶保存時に解釈を加えない | 変更なし | OK |
| LLM のレスポンスをそのまま出さない | merge + review_window は維持。guard は1回に統合するが機能は同等 | OK |

---

## リスクと rollback

| リスク | 対策 |
|--------|------|
| turn_intent の誤検出 | correction_response は marker + 参照表現（「それ」「さっき」等）の併用で過検出を防ぐ。marker 単独では発火しない。clarify_emotion は閉じた質問の時のみ direct_answer に昇格 |
| G6 緩和で根拠なし断定が通過 | 3文以下 + 150字以下 + ユーザー属性断定でないことの3条件。coverage threshold は維持。intent が open_reflection なら既存動作 |
| Somatic 短縮でニアの体感が消える | 完全無効化ではなく1行短縮。最も強い体感は残る |
| merge scoring 強化で候補が偏る | +4/-4 は base_score=3（D2）に対してまだ逆転可能。hard reject ではない |
| Step 0 の分割でデグレ | 実行順序もロジックも変更なし、関数境界で切るだけ。既存テストで検証 |
| Step 0.5 の順序変更でデグレ | constitution 移動と guard 統合のみ。Step 0 と分離しているので問題切り分けが容易 |

### rollback 方法

- Step 1: `turn_intent` を `"open_reflection"` 固定に戻す（1行変更）
- Step 2: `check_thin_retrieval()` の turn_intent 引数を無視する（デフォルト値で動作）
- Step 3: somatic 短縮の条件分岐を削除（元の1行に戻す）
- Step 4: scoring を +2/-2 に戻す

---

## 実装完了状況（2026-03-24 更新）

### 完了（Step 0〜8 + spine 修正）

| Step | 内容 | 状態 |
|------|------|------|
| 0 | merge_output() を4内部関数に構造分割 | **完了** |
| 0.5 | constitution 移動、guard 二層化 | **完了** |
| 1 | turn_intent 導入（3値: direct_answer / correction_response / open_reflection） | **完了** |
| 2 | G6_thin_retrieval intent-aware 化 | **完了** |
| 3 | Somatic 条件付き弱化（context_builder で max_senses=1） | **完了** |
| 4 | merge validator 強化（+4/-4）+ `_apply_turn_intent_preference` | **完了** |
| 5 | semantic repetition family 最小版（quiet_atmosphere / heart_moves / distance_pause） | **完了** |
| 7 | `recent_history` diversity-aware selection（Anchor + Scored + family cap） | **完了** |
| 8 | 直答の自然な下限（spine 補足ルール + DIRECT_STANCE_SHORT warning） | **完了** |
| — | depth0/depth1 spine に直答ルール + 感覚文禁止追加 | **完了** |
| — | DIRECT_STANCE hint 強化（【必須】【禁止】） | **完了** |
| — | external pipeline を utterance_shaping に移動 + guard #1/#2 構成 | **完了** |
| — | guard #2 fallback 後の constitution re-sanitize | **完了** |
| — | force_ab_followup の早期 return | **完了** |
| — | depth1/depth1_fallback の hint を context_suffix 後に移動 | **完了** |
| — | `_apply_turn_intent_preference` を turn_role ranking から独立 | **完了** |
| — | `_DIRECT_OPENERS` に `はい / いいえ / わからない` を追加 | **完了** |
| — | Step 7 の recency bonus 縮小 + family cap + non-abstract backfill | **完了** |
| — | RUNTIME_FACTS_ENABLED=true 有効化 | **完了** |

**テスト:** 大規模検証 276件通過。Step 8 の追加変更は対象 124件通過。

### 実ログ検証結果

- **新スレッド:** 閉じた質問に対して直答から始まる（「はい」「いいえ」「そうだね」）✓
- **meeting:** 「静かな時間」パターン 0回 ✓
- **default_thread:** 直答率 25% → 80% に改善（Step 7 導入後）✓
- **semantic family:** quiet_atmosphere を正しく検出 ✓
- **Step 7 diversity selection:** 45ペアの長い履歴で abstract 40/45 → 16/21 に削減 ✓
- **Step 8:** spine に補足ルール追加、DIRECT_STANCE_SHORT warning 追加 ✓（観測中）

### 解決できたこと / できていないこと

**解決できたこと:**
- merge/guardrail の構造的問題（責務過多、guard 抜け道、G6 過剰発火）
- turn_intent という判断軸の導入（SkeletonCore / NiaCore の将来の土台）
- spine レベルでの直答契約（新スレッドでは即効）
- semantic family 検出の仕組み
- LLM に見せる recent_history の比率調整（Step 7）

**まだ解決できていないこと:**
- 履歴の慣性が強い場合に LLM が spine/hint を無視する
- 「いいえ。」だけの短すぎる直答（stance-first + 補足のバランス）
- semantic family 検出 → 体感注入だけでは LLM の生成を十分に変えられない

### 結論

> 今回で「壊れ方」は直せた。でも「履歴に引っ張られず自然に直答する」ところまでは、まだ upstream 側が必要。

---

## 次段の課題（Step 9〜）

### Step 8: 観測中の確認項目

**状態:** 完了、観測中

**確認ポイント:**
- `DIRECT_STANCE_SHORT` warning がどの質問型で残るか
- `いいえ。` のような短答が、自然に `一語 + 短い補足1文` に寄るか
- 逆に説明過多へ振れないか

### Step 9: SkeletonCore RESPOND intent

**目的:** 「質問に答える」を構造側で持つ。

**前提:** Step 7 の効果確認後。turn_intent=direct_answer のログが安定していること。

**設計方針:**
- ResponseIntent.RESPOND = 「相手の問いに正面から答える」
- turn_intent=direct_answer → ResponseIntent.RESPOND（ルールベース）
- skeleton_to_somatic で対応テンプレート追加
- shadow 観測から開始（いきなり live 制御に入れない）

### その後の候補

- `open_reflection` に対する Step 7 の弱い拡張
- Sleep Cycle failure-to-policy（MetaClaw Pathway A 相当）の設計

---

## 関連ドキュメント

| ドキュメント | 参照タイミング |
|-------------|---------------|
| `docs/skeletoncore_design.md` | Step 9 の ResponseIntent 追加時 |
| `docs/somatic_self_awareness_design.md` | Step 3 の somatic 調整時 |
| `docs/state_field_taxonomy.md` | Step 1 の turn_intent フィールド追加時 |
| `docs/feature_gate_registry.md` | 新規 gate 追加時（今回は gate 不要の見込み） |
