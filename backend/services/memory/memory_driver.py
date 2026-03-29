from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from typing import Optional

from backend.core.config import settings
from backend.core.logger import logger
from backend.services.memory.models import MemoryEvent, MemoryIndexEntry
from backend.services.memory.storage_driver import StorageDriver


class MemoryDriver:
    """
    Memory semantics/rules layer.
    Keeps raw event append-only and derives query index entries.
    """

    def __init__(self, storage: Optional[StorageDriver] = None) -> None:
        self._storage = storage or StorageDriver()
        self._rebuild_lock = threading.Lock()

    def append_event(
        self,
        *,
        thread_id: str,
        event_type: str,
        payload: dict,
        turn_id: Optional[str] = None,
        message_id: Optional[str] = None,
        created_at: Optional[float] = None,
        schema_version: int = 1,
    ) -> str:
        ts = float(created_at) if created_at is not None else time.time()
        payload_obj = payload or {}
        payload_obj = self._ensure_payload_size(payload_obj, schema_version=schema_version, event_type=event_type)
        normalized_payload = self._normalize_payload_for_schema(schema_version, payload_obj)
        payload_json = json.dumps(payload_obj, ensure_ascii=False)
        event_id = str(uuid.uuid4())
        event = MemoryEvent(
            event_id=event_id,
            thread_id=thread_id,
            turn_id=turn_id,
            message_id=message_id,
            event_type=event_type,
            payload_json=payload_json,
            created_at=ts,
            schema_version=schema_version,
        )
        index = self._build_index_entry(event, payload=normalized_payload)
        self._storage.append_event_and_index(event, index=index)
        return event_id

    def query_index(
        self,
        *,
        thread_id: str,
        scope: Optional[str] = None,
        related_turn_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        return self._storage.query_index(
            thread_id=thread_id,
            scope=scope,
            related_turn_id=related_turn_id,
            limit=limit,
        )

    def load_events_by_ids(self, event_ids: list[str]) -> list[dict]:
        rows = self._storage.load_events_by_ids(event_ids)
        by_id = {r.get("event_id"): r for r in rows}
        ordered: list[dict] = []
        for eid in event_ids:
            row = by_id.get(eid)
            if row:
                ordered.append(row)
        return ordered

    def rebuild_index(self, thread_id: Optional[str] = None, *, limit: int = 5000) -> int:
        acquired = self._rebuild_lock.acquire(blocking=False)
        if not acquired:
            logger.warning("[MemoryDriver] rebuild_index already running; waiting lock thread_id=%s", thread_id)
            self._rebuild_lock.acquire()
        try:
            if thread_id:
                self._storage.clear_index_for_thread(thread_id)
            batch_size = 500
            offset = 0
            indexed = 0
            max_rows = int(limit) if int(limit) > 0 else None
            while True:
                remaining = None if max_rows is None else max_rows - offset
                if remaining is not None and remaining <= 0:
                    break
                fetch_n = batch_size if remaining is None else min(batch_size, remaining)
                rows = self._storage.list_events(thread_id=thread_id, limit=fetch_n, offset=offset)
                if not rows:
                    break
                items: list[MemoryIndexEntry] = []
                for row in rows:
                    schema_version = int(row.get("schema_version") or 1)
                    payload = self._decode_payload(
                        raw=row.get("payload_json"),
                        schema_version=schema_version,
                        event_type=str(row.get("event_type") or ""),
                    )
                    event = MemoryEvent(
                        event_id=str(row.get("event_id")),
                        thread_id=str(row.get("thread_id")),
                        turn_id=row.get("turn_id"),
                        message_id=row.get("message_id"),
                        event_type=str(row.get("event_type")),
                        payload_json=str(row.get("payload_json") or "{}"),
                        created_at=float(row.get("created_at") or time.time()),
                        schema_version=schema_version,
                    )
                    idx = self._build_index_entry(event, payload=payload)
                    if idx is not None:
                        items.append(idx)
                indexed += self._storage.upsert_index_entries(items)
                offset += len(rows)
                if len(rows) < fetch_n:
                    break
            return indexed
        finally:
            self._rebuild_lock.release()

    def _build_index_entry(self, event: MemoryEvent, *, payload: dict) -> Optional[MemoryIndexEntry]:
        if not event.thread_id:
            logger.warning(
                "[MemoryDriver] skip index build: empty thread_id event_id=%s type=%s",
                event.event_id,
                event.event_type,
            )
            return None
        scope = str(payload.get("scope") or self._infer_scope(event.event_type))
        tags = payload.get("tags")
        keywords = payload.get("keywords")
        state_tag = payload.get("state_tag")
        index_id = self._index_id_for(event.event_id, scope)
        ts = float(event.created_at)
        return MemoryIndexEntry(
            index_id=index_id,
            event_id=event.event_id,
            thread_id=event.thread_id,
            scope=scope,
            state_tag=str(state_tag) if state_tag is not None else None,
            tags_json=json.dumps(tags if isinstance(tags, list) else [], ensure_ascii=False),
            keywords_json=json.dumps(keywords if isinstance(keywords, list) else [], ensure_ascii=False),
            related_turn_id=event.turn_id,
            created_at=ts,
            updated_at=ts,
        )

    def _infer_scope(self, event_type: str) -> str:
        et = (event_type or "").lower()
        if et.startswith("review_"):
            return "review"
        if et.startswith("state_"):
            return "state"
        if et.startswith("episode"):
            return "episode"
        return "general"

    def _index_id_for(self, event_id: str, scope: str) -> str:
        seed = f"{event_id}:{scope}".encode("utf-8", errors="ignore")
        return hashlib.sha1(seed).hexdigest()

    def _safe_json_loads(self, raw: object) -> dict:
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                obj = json.loads(raw)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                preview = raw[:120].replace("\n", "\\n")
                logger.warning("[MemoryDriver] payload_json decode failed preview=%r", preview)
                return {}
            logger.warning("[MemoryDriver] payload_json is not object type=%s", type(obj).__name__)
            return {}
        if raw is not None:
            logger.warning("[MemoryDriver] payload_json unexpected type=%s", type(raw).__name__)
        return {}

    def _normalize_payload_for_schema(self, schema_version: int, payload: dict) -> dict:
        if schema_version == 1:
            return payload if isinstance(payload, dict) else {}
        if schema_version == 2:
            if not isinstance(payload, dict):
                return {}
            inner = payload.get("payload")
            if isinstance(inner, dict):
                return inner
            data = payload.get("data")
            if isinstance(data, dict):
                return data
            return payload
        logger.warning("[MemoryDriver] unsupported schema_version=%s in append; fallback v1 style", schema_version)
        return payload if isinstance(payload, dict) else {}

    def _decode_payload(self, *, raw: object, schema_version: int, event_type: str) -> dict:
        payload = self._safe_json_loads(raw)
        if schema_version == 1:
            return payload
        if schema_version == 2:
            inner = payload.get("payload")
            if isinstance(inner, dict):
                return inner
            data = payload.get("data")
            if isinstance(data, dict):
                return data
            logger.warning(
                "[MemoryDriver] schema v2 missing inner payload event_type=%s keys=%s",
                event_type,
                list(payload.keys())[:8],
            )
            return payload
        logger.warning(
            "[MemoryDriver] unsupported schema_version=%s event_type=%s; fallback raw payload",
            schema_version,
            event_type,
        )
        return payload

    def _payload_size_bytes(self, payload_obj: dict) -> int:
        try:
            return len(json.dumps(payload_obj, ensure_ascii=False).encode("utf-8"))
        except Exception:
            return 0

    def _ensure_payload_size(self, payload_obj: dict, *, schema_version: int, event_type: str) -> dict:
        max_bytes = int(getattr(settings, "MEMORY_EVENT_MAX_PAYLOAD_BYTES", 65536))
        size = self._payload_size_bytes(payload_obj)
        if size <= max_bytes:
            return payload_obj

        text = ""
        if isinstance(payload_obj.get("text"), str):
            text = payload_obj.get("text") or ""
        elif isinstance(payload_obj.get("summary"), str):
            text = payload_obj.get("summary") or ""
        elif isinstance(payload_obj.get("details"), str):
            text = payload_obj.get("details") or ""

        clipped = text
        # keep roughly half and shrink until under cap
        target = max(64, int(len(clipped) * 0.5))
        if len(clipped) > target:
            clipped = clipped[:target]
        compact = {
            "_payload_truncated": True,
            "_schema_version": int(schema_version),
            "_event_type": str(event_type),
            "_orig_size_bytes": int(size),
            "_scope": payload_obj.get("scope"),
            "_state_tag": payload_obj.get("state_tag"),
            "_tags": payload_obj.get("tags") if isinstance(payload_obj.get("tags"), list) else [],
            "_keywords": payload_obj.get("keywords") if isinstance(payload_obj.get("keywords"), list) else [],
            "_text_preview": clipped,
        }
        while self._payload_size_bytes(compact) > max_bytes and len(compact.get("_text_preview") or "") > 32:
            compact["_text_preview"] = (compact.get("_text_preview") or "")[: max(32, len(compact["_text_preview"]) // 2)]

        if self._payload_size_bytes(compact) > max_bytes:
            # final hard fallback
            compact = {
                "_payload_truncated": True,
                "_schema_version": int(schema_version),
                "_event_type": str(event_type),
                "_orig_size_bytes": int(size),
            }

        logger.warning(
            "[MemoryDriver] payload too large; truncated event_type=%s size=%s max=%s",
            event_type,
            size,
            max_bytes,
        )
        return compact
