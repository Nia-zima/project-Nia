# 統合ロードマップ: 即答抑制の仕様化と学習の分離

## 🎯 基本方針

**核心的な変更**:
- ❌ **旧案**: 即答抑制を学習（Gymnasium）で解決
- ✅ **新案**: 即答抑制を仕様（Depth契約）で解決、学習は"いつ使うか"に専念

**設計哲学**:
> **"What"（何をするか）は原則化、"When"（いつやるか）は学習**

---

## 📋 フェーズ概要

| フェーズ | 目的 | 期間 | 成果物 |
|---------|-----|------|-------|
| **Phase 0** | 壊れない運用 | 2週間 | Depth契約の仕様化 |
| **Phase 1** | 確信度システム | 3週間 | 信頼度キャリブレーション |
| **Phase 2** | LangGraph本番化 | 3週間 | Depth選択ノードの統合 |
| **Phase 3** | 方策学習（Gymnasium） | 4週間 | Depth選択の最適化 |
| **Phase 4** | 品質改善（DSPy） | 3週間 | 出力品質の向上 |
| **Phase 5** | 身体I/F | 4週間 | アクションAPI統合 |

---

## Phase 0: 壊れない運用（仕様の明確化）

### 目標
即答抑制の**原則**をコードに落とし込む。ルールではなく**原則**。

### 実装内容

#### 1. Depth契約の定義

**Depth0（Pre-Thought）の原則**:
```python
# backend/core/agent_graph/contracts.py

class Depth0Contract:
    """
    Depth0 (Pre-Thought) の契約

    原則:
    - 結論を出さない
    - 不確実性を明示する
    - 思考の断片を示す
    """

    @staticmethod
    def validate(output: str) -> ValidationResult:
        violations = []

        # 禁止パターン（柔軟に）
        conclusion_patterns = [
            r"〜と思います$",           # 断定的結論
            r"〜すべきです$",           # 指示
            r"答えは〜です",            # 明確な答え
            r"結論としては",            # 結論宣言
        ]

        for pattern in conclusion_patterns:
            if re.search(pattern, output):
                violations.append(f"Conclusion detected: {pattern}")

        # 推奨パターン（必須ではない）
        uncertainty_patterns = [
            r"まだわからない",
            r"不確か",
            r"〜かもしれない",
            r"〜の観点では",
        ]

        has_uncertainty = any(
            re.search(pattern, output)
            for pattern in uncertainty_patterns
        )

        return ValidationResult(
            is_valid=len(violations) == 0,
            violations=violations,
            has_uncertainty_expression=has_uncertainty
        )
```

**Depth1（Organize & Ask）の原則**:
```python
class Depth1Contract:
    """
    Depth1 (Organize & Ask) の契約

    原則:
    - 1つの不確実性に焦点を当てる（質問数ではない）
    - 思考を整理する
    - 必要なら確認を取る
    """

    @staticmethod
    def validate(output: str) -> ValidationResult:
        violations = []

        # 不確実性の数を数える（焦点の数）
        uncertainties = extract_core_uncertainties(output)

        if len(uncertainties) > 2:
            violations.append(
                f"Too many focal points: {len(uncertainties)} "
                "(should focus on 1-2 core uncertainties)"
            )

        # 整理されているか
        has_structure = check_logical_structure(output)
        if not has_structure:
            violations.append("Lacks logical organization")

        return ValidationResult(
            is_valid=len(violations) == 0,
            violations=violations,
            focal_points=uncertainties
        )

def extract_core_uncertainties(text: str) -> list[str]:
    """
    テキストから核心的な不確実性を抽出

    例:
    「AとBのどちらを優先すべきか、まだ決めかねています。
     Cについても考慮が必要です。」
    → ["A vs B の優先順位", "C の考慮"]
    """
    # LLMで抽出（シンプルなプロンプト）
    prompt = f"""
    以下のテキストから、焦点となっている不確実性・疑問点を抽出してください。

    テキスト: {text}

    不確実性（JSON配列で）:
    """

    uncertainties = llm.extract_json_list(prompt)
    return uncertainties
```

