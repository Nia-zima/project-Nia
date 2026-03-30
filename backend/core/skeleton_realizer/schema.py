"""Skeleton Realizer — data models.

Design: skeleton_realizer_design.md §3, §6, §9
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── NiaCore output heads (input to Realizer) ─────────────────────────


class RespondMode(str, Enum):
    HOLD = "hold"
    ASK = "ask"
    ANSWER = "answer"
    REFLECT = "reflect"


class ToneBias(str, Enum):
    QUIET = "quiet"
    DIRECT = "direct"
    WARM = "warm"
    DISTANT = "distant"


class Structure(str, Enum):
    ONE_LINE = "one_line"
    CONTRASTIVE = "contrastive"
    SUMMARY_THEN_QUESTION = "summary_then_question"


class RelationPosture(str, Enum):
    APPROACH = "approach"
    STAY = "stay"
    KEEP_DISTANCE = "keep_distance"


class AttentionTarget(str, Enum):
    CLARIFY = "clarify"
    EXPLORE = "explore"
    CONFIRM = "confirm"
    DEFER = "defer"


# ── Realizer input ───────────────────────────────────────────────────


class RealizerInput(BaseModel):
    """NiaCore output heads → Realizer input.

    C.0 shadow: these are derived from SkeletonCore + NiaCore vNext
    since NiaCore multi-head is not yet live.
    """
    depth: int = Field(ge=0, le=2)
    respond_mode: RespondMode = RespondMode.HOLD
    tone_bias: ToneBias = ToneBias.QUIET
    structure: Structure = Structure.ONE_LINE
    relation_posture: RelationPosture = RelationPosture.STAY
    hesitation: float = Field(0.3, ge=0.0, le=1.0)
    attention_target: AttentionTarget = AttentionTarget.CLARIFY


# ── Realizer output ──────────────────────────────────────────────────


class SkeletonGuidance(BaseModel):
    """Realizer output — skeleton guidance for LLM (or shadow log)."""
    structured_header: str
    interpretation_lines: list[str]
    full_text: str
    line_count: int = 0


# ── Adherence ────────────────────────────────────────────────────────


class AdherenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class AdherenceLowCause(str, Enum):
    """§13: Adherence Low 還流分類."""
    REALIZER_RULE_ISSUE = "realizer_rule_issue"
    PROMPT_STACK_CONFLICT = "prompt_stack_conflict"
    LLM_NON_ADHERENCE = "llm_non_adherence"
    NONE = "none"


class AdherenceScores(BaseModel):
    mode_adherence: AdherenceLevel = AdherenceLevel.UNKNOWN
    target_adherence: AdherenceLevel = AdherenceLevel.UNKNOWN
    posture_adherence: AdherenceLevel = AdherenceLevel.UNKNOWN
    tone_adherence: AdherenceLevel = AdherenceLevel.UNKNOWN
    structure_adherence: AdherenceLevel = AdherenceLevel.UNKNOWN
    composite_score: Optional[float] = None


class AdherenceRecord(BaseModel):
    """Per-turn adherence record for shadow logging."""
    record_id: str
    turn_id: str
    thread_id: str

    # Input
    realizer_input: RealizerInput
    skeleton_guidance: SkeletonGuidance

    # Evaluation
    adherence_scores: AdherenceScores
    low_adherence_detected: bool = False
    low_adherence_heads: list[str] = Field(default_factory=list)

    # §13: 還流分類
    feedback_target: AdherenceLowCause = AdherenceLowCause.NONE
    feedback_confidence: AdherenceLevel = AdherenceLevel.UNKNOWN
    conflict_detail: Optional[str] = None

    created_at: str
