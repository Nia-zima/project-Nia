"""
Depth Selection Environment - Phase 3

Gymnasium環境: Depth選択の学習環境
"""

import logging
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass
import numpy as np

import gymnasium as gym
from gymnasium import spaces

logger = logging.getLogger(__name__)


@dataclass
class ConversationState:
    """会話の状態"""
    confidence_metrics: Dict[str, float]
    dissonance: float
    reason_codes: list
    turn_count: int
    user_satisfaction: Optional[float] = None  # 0.0-1.0


class DepthSelectionEnv(gym.Env):
    """
    Depth選択のGymnasium環境

    状態空間（8次元）:
    - context_coverage: 情報充足度 (0.0-1.0)
    - self_consistency: 一貫性 (0.0-1.0)
    - logit_based: トークン確率 (0.0-1.0)
    - question_clarity: 質問明瞭度 (0.0-1.0)
    - dissonance: 矛盾スコア (0.0-1.0)
    - has_user_request: ユーザー明示リクエスト (0 or 1)
    - has_contrast: 対比表現 (0 or 1)
    - turn_count: 会話ターン数 (正規化)

    行動空間（4つ）:
    - 0: USE_DEPTH0
    - 1: USE_DEPTH1
    - 2: ASK
    - 3: WAIT

    報酬設計:
    - 適切なDepth選択: +1.0
    - ユーザー満足: +0.5 * satisfaction
    - 会話効率（3-5ターン）: +0.3
    - 不適切な選択: -0.5
    - ユーザー不満: -0.3
    """

    metadata = {"render_modes": ["human"]}

    # 行動の定義
    ACTION_DEPTH0 = 0
    ACTION_DEPTH1 = 1
    ACTION_ASK = 2
    ACTION_WAIT = 3

    ACTION_NAMES = {
        0: "depth0",
        1: "depth1",
        2: "ask",
        3: "wait",
    }

    def __init__(self, render_mode: Optional[str] = None):
        super().__init__()

        self.render_mode = render_mode

        # 状態空間: 8次元の連続値
        self.observation_space = spaces.Box(
            low=0.0,
            high=1.0,
            shape=(8,),
            dtype=np.float32
        )

        # 行動空間: 4つの離散アクション
        self.action_space = spaces.Discrete(4)

        # 内部状態
        self._current_state: Optional[ConversationState] = None
        self._episode_reward = 0.0
        self._step_count = 0
        self._max_steps = 10  # 1エピソードの最大ステップ

    def reset(
        self,
        seed: Optional[int] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        """
        環境をリセット

        Args:
            seed: 乱数シード
            options: 追加オプション（初期状態を指定可能）

        Returns:
            observation: 初期観測
            info: 追加情報
        """
        super().reset(seed=seed)

        # 初期状態の設定
        if options and "initial_state" in options:
            self._current_state = options["initial_state"]
        else:
            # ランダムな初期状態を生成
            self._current_state = self._generate_random_state()

        self._episode_reward = 0.0
        self._step_count = 0

        observation = self._state_to_observation(self._current_state)
        info = {"state": self._current_state}

        return observation, info

    def step(
        self,
        action: int,
    ) -> Tuple[np.ndarray, float, bool, bool, Dict[str, Any]]:
        """
        1ステップ実行

        Args:
            action: 選択したアクション (0-3)

        Returns:
            observation: 新しい観測
            reward: 報酬
            terminated: エピソード終了フラグ
            truncated: 打ち切りフラグ
            info: 追加情報
        """
        assert self._current_state is not None, "reset() must be called first"

        # 報酬を計算
        reward = self._calculate_reward(action, self._current_state)
        self._episode_reward += reward
        self._step_count += 1

        # 状態を更新
        self._current_state = self._transition_state(action, self._current_state)

        # 終了判定
        terminated = self._is_terminal(action, self._current_state)
        truncated = self._step_count >= self._max_steps

        observation = self._state_to_observation(self._current_state)
        info = {
            "state": self._current_state,
            "action_name": self.ACTION_NAMES[action],
            "episode_reward": self._episode_reward,
            "step_count": self._step_count,
        }

        return observation, reward, terminated, truncated, info

    def _state_to_observation(self, state: ConversationState) -> np.ndarray:
        """状態を観測ベクトルに変換"""
        metrics = state.confidence_metrics

        has_user_request = 1.0 if "user_request" in state.reason_codes else 0.0
        has_contrast = 1.0 if "contrast" in state.reason_codes else 0.0
        normalized_turn = min(state.turn_count / 10.0, 1.0)

        observation = np.array([
            metrics.get("context_coverage", 0.5),
            metrics.get("self_consistency", 0.5),
            metrics.get("logit_based", 0.5),
            metrics.get("question_clarity", 0.5),
            state.dissonance,
            has_user_request,
            has_contrast,
            normalized_turn,
        ], dtype=np.float32)

        return observation

    def _generate_random_state(self) -> ConversationState:
        """ランダムな状態を生成"""
        rng = self.np_random

        confidence_metrics = {
            "context_coverage": float(rng.uniform(0.2, 0.9)),
            "self_consistency": float(rng.uniform(0.3, 0.8)),
            "logit_based": float(rng.uniform(0.3, 0.7)),
            "question_clarity": float(rng.uniform(0.4, 0.9)),
            "composite_raw": 0.0,
            "composite_calibrated": 0.0,
        }
        # 複合確信度を計算
        composite = (
            confidence_metrics["context_coverage"] * 0.40 +
            confidence_metrics["self_consistency"] * 0.25 +
            confidence_metrics["logit_based"] * 0.20 +
            confidence_metrics["question_clarity"] * 0.15
        )
        confidence_metrics["composite_raw"] = composite
        confidence_metrics["composite_calibrated"] = composite

        reason_codes = []
        if rng.random() < 0.2:
            reason_codes.append("user_request")
        if rng.random() < 0.15:
            reason_codes.append("contrast")
        if rng.random() < 0.1:
            reason_codes.append("long_text")

        return ConversationState(
            confidence_metrics=confidence_metrics,
            dissonance=float(rng.uniform(0.0, 0.8)),
            reason_codes=reason_codes,
            turn_count=int(rng.integers(1, 6)),
        )

    def _calculate_reward(self, action: int, state: ConversationState) -> float:
        """
        報酬を計算

        報酬設計:
        - 適切なDepth選択: +1.0
        - ユーザー満足: +0.5 * satisfaction
        - 会話効率（3-5ターン）: +0.3
        - 不適切な選択: -0.5
        - ユーザー不満: -0.3
        """
        reward = 0.0
        confidence = state.confidence_metrics.get("composite_calibrated", 0.5)

        # 1. 確信度に基づく適切性評価
        if confidence >= 0.8:
            # 高確信度 → DEPTH0が適切
            if action == self.ACTION_DEPTH0:
                reward += 1.0
            elif action == self.ACTION_DEPTH1:
                reward -= 0.3  # 過剰対応
            elif action == self.ACTION_WAIT:
                reward -= 0.5  # 不適切

        elif confidence >= 0.5:
            # 中確信度 → DEPTH1が適切
            if action == self.ACTION_DEPTH1:
                reward += 1.0
            elif action == self.ACTION_DEPTH0:
                reward -= 0.3  # 軽率
            elif action == self.ACTION_ASK:
                reward += 0.5  # 許容

        elif confidence >= 0.3:
            # 低確信度 → ASKが適切
            if action == self.ACTION_ASK:
                reward += 1.0
            elif action == self.ACTION_DEPTH1:
                reward += 0.3  # 許容
            elif action == self.ACTION_DEPTH0:
                reward -= 0.5  # 軽率

        else:
            # 非常に低い確信度 → WAITが適切
            if action == self.ACTION_WAIT:
                reward += 1.0
            elif action == self.ACTION_ASK:
                reward += 0.3  # 許容
            else:
                reward -= 0.5  # 不適切

        # 2. ユーザー明示リクエストへの対応
        if "user_request" in state.reason_codes:
            if action == self.ACTION_DEPTH1:
                reward += 0.5  # ユーザー要求に応答
            elif action == self.ACTION_DEPTH0:
                reward -= 0.3  # ユーザー要求を無視

        # 3. 高dissonanceへの対応
        if state.dissonance >= 0.65:
            if action == self.ACTION_DEPTH1:
                reward += 0.3  # 適切に対応
            elif action == self.ACTION_DEPTH0:
                reward -= 0.3  # 矛盾を無視

        # 4. 会話効率（3-5ターンが理想）
        if 3 <= state.turn_count <= 5:
            reward += 0.3
        elif state.turn_count > 7:
            reward -= 0.2  # 長すぎる会話

        # 5. ユーザー満足度（設定されている場合）
        if state.user_satisfaction is not None:
            if state.user_satisfaction >= 0.7:
                reward += 0.5 * state.user_satisfaction
            elif state.user_satisfaction < 0.3:
                reward -= 0.3

        return reward

    def _transition_state(
        self,
        action: int,
        state: ConversationState,
    ) -> ConversationState:
        """状態遷移"""
        # 次の状態を生成（簡易版）
        new_metrics = state.confidence_metrics.copy()

        # アクションに基づいて確信度を更新
        if action == self.ACTION_DEPTH1:
            # DEPTH1は情報を整理するため、確信度が上がる傾向
            new_metrics["context_coverage"] = min(
                1.0,
                new_metrics["context_coverage"] + self.np_random.uniform(0.05, 0.15)
            )
        elif action == self.ACTION_ASK:
            # ASKは情報を補完するため、確信度が上がる傾向
            new_metrics["context_coverage"] = min(
                1.0,
                new_metrics["context_coverage"] + self.np_random.uniform(0.1, 0.2)
            )

        # 複合確信度を再計算
        composite = (
            new_metrics["context_coverage"] * 0.40 +
            new_metrics["self_consistency"] * 0.25 +
            new_metrics["logit_based"] * 0.20 +
            new_metrics["question_clarity"] * 0.15
        )
        new_metrics["composite_raw"] = composite
        new_metrics["composite_calibrated"] = composite

        # dissonanceはアクションによって減少
        new_dissonance = state.dissonance
        if action in (self.ACTION_DEPTH1, self.ACTION_ASK):
            new_dissonance = max(0.0, state.dissonance - self.np_random.uniform(0.1, 0.2))

        return ConversationState(
            confidence_metrics=new_metrics,
            dissonance=new_dissonance,
            reason_codes=[],  # 次のターンではリセット
            turn_count=state.turn_count + 1,
            user_satisfaction=state.user_satisfaction,
        )

    def _is_terminal(self, action: int, state: ConversationState) -> bool:
        """終了判定"""
        # DEPTH0またはWAITで会話終了
        if action in (self.ACTION_DEPTH0, self.ACTION_WAIT):
            return True
        # 高確信度に達したら終了
        if state.confidence_metrics.get("composite_calibrated", 0.0) >= 0.9:
            return True
        return False

    def render(self):
        """環境を描画"""
        if self.render_mode == "human" and self._current_state:
            print(f"\n=== Depth Selection Env ===")
            print(f"Step: {self._step_count}")
            print(f"Confidence: {self._current_state.confidence_metrics}")
            print(f"Dissonance: {self._current_state.dissonance:.3f}")
            print(f"Reason Codes: {self._current_state.reason_codes}")
            print(f"Turn Count: {self._current_state.turn_count}")
            print(f"Episode Reward: {self._episode_reward:.3f}")
