"""Pydantic models for Metabolic Hardening knot system.

Design:
    - MetabolicKnot: core knot entity with trigger/effect/hardening
    - KnotActivation: per-turn activation record
    - KnotBaseline: regime-specific baseline snapshot
    - PerturbationEpisode: self_boundary_knot episode
    - KnotRelation: sibling/support/opposition between knots
    - KnotSignalSnapshot: Sleep-cycle signal history
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── Enums ─────────────────────────────────────────────────────────────


class KnotType(str, Enum):
    RESPONSE = "response"
    RELATIONAL = "relational"
    SELF_BOUNDARY = "self_boundary"


class KnotStatus(str, Enum):
    ACTIVE = "active"
    MERGED = "merged"
    ARCHIVED = "archived"


class RelationType(str, Enum):
    SIBLING = "sibling"
    SUPPORTS = "supports"
    COMPETES_WITH = "competes_with"
    OPPOSES = "opposes"


class PerturbationTrigger(str, Enum):
    CONTRADICTION = "contradiction"
    IDENTITY_CHALLENGE = "identity_challenge"
    REPEATED_REPAIR = "repeated_repair"


# ── Core Models ───────────────────────────────────────────────────────


class MetabolicKnot(BaseModel):
    """A stable deformation operator: when trigger T appears, behavior shifts toward effect E."""

    knot_id: str
    knot_type: KnotType
    status: KnotStatus = KnotStatus.ACTIVE

    # Trigger/Effect as dicts (JSON in DB)
    trigger_signature: dict[str, str | float | bool | list[str]]
    effect_signature: dict[str, float]

    # Activation statistics
    activation_count: int = 0
    distinct_day_count: int = 0
    distinct_thread_count: int = 0
    distinct_regime_count: int = 0
    day_span: int = 0

    # Recovery (self_boundary only)
    recovery_speed_avg: Optional[float] = None
    rebound_stability_avg: Optional[float] = None
    episode_confidence_avg: Optional[float] = None  # average episode confidence

    # Hardening
    hardness_level: int = 0  # 0-3
    protection_score: float = 0.0

    # Signals
    reproducibility: float = 0.0
    damage_sensitivity: float = 0.0
    redundancy: float = 0.0
    temporal_stability: float = 0.0

    # Baseline anchoring
    current_baseline_version: str

    # Coupling
    coupled_knots: list[str] = Field(default_factory=list)
    coupling_type: list[str] = Field(default_factory=list)

    # Rewrite control
    rewrite_threshold: float = 0.30
    contradiction_hold_threshold: float = 0.55
    softening_rate: float = 0.02

    # Lineage
    source_knot_ids: list[str] = Field(default_factory=list)
    supersedes: Optional[str] = None
    merged_into: Optional[str] = None

    # Timestamps
    first_seen_at: str
    last_activated_at: str
    last_contradicted_at: Optional[str] = None
    created_at: str
    updated_at: str


class KnotActivation(BaseModel):
    """Per-turn activation record for a knot."""

    activation_id: str
    knot_id: str
    turn_id: str
    thread_id: str
    interaction_regime: str
    baseline_version: str
    trigger_values: dict[str, str | float | bool | list[str]]
    effect_values: dict[str, float]
    activated_at: str


class KnotBaseline(BaseModel):
    """Regime-specific baseline snapshot (append-only)."""

    baseline_version: str
    regime: str
    effect_key: str
    value: float
    sample_count: int = 0
    created_at: str


class PerturbationEpisode(BaseModel):
    """self_boundary_knot episode: perturbation → destabilization → recovery."""

    episode_id: str
    trigger_type: PerturbationTrigger
    trigger_turn_id: str
    thread_id: str
    destabilization_turns: int = 0
    recovery_turns: int = 0
    recovered: bool = False
    episode_confidence: float = 0.0
    pre_baseline: dict[str, float]
    post_baseline: dict[str, float]
    max_deviation: float = 0.0
    started_at: str
    ended_at: Optional[str] = None


class KnotRelation(BaseModel):
    """Relation between knots: sibling, supports, competes_with, opposes."""

    source_knot_id: str
    target_knot_id: str
    relation_type: RelationType
    strength: float = 0.0
    created_at: str
    updated_at: str


class ContradictionKind(str, Enum):
    REVERSAL = "reversal"
    WEAKENING = "weakening"
    BRANCHING = "branching"


class HoldStatus(str, Enum):
    PENDING = "pending"
    ABSORBED = "absorbed"
    REJECTED = "rejected"
    SPLIT = "split"


class ContradictionHold(BaseModel):
    """Rewrite-delay mechanism for knot contradictions.

    Not a box to stop contradictions — a system to separate
    short-term noise from long-term structural change.
    """

    hold_id: str
    knot_id: str

    # Contradiction details
    contradiction_kind: ContradictionKind
    contradiction_score: float = 0.0
    contradicting_turn_ids: list[str] = Field(default_factory=list)
    evidence_count: int = 0

    # Knot snapshot (frozen at hold creation)
    hardness_level_at_hold: int
    trigger_signature_snapshot: dict
    effect_signature_snapshot: dict[str, float]
    baseline_version_at_hold: str
    protection_score_at_hold: float

    # Hold type
    hold_type: str = "soft"  # soft / hard
    hold_duration_sleeps: int = 0
    min_review_sleeps: int = 1

    # Resolution
    status: HoldStatus = HoldStatus.PENDING
    resolution_reason: Optional[str] = None
    resolved_at: Optional[str] = None

    # Adaptation link
    adaptation_proposal_id: Optional[str] = None
    requires_review: bool = False

    # Timestamps
    created_at: str
    updated_at: str


class KnotSignalSnapshot(BaseModel):
    """Sleep-cycle signal history entry."""

    knot_id: str
    sleep_date: str
    reproducibility: float
    damage_sensitivity: float
    redundancy: float
    temporal_stability: float
    protection_score: float
    hardness_level: int
