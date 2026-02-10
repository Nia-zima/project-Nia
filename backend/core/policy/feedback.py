"""
Human Feedback System - Phase 3

Human-in-the-Loop フィードバック機構
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum

from backend.core.config import settings

logger = logging.getLogger(__name__)

# フィードバック保存先
FEEDBACK_DIR = settings.LOG_DIR / "feedback"
FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)


class FeedbackType(Enum):
    """フィードバックの種類"""
    THUMBS_UP = "thumbs_up"      # 良い
    THUMBS_DOWN = "thumbs_down"  # 悪い
    RATING = "rating"            # 5段階評価
    CORRECTION = "correction"    # 修正提案
    SKIP = "skip"                # スキップ


@dataclass
class Feedback:
    """フィードバックデータ"""
    thread_id: str
    turn_id: int
    feedback_type: str
    value: Any  # 評価値または修正内容
    context: Dict[str, Any]  # 文脈情報
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Feedback":
        return cls(**data)

    def to_reward(self) -> float:
        """
        フィードバックを報酬に変換

        Returns:
            float: 報酬値
        """
        if self.feedback_type == FeedbackType.THUMBS_UP.value:
            return 1.0
        elif self.feedback_type == FeedbackType.THUMBS_DOWN.value:
            return -1.0
        elif self.feedback_type == FeedbackType.RATING.value:
            # 1-5を-1.0〜1.0に変換
            rating = float(self.value)
            return (rating - 3.0) / 2.0
        elif self.feedback_type == FeedbackType.CORRECTION.value:
            # 修正が必要 = 負の報酬
            return -0.5
        else:
            return 0.0


class HumanFeedback:
    """
    Human-in-the-Loop フィードバック管理クラス

    ユーザーからのフィードバックを収集し、
    方策学習の報酬として活用します。
    """

    def __init__(self):
        self.pending_feedback: Dict[str, Dict[int, Dict[str, Any]]] = {}
        self.collected_feedback: List[Feedback] = []

    def request_feedback(
        self,
        thread_id: str,
        turn_id: int,
        context: Dict[str, Any],
    ) -> str:
        """
        フィードバックをリクエスト

        Args:
            thread_id: スレッドID
            turn_id: ターンID
            context: 文脈情報

        Returns:
            str: フィードバックトークン
        """
        if thread_id not in self.pending_feedback:
            self.pending_feedback[thread_id] = {}

        token = f"{thread_id}:{turn_id}:{datetime.now().timestamp()}"

        self.pending_feedback[thread_id][turn_id] = {
            "token": token,
            "context": context,
            "requested_at": datetime.now().isoformat(),
        }

        logger.info(
            "[FEEDBACK] Requested feedback: thread=%s turn=%d",
            thread_id, turn_id
        )

        return token

    def submit_feedback(
        self,
        thread_id: str,
        turn_id: int,
        feedback_type: FeedbackType,
        value: Any,
    ) -> Optional[Feedback]:
        """
        フィードバックを提出

        Args:
            thread_id: スレッドID
            turn_id: ターンID
            feedback_type: フィードバックタイプ
            value: フィードバック値

        Returns:
            Feedback: 作成されたフィードバック
        """
        if thread_id not in self.pending_feedback:
            logger.warning("[FEEDBACK] No pending feedback for thread: %s", thread_id)
            return None

        if turn_id not in self.pending_feedback[thread_id]:
            logger.warning("[FEEDBACK] No pending feedback for turn: %d", turn_id)
            return None

        pending = self.pending_feedback[thread_id].pop(turn_id)

        feedback = Feedback(
            thread_id=thread_id,
            turn_id=turn_id,
            feedback_type=feedback_type.value,
            value=value,
            context=pending["context"],
        )

        self.collected_feedback.append(feedback)

        logger.info(
            "[FEEDBACK] Collected feedback: thread=%s turn=%d type=%s value=%s",
            thread_id, turn_id, feedback_type.value, value
        )

        return feedback

    def submit_thumbs_up(self, thread_id: str, turn_id: int) -> Optional[Feedback]:
        """サムズアップ"""
        return self.submit_feedback(
            thread_id, turn_id, FeedbackType.THUMBS_UP, True
        )

    def submit_thumbs_down(self, thread_id: str, turn_id: int) -> Optional[Feedback]:
        """サムズダウン"""
        return self.submit_feedback(
            thread_id, turn_id, FeedbackType.THUMBS_DOWN, False
        )

    def submit_rating(
        self,
        thread_id: str,
        turn_id: int,
        rating: int,
    ) -> Optional[Feedback]:
        """
        5段階評価

        Args:
            rating: 1-5の評価
        """
        if not 1 <= rating <= 5:
            logger.warning("[FEEDBACK] Invalid rating: %d", rating)
            return None

        return self.submit_feedback(
            thread_id, turn_id, FeedbackType.RATING, rating
        )

    def submit_correction(
        self,
        thread_id: str,
        turn_id: int,
        correct_action: str,
        reason: Optional[str] = None,
    ) -> Optional[Feedback]:
        """
        修正提案

        Args:
            correct_action: 正しいアクション ("depth0", "depth1", "ask", "wait")
            reason: 理由（オプション）
        """
        return self.submit_feedback(
            thread_id,
            turn_id,
            FeedbackType.CORRECTION,
            {"correct_action": correct_action, "reason": reason},
        )

    def get_pending_count(self, thread_id: Optional[str] = None) -> int:
        """
        保留中のフィードバック数を取得

        Args:
            thread_id: スレッドID（省略時は全体）
        """
        if thread_id:
            return len(self.pending_feedback.get(thread_id, {}))
        return sum(len(turns) for turns in self.pending_feedback.values())

    def get_collected_feedback(
        self,
        thread_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Feedback]:
        """
        収集済みフィードバックを取得

        Args:
            thread_id: スレッドID（省略時は全体）
            limit: 最大数
        """
        if thread_id:
            filtered = [f for f in self.collected_feedback if f.thread_id == thread_id]
        else:
            filtered = self.collected_feedback

        return filtered[-limit:]

    def get_satisfaction_score(
        self,
        thread_id: Optional[str] = None,
    ) -> Optional[float]:
        """
        満足度スコアを計算

        Returns:
            float: 0.0-1.0のスコア（Noneはデータなし）
        """
        feedback_list = self.get_collected_feedback(thread_id)
        if not feedback_list:
            return None

        total_reward = sum(f.to_reward() for f in feedback_list)
        # -1〜1を0〜1に正規化
        score = (total_reward / len(feedback_list) + 1.0) / 2.0
        return max(0.0, min(1.0, score))

    def save(self, filename: Optional[str] = None):
        """
        フィードバックを保存

        Args:
            filename: ファイル名
        """
        if not self.collected_feedback:
            logger.warning("[FEEDBACK] No feedback to save")
            return

        if filename is None:
            filename = f"feedback_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"

        filepath = FEEDBACK_DIR / filename

        with open(filepath, "w", encoding="utf-8") as f:
            for fb in self.collected_feedback:
                f.write(json.dumps(fb.to_dict(), ensure_ascii=False) + "\n")

        logger.info("[FEEDBACK] Saved %d feedback to %s", len(self.collected_feedback), filepath)

    def load(self, filename: str) -> int:
        """
        フィードバックを読み込み

        Args:
            filename: ファイル名

        Returns:
            int: 読み込んだ数
        """
        filepath = FEEDBACK_DIR / filename

        if not filepath.exists():
            logger.warning("[FEEDBACK] File not found: %s", filepath)
            return 0

        loaded = 0
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                data = json.loads(line.strip())
                self.collected_feedback.append(Feedback.from_dict(data))
                loaded += 1

        logger.info("[FEEDBACK] Loaded %d feedback from %s", loaded, filepath)
        return loaded

    def get_statistics(self) -> Dict[str, Any]:
        """
        統計情報を取得

        Returns:
            Dict: 統計情報
        """
        if not self.collected_feedback:
            return {"count": 0}

        type_counts = {}
        for fb in self.collected_feedback:
            type_counts[fb.feedback_type] = type_counts.get(fb.feedback_type, 0) + 1

        rewards = [fb.to_reward() for fb in self.collected_feedback]

        return {
            "count": len(self.collected_feedback),
            "type_distribution": type_counts,
            "mean_reward": sum(rewards) / len(rewards),
            "satisfaction_score": self.get_satisfaction_score(),
            "pending_count": self.get_pending_count(),
        }


# グローバルインスタンス
human_feedback = HumanFeedback()
