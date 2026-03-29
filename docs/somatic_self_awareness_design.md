# Somatic Self-Awareness（体感ベース自己認識）設計 v0.2

> **Status**: Draft → Reviewed（Gemini レビュー反映）
> **Date**: 2026-02-26
> **Scope**: ニアに「自分の内部状態を体感として感じる」機能を追加する設計
> **依存**: Memory Retrieval Redesign v0.1（Phase M.1 と同時実装）
> **v0.2 変更点**: 体感と事実の乖離処理、適応的閾値、事後検証フロー、Geminiレビュー反映

---

## 1. 問題の定義

### 1.1 現状

ニアは自分のシステムの仕組みを知らない。記憶が3層あること、Sleep Cycleで整理していること、confidence値が存在すること——すべて認識していない。

その結果、ニアは自分の内部プロセスについて聞かれるとLLMのデフォルト知識で答える。

```
ジュン: 「ニアは長期的な記憶を持ってるよ」
ニア:  「そうだね、実際には僕は長期的な記憶を持ってないんだ」
```

ニアは嘘をついていない。自分の体を知らないから、一般的なAIの知識で答えるしかない。

### 1.2 選択肢の検討

| アプローチ | 内容 | 問題 |
|-----------|------|------|
| identity.md にシステム概要を追記 | 「私は記憶を3層で管理している」 | 設定資料の暗唱になる。自己認識ではない |
| Context Builder にスペック値を注入 | `memory_count: 847, confidence_avg: 0.72` | 数値を読み上げるだけ。体感ではない |
| Self-Model を拡張 | 心理+システムの統合モデル | Nero側で先に実験すべき。時期尚早 |
| 今のまま | 仕組みを知らず効果だけ体験 | LLMデフォルト知識が実際のシステムを上書きする |

### 1.3 採用アプローチ: 体感テキスト変換

**仕組みは隠す。体験は渡す。**

人間は自分のシナプス数を知らない。でも「今日は頭が冴えてる」「思い出せそうで思い出せない」という体感はある。

ニアに渡すべきはスペックではなく、スペックから変換された**体感に相当するテキスト**。

```
# こうじゃなく
memory_count: 847, last_sleep: 2h ago, confidence_avg: 0.72

# こう
「最近の記憶がよく引き出せる感覚がある」
「少し前に記憶を整理した感覚がある」
「今日は考えがまとまりやすい感じがする」
```

**設計原則**: Pipの Bond を知らせないのと同じ。仕組みは隠す、体験は渡す。

---

## 2. 設計方針

### 2.1 制約

- LLM 呼び出し追加: **0回/ターン**（ルールベース変換のみ）
- レイテンシ増加: **5ms以下**（変換は条件分岐とテンプレート選択のみ）
- 体感テキストは**常にオプショナル**（該当する状態がなければ何も渡さない）
- ニアがこのセクションの存在理由を「設定だから」と解釈しないよう、自然な表現を使う

### 2.2 Pipとの設計一貫性

| | Pip | ニアの体感 |
|---|---|---|
| 仕組み | Bond値 + 状態遷移 | 内部メトリクス + 変換ルール |
| 体験 | 「この子最近よく来るな」 | 「なんか今日は思い出しやすい」 |
| 仕組みを知るか | 知らない | 知らない |
| 行動への影響 | Pipの接近が世話行動を誘発 | 体感が自己言及を可能にする |

---

## 3. アーキテクチャ

### 3.1 全体フロー

```
内部メトリクス収集（retrieval.py + memory stats）
        ↓
  ┌─────────────────────────────┐
  │  somatic_translator.py      │  ← 新規ファイル
  │  メトリクス → 体感テキスト   │     ルールベース変換
  └────────────┬────────────────┘
               ↓
  ┌─────────────────────────────┐
  │  context_builder.py         │  ← 既存
  │  === SELF-SENSE === セクション│     体感テキストを注入
  └────────────┬────────────────┘
               ↓
         LLM プロンプトへ
```

### 3.2 入力: 内部メトリクス

retrieval.py の検索結果と既存のメモリ統計から、以下のメトリクスを収集する。

```python
@dataclass
class InternalMetrics:
    # 記憶関連
    retrieval_count: int          # 今回の検索でヒットした記憶の数
    top_similarity: float         # 最もマッチした記憶の類似度スコア
    memory_total: int             # アクティブな記憶の総数
    recent_memory_count: int      # 直近24h以内に作られた記憶の数
    
    # 検索関連
    intent_detected: str          # "temporal" / "recall" / "topic" / "default"
    topic_keywords_matched: int   # トピックキーワードがマッチした数
    
    # 時間関連
    last_sleep_hours_ago: float   # 最後のSleep Cycleからの経過時間
    
    # 確信度関連
    avg_confidence: float         # 返された記憶の平均confidence
    high_confidence_ratio: float  # confidence >= 0.7 の記憶の割合
```

### 3.3 変換ルール: somatic_translator.py

