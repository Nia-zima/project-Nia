from __future__ import annotations

import time
from typing import Any, Iterable


def _normalize_reason_codes(reason_codes: Iterable[Any] | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for code in reason_codes or []:
        if not code:
            continue
        text = str(code)
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def build_decision_event_payload(
    *,
    source: str,
    entity_kind: str,
    decision: str,
    status: str,
    thread_id: str | None = None,
    actor: str | None = None,
    turn_id: str | None = None,
    message_id: str | None = None,
    stream_id: str | None = None,
    review_token: str | None = None,
    pending_id: str | None = None,
    action_id: str | None = None,
    item_kind: str | None = None,
    reason: str | None = None,
    reason_codes: Iterable[Any] | None = None,
    approved_by: str | None = None,
    result: Any = None,
    ts: float | None = None,
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "decision_event.v2",
        "source": source,
        "entity_kind": entity_kind,
        "decision": decision,
        "status": status,
        "thread_id": thread_id,
        "actor": actor,
        "turn_id": turn_id,
        "message_id": message_id,
        "stream_id": stream_id,
        "review_token": review_token,
        "pending_id": pending_id,
        "action_id": action_id,
        "item_kind": item_kind,
        "reason": reason,
        "reason_codes": _normalize_reason_codes(reason_codes),
        "approved_by": approved_by,
        "result": result,
        "ts": float(ts if ts is not None else time.time()),
    }
    if extras:
        payload.update(extras)
    return {key: value for key, value in payload.items() if value is not None}
