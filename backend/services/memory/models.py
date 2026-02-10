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
