# backend/core/actions/types.py

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


class RiskLevel(Enum):
    """リスクレベル"""
    SAFE = 0.0          # 完全に安全（読み取り専用）
    LOW = 0.3           # 低リスク（表示更新など）
    MEDIUM = 0.6        # 中リスク（データ変更）
    HIGH = 0.8          # 高リスク（外部通信）
    CRITICAL = 1.0      # 重大リスク（削除、課金など）


class ActionCategory(Enum):
    """アクションカテゴリ"""
    MEMORY = "memory"           # メモリ操作
    DISPLAY = "display"         # 表示更新
    COMMUNICATION = "comm"      # 外部通信
    FILE_SYSTEM = "file"        # ファイル操作
    WEB_SEARCH = "search"       # Web検索
    TOOL_CALL = "tool"          # ツール呼び出し
    SYSTEM = "system"           # システム操作


@dataclass
class Action:
    """アクション定義"""
    id: str                     # アクションID
    name: str                   # 表示名
    category: ActionCategory    # カテゴリ
    risk_level: RiskLevel      # リスクレベル
    description: str            # 説明
    payload: Dict[str, Any]     # ペイロード
    requires_confirmation: bool = False  # 確認必須か

    @property
    def risk_score(self) -> float:
        """リスクスコア（0.0-1.0）"""
        return self.risk_level.value


@dataclass
class ActionDecision:
    """アクション実行判定結果"""
    should_execute: bool         # 実行すべきか
    reason: str                  # 理由
    requires_confirmation: bool = False  # ユーザー確認が必要か
    suggested_depth: Optional[int] = None  # 推奨Depth
