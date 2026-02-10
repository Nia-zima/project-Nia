# backend/services/pending_actions_service.py
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
import os
from typing import Any, Dict, Optional, Iterable

import sqlite3

from backend.services.pending_actions_repo import pending_actions_repo
from backend.services.telemetry_logger import telemetry
from backend.services.memory_gate import run_gate
from backend.core.config import settings


_EPISODIC_COLUMNS = {
    "id",
    "thread_id",
    "created_at",
    "raw_text",
    "state_tag",
    "emotion_tags",
    "stream_id",
    "message_id",
    "origin_message_id",
    "surprise",
    "keywords",
    "entities",
    "tags",
    "refs",
    "retention",
    "stage",
    "text_hash",
}

logger = logging.getLogger(__name__)


def _dedupe_key(thread_id: str, message_id: str) -> str:
    raw = f"{thread_id}:{message_id}:memory_add".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _build_commit_line(
    event: str,
    *,
    memory_delta: int,
    reason: Optional[str],
    dissonance_before: Optional[float],
    dissonance_after: Optional[float],
) -> str:
    before = f"{dissonance_before:.2f}" if isinstance(dissonance_before, (int, float)) else "null"
    after = f"{dissonance_after:.2f}" if isinstance(dissonance_after, (int, float)) else "null"
    reason_str = reason or ""
    return (
        f"[COMMIT] applied:{1 if memory_delta == 1 else 0} action:memory_add "
        f"event:{event} memory:+{memory_delta} D:{before}->{after} reasons:{reason_str}"
    )


async def _commit_log(
    event: str,
    payload: Dict[str, Any],
    *,
    memory_delta: int,
    reason: Optional[str] = None,
    dissonance_before: Optional[float] = None,
    dissonance_after: Optional[float] = None,
    schema_version: Optional[str] = None,
    rationale: Optional[str] = None,
    rationale_code: Optional[str] = None,
    gate_mode: Optional[str] = None,
    pending_count: Optional[int] = None,
    dissonance_delta: Optional[float] = None,
    candidate_summary: Optional[str] = None,
) -> None:
    meta = {
        "event": event,
        "action_kind": "memory_add",
        "memory_delta": memory_delta,
        "reason": reason,
        "reasons": [reason] if reason else [],
        "dissonance_before": dissonance_before,
        "dissonance_after": dissonance_after,
        "schema_version": schema_version,
        "kind": "memory_add",
        "rationale": rationale,
        "rationale_code": rationale_code,
        "gate_mode": gate_mode,
        "pending_count": pending_count,
        "dissonance_delta": dissonance_delta,
        "candidate_summary": candidate_summary,
    }
    line = _build_commit_line(
        event,
        memory_delta=memory_delta,
        reason=reason,
        dissonance_before=dissonance_before,
        dissonance_after=dissonance_after,
    )
    await telemetry.event(
        payload.get("thread_id"),
        "commit_log",
        {"line": line, **meta, **payload},
    )


def _pending_delta(count: int) -> float:
    return min(0.15, max(0, int(count)) * 0.01)


def _filter_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in (payload or {}).items() if k in _EPISODIC_COLUMNS}


def _candidate_summary(text: Optional[str], max_len: int = 120) -> str:
    if not text:
        return ""
    s = str(text).strip().replace("\n", " ")
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


def _insert_episodic_capture(payload: Dict[str, Any]) -> None:
    if getattr(settings, "LEGACY_MEMORY_READ_ONLY", False):
        from backend.services.memory_manager import memory_manager

        event_payload = {
            "legacy_capture_id": payload.get("id"),
            "raw_text": payload.get("raw_text") or "",
            "state_tag": payload.get("state_tag"),
            "tags": payload.get("tags"),
            "refs": payload.get("refs"),
            "retention": float(payload.get("retention") or 0.0),
            "stage": payload.get("stage") or "capture",
            "scope": str(payload.get("stage") or "capture"),
            "text_hash": payload.get("text_hash"),
        }
        memory_manager.append_memory_event(
            thread_id=str(payload.get("thread_id") or "default_thread"),
            event_type="capture_recorded",
            payload=event_payload,
            turn_id=str(payload.get("origin_message_id") or payload.get("message_id") or "") or None,
            message_id=str(payload.get("message_id") or payload.get("id") or "") or None,
            created_at=float(payload.get("created_at") or time.time()),
        )
        logger.info(
            "approve_pending_action: wrote capture_recorded event in read-only mode thread_id=%s message_id=%s",
            payload.get("thread_id"),
            payload.get("message_id"),
        )
        return

    from backend.core.db import get_conn

    required = ("id", "thread_id", "created_at", "raw_text")
    for k in required:
        if not payload.get(k):
            raise ValueError(f"episodic_payload missing required field: {k}")

    cols = []
    vals = []
    for k, v in payload.items():
        cols.append(k)
        vals.append(v)

    placeholders = ",".join(["?"] * len(cols))
    sql = f"INSERT INTO episodic_captures ({','.join(cols)}) VALUES ({placeholders})"

    conn = get_conn()
    try:
        conn.execute(sql, tuple(vals))
    finally:
        conn.close()