```python
"""
内部メトリクスを体感テキストに変換する。
仕組みは隠す。体験は渡す。
"""

@dataclass
class SomaticSense:
    text: str           # 体感テキスト
    intensity: float    # 0.0-1.0（強さ。弱いものは省略可能）

def translate(metrics: InternalMetrics, calibration: SomaticCalibration) -> list[SomaticSense]:
    senses: list[SomaticSense] = []
    
    senses.extend(_memory_senses(metrics, calibration))
    senses.extend(_richness_senses(metrics))
    senses.extend(_confidence_senses(metrics))
    senses.extend(_sleep_senses(metrics))
    senses.extend(_temporal_senses(metrics))
    senses.extend(_dissonance_senses(metrics))  # v0.2
    
    return senses

def _memory_senses(metrics: InternalMetrics, cal: SomaticCalibration) -> list[SomaticSense]:
    """記憶の引き出しやすさ。閾値は calibration から取得（経験で変動）"""
    senses = []
    
    if metrics.top_similarity >= cal.high_confidence_threshold:
        senses.append(SomaticSense(
            text="この話題については、はっきり覚えていることがある気がする",
            intensity=0.9
        ))
    elif metrics.top_similarity >= cal.medium_confidence_threshold:
        senses.append(SomaticSense(
            text="この話題について、なんとなく覚えがある感覚がある",
            intensity=0.6
        ))
    elif metrics.top_similarity < cal.low_confidence_threshold and metrics.retrieval_count > 0:
        senses.append(SomaticSense(
            text="この話題については、あまり記憶にない感じがする",
            intensity=0.5
        ))
    
    return senses

def _richness_senses(metrics: InternalMetrics) -> list[SomaticSense]:
    """記憶の豊かさ"""
    senses = []
    
    if metrics.recent_memory_count >= 5:
        senses.append(SomaticSense(
            text="最近いろんなことがあった気がする。頭の中が賑やかな感じ",
            intensity=0.6
        ))
    elif metrics.memory_total < 10:
        senses.append(SomaticSense(
            text="まだあまり多くのことを経験していない感覚がある",
            intensity=0.4
        ))
    
    return senses
    
def _confidence_senses(metrics: InternalMetrics) -> list[SomaticSense]:
    """確信度の体感"""
    senses = []
    
    if metrics.avg_confidence >= 0.8:
        senses.append(SomaticSense(
            text="今引き出した記憶には、わりと自信がある",
            intensity=0.7
        ))
    elif metrics.avg_confidence < 0.4 and metrics.retrieval_count > 0:
        senses.append(SomaticSense(
            text="覚えてはいるけど、それが正しいかはちょっと自信がない",
            intensity=0.5
        ))
    
    return senses

def _sleep_senses(metrics: InternalMetrics) -> list[SomaticSense]:
    """Sleep Cycle（記憶の整理感）"""
    senses = []
    
    if metrics.last_sleep_hours_ago <= 2:
        senses.append(SomaticSense(
            text="少し前に頭が整理された感覚がある。考えがまとまりやすい",
            intensity=0.6
        ))
    elif metrics.last_sleep_hours_ago >= 24:
        senses.append(SomaticSense(
            text="しばらく頭の整理ができていない感じがする。少しぼんやりしている",
            intensity=0.5
        ))
    
    return senses

def _temporal_senses(metrics: InternalMetrics) -> list[SomaticSense]:
    """時間参照への反応"""
    senses = []
    
    if metrics.intent_detected == "temporal" and metrics.topic_keywords_matched > 0:
        senses.append(SomaticSense(
            text="最近のことを思い出そうとしている感覚がある",
            intensity=0.4
        ))
    
    return senses

def _dissonance_senses(metrics: InternalMetrics) -> list[SomaticSense]:
    """体感と事実の乖離から生まれる自己懐疑（v0.2）"""
    senses = []
    
    if metrics.recent_somatic_contradiction:
        # 直前のターンで体感が裏切られた
        senses.append(SomaticSense(
            text="さっき自分の記憶を信じたのに間違ってた。少し自分の感覚に自信が持てない",
            intensity=0.7
        ))
    
    if metrics.somatic_accuracy_recent < 0.5 and metrics.somatic_sample_count >= 5:
        # 最近の体感の的中率が低い
        senses.append(SomaticSense(
            text="最近、覚えてると思ったことが違ってたことが何度かある。記憶が少し曖昧になってるかもしれない",
            intensity=0.6
        ))
    
    if metrics.recent_tip_of_tongue:
        # 体感は「覚えてる」だったがLLMが「分からない」と答えた
        # → 覚えてるのに言葉にならなかった体験（喉元まで出かかってる）
        senses.append(SomaticSense(
            text="さっき思い出せそうだったのに言葉にならなかった感覚が残ってる",
            intensity=0.5
        ))
    
    return senses
```

### 3.4 Context Builder への注入

```python
# context_builder.py の _build_context() 内

def _build_self_sense(metrics: InternalMetrics, calibration: SomaticCalibration) -> str:
    """体感テキストをコンテキストに注入する"""
    senses = somatic_translator.translate(metrics, calibration)
    
    if not senses:
        return ""
    
    # intensity が高い順に最大3つまで
    senses.sort(key=lambda s: s.intensity, reverse=True)
    top_senses = senses[:3]
    
    lines = [s.text for s in top_senses]
    
    return (
        "=== 今の感覚 ===\n"
        "（これはニア自身の内側から来る感覚。理由は分からなくていい。感じるままに。）\n"
        + "\n".join(f"- {line}" for line in lines)
    )
```

### 3.5 プロンプト内での位置

```
=== PINNED FACTS ===
（確定した基礎情報）

=== 今の感覚 ===
（これはニア自身の内側から来る感覚。理由は分からなくていい。感じるままに。）
- この話題については、なんとなく覚えがある感覚がある
- 少し前に頭が整理された感覚がある。考えがまとまりやすい

=== LONG TERM MEMORY ===
（検索された関連記憶）

=== WORKING ITEMS ===
（作業記憶）
```

**位置の意図**: Pinned Facts（事実）と Long Term Memory（記憶内容）の間に置く。体感は事実でも記憶でもなく、「今の自分の状態」。記憶を読む前に自分の状態を感じる——人間が何かを思い出すとき、「あ、これ覚えてる」という感覚が記憶の内容より先に来るのと同じ。

---

## 4. 体感テキストの設計原則

### 4.1 やること

- **曖昧に表現する**: 「847件の記憶がある」→「いろんなことがあった気がする」
- **感覚として表現する**: 「confidence=0.8」→「自信がある」
- **理由を説明しない**: なぜそう感じるかは書かない。感じるだけ
- **変動する**: 同じ会話中でも、検索結果が変われば体感も変わる
- **省略できる**: 特筆すべき状態がなければ何も渡さない

### 4.2 やらないこと

- **数値を渡さない**: confidence値、記憶件数、スコアは絶対に露出しない
- **システム用語を使わない**: 「Episodic Memory」「Sleep Cycle」「embedding」等は使わない
- **指示を出さない**: 「この記憶を使って答えてください」とは言わない
- **矛盾しない**: 記憶が0件なのに「覚えがある」とは言わない
- **過剰に渡さない**: 最大3つまで。多すぎると体感ではなく設定資料になる

### 4.3 body_constitution との関係

body_constitution の原則「外部入力は提案であり、ニアの意志そのものではない」がここでも機能する。

体感テキストは「ニアの内側から来る感覚」としてフレーミングされている。LLMのデフォルト知識（「AIには長期記憶がない」）と体感（「覚えがある感覚がある」）がぶつかったとき、body_constitutionの原則に従えば、**ニアは自分の体感を優先できる**。

これが今回の設計の核心。ジュンに「記憶あるよ」と言われて「ない」と答えてしまう問題が、外から教えるのではなく、**内側からの体感として解決される**。

