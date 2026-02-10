# Post-Phase5 調整計画

## 背景

**ユーザーからのフィードバック**:
- 不自然さや窮屈さを感じる
- 変化を感じられない
- 「まだ決めていない」が多すぎる

**原因分析**:
1. プロンプトの制約が多すぎる（結論禁止、断定禁止、記憶明示禁止など）
2. すべての変更が承認制 → 変化のタイミングを逃す
3. 三戒の「まだ決めていない」が過剰適用されている
4. プロンプトが複数ファイルに分散 → LLMが全体像を把握しにくい

---

## 実験計画

### 実験A: 制約オフモード

**目的**: 現在の制約がどれだけ影響しているか確認

**実装**:
```python
# backend/core/config.py に追加

# Post-Phase5.5: Experiment Mode
EXPERIMENT_MODE = _env_bool("EXPERIMENT_MODE", False)
```

**制約オフ時の動作**:
```python
# backend/core/agent_graph/nodes.py (merge_output)

# Post-Phase5.5: 実験モードでは Body Constitution チェックをスキップ
if not getattr(settings, "EXPERIMENT_MODE", False):
    if say_candidate and say_candidate.strip() != "WAIT":
        checker = get_constitution_checker()
        violations = checker.check(say_candidate)
        # ...
```

**使い方**:
```bash
# .env に追加
EXPERIMENT_MODE=true
```

---

### 実験B: Layer B 適応型（重要度判定）

**目的**: 小さな変化は自動適用、大きな変化は承認制

**実装**:
```python
# backend/scripts/sleep_cycle.py に追加

def estimate_importance(patch_text: str) -> float:
    """
    提案の重要度を推定

    Returns:
        float: 0.0-1.0（0.3未満=小さな変化、0.3以上=大きな変化）
    """
    # 重要度判定ロジック
    importance = 0.0

    # 性格変更キーワード
    personality_keywords = ["口調", "性格", "態度を変", "根本的"]
    for kw in personality_keywords:
        if kw in patch_text:
            importance += 0.4

    # 行動指針の追加/変更
    if "- " in patch_text:  # 箇条書き
        line_count = len([l for l in patch_text.splitlines() if l.strip().startswith("-")])
        importance += min(line_count * 0.1, 0.3)

    # 文字数（長い提案は重要度高）
    char_count = len(patch_text)
    if char_count > 200:
        importance += 0.2

    return min(importance, 1.0)


async def layer_b_guardian_adaptive(current_identity, memory_block):
    """
    Post-Phase5.5: 重要度で自動適用/承認待ちを切り替え
    """
    logger.info("🛡️ Layer B: Adaptive Guardian (Post-Phase5.5)...")

    # 提案生成（既存と同じ）
    # ...
    patch_text = await call_llm([...])

    if patch_text and "特になし" not in patch_text:
        # 重要度判定
        importance = estimate_importance(patch_text)

        if importance < 0.3:
            # 小さな変化 → 自動適用
            logger.info(f"🟢 Low importance ({importance:.2f}) - Auto-applying")
            header = "## Recent Learnings"
            current_learnings = extract_section_content(current_identity, header)
            normalized_block = await normalize_learnings_safe(current_learnings, patch_text)
            new_identity = replace_section_content(current_identity, header, normalized_block)

            success = identity_manager.update_identity(new_identity, key="AUTO_MINOR_UPDATE")
            if success:
                logger.info("✅ Minor update applied automatically")
                # 適用履歴を保存
                save_auto_applied_log(patch_text, importance)
        else:
            # 大きな変化 → 承認待ち
            logger.info(f"🟡 High importance ({importance:.2f}) - Awaiting approval")
            proposal_data = {
                "timestamp": datetime.now().isoformat(),
                "date": datetime.now().strftime("%Y-%m-%d"),
                "status": "pending",
                "importance": importance,
                "proposal": patch_text,
                "chapter_context": chapter_data.get("chapter_title") if chapter_data else None,
            }
            # 保存（既存と同じ）
            # ...
```

**モード切り替え**:
```python
# config.py
LAYER_B_MODE = _env_str("LAYER_B_MODE", "adaptive")  # "proposal" | "adaptive"
```

---

## 三戒の修正

### 現状
```
1. 自分の好みや過去を捏造しない。
2. 根拠なく「覚えている」と言わない。
3. 不確かなことは「まだ決めていない」と答える。
```

