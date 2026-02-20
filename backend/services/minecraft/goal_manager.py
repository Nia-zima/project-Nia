"""Goal management for Nia's autonomous Minecraft gameplay."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Goal:
    description: str
    priority: int = 1  # 1=highest
    source: str = "self"  # "self" or "user"
    created_at: float = field(default_factory=time.time)
    completed: bool = False


class GoalManager:
    """Manages Nia's short-term and mid-term goals."""

    def __init__(self):
        self._goals: list[Goal] = []

    def add_goal(self, description: str, priority: int = 1, source: str = "self") -> Goal:
        """Add a new goal."""
        goal = Goal(description=description, priority=priority, source=source)
        self._goals.append(goal)
        self._goals.sort(key=lambda g: (g.completed, g.priority))
        logger.info("[GoalManager] Added: %s (priority=%d, source=%s)", description, priority, source)
        return goal

    def complete_goal(self, description: str) -> bool:
        """Mark a goal as completed by description match."""
        for goal in self._goals:
            if not goal.completed and description.lower() in goal.description.lower():
                goal.completed = True
                logger.info("[GoalManager] Completed: %s", goal.description)
                return True
        return False

    def get_active_goals(self) -> list[Goal]:
        """Get uncompleted goals sorted by priority."""
        return [g for g in self._goals if not g.completed]

    def format_for_prompt(self) -> str:
        """Format goals for LLM prompt injection."""
        active = self.get_active_goals()
        if not active:
            return ""
        lines = []
        for g in active:
            src = " (ユーザーから)" if g.source == "user" else ""
            lines.append(f"- {g.description}{src}")
        return "\n".join(lines)

    def clear_completed(self) -> int:
        """Remove completed goals. Returns count removed."""
        before = len(self._goals)
        self._goals = [g for g in self._goals if not g.completed]
        removed = before - len(self._goals)
        if removed:
            logger.info("[GoalManager] Cleared %d completed goals", removed)
        return removed