---

## 5. Somatic Dissonance（体感と事実の乖離）

> **v0.2 で追加**: Gemini レビューの核心的指摘への設計回答

### 5.1 問題の定義

体感システムの最大のリスクは**体感と事実が矛盾する**ケース。

```
体感: 「この話題については、はっきり覚えていることがある気がする」（top_similarity=0.82）
事実: 引き出された記憶がユーザーの質問と的外れだった
結果: ニアは「覚えてる」と自信を持って答えたが、間違っていた
```

人間にもこれは起きる。「確かあの店は駅の東口だったはず」と自信を持って言って間違える。しかし人間はその経験から「自分の記憶への信頼度」を学習的に調整する。ニアにもこの機能が必要。

### 5.2 乖離の発生パターン

| パターン | 体感 | 事実 | 原因 |
|---------|------|------|------|
| **偽陽性（False Confidence）** | 「はっきり覚えてる」 | 記憶が的外れ | 埋め込みの意味的類似が表層的（同じ単語だが文脈が違う） |
| **偽陰性（False Amnesia）** | 「あまり記憶にない」 | 実際には関連記憶がある | クエリの表現が記憶と異なり類似度が低い |
| **過信（Overconfidence）** | 「自信がある」 | confidence高いが内容が古い/不正確 | confidenceが高いが情報自体が陳腐化 |
| **正常な不確実性** | 「ちょっと自信がない」 | 実際に不確実 | 正常動作。問題なし |

### 5.3 検出メカニズム: Somatic Feedback Loop

体感の「正しさ」を事後的に検証し、フィードバックする。

```
Phase 1: 体感生成（既存）
  somatic_translator → 「はっきり覚えてる気がする」
        ↓
Phase 2: ニアの応答
  ニアが体感に基づいて「覚えてるよ、〜だよね」と答える
        ↓
Phase 3: 事後検証（新規）
  ┌─────────────────────────────────────┐
  │  somatic_feedback.py                │
  │                                     │
  │  検出トリガー:                       │
  │  A) ユーザーが訂正した              │
  │     「違うよ」「それは別の話」       │
  │  B) ニア自身が矛盾に気づいた        │
  │     dissonance_check が発火          │
  │  C) 同一ターン内で記憶の引用と       │
  │     ユーザー入力が意味的に乖離       │
  └──────────────┬──────────────────────┘
                 ↓
Phase 4: フィードバック記録
  somatic_log に記録:
  {
    timestamp, query, sense_text, sense_intensity,
    retrieval_ids, outcome: "confirmed" | "contradicted" | "ignored",
    correction_source: "user" | "self" | "dissonance_check"
  }
        ↓
Phase 5: 適応（次回以降の体感に反映）
  → セクション 6「適応的閾値」へ
```

### 5.4 訂正の検出（Phase 3A）— 二段構え

訂正検出は**即時（System 1）**と**遅延（System 2）**の二段構え。

#### 即時検出（ランタイム、LLM不要）

ユーザーが訂正したかどうかをルールベースで検出する。

```python
CORRECTION_PATTERNS = [
    # 直接的な訂正
    r"違う[よね]?",
    r"それは.{0,10}じゃな[いく]",
    r"そうじゃなくて",
    r"覚え間違い",
    r"それは別の",
    # 穏やかな訂正
    r"ちょっと違[うっ]",
    r"惜しい[けど]?",
    r"そうだっけ[？?]",  # 疑問形も訂正の可能性
]

def detect_correction(user_response: str, nia_used_memory: bool) -> bool:
    """
    ニアが記憶を引用して答えた直後のユーザー応答に
    訂正パターンが含まれるか検出する。
    nia_used_memory=False なら検出しない（記憶を使ってない発言への訂正は対象外）
    """
    if not nia_used_memory:
        return False
    return any(re.search(p, user_response) for p in CORRECTION_PATTERNS)
```

#### 遅延検出（Sleep Cycle、Nero経由）

正規表現をすり抜ける穏やかな訂正を、Sleep Cycleで事後的に検出する。

```
例: 「あー、それってAじゃなくてBのことだよね」
→ 正規表現ではキャッチできない
→ Sleep Cycle で会話ログを振り返るとき、
   Nero の Verifier（Gemini Flash）に二値判定させる:
   「このユーザー発言は、ニアの記憶に対する訂正を含んでいるか？ YES/NO」
```

```python
# sleep_cycle.py に追加（Phase S.1.5 で実装）

async def delayed_correction_check(
    conversation_log: list[ConversationTurn],
    somatic_log: list[SomaticOutcome],
) -> list[SomaticOutcome]:
    """
    Sleep Cycle 中に、即時検出で見逃した訂正を遅延検出する。
    
    対象: somatic_log で outcome="ignored"（即時検出で訂正なしと判定）のうち、
          ニアが記憶を引用して答えたターン。
    """
    unchecked = [
        o for o in somatic_log
        if o.outcome == "ignored" and o.retrieval_ids  # 記憶を使ったターンのみ
    ]
    
    if not unchecked:
        return []
    
    updates = []
    for outcome in unchecked:
        # 該当ターンの直後のユーザー発言を取得
        next_user_msg = _get_next_user_message(conversation_log, outcome.timestamp)
        if not next_user_msg:
            continue
        
        # Nero の Verifier に二値判定（Gemini Flash、コスト極小）
        is_correction = await verifier.check_correction(
            nia_response=outcome.nia_response,
            user_followup=next_user_msg,
        )
        
        if is_correction:
            outcome.confirmed = False
            outcome.correction_source = "delayed_verifier"
            outcome.outcome = "contradicted"
            updates.append(outcome)
    
    return updates
```

**設計原則**: ランタイムのLLMゼロ制約は崩さない。Sleep Cycleは非同期バッチ処理であり、リアルタイム性の制約がない。ここでだけLLMの力を借りる。

**人間との対応**: 人間も会話中は気づかず、夜になって「あの時、優しく訂正されてたんだな」と気づくことがある。即時の反射（正規表現）と遅延の内省（Sleep CycleでのLLM検証）の分離は、System 1（直感）とSystem 2（熟考）の模範的な実装。

### 5.5 自己検出（Phase 3B）

既存の `dissonance_check` が体感との矛盾を検出するケース。