async def enqueue_memory_add(
    thread_id: str,
    message_id: str,
    episodic_payload: Dict[str, Any],
    *,
    review_window_id: Optional[str] = None,
    user_text: Optional[str] = None,
    candidate_tags: Optional[str] = None,
) -> Dict[str, str]:
    now = time.time()
    payload = dict(episodic_payload or {})
    if not payload.get("id"):
        payload["id"] = uuid.uuid4().hex
    payload.setdefault("thread_id", thread_id)
    payload.setdefault("schema_version", "v0")
    payload["created_at"] = float(now)
    payload_json = json.dumps(payload, ensure_ascii=False)

    dedupe_key = _dedupe_key(thread_id, message_id)
    pending_id = uuid.uuid4().hex

    gate_mode = os.getenv("MEMORY_GATE_V1_MODE", "").lower().strip()
    if gate_mode in {"log_only", "enforce"}:
        pending_count = pending_actions_repo.count_pending_actions(thread_id)
        dissonance_delta = _pending_delta(pending_count)
        decision = run_gate(
            user_text or "",
            str(payload.get("raw_text") or ""),
            candidate_tags or str(payload.get("tags") or ""),
        )
        should = bool(decision.get("should_propose"))
        rationale = str(decision.get("rationale") or "")
        rationale_code = str(decision.get("rationale_code") or "low_signal")
        if not should:
            await _commit_log(
                "MEMORY_ADD_SKIPPED_BY_GATE",
                {
                    "pending_action_id": pending_id,
                    "thread_id": thread_id,
                    "message_id": message_id,
                    "text_hash": payload.get("text_hash"),
                    "schema_version": payload.get("schema_version"),
                },
                memory_delta=0,
                reason=rationale_code,
                schema_version=payload.get("schema_version"),
                rationale=rationale,
                rationale_code=rationale_code,
                gate_mode=gate_mode,
                pending_count=pending_count,
                dissonance_delta=dissonance_delta,
                candidate_summary=_candidate_summary(str(payload.get("raw_text") or "")),
            )
            if gate_mode == "enforce":
                return {"pending_action_id": pending_id, "status": "SKIPPED_BY_GATE"}

    try:
        pending_actions_repo.insert_pending_action(
            id=pending_id,
            thread_id=thread_id,
            message_id=message_id,
            action_type="memory_add",
            payload_json=payload_json,
            status="PENDING",
            reason=None,
            review_window_id=review_window_id,
            dedupe_key=dedupe_key,
            created_at=now,
            updated_at=now,
        )
        await _commit_log(
            "MEMORY_ADD_ENQUEUED",
            {
                "pending_action_id": pending_id,
                "thread_id": thread_id,
                "message_id": message_id,
                "text_hash": payload.get("text_hash"),
                "schema_version": payload.get("schema_version"),
            },
            memory_delta=0,
            reason=None,
            schema_version=payload.get("schema_version"),
        )
        return {"pending_action_id": pending_id, "status": "ENQUEUED"}
    except sqlite3.IntegrityError:
        existing = pending_actions_repo.get_by_dedupe_key(dedupe_key)
        if existing:
            return {"pending_action_id": str(existing.get("id")), "status": "ALREADY_ENQUEUED"}
        raise


async def hold_pending_action(id: str, reason: Optional[str]) -> bool:
    now = time.time()
    row = pending_actions_repo.get_by_id(id) or {}
    thread_id = row.get("thread_id")
    before_count = pending_actions_repo.count_pending_actions(thread_id) if thread_id else 0
    ok = pending_actions_repo.try_update_status(
        id=id,
        next_status="HELD",
        reason=reason,
        now=now,
    )
    if not ok:
        return False
    after_count = pending_actions_repo.count_pending_actions(thread_id) if thread_id else before_count
    await _commit_log(
        "MEMORY_ADD_HELD",
        {
            "pending_action_id": id,
            "thread_id": thread_id,
            "message_id": row.get("message_id"),
        },
        memory_delta=0,
        reason=reason,
        dissonance_before=_pending_delta(before_count),
        dissonance_after=_pending_delta(after_count),
        schema_version=None,
    )
    return True


async def reject_pending_action(id: str, reason: Optional[str]) -> bool:
    now = time.time()
    row = pending_actions_repo.get_by_id(id) or {}
    thread_id = row.get("thread_id")
    before_count = pending_actions_repo.count_pending_actions(thread_id) if thread_id else 0
    ok = pending_actions_repo.try_update_status(
        id=id,
        next_status="REJECTED",
        reason=reason,
        now=now,
    )
    if not ok:
        return False
    after_count = pending_actions_repo.count_pending_actions(thread_id) if thread_id else before_count
    await _commit_log(
        "MEMORY_ADD_REJECTED",
        {
            "pending_action_id": id,
            "thread_id": thread_id,
            "message_id": row.get("message_id"),
        },
        memory_delta=0,
        reason=reason,
        dissonance_before=_pending_delta(before_count),
        dissonance_after=_pending_delta(after_count),
        schema_version=None,
    )
    return True


