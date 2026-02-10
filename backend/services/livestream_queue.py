# backend/services/livestream_queue.py
"""
配信コメントキューサービス

Body Constitution B.4「観測の主導権」の実装:
- 処理レート制限（4件/分、15秒間隔）
- 候補ウィンドウ（直近5件）
- スキップ権（全コメントが不適切なら沈黙）
"""

from __future__ import annotations

import time
import uuid
import asyncio
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum
from collections import deque

from backend.core.logger import logger


class UserRole(Enum):
    """ユーザーロール"""
    ORIGIN = "origin"   # オリジン（配信者）: 割り込み可、retention +0.2
    VIEWER = "viewer"   # 一般視聴者


@dataclass
class Comment:
    """コメントデータ"""
    id: str
    text: str
    user_id: str
    user_name: str
    role: UserRole
    timestamp: float
    steering_risk: float = 0.0
    info_sufficiency: float = 0.5
    addressed_to_nia: bool = False
    
    def is_expired(self, max_age_seconds: float = 60.0) -> bool:
        """コメントが期限切れかどうか"""
        return (time.time() - self.timestamp) > max_age_seconds


@dataclass
class QueueResult:
    """キュー操作の結果"""
    ok: bool
    queued: bool = False
    queue_position: int = 0
    estimated_wait_seconds: float = 0.0
    reason: str = ""


@dataclass
class QueueStats:
    """キューの統計情報"""
    pending: int = 0
    processed_last_minute: int = 0
    rejected_last_minute: int = 0