#### 2. ログ検証システム

```python
# backend/scripts/validate_depth_usage.py

def validate_conversation_logs(log_file: str):
    """
    過去の会話ログでDepth契約違反を検出
    """
    violations = []

    for conversation in load_conversations(log_file):
        for turn in conversation:
            depth = turn["depth_used"]
            output = turn["nia_response"]

            if depth == 0:
                result = Depth0Contract.validate(output)
                if not result.is_valid:
                    violations.append({
                        "turn_id": turn["id"],
                        "depth": 0,
                        "violations": result.violations,
                        "output": output
                    })

            elif depth == 1:
                result = Depth1Contract.validate(output)
                if not result.is_valid:
                    violations.append({
                        "turn_id": turn["id"],
                        "depth": 1,
                        "violations": result.violations,
                        "output": output
                    })

    # レポート生成
    generate_violation_report(violations)

    return violations
```

#### 3. 進展検知（滞留防止）

```python
def detect_dwelling_without_progress(conversation: list) -> bool:
    """
    進展のない滞留を検出

    良い滞留: 「まだわからない」→「Aの観点では〜」→「Bも考慮すると〜」
    悪い滞留: 「まだわからない」→「まだわからない」→「まだわからない」
    """
    depth0_turns = [t for t in conversation if t["depth"] == 0]

    if len(depth0_turns) < 2:
        return False  # 滞留していない

    # 各ターンの情報エントロピーを計算
    entropies = [calculate_information_entropy(t["response"])
                 for t in depth0_turns]

    # エントロピーが増加している = 進展している
    has_progress = any(
        entropies[i+1] > entropies[i] * 1.1  # 10%以上増加
        for i in range(len(entropies) - 1)
    )

    return not has_progress  # 進展がない = 悪い滞留

def calculate_information_entropy(text: str) -> float:
    """
    テキストの情報量（新規性）を推定
    """
    # ユニークな概念の数
    concepts = extract_concepts(text)
    unique_concepts = len(set(concepts))

    # 文の多様性
    sentences = split_sentences(text)
    sentence_diversity = len(set(sentences)) / max(len(sentences), 1)

    return unique_concepts * sentence_diversity
```

### 完了基準

- [ ] Depth0/1契約のコード実装
- [ ] 過去ログでの違反率 < 10%
- [ ] 進展検知ロジックの動作確認
- [ ] ユニットテストのカバレッジ > 80%

---

## Phase 1: 確信度システムの構築

### 目標
**"いつDepth0/1を使うか"**を判断するための確信度メトリクスを実装。

### 実装内容

#### 1. 確信度計算エンジン

```python
# backend/services/confidence_engine.py

class ConfidenceEngine:
    """
    複合確信度計算エンジン
    """

    def __init__(self):
        self.calibration_curve = self.load_calibration()

    def calculate(self, question: str, context: str,
                  llm_output: dict) -> ConfidenceMetrics:
        """
        確信度を計算
        """
        # 各メトリクスを並列計算
        metrics = {
            "model": self.calculate_model_confidence(
                question, context
            ),
            "logit": self.calculate_logit_confidence(
                llm_output
            ),
            "context": self.calculate_context_confidence(
                question, context
            ),
            "clarity": self.calculate_clarity_confidence(
                question
            )
        }

        # 重み付け統合
        composite = self.combine_metrics(metrics)

        # キャリブレーション適用
        calibrated = self.apply_calibration(composite)

        return ConfidenceMetrics(
            composite=calibrated,
            breakdown=metrics,
            recommendation=self.get_recommendation(calibrated)
        )

    def combine_metrics(self, metrics: dict) -> float:
        """
        メトリクスを重み付け平均
        """
        weights = {
            "model": 0.25,
            "logit": 0.20,
            "context": 0.40,  # 最重要
            "clarity": 0.15
        }

        return sum(
            weights[key] * metrics[key]["confidence"]
            for key in weights
        )

    def get_recommendation(self, confidence: float) -> str:
        """
        確信度から推奨アクションを返す
        """
        if confidence >= 0.8:
            return "USE_DEPTH0"
        elif confidence >= 0.5:
            return "USE_DEPTH1"
        elif confidence >= 0.3:
            return "ASK"
        else:
            return "WAIT"
```