async def archive_pending_action(id: str, reason: Optional[str]) -> bool:
    now = time.time()
    row = pending_actions_repo.get_by_id(id) or {}
    thread_id = row.get("thread_id")
    before_count = pending_actions_repo.count_pending_actions(thread_id) if thread_id else 0
    ok = pending_actions_repo.try_update_status_in(
        id=id,
        from_statuses=["REJECTED", "ERROR"],
        to_status="ARCHIVED",
        reason=reason,
        now=now,
    )
    if not ok:
        return False
    await _commit_log(
        "MEMORY_ADD_ARCHIVED",
        {
            "pending_action_id": id,
            "thread_id": thread_id,
            "message_id": row.get("message_id"),
        },
        memory_delta=0,
        reason=reason,
        dissonance_before=_pending_delta(before_count),
        dissonance_after=_pending_delta(before_count),
        schema_version=None,
    )
    return True

async def approve_pending_action(id: str, reason: Optional[str]) -> str:
    now = time.time()
    row = pending_actions_repo.get_by_id(id) or {}
    thread_id = row.get("thread_id")
    before_count = pending_actions_repo.count_pending_actions(thread_id) if thread_id else 0
    ok = pending_actions_repo.try_update_status(
        id=id,
        next_status="APPROVED",
        reason=reason,
        now=now,
    )
    if not ok:
        return "CONFLICT"

    await _commit_log(
        "MEMORY_ADD_APPROVED",
        {
            "pending_action_id": id,
            "thread_id": thread_id,
            "message_id": row.get("message_id"),
        },
        memory_delta=0,
        reason=reason,
        dissonance_before=_pending_delta(before_count),
        dissonance_after=_pending_delta(before_count),
        schema_version=None,
    )

    payload_json = row.get("payload_json") or "{}"
    parsed_full = json.loads(payload_json)
    schema_version = parsed_full.get("schema_version")
    payload = _filter_payload(parsed_full)
    payload.setdefault("id", uuid.uuid4().hex)
    payload.setdefault("thread_id", thread_id)
    payload.setdefault("created_at", float(row.get("created_at") or now))
    try:
        _insert_episodic_capture(payload)
        pending_actions_repo.try_update_status_from(
            id=id,
            from_status="APPROVED",
            to_status="APPLIED",
            reason=None,
            now=now,
        )
        after_count = pending_actions_repo.count_pending_actions(thread_id) if thread_id else before_count
        await _commit_log(
            "MEMORY_ADD_APPLIED",
            {
                "pending_action_id": id,
                "thread_id": thread_id,
                "message_id": row.get("message_id"),
                "text_hash": payload.get("text_hash"),
                "schema_version": schema_version,
            },
            memory_delta=1,
            reason=None,
            dissonance_before=_pending_delta(before_count),
            dissonance_after=_pending_delta(after_count),
            schema_version=schema_version,
        )
        return "APPLIED"
    except sqlite3.IntegrityError as e:
        msg = str(e).lower()
        if "text_hash" in msg:
            pending_actions_repo.try_update_status_from(
                id=id,
                from_status="APPROVED",
                to_status="CANCELLED",
                reason="ALREADY_EXISTS",
                now=now,
            )
            after_count = pending_actions_repo.count_pending_actions(thread_id) if thread_id else before_count
            await _commit_log(
                "MEMORY_ADD_CANCELLED_ALREADY_EXISTS",
                {
                    "pending_action_id": id,
                    "thread_id": thread_id,
                    "message_id": row.get("message_id"),
                    "text_hash": payload.get("text_hash"),
                    "schema_version": schema_version,
                },
                memory_delta=0,
                reason="ALREADY_EXISTS",
                dissonance_before=_pending_delta(before_count),
                dissonance_after=_pending_delta(after_count),
                schema_version=schema_version,
            )
            return "CANCELLED_ALREADY_EXISTS"
        pending_actions_repo.try_update_status_from(
            id=id,
            from_status="APPROVED",
            to_status="ERROR",
            reason=str(e),
            now=now,
        )
        after_count = pending_actions_repo.count_pending_actions(thread_id) if thread_id else before_count
        await _commit_log(
            "MEMORY_ADD_APPLY_FAILED",
            {
                "pending_action_id": id,
                "thread_id": thread_id,
                "message_id": row.get("message_id"),
                "error": str(e),
            },
            memory_delta=0,
            reason=str(e),
            dissonance_before=_pending_delta(before_count),
            dissonance_after=_pending_delta(after_count),
            schema_version=None,
        )
        raise
    except Exception as e:
        pending_actions_repo.try_update_status_from(
            id=id,
            from_status="APPROVED",
            to_status="ERROR",
            reason=str(e),
            now=now,
        )
        after_count = pending_actions_repo.count_pending_actions(thread_id) if thread_id else before_count
        await _commit_log(
            "MEMORY_ADD_APPLY_FAILED",
            {
                "pending_action_id": id,
                "thread_id": thread_id,
                "message_id": row.get("message_id"),
                "error": str(e),
            },
            memory_delta=0,
            reason=str(e),
            dissonance_before=_pending_delta(before_count),
            dissonance_after=_pending_delta(after_count),
            schema_version=None,
        )
        raise
