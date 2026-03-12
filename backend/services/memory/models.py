from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class MemoryEvent:
    event_id: str
    thread_id: str
    event_type: str
    payload_json: str
    created_at: float
    schema_version: int = 1
    turn_id: Optional[str] = None
    message_id: Optional[str] = None


@dataclass
class MemoryIndexEntry:
    index_id: str
    event_id: str
    thread_id: str
    scope: str
    created_at: float
    updated_at: float
    state_tag: Optional[str] = None
    tags_json: Optional[str] = None
    keywords_json: Optional[str] = None
    related_turn_id: Optional[str] = None


@dataclass
class SemanticMemory:
    id: str
    thread_id: str
    content: str
    valid_from: float
    created_at: float
    updated_at: float
    status: str = "inferred"
    confidence: float = 0.5
    state_tag: Optional[str] = None
    supersedes_id: Optional[str] = None
    revoked_by_id: Optional[str] = None
    revoke_reason: Optional[str] = None
    valid_to: Optional[float] = None
    staleness_days: Optional[float] = None
    source_turn_ids: str = "[]"
    source_event_ids: str = "[]"
    note: Optional[str] = None
    seed_retention: float = 0.5
    vector_sync_pending: int = 1
    embedding: Optional[bytes] = None
    defeaters: str = "[]"


@dataclass
class WorkingItem:
    id: str
    thread_id: str
    item_type: str
    content: str
    created_turn_id: str
    created_at: float
    updated_at: float
    priority: int = 3
    status: str = "open"
    close_reason: Optional[str] = None
    linked_semantic_ids: str = "[]"
    linked_event_ids: str = "[]"
    merged_into_id: Optional[str] = None
    ttl_turns: Optional[int] = None
    expires_at: Optional[float] = None
    stale_turn_count: int = 0


# ── Memory Governance Models ────────────────────────────


@dataclass
class SemanticState:
    semantic_id: str
    created_at: float
    updated_at: float
    owner_agent: str = "nia"
    memory_domain: str = "default"
    memory_strength: float = 0.5
    confidence: float = 0.5
    seed_retention: float = 0.5
    last_reinforced_at: Optional[float] = None
    retrieval_count: int = 0
    contradiction_score: float = 0.0
    deprecation_score: float = 0.0
    merge_score: float = 0.0
    state: str = "active"
    promotion_path: str = "legacy"
    decay_path: str = "legacy_expiry"


@dataclass
class RawPromotionCandidate:
    candidate_id: str
    candidate_kind_rough: str
    source_type: str
    created_at: float
    updated_at: float
    source_ref: Optional[str] = None
    topic_key: Optional[str] = None
    focus: Optional[str] = None
    response_intent: Optional[str] = None
    question_intent: Optional[str] = None
    unresolved_ref: Optional[str] = None
    owner_agent: str = "nia"
    memory_domain: str = "default"
    status: str = "pending"
    thread_id: Optional[str] = None
    turn_id: Optional[str] = None
    message_id: Optional[str] = None
    stream_id: Optional[str] = None
    trace_id: Optional[str] = None


@dataclass
class MemoryClaim:
    claim_id: str
    claim_type: str
    subject: str
    predicate: str
    created_at: float
    updated_at: float
    object_json: Optional[str] = None
    scope: str = "long_term"
    status: str = "candidate"
    owner_agent: str = "nia"
    memory_domain: str = "default"
    semantic_ref: Optional[str] = None
    thread_id: Optional[str] = None
    turn_id: Optional[str] = None
    message_id: Optional[str] = None
    stream_id: Optional[str] = None
    trace_id: Optional[str] = None


@dataclass
class MemoryEvidence:
    evidence_id: str
    source_type: str
    created_at: float
    candidate_id: Optional[str] = None
    claim_id: Optional[str] = None
    source_ref: Optional[str] = None
    evidence_date: Optional[str] = None
    reliability: float = 0.5
    thread_id: Optional[str] = None
    turn_id: Optional[str] = None
    message_id: Optional[str] = None
    stream_id: Optional[str] = None
    trace_id: Optional[str] = None


@dataclass
class PromotionReview:
    review_id: str
    claim_id: str
    reviewer_type: str
    decision: str
    created_at: float
    reason: Optional[str] = None
    owner_agent: str = "nia"
    thread_id: Optional[str] = None
    turn_id: Optional[str] = None
    message_id: Optional[str] = None
    stream_id: Optional[str] = None
    trace_id: Optional[str] = None


@dataclass
class SemanticLineage:
    lineage_id: str
    claim_id: str
    semantic_id: str
    promoted_at: float
    evidence_snapshot_json: Optional[str] = None
    owner_agent: str = "nia"
    thread_id: Optional[str] = None
    turn_id: Optional[str] = None
    message_id: Optional[str] = None
    stream_id: Optional[str] = None
    trace_id: Optional[str] = None


@dataclass
class SemanticReview:
    review_id: str
    semantic_id: str
    reviewer_type: str
    decision: str
    created_at: float
    reason: Optional[str] = None
    evidence_snapshot_json: Optional[str] = None
    thread_id: Optional[str] = None
    turn_id: Optional[str] = None
    message_id: Optional[str] = None
    stream_id: Optional[str] = None
    trace_id: Optional[str] = None


@dataclass
class SemanticTombstone:
    tombstone_id: str
    semantic_id: str
    retirement_reason: str
    archived_at: float
    claim_ref: Optional[str] = None
    owner_agent: str = "nia"
    memory_domain: str = "default"
    replaced_by: Optional[str] = None
    notes: Optional[str] = None


@dataclass
class SemanticTransition:
    transition_id: str
    semantic_id: str
    from_state: str
    to_state: str
    trigger_type: str
    created_at: float
    trigger_ref: Optional[str] = None
