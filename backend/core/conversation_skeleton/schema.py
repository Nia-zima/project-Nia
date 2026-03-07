"""SkeletonCore enum / dataclass 定義.

会話骨格の3要素: focus（何を見ているか）, response_intent（どう返すか）,
question_intent（何を聞くか）.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Focus(str, Enum):
    """何を見ているか."""

    USER_GOAL = "user_goal"
    MISSING_CONTEXT = "missing_context"
    CONTRADICTION = "contradiction"
    PRIORITY_DECISION = "priority_decision"
    EMOTIONAL_STATE = "emotional_state"


class ResponseIntent(str, Enum):
    """どう返すか."""

    RECEIVE = "receive"
    ORGANIZE = "organize"
    ASK = "ask"
    HOLD = "hold"


class QuestionIntent(str, Enum):
    """何を聞くか（response_intent == ASK の時のみ）."""

    CLARIFY_GOAL = "clarify_goal"
    CLARIFY_PRIORITY = "clarify_priority"
    CLARIFY_EMOTION = "clarify_emotion"
    FILL_MISSING_FACT = "fill_missing_fact"
    RESOLVE_CONTRADICTION = "resolve_contradiction"


@dataclass
class ConversationSkeleton:
    """1ターンの会話骨格."""

    focus: Focus
    response_intent: ResponseIntent
    question_intent: Optional[QuestionIntent] = None
    source: str = "nia_internal"  # "nia_internal" | "nero_external"
    confidence: float = 0.5
    rule_trace: list[str] = field(default_factory=list)