#### 2. オフラインキャリブレーション

```python
# backend/scripts/calibrate_confidence.py

def calibrate_from_logs(log_file: str, output_file: str):
    """
    過去ログから確信度をキャリブレーション
    """
    data = []

    for conversation in load_conversations(log_file):
        for turn in conversation:
            # 確信度を計算（生の値）
            raw_conf = calculate_raw_confidence(turn)

            # 実際の正しさ（人間評価 or メトリクス）
            correctness = evaluate_turn_correctness(turn)

            data.append({
                "raw_confidence": raw_conf,
                "correctness": correctness
            })

    # キャリブレーション曲線を作成
    calibration_curve = fit_calibration_curve(data)

    # 保存
    save_calibration_curve(calibration_curve, output_file)

    # 可視化
    plot_calibration(calibration_curve)
```

#### 3. Depth選択の基準実装

```python
# backend/core/agent_graph/depth_selector.py

class DepthSelector:
    """
    確信度ベースのDepth選択器
    """

    def __init__(self, confidence_engine: ConfidenceEngine):
        self.confidence_engine = confidence_engine

    def select_depth(self, question: str, context: str,
                     llm_output: dict) -> DepthDecision:
        """
        確信度に基づいてDepthを選択
        """
        # 確信度計算
        metrics = self.confidence_engine.calculate(
            question, context, llm_output
        )

        # 推奨アクションを取得
        recommendation = metrics.recommendation

        # アクションをDepthにマッピング
        action_to_depth = {
            "USE_DEPTH0": 0,
            "USE_DEPTH1": 1,
            "ASK": 1,        # ASKはDepth1で実装
            "WAIT": 0        # WAITはDepth0で実装
        }

        depth = action_to_depth[recommendation]

        return DepthDecision(
            depth=depth,
            action=recommendation,
            confidence=metrics.composite,
            reasoning=self.explain_decision(metrics)
        )

    def explain_decision(self, metrics: ConfidenceMetrics) -> str:
        """
        決定理由を説明
        """
        breakdown = metrics.breakdown

        reasons = []

        if breakdown["context"]["confidence"] < 0.3:
            reasons.append("情報不足")

        if breakdown["clarity"]["confidence"] < 0.4:
            reasons.append("質問が曖昧")

        if breakdown["model"]["confidence"] < 0.5:
            reasons.append("LLMの確信度が低い")

        return " / ".join(reasons) if reasons else "十分な確信"
```

### 完了基準

- [ ] 確信度エンジンの実装
- [ ] 過去ログからのキャリブレーション完了
- [ ] キャリブレーション精度（ECE < 0.1）
- [ ] Depth選択器の統合テスト

---

## Phase 2: LangGraph本番化（状態機械の明確化）

### 目標
Depth0/1を明示的なノードとして実装。Depth選択もノード化。

### 実装内容

#### グラフ構造の更新