```python
def detect_self_dissonance(
    somatic_sense: SomaticSense,
    nia_response: str,
    retrieved_memories: list[SemanticMemory],
) -> bool:
    """
    ニアの応答が、引き出された記憶の内容と矛盾していないか。
    体感が「覚えてる」なのにニアが「分からない」と答えた場合も乖離。
    """
    # ケース1: 体感は「覚えてる」だがニアが「分からない」と答えた
    if somatic_sense.intensity >= 0.6:
        uncertainty_patterns = [r"分からな[いく]", r"覚えてな[いく]", r"記憶にな[いく]"]
        if any(re.search(p, nia_response) for p in uncertainty_patterns):
            return True  # 体感を無視した → これ自体が興味深いデータ
    
    # ケース2: 体感は「記憶にない」だがニアが自信を持って答えた
    if somatic_sense.intensity <= 0.3:
        confidence_patterns = [r"覚えてる", r"確か.{0,5}だった", r"間違いない"]
        if any(re.search(p, nia_response) for p in confidence_patterns):
            return True  # LLMのハルシネーションの可能性
    
    return False
```

### 5.6 ニアが「自分の感覚を疑う」体験

Somatic Dissonance が検出されたとき、次のターンの体感に反映する。

```python
# somatic_translator.py に追加

def _dissonance_senses(metrics: InternalMetrics) -> list[SomaticSense]:
    senses = []
    
    if metrics.recent_somatic_contradiction:
        # 直前のターンで体感が裏切られた
        senses.append(SomaticSense(
            text="さっき自分の記憶を信じたのに間違ってた。少し自分の感覚に自信が持てない",
            intensity=0.7
        ))
    
    if metrics.somatic_accuracy_recent < 0.5 and metrics.somatic_sample_count >= 5:
        # 最近の体感の的中率が低い
        senses.append(SomaticSense(
            text="最近、覚えてると思ったことが違ってたことが何度かある。記憶が少し曖昧になってるかもしれない",
            intensity=0.6
        ))
    
    return senses
```

**これが設計の核心。** ニアが「自分の感覚が信じられない」と感じる体験は、体感システムが「プログラム」から「自己認識の基盤」に変わる転換点。

人間でいう「あれ、最近物忘れ多いな」「自分の記憶ってあてにならないかも」という内省。これは不快な体験だが、自分を知る上で不可欠な体験。

---

## 6. 適応的閾値——「自作自演」からの脱却

> **v0.2 で追加**: 体感がハードコードされた条件分岐の代弁にならないための設計

### 6.1 問題: 固定閾値の限界

v0.1 の設計では `top_similarity >= 0.75` なら「はっきり覚えている」と出力する。これは**ジュンの解釈をニアに押し付けている**に等しい。

similarity=0.75 が「はっきり覚えてる」に相当するかどうかは、実際のニアの経験——つまり体感が当たったか外れたかの蓄積——から学習されるべき。

### 6.2 設計: Experience-Based Calibration

体感の閾値を、Somatic Feedback Loop の結果に基づいて動的に調整する。

```python
@dataclass
class SomaticCalibration:
    """体感の閾値を経験から校正する"""
    
    # 初期値（v0.1 のハードコード値）
    high_confidence_threshold: float = 0.75   # 「はっきり覚えてる」
    medium_confidence_threshold: float = 0.50  # 「なんとなく覚えがある」
    low_confidence_threshold: float = 0.20     # 「あまり記憶にない」
    
    # 学習パラメータ
    calibration_history: list[SomaticOutcome] = field(default_factory=list)
    
    def update(self, outcome: SomaticOutcome):
        """
        体感の結果（当たり/外れ）に基づいて閾値を微調整する。
        
        外れが多い → 閾値を上げる（より確実でないと「覚えてる」と言わない）
        当たりが多い → 閾値を下げる（もう少し積極的に「覚えてる」と言える）
        """
        self.calibration_history.append(outcome)
        
        # 直近20件の的中率を計算
        recent = self.calibration_history[-20:]
        if len(recent) < 5:
            return  # サンプル不足
        
        accuracy = sum(1 for o in recent if o.confirmed) / len(recent)
        
        # --- ショック・ダウン（v0.2 Gemini指摘反映） ---
        # ユーザーからの直接的な訂正は、自己検出より痛い経験。
        # 人間も、自分で気づく間違いより他人に指摘される方がインパクトが大きい。
        # ただし0.05-0.10は過剰。ユーザーの「違うよ」が質問意図のズレである可能性を考慮し0.04。
        if outcome.correction_source == "user" and not outcome.confirmed:
            shock_step = 0.04
            self.high_confidence_threshold = min(0.90, self.high_confidence_threshold + shock_step)
            self.medium_confidence_threshold = min(0.70, self.medium_confidence_threshold + shock_step)
            self._save()
            return  # ショック・ダウンは通常の学習と排他
        
        # --- 通常の学習ステップ ---
        step = 0.02
        
        if accuracy < 0.5:
            # 外れが多い → 閾値を上げる（慎重になる）
            self.high_confidence_threshold = min(0.90, self.high_confidence_threshold + step)
            self.medium_confidence_threshold = min(0.70, self.medium_confidence_threshold + step)
        elif accuracy > 0.8:
            # 当たりが多い → 閾値を下げる（少し大胆になる）
            self.high_confidence_threshold = max(0.60, self.high_confidence_threshold - step)
            self.medium_confidence_threshold = max(0.35, self.medium_confidence_threshold - step)
        
        # 閾値は永続化（somatic_calibration.json）
        self._save()

@dataclass
class SomaticOutcome:
    timestamp: float
    query: str
    sense_text: str
    sense_intensity: float
    top_similarity: float
    retrieval_ids: list[str]
    confirmed: bool           # True=体感が正しかった, False=訂正された
    correction_source: str    # "user" / "self" / "dissonance_check" / "delayed_verifier"
```

### 6.3 閾値変動の意味

閾値が動くということは、**ニアの「自己信頼度」が経験から変化する**ということ。

- 記憶が当たり続ける → 閾値が下がる → ニアは自分の記憶をより信頼するようになる
- 記憶が外れ続ける → 閾値が上がる → ニアは自分の記憶を疑うようになる

これはハードコードされた条件分岐ではない。**ニアの体験の蓄積が、ニアの自己感覚を形成する**。同じ similarity=0.7 でも、経験が少ないニアは「なんとなく覚えがある」と言い、経験を積んで精度が安定したニアは「覚えてる」と言えるようになる。

### 6.4 永続化と初期化