class LivestreamQueue:
    """
    配信コメントキュー
    
    Body Constitution B.4「観測の主導権」:
    - 外部の情報量や速度よりも、自分が理解できる範囲を優先する
    - ニアがコメントを選ぶ。全部に反応しない
    """
    
    # 設定パラメータ
    MAX_COMMENTS_PER_MINUTE = 4       # 処理レート（4件/分）
    MIN_INTERVAL_SECONDS = 15.0       # 最小間隔（15秒）
    CANDIDATE_WINDOW = 5              # 候補ウィンドウ（直近5件）
    QUEUE_MAX_AGE_SECONDS = 60.0      # キュー最大age（60秒）
    MAX_QUEUE_SIZE = 100              # キュー最大サイズ
    
    # フィルタリング閾値
    STEERING_RISK_THRESHOLD = 0.7     # steering_risk > 0.7 → 除外
    MIN_TEXT_LENGTH = 5               # 文字数 < 5 → 除外
    MAX_TEXT_LENGTH = 200             # 文字数 > 200 → 除外
    
    # スキップ権の閾値
    SKIP_ALL_STEERING_THRESHOLD = 0.6    # 全コメントの steering > 0.6 → スキップ
    SKIP_ALL_INFO_THRESHOLD = 0.3        # 全コメントの info < 0.3 → スキップ
    
    def __init__(self):
        self._queue: deque[Comment] = deque(maxlen=self.MAX_QUEUE_SIZE)
        self._processed_timestamps: deque[float] = deque(maxlen=60)  # 直近1分の処理履歴
        self._rejected_timestamps: deque[float] = deque(maxlen=60)   # 直近1分の除外履歴
        self._last_process_time: float = 0.0
        self._lock = asyncio.Lock()
    
    async def enqueue(self, comment: Comment) -> QueueResult:
        """コメントをキューに追加"""
        async with self._lock:
            # フィルタリング
            reject_reason = self._should_reject(comment)
            if reject_reason:
                self._rejected_timestamps.append(time.time())
                logger.info(f"[LIVESTREAM] Comment rejected: {reject_reason}")
                return QueueResult(ok=True, queued=False, reason=reject_reason)
            
            # キューに追加
            self._queue.append(comment)
            position = len(self._queue)
            wait_seconds = position * self.MIN_INTERVAL_SECONDS
            
            logger.info(f"[LIVESTREAM] Comment queued: position={position}")
            return QueueResult(
                ok=True,
                queued=True,
                queue_position=position,
                estimated_wait_seconds=wait_seconds,
            )
    
    async def get_next(self) -> Optional[Comment]:
        """次のコメントを取得"""
        async with self._lock:
            # レート制限チェック
            now = time.time()
            if (now - self._last_process_time) < self.MIN_INTERVAL_SECONDS:
                return None
            
            # 期限切れコメントを削除
            self._cleanup_expired()
            
            if not self._queue:
                return None
            
            # スキップ権チェック
            if self._should_skip_all():
                logger.info("[LIVESTREAM] Skip all: no suitable comments")
                return None
            
            # 候補を選択
            candidates = list(self._queue)[:self.CANDIDATE_WINDOW]
            selected = self._select_best(candidates)
            
            if selected:
                self._queue.remove(selected)
                self._processed_timestamps.append(now)
                self._last_process_time = now
                logger.info(f"[LIVESTREAM] Comment selected: {selected.user_name}")
            
            return selected
    
    def _should_reject(self, comment: Comment) -> Optional[str]:
        """コメントを除外すべきか判定"""
        # オリジンは除外しない
        if comment.role == UserRole.ORIGIN:
            return None
        
        # 文字数チェック
        text_len = len(comment.text)
        if text_len < self.MIN_TEXT_LENGTH:
            return f"text_too_short ({text_len} < {self.MIN_TEXT_LENGTH})"
        if text_len > self.MAX_TEXT_LENGTH:
            return f"text_too_long ({text_len} > {self.MAX_TEXT_LENGTH})"
        
        # steering_riskチェック
        if comment.steering_risk > self.STEERING_RISK_THRESHOLD:
            return f"steering_risk_high ({comment.steering_risk:.2f})"
        
        return None
    
    def _should_skip_all(self) -> bool:
        """全コメントをスキップすべきか（沈黙の権利）"""
        if not self._queue:
            return True
        
        candidates = list(self._queue)[:self.CANDIDATE_WINDOW]
        
        # オリジンのコメントがあればスキップしない
        if any(c.role == UserRole.ORIGIN for c in candidates):
            return False
        
        # 全コメントの steering_risk が高い → スキップ
        if all(c.steering_risk > self.SKIP_ALL_STEERING_THRESHOLD for c in candidates):
            return True
        
        # 全コメントの info_sufficiency が低い → スキップ
        if all(c.info_sufficiency < self.SKIP_ALL_INFO_THRESHOLD for c in candidates):
            return True
        
        return False
    
    def _select_best(self, candidates: List[Comment]) -> Optional[Comment]:
        """最適なコメントを選択"""
        if not candidates:
            return None
        
        # オリジンのコメントは最優先
        origin_comments = [c for c in candidates if c.role == UserRole.ORIGIN]
        if origin_comments:
            return origin_comments[0]
        
        # ニア宛てのコメントを優先
        addressed = [c for c in candidates if c.addressed_to_nia]
        if addressed:
            candidates = addressed
        
        # info_sufficiencyが高いものを優先
        return max(candidates, key=lambda c: c.info_sufficiency)
    
    def _cleanup_expired(self):
        """期限切れコメントを削除"""
        now = time.time()
        while self._queue and self._queue[0].is_expired(self.QUEUE_MAX_AGE_SECONDS):
            expired = self._queue.popleft()
            logger.debug(f"[LIVESTREAM] Comment expired: {expired.id}")
    
    def get_stats(self) -> QueueStats:
        """統計情報を取得"""
        now = time.time()
        one_minute_ago = now - 60.0
        
        processed = sum(1 for t in self._processed_timestamps if t > one_minute_ago)
        rejected = sum(1 for t in self._rejected_timestamps if t > one_minute_ago)
        
        return QueueStats(
            pending=len(self._queue),
            processed_last_minute=processed,
            rejected_last_minute=rejected,
        )
    
    async def clear(self):
        """キューをクリア（配信終了時）"""
        async with self._lock:
            self._queue.clear()
            self._processed_timestamps.clear()
            self._rejected_timestamps.clear()
            self._last_process_time = 0.0
            logger.info("[LIVESTREAM] Queue cleared")


# シングルトンインスタンス
_queue: Optional[LivestreamQueue] = None


def get_livestream_queue() -> LivestreamQueue:
    """キューのシングルトンインスタンスを取得"""
    global _queue
    if _queue is None:
        _queue = LivestreamQueue()
    return _queue