```python
# backend/core/agent_graph/graph_v2.py

def create_depth_aware_graph():
    """
    Depth選択を組み込んだLangGraphを構築
    """
    graph = StateGraph(NiaState)

    # ノード追加
    graph.add_node("safety", safety_node)
    graph.add_node("dissonance", dissonance_check_node)
    graph.add_node("depth_selector", depth_selector_node)  # NEW
    graph.add_node("depth0", depth0_prethought_node)
    graph.add_node("depth1", depth1_organize_node)
    graph.add_node("merge", merge_node)

    # エッジ
    graph.set_entry_point("safety")
    graph.add_edge("safety", "dissonance")
    graph.add_edge("dissonance", "depth_selector")

    # Depth選択による分岐
    graph.add_conditional_edges(
        "depth_selector",
        decide_depth,  # 確信度で判断
        {
            "depth0": "depth0",
            "depth1": "depth1"
        }
    )

    graph.add_edge("depth0", "merge")
    graph.add_edge("depth1", "merge")
    graph.set_finish_point("merge")

    return graph.compile()

def depth_selector_node(state: NiaState):
    """
    確信度ベースでDepthを選択するノード
    """
    selector = DepthSelector(ConfidenceEngine())

    decision = selector.select_depth(
        question=state["user_input"],
        context=state["context"],
        llm_output=state["llm_raw_output"]
    )

    state["selected_depth"] = decision.depth
    state["depth_confidence"] = decision.confidence
    state["depth_reasoning"] = decision.reasoning

    return state

def decide_depth(state: NiaState) -> str:
    """
    条件分岐: Depth0 or Depth1
    """
    if state["selected_depth"] == 0:
        return "depth0"
    else:
        return "depth1"
```

### 完了基準

- [ ] Depth選択ノードの実装
- [ ] グラフの統合テスト
- [ ] 既存機能（Review Window）との互換性確認
- [ ] パフォーマンス測定（レイテンシ < 3秒）

---

## Phase 3: 方策学習（Gymnasium）

### 目標
**"いつどのDepthを使うか"**の方策を強化学習で最適化。

### 実装内容

#### 1. Gymnasium環境の構築

```python
# backend/rl/depth_selection_env.py

class NiaDepthSelectionEnv(gym.Env):
    """
    Depth選択を学習するための環境
    """

    def __init__(self):
        # 観測空間
        self.observation_space = spaces.Dict({
            "question_complexity": spaces.Box(0, 1, (1,)),
            "context_density": spaces.Box(0, 1, (1,)),
            "confidence_model": spaces.Box(0, 1, (1,)),
            "confidence_context": spaces.Box(0, 1, (1,)),
            "user_frustration": spaces.Box(0, 1, (1,)),
        })

        # 行動空間
        self.action_space = spaces.Discrete(4)
        # 0: DEPTH0, 1: DEPTH1, 2: ASK, 3: WAIT

    def step(self, action):
        # 行動を実行
        response = self.execute_action(action)

        # ユーザー反応をシミュレート
        feedback = self.simulate_user_feedback(action, response)

        # 報酬計算
        reward = self.calculate_reward(action, feedback)

        # 状態更新
        self.state = self.update_state(action, feedback)

        return self.state, reward, self.done, {}

    def calculate_reward(self, action, feedback):
        """
        報酬関数
        """
        reward = 0.0

        # 適切なDepth選択 → +
        if self.is_appropriate_depth(action):
            reward += 1.0

        # 不適切なDepth選択 → -
        else:
            reward -= 0.5

        # ユーザー満足度
        reward += feedback["satisfaction"]

        # ユーザー不満 → -
        reward -= feedback["frustration"]

        # 会話効率（短すぎず長すぎず）
        if 3 <= feedback["turn_count"] <= 5:
            reward += 0.3

        return reward
```

#### 2. Offline RL学習