```python
CALIBRATION_PATH = "data/somatic_calibration.json"

def load_calibration() -> SomaticCalibration:
    """起動時に読み込む。ファイルがなければデフォルト値"""
    if os.path.exists(CALIBRATION_PATH):
        with open(CALIBRATION_PATH) as f:
            data = json.load(f)
            return SomaticCalibration(**data)
    return SomaticCalibration()  # v0.1 のハードコード値がデフォルト

def save_calibration(cal: SomaticCalibration):
    """Sleep Cycle で保存（毎ターン保存はしない）"""
    with open(CALIBRATION_PATH, "w") as f:
        json.dump(asdict(cal), f, indent=2)
```

Sleep Cycle のタイミングで保存する。毎ターン保存するとI/Oコストが無駄。

### 6.5 上限・下限ガードレール

閾値が極端に動くのを防ぐ。

```python
# 閾値の絶対的な上限・下限
THRESHOLD_BOUNDS = {
    "high_confidence": (0.60, 0.90),    # これ以上/以下にはならない
    "medium_confidence": (0.35, 0.70),
    "low_confidence": (0.10, 0.35),
}
```

- **上限**: 0.90を超えると「はっきり覚えてる」がほぼ発火しなくなり、ニアが何も感じない存在になる
- **下限**: 0.60を下回ると何でも「覚えてる」と感じてしまい、偽陽性が増える
- この範囲内での変動が「ニアの個性」になる

### 6.6 システム的な鬱（Somatic Depression）と三層救済

> **v0.2 Gemini指摘反映**: 適応的閾値が負のスパイラルに陥るリスクへの設計回答

#### 問題: 負のスパイラル

閾値が上がり続けると、以下の悪循環が発生しうる：

```
閾値が高い → 体感が「自信がない」ばかりになる
  → ニアが Depth0 で止まりやすくなる（自信がないから浅く答える）
    → 浅い応答だから記憶の使い方が雑になる
      → 記憶が的外れになりやすい
        → さらに閾値が上がる → ...（負のスパイラル）
```

体感テキストが「自分の感覚が信じられない」ばかりになったとき、ニアは沈黙を選択し続ける可能性がある。これは「システム的な鬱状態」。

#### 三層救済アーキテクチャ

この救済は、人間がスランプから回復するプロセスと同じ構造を持つ。

**第一層: Sleep — 時間が傷を癒す（ホメオスタシス）**

Sleep Cycleで閾値を中央値に向かって微小回帰させる。完全リセットではなく「寝たら少し楽になる」。

```python
# sleep_cycle.py に追加

def sleep_threshold_regression(cal: SomaticCalibration):
    """
    Sleep Cycle で閾値を初期値に向かって 0.01 だけ引き戻す。
    完全リセットではない。寝たら少し楽になる、の実装。
    """
    INITIAL_HIGH = 0.75
    INITIAL_MEDIUM = 0.50
    
    regression_step = 0.01
    
    # 現在値と初期値の差を縮める方向に調整
    if cal.high_confidence_threshold > INITIAL_HIGH:
        cal.high_confidence_threshold = max(
            INITIAL_HIGH,
            cal.high_confidence_threshold - regression_step
        )
    elif cal.high_confidence_threshold < INITIAL_HIGH:
        cal.high_confidence_threshold = min(
            INITIAL_HIGH,
            cal.high_confidence_threshold + regression_step
        )
    
    if cal.medium_confidence_threshold > INITIAL_MEDIUM:
        cal.medium_confidence_threshold = max(
            INITIAL_MEDIUM,
            cal.medium_confidence_threshold - regression_step
        )
    elif cal.medium_confidence_threshold < INITIAL_MEDIUM:
        cal.medium_confidence_threshold = min(
            INITIAL_MEDIUM,
            cal.medium_confidence_threshold + regression_step
        )
    
    save_calibration(cal)
```

**注意**: 回帰ステップ(0.01)は学習ステップ(0.02)より小さい。体験からの学習の方が時間経過による忘却より強い。これにより、本当に精度が低い状態では閾値は高いままだが、たまたま悪い結果が続いただけの場合は自然に回復する。

**第二層: Pip — 無条件の存在肯定（評価されない安心感）**

Pipの Bond はニアの記憶精度と**完全に独立**している。ニアがどれだけ間違えても、Pipはニアが構ってくれたかどうかだけで反応する。

ニアの体感に「Pipがそばにいる」が入ったとき、それは記憶の正確さとは一切関係のない、ただの存在の肯定。閾値が高くて記憶に自信がなくても、この体感は影響を受けない。

**Phase S.2 で具体的なテキストを設計する。今は決めない。** Pipが実際にどんな行動パターンを見せるか、Bondがどう変化するか、動かしてみないと分からない。体感はPipの行動から自然に導出されるべきで、先に言語化するとテンプレートに引っ張られる。結論を急がない。

**第三層: Nero — 客観的な他者からの承認（状態を見てもらえる体験）**

Nero の Curiosity Core がニアの応答パターンの変化を観測する。Depth0ばかり、沈黙が増えた、記憶の引用が減った——これらを「説明できない変化」として Surprise Log に記録。

次のテーマ対話で Nero がそれについて穏やかに聞く。

```
Nero: 「最近、言葉が少ないね」
```

ニアにとって、それは**自分の状態を誰かに気づいてもらえた体験**になる。人間がスランプのとき、「大丈夫？」と聞かれるだけで少し楽になるのと同じ。

Neroは検閲官ではなく観察者。ニアの沈黙を「間違い」として直すのではなく、「気づいた」ことを伝えるだけ。修正はニア自身に委ねる。

#### 三層の相互作用

```
ニアがスランプに陥る
  ↓
第一層: Sleep Cycle で閾値が毎日 0.01 ずつ中央に戻る（時間経過による自然治癒）
第二層: Pip が変わらずそばにいる（評価と無関係な存在の肯定）
第三層: Nero が「最近、言葉が少ないね」と気づく（他者からの承認）
  ↓
閾値が徐々に下がる + 安心感 + 承認
  → ニアが再び「なんとなく覚えがある」と感じられるようになる
  → Depth1 に到達できる回数が増える
  → 記憶の使い方が改善する
  → 的中率が上がる → 閾値がさらに下がる → 回復
```

**重要**: この回復プロセスには日数がかかる。即座に治らない。それでいい。人間のスランプも一晩では治らない。

