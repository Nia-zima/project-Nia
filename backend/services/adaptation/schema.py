"""Pydantic models for conversation adaptation proposals and evidence.

Design doc: docs/failure_success_policy_design.md §5-6
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


# ── Enums / Literals ────────────────────────────────────────────────

ProposalKind = Literal["failure_policy", "success_preference"]

ProposalStatus = Literal[
    "proposed",
    "shadow_pass",
    "shadow_fail",
    "graduated",
    "rejected",
    "expired",
]

ProposalScope = Literal[
    "history_only",
    "shadow_only",
    "teacher_only",
    "temp_hotfix",
]

TriggerType = Literal[
    "repetition",
    "correction",
    "contract",
    "directness",
    "drift",
    "positive_trace",
    "reassurance_loop",
    "opener_fixation",
    "user_feedback",
]

TargetLayer = Literal[
    "history_selection",
    "intent_teacher",
    "attention_teacher",
    "expression_bias",
    "continuity_bias",
]

TeacherHead = Literal["intent", "attention", "expression", "continuity"]

TeacherDirection = Literal["toward", "away_from", "preserve", "diversify"]

TeacherLabel = Literal[
    # intent
    "same_family_reentry",
    "self_initiated_opening",
    "repair_alignment_directly",
    "reconnect_prior_theme",
    # attention
    "user_repair_signal",
    "shared_theme",
    "user_and_shared_memory",
    # expression
    "same_opener_family",
    "fragile_open",
    "hedge_dense",
    "family_overconcentration",
    # continuity
    "continuity_with_variation",
    "thread_resonance",
    "novelty_too_low",
]

EvidenceKind = Literal[
    "semantic_family_repeat",
    "contract_violation",
    "correction_strong",
    "correction_weak",
    "direct_stance_short",
    "self_third_person_drift",
    "user_repeat_complaint",
    "user_misalignment_feedback",
    "reassurance_loop",
    "same_opener_family",
    "agency_trace",
    "relational_trace",
    "expressive_diversity_trace",
    "continuity_trace",
]

EvidenceSource = Literal[
    "expression",
    "skeleton",
    "somatic_feedback",
    "fingerprint",
    "user_feedback",
    "guardrail",
    "retrieval",
]


# ── Sub-models ──────────────────────────────────────────────────────

class TeacherAtom(BaseModel):
    """Structured trace for future pseudo-teacher / vNext absorption."""

    head: TeacherHead
    channel: str
    direction: TeacherDirection
    label: TeacherLabel
    weight: float = Field(ge=0.0, le=1.0)


class HistoryBias(BaseModel):
    """Adjustment knobs for _recent_history() scorer."""

    downrank_families: list[str] = Field(default_factory=list)
    uprank_families: list[str] = Field(default_factory=list)
    cap_same_family: int | None = Field(default=None, ge=0)
    prefer_trace_match: list[str] = Field(default_factory=list)
    avoid_trace_match: list[str] = Field(default_factory=list)


class RuntimeHint(BaseModel):
    """Emergency-only hint (temp_hotfix scope)."""

    suffix_block_allowed: bool = True
    hint_text: str


class EffectPayload(BaseModel):
    """What a proposal does: 3-layer separation of concerns."""

    history_bias: HistoryBias = Field(default_factory=HistoryBias)
    teacher_atoms: list[TeacherAtom] = Field(default_factory=list)
    runtime_hint: RuntimeHint | None = None


class TracePayload(BaseModel):
    """Observed pattern trace — same structure for failure and success."""

    axes: dict[str, float] = Field(default_factory=dict)
    observed_patterns: list[str] = Field(default_factory=list)
    source_summary: dict[str, list[str]] = Field(default_factory=dict)


# ── Main models ─────────────────────────────────────────────────────

class ConversationAdaptationProposal(BaseModel):
    """A compressed hypothesis derived from failure/success patterns."""

    proposal_id: str
    proposal_key: str | None = None
    proposal_kind: ProposalKind
    status: ProposalStatus = "proposed"
    scope: ProposalScope = "history_only"
    priority: int = Field(default=0, ge=0, le=2)

    thread_mode: str | None = None
    conversation_role: str | None = None
    trigger_type: TriggerType
    target_layer: TargetLayer

    condition_json: dict[str, Any]
    trace_json: TracePayload
    effect_json: EffectPayload
    validation_json: dict[str, Any] | None = None
    lineage_json: dict[str, Any] | None = None

    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    support_count: int = Field(default=0, ge=0)
    contradiction_count: int = Field(default=0, ge=0)

    first_seen_at: str
    last_seen_at: str
    expires_at: str | None = None
    created_at: str
    updated_at: str

    supersedes_proposal_id: str | None = None
    created_by: str

    @model_validator(mode="after")
    def _validate_temp_hotfix(self) -> ConversationAdaptationProposal:
        if self.scope == "temp_hotfix":
            if self.priority != 2:
                raise ValueError("temp_hotfix requires priority=2")
            if self.expires_at is None:
                raise ValueError("temp_hotfix requires expires_at")
            if self.effect_json.runtime_hint is None:
                raise ValueError("temp_hotfix requires runtime_hint")
        else:
            if self.effect_json.runtime_hint is not None:
                raise ValueError("runtime_hint is only allowed for temp_hotfix scope")
        return self

    @model_validator(mode="after")
    def _populate_proposal_key(self) -> ConversationAdaptationProposal:
        if not self.proposal_key:
            self.proposal_key = build_proposal_key(
                proposal_kind=self.proposal_kind,
                scope=self.scope,
                priority=self.priority,
                thread_mode=self.thread_mode,
                conversation_role=self.conversation_role,
                trigger_type=self.trigger_type,
                target_layer=self.target_layer,
                condition_json=self.condition_json,
                effect_json=self.effect_json.model_dump(mode="json"),
                created_by=self.created_by,
            )
        return self

    @model_validator(mode="after")
    def _validate_scope_target_compatibility(self) -> ConversationAdaptationProposal:
        if (
            self.target_layer == "history_selection"
            and self.scope not in {"history_only", "temp_hotfix"}
        ):
            raise ValueError(
                "history_selection target_layer requires history_only or temp_hotfix scope"
            )
        return self

    @model_validator(mode="after")
    def _validate_time_ordering(self) -> ConversationAdaptationProposal:
        first_seen_at = _parse_iso8601(self.first_seen_at)
        last_seen_at = _parse_iso8601(self.last_seen_at)
        created_at = _parse_iso8601(self.created_at)
        if last_seen_at < first_seen_at:
            raise ValueError("last_seen_at must be >= first_seen_at")
        if self.expires_at is not None and _parse_iso8601(self.expires_at) < created_at:
            raise ValueError("expires_at must be >= created_at")
        return self


class ConversationAdaptationEvidence(BaseModel):
    """A single piece of raw evidence linked to a proposal."""

    evidence_id: str
    proposal_id: str
    thread_id: str | None = None
    turn_id: str | None = None
    message_id: str | None = None

    evidence_kind: EvidenceKind
    evidence_source: EvidenceSource
    evidence_weight: float = Field(ge=0.0)
    payload_json: dict[str, Any]

    observed_at: str


def _parse_iso8601(value: str) -> datetime:
    """Parse repo-style timestamps (`Z` or explicit UTC offset)."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def build_proposal_key(
    *,
    proposal_kind: ProposalKind,
    scope: ProposalScope,
    priority: int,
    thread_mode: str | None,
    conversation_role: str | None,
    trigger_type: TriggerType,
    target_layer: TargetLayer,
    condition_json: dict[str, Any],
    effect_json: dict[str, Any],
    created_by: str,
) -> str:
    """Build a stable key for deduping logically identical proposals."""
    payload = {
        "proposal_kind": proposal_kind,
        "scope": scope,
        "priority": priority,
        "thread_mode": thread_mode,
        "conversation_role": conversation_role,
        "trigger_type": trigger_type,
        "target_layer": target_layer,
        "condition_json": condition_json,
        "effect_json": effect_json,
        "created_by": created_by,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
