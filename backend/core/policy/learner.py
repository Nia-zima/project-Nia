"""
Policy Learner - Phase 3

Offline RLによる方策学習アルゴリズム
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
import numpy as np

from backend.core.config import settings
from .collector import ExperienceCollector, Experience

logger = logging.getLogger(__name__)

# モデル保存先
MODEL_DIR = settings.LOG_DIR / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class PolicyConfig:
    """方策設定"""
    learning_rate: float = 0.01
    discount_factor: float = 0.95
    epsilon: float = 0.1  # 探索率
    batch_size: int = 32
    n_epochs: int = 100
    state_dim: int = 8
    n_actions: int = 4


class PolicyLearner:
    """
    方策学習クラス

    シンプルなテーブル形式のQ-learningを実装。
    状態空間を離散化してQ値を学習します。

    Phase 3 v1: 離散化Q-learning
    Phase 3.5+: ニューラルネットワークへの拡張予定
    """

    def __init__(self, config: Optional[PolicyConfig] = None):
        self.config = config or PolicyConfig()

        # Q-tableの初期化
        # 状態を離散化するために、各次元を10ビンに分割
        self.n_bins = 10
        self.q_table: Dict[tuple, np.ndarray] = {}

        # 学習履歴
        self.training_history: List[Dict[str, float]] = []

    def _discretize_state(self, state: np.ndarray) -> tuple:
        """
        状態を離散化

        Args:
            state: 連続状態ベクトル (8次元)

        Returns:
            tuple: 離散化された状態キー
        """
        # 各次元を0-9の整数に変換
        discretized = np.clip(
            (state * self.n_bins).astype(int),
            0,
            self.n_bins - 1
        )
        return tuple(discretized)

    def _get_q_values(self, state: np.ndarray) -> np.ndarray:
        """
        状態のQ値を取得

        Args:
            state: 状態ベクトル

        Returns:
            np.ndarray: Q値 (4次元)
        """
        key = self._discretize_state(state)
        if key not in self.q_table:
            # 初期Q値は0
            self.q_table[key] = np.zeros(self.config.n_actions)
        return self.q_table[key]

    def select_action(
        self,
        state: np.ndarray,
        explore: bool = False,
    ) -> int:
        """
        行動を選択

        Args:
            state: 状態ベクトル
            explore: 探索を有効にするか

        Returns:
            int: 選択した行動
        """
        if explore and np.random.random() < self.config.epsilon:
            # ε-greedy探索
            return np.random.randint(self.config.n_actions)

        q_values = self._get_q_values(state)
        return int(np.argmax(q_values))

    def get_action_probabilities(self, state: np.ndarray) -> np.ndarray:
        """
        行動確率を取得（ソフトマックス）

        Args:
            state: 状態ベクトル

        Returns:
            np.ndarray: 行動確率分布
        """
        q_values = self._get_q_values(state)

        # ソフトマックス（温度パラメータ = 1.0）
        exp_q = np.exp(q_values - np.max(q_values))  # 数値安定性
        return exp_q / np.sum(exp_q)

    def train_step(
        self,
        state: np.ndarray,
        action: int,
        reward: float,
        next_state: np.ndarray,
        done: bool,
    ) -> float:
        """
        1ステップの学習

        Args:
            state: 現在の状態
            action: 取った行動
            reward: 得た報酬
            next_state: 次の状態
            done: エピソード終了フラグ

        Returns:
            float: TD誤差
        """
        key = self._discretize_state(state)
        if key not in self.q_table:
            self.q_table[key] = np.zeros(self.config.n_actions)

        # 現在のQ値
        current_q = self.q_table[key][action]

        # ターゲットQ値
        if done:
            target_q = reward
        else:
            next_q_values = self._get_q_values(next_state)
            target_q = reward + self.config.discount_factor * np.max(next_q_values)

        # TD誤差
        td_error = target_q - current_q

        # Q値を更新
        self.q_table[key][action] += self.config.learning_rate * td_error

        return td_error

    def train(
        self,
        collector: ExperienceCollector,
        n_epochs: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        バッチ学習

        Args:
            collector: 経験収集器
            n_epochs: エポック数

        Returns:
            Dict: 学習結果
        """
        n_epochs = n_epochs or self.config.n_epochs

        if len(collector.buffer) == 0:
            logger.warning("[LEARNER] No experiences to train on")
            return {"error": "No experiences"}

        logger.info("[LEARNER] Starting training with %d experiences", len(collector.buffer))

        total_td_errors = []
        epoch_losses = []

        for epoch in range(n_epochs):
            # バッチを取得
            states, actions, rewards, next_states, dones = collector.get_numpy_batch(
                self.config.batch_size
            )

            epoch_td_errors = []
            for i in range(len(states)):
                td_error = self.train_step(
                    states[i],
                    actions[i],
                    rewards[i],
                    next_states[i],
                    dones[i],
                )
                epoch_td_errors.append(abs(td_error))

            mean_td_error = np.mean(epoch_td_errors)
            total_td_errors.extend(epoch_td_errors)
            epoch_losses.append(mean_td_error)

            if (epoch + 1) % 10 == 0:
                logger.info(
                    "[LEARNER] Epoch %d/%d: mean_td_error=%.4f",
                    epoch + 1, n_epochs, mean_td_error
                )

        # 学習履歴を記録
        result = {
            "n_epochs": n_epochs,
            "n_experiences": len(collector.buffer),
            "final_td_error": float(epoch_losses[-1]) if epoch_losses else 0.0,
            "mean_td_error": float(np.mean(total_td_errors)),
            "q_table_size": len(self.q_table),
            "timestamp": datetime.now().isoformat(),
        }

        self.training_history.append(result)
        logger.info("[LEARNER] Training completed: %s", result)

        return result

    def evaluate(
        self,
        collector: ExperienceCollector,
        n_samples: int = 100,
    ) -> Dict[str, Any]:
        """
        方策を評価

        Args:
            collector: 経験収集器
            n_samples: 評価サンプル数

        Returns:
            Dict: 評価結果
        """
        if len(collector.buffer) == 0:
            return {"error": "No experiences"}

        batch = collector.get_batch(min(n_samples, len(collector.buffer)))

        correct_predictions = 0
        total_reward_diff = 0.0

        for exp in batch:
            state_vec, action, reward, _, _ = exp.to_numpy()
            predicted_action = self.select_action(state_vec, explore=False)

            if predicted_action == action:
                correct_predictions += 1

            # 予測した行動のQ値と実際の報酬の差
            q_values = self._get_q_values(state_vec)
            total_reward_diff += abs(q_values[action] - reward)

        accuracy = correct_predictions / len(batch)
        mean_reward_diff = total_reward_diff / len(batch)

        return {
            "accuracy": accuracy,
            "mean_reward_diff": mean_reward_diff,
            "n_samples": len(batch),
        }

    def save(self, filename: Optional[str] = None):
        """
        モデルを保存

        Args:
            filename: ファイル名
        """
        if filename is None:
            filename = f"policy_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        filepath = MODEL_DIR / filename

        # Q-tableを保存可能な形式に変換
        q_table_serializable = {
            str(k): v.tolist() for k, v in self.q_table.items()
        }

        data = {
            "config": {
                "learning_rate": self.config.learning_rate,
                "discount_factor": self.config.discount_factor,
                "epsilon": self.config.epsilon,
                "n_bins": self.n_bins,
            },
            "q_table": q_table_serializable,
            "training_history": self.training_history,
            "timestamp": datetime.now().isoformat(),
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info("[LEARNER] Saved model to %s", filepath)

    def load(self, filename: str) -> bool:
        """
        モデルを読み込み

        Args:
            filename: ファイル名

        Returns:
            bool: 成功したか
        """
        filepath = MODEL_DIR / filename

        if not filepath.exists():
            logger.warning("[LEARNER] Model file not found: %s", filepath)
            return False

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 設定を復元
        config_data = data.get("config", {})
        self.config.learning_rate = config_data.get("learning_rate", 0.01)
        self.config.discount_factor = config_data.get("discount_factor", 0.95)
        self.config.epsilon = config_data.get("epsilon", 0.1)
        self.n_bins = config_data.get("n_bins", 10)

        # Q-tableを復元
        q_table_data = data.get("q_table", {})
        self.q_table = {}
        for k, v in q_table_data.items():
            # 文字列キーをタプルに変換
            key = tuple(map(int, k.strip("()").split(", ")))
            self.q_table[key] = np.array(v)

        self.training_history = data.get("training_history", [])

        logger.info("[LEARNER] Loaded model from %s", filepath)
        return True

    def get_policy_summary(self) -> Dict[str, Any]:
        """
        方策のサマリーを取得

        Returns:
            Dict: 方策サマリー
        """
        if not self.q_table:
            return {"status": "untrained"}

        # 各状態での最適行動の分布を計算
        action_counts = {0: 0, 1: 0, 2: 0, 3: 0}
        for q_values in self.q_table.values():
            best_action = int(np.argmax(q_values))
            action_counts[best_action] += 1

        total = sum(action_counts.values())
        action_distribution = {
            "depth0": action_counts[0] / total if total > 0 else 0,
            "depth1": action_counts[1] / total if total > 0 else 0,
            "ask": action_counts[2] / total if total > 0 else 0,
            "wait": action_counts[3] / total if total > 0 else 0,
        }

        return {
            "status": "trained",
            "q_table_size": len(self.q_table),
            "action_distribution": action_distribution,
            "training_epochs": len(self.training_history),
        }


# グローバルインスタンス
policy_learner = PolicyLearner()