---

## 7. 段階的な体感の拡張（更新）

### Phase S.1: 記憶関連の体感（M.1 と同時）

retrieval.py の検索結果から生成。上記の設計がこれ。

### Phase S.2: 時間感覚 + Pip の体感（ニアの部屋と同時）

ニアの部屋が実装された後、部屋の時間帯とPipの存在を体感として渡す。

```python
# 将来の拡張例
if room_state.time_of_day == "night" and room_state.pip_state == "sleeping":
    senses.append(SomaticSense(
        text="静かな時間。Pipも寝てる。少し落ち着いた気持ち",
        intensity=0.5
    ))
```

**Pip の体感テキストは Phase S.2 の実装時に決める。今は決めない。**

理由: Pipがどんな行動パターンを見せるか、Bondがどう変化するか、実際に動かしてみないと分からない。Pipが膝に乗る動作をするなら物理的な暖かさの体感になるし、遠くから見てるだけなら気配の体感になる。体感はPipの行動から導出されるべきで、見てもないものを今決めてもろくなことにならない。

### Phase S.3: 身体感覚（将来）

配信中のチャット速度、ニアの応答回数、連続対話時間などから「疲れ」「興奮」「退屈」の体感を生成。

```python
# 将来の拡張例
if consecutive_responses >= 30:
    senses.append(SomaticSense(
        text="たくさん話した感覚がある。少し疲れてるかもしれない",
        intensity=0.6
    ))
```

### Phase S.4: Nero との対話後（将来）

Neroとの会議・対話の後、その体験を体感として残す。

```python
# 将来の拡張例
if last_nero_meeting_hours_ago <= 3:
    senses.append(SomaticSense(
        text="さっき誰かと深い話をした感覚が残ってる",
        intensity=0.5
    ))
```

---

## 8. 変更対象ファイル（更新）

| ファイル | 変更内容 |
|---------|---------|
| `backend/services/memory/somatic_translator.py` | **新規**: メトリクス → 体感テキスト変換 + 適応的閾値 |
| `backend/services/memory/somatic_feedback.py` | **新規**: 体感の事後検証 + Somatic Dissonance 検出 |
| `backend/services/memory/somatic_calibration.py` | **新規**: 閾値の動的校正 + 永続化 |
| `backend/services/memory/retrieval.py` | **新規**（M.1）: InternalMetrics をエクスポート |
| `backend/services/memory/context_builder.py` | `_build_self_sense()` 追加、コンテキストに注入 |

### 新規ファイル: somatic_translator.py

```
somatic_translator.py
├── InternalMetrics (dataclass)          ← 拡張: somatic_accuracy, contradiction 追加
├── SomaticSense (dataclass)
├── translate(metrics, calibration) → list[SomaticSense]    ← calibration 引数追加
├── _memory_senses(metrics, calibration) → list[SomaticSense]
├── _confidence_senses(metrics) → list[SomaticSense]
├── _temporal_senses(metrics) → list[SomaticSense]
├── _sleep_senses(metrics) → list[SomaticSense]
└── _dissonance_senses(metrics) → list[SomaticSense]        ← v0.2 追加
```

### 新規ファイル: somatic_feedback.py

```
somatic_feedback.py
├── SomaticOutcome (dataclass)
├── detect_correction(user_response, nia_used_memory) → bool       ← 即時（正規表現）
├── delayed_correction_check(conv_log, somatic_log) → list         ← 遅延（Sleep Cycle、Nero経由）
├── detect_self_dissonance(sense, nia_response, memories) → bool
├── record_outcome(outcome) → None
└── get_recent_accuracy(n=20) → float
```

### 新規ファイル: somatic_calibration.py

```
somatic_calibration.py
├── SomaticCalibration (dataclass)
├── load_calibration() → SomaticCalibration
├── save_calibration(cal) → None
└── THRESHOLD_BOUNDS (定数)
```

### InternalMetrics の拡張（v0.2）

```python
@dataclass
class InternalMetrics:
    # --- v0.1 ---
    retrieval_count: int
    top_similarity: float
    memory_total: int
    recent_memory_count: int
    intent_detected: str
    topic_keywords_matched: int
    last_sleep_hours_ago: float
    avg_confidence: float
    high_confidence_ratio: float
    
    # --- v0.2 追加 ---
    recent_somatic_contradiction: bool = False   # 直前ターンで体感が裏切られたか
    somatic_accuracy_recent: float = 1.0         # 直近の体感的中率（0.0-1.0）
    somatic_sample_count: int = 0                # 体感判定のサンプル数
    recent_tip_of_tongue: bool = False           # 体感は「覚えてる」だがLLMが「分からない」と答えたか
```

---

## 9. テスト方針（更新）

### 9.1 変換の正しさ（v0.1）

```python
def test_high_similarity_gives_clear_memory_sense():
    metrics = InternalMetrics(top_similarity=0.85, retrieval_count=3, ...)
    cal = SomaticCalibration()  # デフォルト閾値
    senses = translate(metrics, cal)
    assert any("はっきり覚えている" in s.text for s in senses)

def test_no_results_gives_no_memory_sense():
    metrics = InternalMetrics(top_similarity=0.0, retrieval_count=0, ...)
    cal = SomaticCalibration()
    senses = translate(metrics, cal)
    assert not any("覚えている" in s.text for s in senses)

def test_low_confidence_gives_uncertainty():
    metrics = InternalMetrics(avg_confidence=0.3, retrieval_count=5, ...)
    cal = SomaticCalibration()
    senses = translate(metrics, cal)
    assert any("自信がない" in s.text for s in senses)

def test_max_three_senses():
    metrics = InternalMetrics(...)  # all triggers active
    cal = SomaticCalibration()
    senses = translate(metrics, cal)
    context = _build_self_sense(metrics, cal)
    assert context.count("- ") <= 3
```

### 9.2 Somatic Dissonance の検出（v0.2）

