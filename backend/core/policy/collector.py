"""
Experience Collector - Phase 3

Offline RL用の経験データ収集機構
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
import numpy as np

from backend.core.config import settings

logger = logging.getLogger(__name__)

# 経験データ保存先
EXPERIENCE_DIR = settings.LOG_DIR / "experiences"
EXPERIENCE_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class Experience:
    """
    1ステップの経験データ

    Offline RLで使用する(s, a, r, s', done)タプル
    """
    # 状態
    state: Dict[str, float]  # 観測ベクトル
    confidence_metrics: Dict[str, float]
    dissonance: float
    reason_codes: List[str]
    turn_count: int

    # 行動
    action: int  # 0: depth0, 1: depth1, 2: ask, 3: wait
    action_name: str

    # 報酬
    reward: float
    reward_components: Dict[str, float] = field(default_factory=dict)

    # 次の状態
    next_state: Optional[Dict[str, float]] = None
    done: bool = False

    # メタデータ
    thread_id: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    user_satisfaction: Optional[float] = None  # 人間フィードバック

    def to_dict(self) -> Dict[str, Any]:
        """辞書に変換"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Experience":
        """辞書から生成"""
        return cls(**data)

    def to_numpy(self) -> tuple:
        """NumPy形式に変換"""
        state_vec = np.array([
            self.state.get("context_coverage", 0.5),
            self.state.get("self_consistency", 0.5),
            self.state.get("logit_based", 0.5),
            self.state.get("question_clarity", 0.5),
            self.dissonance,
            1.0 if "user_request" in self.reason_codes else 0.0,
            1.0 if "contrast" in self.reason_codes else 0.0,
            min(self.turn_count / 10.0, 1.0),
        ], dtype=np.float32)

        next_state_vec = None
        if self.next_state:
            next_state_vec = np.array([
                self.next_state.get("context_coverage", 0.5),
                self.next_state.get("self_consistency", 0.5),
                self.next_state.get("logit_based", 0.5),
                self.next_state.get("question_clarity", 0.5),
                self.next_state.get("dissonance", 0.0),
                1.0 if "user_request" in self.reason_codes else 0.0,
                1.0 if "contrast" in self.reason_codes else 0.0,
                min((self.turn_count + 1) / 10.0, 1.0),
            ], dtype=np.float32)

        return (state_vec, self.action, self.reward, next_state_vec, self.done)


class ExperienceCollector:
    """
    経験データ収集クラス

    depth_selectorの決定をリアルタイムで収集し、
    Offline RL用のデータセットを構築します。
    """

    def __init__(self, buffer_size: int = 10000):
        self.buffer_size = buffer_size
        self.buffer: List[Experience] = []
        self._current_episode: List[Experience] = []

    def collect(
        self,
        confidence_metrics: Dict[str, float],
        dissonance: float,
        reason_codes: List[str],
        action: int,
        action_name: str,
        thread_id: str = "",
        turn_count: int = 1,
    ) -> Experience:
        """
        経験を収集（報酬は後で付与）

        Args:
            confidence_metrics: 確信度メトリクス
            dissonance: dissonanceスコア
            reason_codes: 理由コード
            action: 選択したアクション
            action_name: アクション名
            thread_id: スレッドID
            turn_count: 会話ターン数

        Returns:
            Experience: 収集した経験
        """
        state = {
            "context_coverage": confidence_metrics.get("context_coverage", 0.5),
            "self_consistency": confidence_metrics.get("self_consistency", 0.5),
            "logit_based": confidence_metrics.get("logit_based", 0.5),
            "question_clarity": confidence_metrics.get("question_clarity", 0.5),
        }

        exp = Experience(
            state=state,
            confidence_metrics=confidence_metrics,
            dissonance=dissonance,
            reason_codes=reason_codes,
            turn_count=turn_count,
            action=action,
            action_name=action_name,
            reward=0.0,  # 後で計算
            thread_id=thread_id,
        )

        self._current_episode.append(exp)
        logger.debug("[COLLECTOR] Collected experience: action=%s", action_name)

        return exp

    def assign_reward(
        self,
        reward: float,
        reward_components: Optional[Dict[str, float]] = None,
        user_satisfaction: Optional[float] = None,
    ):
        """
        直近の経験に報酬を付与

        Args:
            reward: 報酬値
            reward_components: 報酬の内訳
            user_satisfaction: ユーザー満足度（0.0-1.0）
        """
        if not self._current_episode:
            logger.warning("[COLLECTOR] No experience to assign reward")
            return

        exp = self._current_episode[-1]
        exp.reward = reward
        exp.reward_components = reward_components or {}
        exp.user_satisfaction = user_satisfaction

        logger.debug("[COLLECTOR] Assigned reward=%.3f", reward)

    def end_episode(self, final_reward: float = 0.0):
        """
        エピソード終了

        Args:
            final_reward: 最終報酬（全ステップに追加）
        """
        if not self._current_episode:
            return

        # 最後の経験をdone=Trueに
        self._current_episode[-1].done = True

        # 次の状態を設定
        for i in range(len(self._current_episode) - 1):
            self._current_episode[i].next_state = self._current_episode[i + 1].state

        # 最終報酬を追加
        if final_reward != 0.0:
            for exp in self._current_episode:
                exp.reward += final_reward / len(self._current_episode)

        # バッファに追加
        self.buffer.extend(self._current_episode)

        # バッファサイズを超えたら古いものを削除
        if len(self.buffer) > self.buffer_size:
            self.buffer = self.buffer[-self.buffer_size:]

        logger.info(
            "[COLLECTOR] Episode ended: %d experiences, buffer=%d",
            len(self._current_episode),
            len(self.buffer)
        )

        self._current_episode = []

    def save(self, filename: Optional[str] = None):
        """
        経験データを保存

        Args:
            filename: ファイル名（省略時は日時）
        """
        if not self.buffer:
            logger.warning("[COLLECTOR] No experiences to save")
            return

        if filename is None:
            filename = f"experiences_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"

        filepath = EXPERIENCE_DIR / filename

        with open(filepath, "w", encoding="utf-8") as f:
            for exp in self.buffer:
                f.write(json.dumps(exp.to_dict(), ensure_ascii=False) + "\n")

        logger.info("[COLLECTOR] Saved %d experiences to %s", len(self.buffer), filepath)

    def load(self, filename: str) -> int:
        """
        経験データを読み込み

        Args:
            filename: ファイル名

        Returns:
            int: 読み込んだ経験数
        """
        filepath = EXPERIENCE_DIR / filename

        if not filepath.exists():
            logger.warning("[COLLECTOR] File not found: %s", filepath)
            return 0

        loaded = []
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                data = json.loads(line.strip())
                loaded.append(Experience.from_dict(data))

        self.buffer.extend(loaded)
        logger.info("[COLLECTOR] Loaded %d experiences from %s", len(loaded), filepath)

        return len(loaded)

    def load_all(self) -> int:
        """
        全ての経験データを読み込み

        Returns:
            int: 読み込んだ総経験数
        """
        total = 0
        for filepath in EXPERIENCE_DIR.glob("*.jsonl"):
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    data = json.loads(line.strip())
                    self.buffer.append(Experience.from_dict(data))
                    total += 1

        logger.info("[COLLECTOR] Loaded %d total experiences", total)
        return total

    def get_batch(self, batch_size: int = 32) -> List[Experience]:
        """
        ランダムバッチを取得

        Args:
            batch_size: バッチサイズ

        Returns:
            List[Experience]: 経験のリスト
        """
        if len(self.buffer) < batch_size:
            return self.buffer.copy()

        indices = np.random.choice(len(self.buffer), batch_size, replace=False)
        return [self.buffer[i] for i in indices]

    def get_numpy_batch(self, batch_size: int = 32) -> tuple:
        """
        NumPy形式のバッチを取得

        Returns:
            tuple: (states, actions, rewards, next_states, dones)
        """
        batch = self.get_batch(batch_size)

        states = []
        actions = []
        rewards = []
        next_states = []
        dones = []

        for exp in batch:
            s, a, r, ns, d = exp.to_numpy()
            states.append(s)
            actions.append(a)
            rewards.append(r)
            if ns is not None:
                next_states.append(ns)
            else:
                next_states.append(np.zeros(8, dtype=np.float32))
            dones.append(d)

        return (
            np.array(states),
            np.array(actions),
            np.array(rewards),
            np.array(next_states),
            np.array(dones),
        )

    def get_statistics(self) -> Dict[str, Any]:
        """
        統計情報を取得

        Returns:
            Dict: 統計情報
        """
        if not self.buffer:
            return {"count": 0}

        rewards = [exp.reward for exp in self.buffer]
        actions = [exp.action for exp in self.buffer]

        action_counts = {
            "depth0": actions.count(0),
            "depth1": actions.count(1),
            "ask": actions.count(2),
            "wait": actions.count(3),
        }

        return {
            "count": len(self.buffer),
            "reward_mean": float(np.mean(rewards)),
            "reward_std": float(np.std(rewards)),
            "reward_min": float(np.min(rewards)),
            "reward_max": float(np.max(rewards)),
            "action_distribution": action_counts,
        }


# グローバルインスタンス
experience_collector = ExperienceCollector()
