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