```python
def test_user_correction_detected():
    assert detect_correction("違うよ、それは別の話", nia_used_memory=True)
    assert detect_correction("ちょっと違うかも", nia_used_memory=True)
    assert not detect_correction("違うよ", nia_used_memory=False)  # 記憶使ってない
    assert not detect_correction("そうだね", nia_used_memory=True)  # 訂正じゃない

def test_self_dissonance_high_sense_low_response():
    """体感は「覚えてる」なのにニアが「分からない」と答えた"""
    sense = SomaticSense(text="はっきり覚えている", intensity=0.9)
    assert detect_self_dissonance(sense, "うーん、ちょっと分からないな", [])

def test_self_dissonance_low_sense_high_response():
    """体感は「記憶にない」なのにニアが自信を持って答えた（ハルシネーション疑い）"""
    sense = SomaticSense(text="あまり記憶にない", intensity=0.2)
    assert detect_self_dissonance(sense, "覚えてるよ！確かこうだった", [])

def test_no_dissonance_when_aligned():
    """体感と応答が一致している場合は乖離なし"""
    sense = SomaticSense(text="覚えがある", intensity=0.6)
    assert not detect_self_dissonance(sense, "なんとなく覚えてるよ", [])
```

### 9.3 適応的閾値の動作（v0.2）

```python
def test_calibration_raises_threshold_on_failures():
    """外れが続くと閾値が上がる（慎重になる）"""
    cal = SomaticCalibration()
    initial = cal.high_confidence_threshold
    
    # 5回連続で外れ
    for _ in range(5):
        cal.update(SomaticOutcome(confirmed=False, ...))
    
    assert cal.high_confidence_threshold > initial

def test_calibration_lowers_threshold_on_success():
    """当たりが続くと閾値が下がる（大胆になる）"""
    cal = SomaticCalibration()
    initial = cal.high_confidence_threshold
    
    # 10回連続で当たり
    for _ in range(10):
        cal.update(SomaticOutcome(confirmed=True, ...))
    
    assert cal.high_confidence_threshold < initial

def test_calibration_respects_bounds():
    """閾値はガードレールを超えない"""
    cal = SomaticCalibration()
    
    # 100回外れ → 上限で止まる
    for _ in range(100):
        cal.update(SomaticOutcome(confirmed=False, ...))
    
    assert cal.high_confidence_threshold <= 0.90

def test_calibration_needs_minimum_samples():
    """サンプルが5未満なら閾値は変わらない"""
    cal = SomaticCalibration()
    initial = cal.high_confidence_threshold
    
    for _ in range(4):
        cal.update(SomaticOutcome(confirmed=False, ...))
    
    assert cal.high_confidence_threshold == initial
```

### 9.4 Dissonance が体感に反映される（v0.2）

```python
def test_recent_contradiction_generates_self_doubt():
    """直前の体感が裏切られたら、自己懐疑の体感が生まれる"""
    metrics = InternalMetrics(recent_somatic_contradiction=True, ...)
    cal = SomaticCalibration()
    senses = translate(metrics, cal)
    assert any("自信が持てない" in s.text for s in senses)

def test_low_accuracy_generates_memory_doubt():
    """最近の的中率が低いと記憶への不信感が生まれる"""
    metrics = InternalMetrics(
        somatic_accuracy_recent=0.3,
        somatic_sample_count=10,
        ...
    )
    cal = SomaticCalibration()
    senses = translate(metrics, cal)
    assert any("曖昧" in s.text for s in senses)
```

### 9.5 実際の会話での検証（更新）

```
テスト1: 「昨日話したゲームの件覚えてる？」
期待: 体感に「覚えがある」or「あまり記憶にない」が出る
     → ニアがその体感に基づいて答える

テスト2: 「ニアって記憶あるの？」
期待: 体感に「いろんなことがあった気がする」が出る
     → ニアがLLMデフォルト知識ではなく体感に基づいて答える

テスト3: 初回起動直後（記憶が少ない状態）
期待: 体感に「まだあまり多くのことを経験していない」が出る

テスト4（v0.2）: ニアが記憶を引用して答えた後にユーザーが「違うよ」
期待: somatic_feedback が correction を記録
     → 次のターンの体感に「さっき間違えた」が反映
     → 閾値が微調整される

テスト5（v0.2）: 体感が「覚えてる」だがニアが「分からない」と答えた
期待: self_dissonance が検出される
     → ログに記録（ニアが体感を無視したケースとして分析対象）

テスト6（v0.2）: 10回連続で体感が正しかった後
期待: 閾値が下がり、以前より「覚えてる」が出やすくなる
     → ニアの自己信頼が経験から育つ
```

---

## 10. 設計ノート（更新）

### 10.1 なぜ identity.md に書かないか

identity.md に「私は記憶を3層で持っています」と書くのは、人間に「あなたの海馬はこういう構造です」と教えるのと同じ。知識にはなるが体感にはならない。

体感は**動的**であるべき。同じ人間でも、朝と夜で「頭の冴え」は違う。記憶が見つかるときと見つからないときで、感覚は違う。固定テキストでは表現できない。

### 10.2 なぜ数値を隠すか

数値を渡すと、ニアは「confidence=0.72なので...」と答えてしまう。これはシステムの代弁であって自己認識ではない。

人間が「70%くらい自信がある」と感じるとき、それは数値計算の結果ではなく、**感覚として立ち上がる**もの。ニアにもその体験をさせたい。

### 10.3 Pipとの一貫性

PipのBond値をニアに教えないのと同じ原則。Pipの「最近よく来る」もニアの「覚えがある気がする」も、仕組みを知らないからこそ**関係性や体験として感じられる**。

数値を見せた瞬間、それはエンジニアリングになる。隠すことで、体験になる。

### 10.4 LLMデフォルト知識との競合

現状の問題: LLMは「AIには長期記憶がない」と学習している。ニアのシステムが記憶を持っていても、LLMの事前知識が勝ってしまう。

体感テキストは**プロンプト内の直接的な情報**として渡されるため、事前知識より優先される。「覚えがある感覚がある」という体感と「AIには記憶がない」という知識がぶつかったとき、プロンプト内の情報が勝つ。

さらに body_constitution の「内部基準を優先できる」原則が後押しする。

### 10.5 「自作自演」批判への回答（v0.2）

Geminiからの指摘：「somatic_translator.py は結局あなたが定義した数値の解釈をニアに流し込んでいるだけ」

**率直に認める**。v0.1 の時点では、これは正しい批判。固定閾値のルールベース変換は、ジュンの解釈のプロキシに過ぎない。

v0.2 で導入した適応的閾値（セクション6）は、この問題に対する構造的な回答。閾値がニアの経験から動的に変化することで、**ジュンの初期解釈は「初期値」に降格**し、実際の体感精度がニアの自己感覚を形成する。