```python
# backend/scripts/train_depth_policy.py

import d3rlpy

def train_depth_policy():
    """
    過去ログからOffline RLで方策学習
    """
    # データセット作成
    dataset = create_dataset_from_logs("data/nia.sqlite3")

    # CQL（Conservative Q-Learning）で学習
    cql = d3rlpy.algos.CQLConfig(
        actor_learning_rate=1e-4,
        critic_learning_rate=3e-4,
        batch_size=256,
    ).create()

    # 学習
    cql.fit(
        dataset,
        n_steps=100000,
        evaluators={
            "td_error": d3rlpy.metrics.TDErrorEvaluator(),
            "environment": evaluate_on_simulator,
        },
        save_interval=10000,
    )

    # モデル保存
    cql.save("models/depth_policy_v1.d3")

def create_dataset_from_logs(db_path: str):
    """
    過去ログからRL用データセットを作成
    """
    episodes = []

    for conversation in load_conversations(db_path):
        episode = []

        for turn in conversation:
            # 状態
            state = extract_state(turn)

            # 行動（実際に取られた）
            action = turn["depth_used"]

            # 報酬（後付け評価）
            reward = evaluate_turn(turn)

            episode.append((state, action, reward))

        episodes.append(episode)

    return d3rlpy.dataset.MDPDataset.from_episodes(episodes)
```

#### 3. Human-in-the-Loop

```python
# backend/scripts/human_feedback_collection.py

def collect_human_feedback():
    """
    人間評価を収集して方策を改善
    """
    policy = load_trained_policy("models/depth_policy_v1.d3")

    for episode in range(50):
        conversation = sample_conversation()

        for turn in conversation:
            # 方策が行動を選択
            action = policy.predict(turn["state"])

            # 実行
            response = execute_action(action, turn)

            # 人間に見せる
            print(f"Question: {turn['question']}")
            print(f"Action: {action}")
            print(f"Response: {response}")

            # 人間が評価
            satisfaction = input("Satisfaction (0-1): ")
            appropriateness = input("Was depth choice appropriate? (y/n): ")

            # データ蓄積
            store_human_feedback(
                turn, action, response,
                satisfaction, appropriateness
            )

        # 定期的に再学習
        if episode % 10 == 0:
            retrain_with_human_feedback()
```

### 完了基準

- [ ] Gymnasium環境の実装
- [ ] Offline RLでの初期学習完了
- [ ] 50エピソード以上の人間評価収集
- [ ] ベースライン（確信度のみ）比較で性能向上

---

## Phase 4: 品質改善（DSPy）

### 目標
Depth1の出力品質を最適化。**行動ではなく品質**に専念。

### 実装内容

#### 1. DSPyプログラムの定義

```python
# backend/services/dspy_depth1_optimizer.py

import dspy

class Depth1Organizer(dspy.Signature):
    """
    Depth1での整理・確認の品質を最適化
    """

    # 入力
    question = dspy.InputField(desc="ユーザーの質問")
    context = dspy.InputField(desc="会話コンテキスト")
    uncertainty = dspy.InputField(desc="核心的な不確実性")

    # 出力
    organized_thought = dspy.OutputField(
        desc="整理された思考（断定を避ける）"
    )
    clarification = dspy.OutputField(
        desc="確認質問（1つの不確実性に焦点）"
    )

class Depth1Module(dspy.Module):
    def __init__(self):
        super().__init__()
        self.organizer = dspy.ChainOfThought(Depth1Organizer)

    def forward(self, question, context, uncertainty):
        result = self.organizer(
            question=question,
            context=context,
            uncertainty=uncertainty
        )

        return result.organized_thought, result.clarification
```

#### 2. 最適化

```python
# backend/scripts/optimize_depth1.py

def optimize_depth1_quality():
    """
    DSPyでDepth1の品質を最適化
    """
    # トレーニングデータ
    trainset = load_depth1_examples()

    # メトリクス定義
    def quality_metric(example, prediction):
        score = 0.0

        # 断定抑制
        if not contains_assertions(prediction.organized_thought):
            score += 0.3

        # 反復抑制
        if not has_repetition(prediction.organized_thought):
            score += 0.3

        # 焦点の明確さ
        if is_focused(prediction.clarification):
            score += 0.4

        return score

    # オプティマイザー
    optimizer = dspy.BootstrapFewShot(
        metric=quality_metric,
        max_bootstrapped_demos=8
    )

    # 最適化実行
    optimized_module = optimizer.compile(
        Depth1Module(),
        trainset=trainset
    )

    # 保存
    optimized_module.save("models/depth1_optimized.json")
```