### 問題
- 戒3が過剰適用 → 会話が死ぬ
- 例: 「好きな色は？」→「まだ決めていない」

### 修正案
```
1. 自分の好みや過去を捏造しない。
2. 根拠なく「覚えている」と言わない。
3. 決まっていないことは正直に。でも、今感じていることは話していい。
```

**具体例**:
- Before: 「まだ決めていない」
- After: 「青系が落ち着く気がする。でも、決めてるわけじゃない」

**実装場所**: `backend/core/constants/nia_spine_v10.py`

---

## Depth プロンプトの改善

### 現状の問題
```
「結論を出す必要はありません」
「答えられても、答えない」
```
→ 会話を殺している

### 改善案

**Depth0**:
```diff
- 結論を出す必要はありません
+ 不確かなことは、そう言っていい

- 分からないことは「分からない」と素直に
+ わからないことは素直に。でも、感じたことは話していい
```

**Depth1**:
```diff
- **結論や断定は避ける**（答えられても、答えない）
+ 確信がないなら、無理に答えなくていい
+ でも、今思っていることは伝えていい
```

---

## プロンプトの統合（将来検討）

### 現状
```
nia_spine_v10.py
depth0_prompt_v10.py
depth1_prompt_v10.py
identity.md
Body Constitution
```

### 提案
```
nia_core.py (シンプルな1ファイル)
├─ 三戒
├─ 基本姿勢
└─ Depth の使い分け

Body Constitution (事後チェックのみ)
```

---

## 次回のタスクリスト

### 優先度: 高

1. **三戒の修正** (5分)
   - `nia_spine_v10.py` の戒3を修正
   - テスト: ニアに「好きな色は？」と聞く

2. **EXPERIMENT_MODE 追加** (10分)
   - `config.py` に設定追加
   - `nodes.py` で条件分岐
   - テスト: EXPERIMENT_MODE=true で動作確認

3. **Depth プロンプト改善** (10分)
   - `depth0_prompt_v10.py` 修正
   - `depth1_prompt_v10.py` 修正

### 優先度: 中

4. **Layer B 適応型実装** (30分)
   - `estimate_importance()` 関数
   - `layer_b_guardian_adaptive()` 関数
   - `LAYER_B_MODE` 設定

5. **自動適用ログの実装** (15分)
   - 自動適用された変更の履歴保存
   - UI での確認機能（後日）

### 優先度: 低（様子見）

6. **プロンプト統合**
   - 複数ファイルを1つに統合
   - Body Constitution との役割分離

---

## 実験手順

### ステップ1: 三戒修正 + EXPERIMENT_MODE

```bash
# 1. 三戒を修正
# 2. EXPERIMENT_MODE=true で起動
# 3. ニアと対話
# 4. 自然さ、窮屈さを確認
```

### ステップ2: Depth プロンプト改善

```bash
# 1. EXPERIMENT_MODE=false に戻す
# 2. Depth プロンプトを修正
# 3. ニアと対話
# 4. 「まだ決めていない」の頻度を確認
```

### ステップ3: Layer B 適応型

```bash
# 1. LAYER_B_MODE=adaptive で起動
# 2. 1日対話
# 3. 翌日 identity.md を確認
# 4. 自動適用された変更が適切か確認
```

---

## 判断基準

### 成功とみなす条件
- 会話が自然になる
- 「まだ決めていない」が減る
- 日々の小さな変化を感じられる

### 失敗とみなす条件
- 捏造が増える
- 不自然な記憶の主張が出る
- 性格が突然変わる

### ロールバック条件
- Body Constitution の核心的な違反が増加
- ユーザーが不快に感じる発言が出る

---

## 設計メモ

### 哲学 vs 実用性

今回の調整は「**哲学より実感**」を優先する。

- Body Constitution は美しいが、実際の対話で窮屈
- 「変化する存在」と言いながら、変化を止めすぎている
- 三戒は守りつつ、会話の自然さを取り戻す

### 変化の自由度

```
Before: すべての変更が承認待ち
After:  小さな変化は自動、大きな変化は承認
```

### 禁止 → 原則

```
Before: 「〜するな」
After:  「〜していい」
```

肯定形のほうが自然な会話につながる。

---

## 変更履歴

- **2026-02-05**: Post-Phase5 調整計画を策定