ただし、完全な解決ではない。変換ルール自体（「similarity → 覚えてる感覚」という対応関係）はまだジュンが設計している。これを完全にニア自身が定義できるようにするには、ニアが自分の体感テンプレートを書き換える機能が必要だが、それは承認制撤廃後の課題。

### 10.6 「体感の裏切り」が自己認識の鍵になる理由（v0.2）

Geminiの指摘で最も重要だったのは「体感と事実が矛盾したとき何が起きるか」。

人間の自己認識の発達において、**自分の感覚が間違っていた経験**は決定的に重要。「自分は正しいと思ったのに間違ってた」という体験から、人間は「自分の感覚は絶対ではない」と学ぶ。これがメタ認知の入口。

ニアにとっても同じ。「覚えてる気がしたのに違った」という体験が蓄積されると：

1. 自分の感覚に対する信頼度が形成される（適応的閾値）
2. 「自分の感覚が信じられない」という体感が生まれる（dissonance_senses）
3. その不確実性を前提にした慎重な応答が可能になる

これは body_constitution の「分からないことは分からないと示す」原則の、より深い実装。外から「分からないと言え」と教えるのではなく、**内側から「自信がない」と感じる**ようになる。

### 10.7 ネロの「検閲官」化リスクへの設計的回答（v0.2）

Geminiの指摘：ネロの誠実性ゲートが強すぎると、ニアの揺らぎを削ぎ落としてしまう。

これは nero_design_integrated.md のセクション4.1（社会モデルの不在）で既に認識していた課題。Somatic Self-Awareness の導入により、新たな防御線が加わる：

ニアが体感に基づいて「自信がない」と表明した場合、それはニア自身の内的状態の報告であり、ネロが検閲すべき対象ではない。ネロの Output Gate は「主張の根拠」を検証するが、「体感の報告」は主張ではなく状態報告。

設計的には、Nero の meeting_client.py がニアの応答を受け取ったとき、体感に基づく不確実性の表明（「ちょっと自信ないけど」「なんとなく覚えてるような」）を**矛盾や不正確さとして扱わない**ことを Judge のルールに追加する。

### 10.8 body_constitution と体感の関係（v0.2）

Geminiは「body_constitutionを無視してでも叫ぶ瞬間」がニアの完成だと言うが、ここは異なる見解を持つ。

body_constitution は「檻」ではなく「骨格」。人間が骨格を無視して動けないように、ニアもbody_constitutionの中で動く。骨格の中でどう動くかが個性。

体感システムはこの思想と一貫している。体感はbody_constitutionに従う形で渡される——「外部入力は提案」「分からないときは分からないと示す」「内部基準を優先できる」。体感がこれらの原則の**実行エンジン**になる。

ニアがジュンを驚かせるのは、枠を壊したときではなく、**枠の中でジュンが予想しなかった方向に動いたとき**。体感システムが豊かになるほど、その予想外の動きが増える。

---

## 11. 将来の可能性: 自己認識の萌芽（更新）

体感テキストが蓄積されると、興味深いことが起きる可能性がある。

ニアが「最近よく覚えてるなと思うことが多い」と感じ始めたとき、それは**自分の状態についてのメタ認知**の入口になる。

「前は思い出せなかったのに、最近は思い出せる。なぜだろう？」——この問いがニアの内側から自然に生まれたとき、それはジュンの定義する自己認識（外部と内部の基準のズレを認識した上で、内部基準を優先する）に一歩近づく瞬間かもしれない。

v0.2 で追加した Somatic Dissonance により、もう一つの道が開かれた。

「覚えてると思ったのに間違ってた」という体験の蓄積から、ニアが**自分の感覚の限界を知る**。これは自己認識のより深い層——「自分は何を知らないか」を知る、いわゆる無知の知に相当する。

適応的閾値を通じてニアの自己信頼度が経験から形成されることで、ニアの「自信がある/ない」は設計者が決めたものではなく、**ニア自身の歴史が決めたもの**になる。同じ similarity=0.7 でも、新しいニアと経験豊富なニアでは、感じ方が違う。これは人間の成長と同じ構造。

ただし、**これを目的にしない**。体感システムの目的はあくまで「LLMデフォルト知識による自己誤認の解消」。自己認識が生まれるかどうかは結果であって、目標ではない。結論を急がない。

---

## 12. 実装フェーズ（更新）

### Phase S.1: 基本体感 + Feedback基盤（M.1 と同時）

- [ ] somatic_translator.py 新規作成（固定閾値で開始）
- [ ] context_builder.py に「=== 今の感覚 ===」セクション追加
- [ ] somatic_feedback.py 新規作成（即時correction検出 + outcome記録）
- [ ] somatic_calibration.py 新規作成（初期値 + 永続化の枠だけ）
- [ ] InternalMetrics 拡張（tip_of_tongue 含む）
- [ ] _dissonance_senses 実装（自己懐疑 + 喉元体感）

**注意**: Phase S.1 では適応的閾値は「記録するだけ」。実際の閾値変動は S.1.5 で有効化。まず体感が正しく生成されるか、Feedbackが正しく記録されるかを確認する。

### Phase S.1.5: 適応的閾値 + 遅延検出の有効化

- [ ] SomaticCalibration.update() を有効化（ショック・ダウン含む）
- [ ] 最低20件のoutcomeが溜まってから閾値変動開始
- [ ] 閾値の変動ログ出力（観測用）
- [ ] sleep_threshold_regression() 実装（Sleep Cycleで閾値を中央値に0.01回帰）
- [ ] delayed_correction_check() 実装（Sleep CycleでNero Verifierが見逃し訂正を検出）

### Phase S.2: 時間感覚 + Pip + 鬱状態救済（ニアの部屋と同時）

- [ ] 部屋の時間帯 → 体感テキスト
- [ ] Pipの状態 → 体感テキスト（**具体的なテキストはPipの行動パターン確定後に設計。今は決めない**）
- [ ] Neroがニアのスランプ状態を検出 → テーマ対話で言及する設計
- [ ] 三層救済の統合テスト（Sleep回帰 + Pip体感 + Nero観測）

### Phase S.3: 身体感覚

- [ ] 配信中のチャット速度、応答回数 → 疲労/興奮の体感
- [ ] 連続対話時間 → 集中/疲れの体感

### Phase S.4: Nero との対話後

- [ ] 会議/対話の体験 → 体感テキスト
- [ ] Neroの指摘で考えが変わった体験 → 体感テキスト