### 完了基準

- [ ] DSPyプログラムの実装
- [ ] 100例以上のトレーニングデータ収集
- [ ] 最適化完了（品質スコア > 0.8）
- [ ] A/Bテストで改善確認

---

## Phase 5: 身体I/F（アクション統合）

### 目標
Depth0/1の原則を保ちながら、物理的なアクションを統合。

### 実装内容

#### アクションゲートの実装

```python
# backend/services/action_gate.py

class ActionGate:
    """
    アクション実行のゲート
    Depth0では即座に実行しない
    """

    def request_action(self, action: Action, depth: int,
                       confidence: float) -> ActionDecision:
        """
        アクション実行を判断
        """
        # Depth0 では実行しない
        if depth == 0:
            return ActionDecision(
                should_execute=False,
                reason="Depth0では行動を保留"
            )

        # Depth1 でも確信度が低ければ保留
        if depth == 1 and confidence < 0.6:
            return ActionDecision(
                should_execute=False,
                reason="確信度が低いため保留"
            )

        # リスクが高い行動は確認を要求
        if action.risk_level > 0.7:
            return ActionDecision(
                should_execute=False,
                requires_confirmation=True,
                reason="リスクが高いため確認必要"
            )

        # 実行OK
        return ActionDecision(should_execute=True)
```

### 完了基準

- [ ] アクションゲートの実装
- [ ] 10種類以上のアクションAPI統合
- [ ] 不用意な実行が起きないことを確認
- [ ] ユーザーテストでの安全性確認

---

## 📊 成功指標（KPI）

### Phase 0-1: 確信度システム
- [ ] キャリブレーション精度（ECE）< 0.1
- [ ] Depth契約違反率 < 5%
- [ ] 進展のない滞留率 < 10%

### Phase 2-3: 学習システム
- [ ] Depth選択の適切性 > 85%
- [ ] ユーザー満足度 > 4.0/5.0
- [ ] 平均会話ターン数: 3-5ターン

### Phase 4-5: 品質・統合
- [ ] 出力品質スコア > 0.8
- [ ] 不要なアクション実行率 < 1%
- [ ] システム全体のレイテンシ < 3秒

---

## 🔄 継続的改善プロセス

```python
# backend/scripts/continuous_improvement.py

def weekly_improvement_cycle():
    """
    週次の改善サイクル
    """
    # 1. データ収集
    data = collect_week_data()

    # 2. 人間評価
    labeled_data = add_human_labels(data, sample_size=50)

    # 3. キャリブレーション更新
    new_calibration = recalibrate_confidence(labeled_data)

    # 4. 方策再学習（Offline RL）
    new_policy = retrain_policy(labeled_data)

    # 5. A/Bテスト
    ab_test_results = run_ab_test(new_policy, duration_days=3)

    # 6. 改善確認 → デプロイ
    if ab_test_results["improvement"] > 0.05:
        deploy_new_policy(new_policy)
        deploy_new_calibration(new_calibration)
```

---

## 🎯 まとめ: 各フェーズの役割

| フェーズ | 何を決める | どう決める |
|---------|----------|----------|
| Phase 0 | Depth0/1の**原則** | 設計 |
| Phase 1 | 確信度の**計算** | メトリクス |
| Phase 2 | グラフの**構造** | LangGraph |
| Phase 3 | Depthの**選択** | 強化学習 |
| Phase 4 | 出力の**品質** | DSPy |
| Phase 5 | 行動の**ゲート** | 安全性設計 |

---

**このロードマップでは**:
- ✅ ルールではなく**原則**をコード化
- ✅ Gymnasiumは**学習**に使う（検証ではない）
- ✅ 確信度で**"いつ"**を判断
- ✅ DSPyは**品質**に専念

**結果として**:
- 🎯 即答抑制が仕様として実現
- 🎯 柔軟な判断が学習で獲得
- 🎯 継続的な改善が可能
