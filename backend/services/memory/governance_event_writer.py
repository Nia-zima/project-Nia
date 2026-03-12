"""Governance Event Writer — append-only event log for Memory Governance.

Records candidate, evidence, promotion, decay, retrieval, and context builder
events into the ``governance_events`` table.

Design doc: docs/memory_system_supplementary.md §3.1

Write modes:
  - Default (strict=False): fire-and-forget.  Failures are logged at DEBUG
    and return None / 0.  Suitable for observability / telemetry call-sites.
  - Strict  (strict=True):  failures propagate as exceptions.  Use this when
    the event is part of a provenance chain whose loss would silently corrupt
    the governance audit trail.
  - In-transaction (*_with_conn):  caller が管理する既存 transaction の conn を
    受け取り、同一 transaction 内に書き込む。provenance chain の原子性が必要な
    場合（例: semantic upsert + semantic_promoted を同一 COMMIT で保証）に使う。
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

from backend.core.db import managed_conn
from backend.core.logger import logger

_SCHEMA_VERSION = "governance_event.v1"


def record_event(
    *,
    event_name: str,
    thread_id: str | None = None,
    turn_id: str | None = None,
    message_id: str | None = None,
    stream_id: str | None = None,
    trace_id: str | None = None,
    owner_agent: str = "nia",
    memory_domain: str = "default",
    candidate_id: str | None = None,
    claim_id: str | None = None,
    semantic_id: str | None = None,
    contradiction_case_id: str | None = None,
    source_harvester: str | None = None,
    payload: dict[str, Any] | None = None,
    strict: bool = False,
) -> str | None:
    """Insert one row into governance_events.

    Returns the row id on success, None on failure (when *strict* is False).
    Raises on failure when *strict* is True.
    """
    try:
        row_id = uuid.uuid4().hex
        now = time.time()
        payload_json = json.dumps(payload, ensure_ascii=False) if payload else None
        with managed_conn() as conn:
            conn.execute(
                _INSERT_SQL,
                (
                    row_id, now, _SCHEMA_VERSION, event_name,
                    thread_id, turn_id, message_id, stream_id, trace_id,
                    owner_agent, memory_domain,
                    candidate_id, claim_id, semantic_id, contradiction_case_id,
                    source_harvester, payload_json,
                ),
            )
        return row_id
    except Exception:
        if strict:
            raise
        logger.debug("[GOVERNANCE_EVENT] write failed", exc_info=True)
        return None


def record_event_batch(
    events: list[dict[str, Any]],
    *,
    strict: bool = False,
) -> int:
    """Insert multiple governance events in a single transaction.

    Each dict in *events* should contain keyword arguments accepted by
    ``record_event`` (at minimum ``event_name``).

    Returns the number of rows successfully inserted.
    Raises on failure when *strict* is True.
    """
    if not events:
        return 0
    try:
        now = time.time()
        rows = [_build_row(ev, now) for ev in events]
        with managed_conn() as conn:
            conn.executemany(_INSERT_SQL, rows)
        return len(rows)
    except Exception:
        if strict:
            raise
        logger.debug("[GOVERNANCE_EVENT] batch write failed", exc_info=True)
        return 0


_INSERT_SQL = """\
INSERT INTO governance_events
   (id, ts, schema_version, event_name,
    thread_id, turn_id, message_id, stream_id, trace_id,
    owner_agent, memory_domain,
    candidate_id, claim_id, semantic_id, contradiction_case_id,
    source_harvester, payload_json)
   VALUES (?,?,?,?, ?,?,?,?,?, ?,?, ?,?,?,?, ?,?)"""


def _build_row(ev: dict[str, Any], now: float) -> tuple:
    """Build a single row tuple from an event dict."""
    payload = ev.get("payload")
    payload_json = json.dumps(payload, ensure_ascii=False) if payload else None
    return (
        uuid.uuid4().hex,
        now,
        _SCHEMA_VERSION,
        ev["event_name"],
        ev.get("thread_id"),
        ev.get("turn_id"),
        ev.get("message_id"),
        ev.get("stream_id"),
        ev.get("trace_id"),
        ev.get("owner_agent", "nia"),
        ev.get("memory_domain", "default"),
        ev.get("candidate_id"),
        ev.get("claim_id"),
        ev.get("semantic_id"),
        ev.get("contradiction_case_id"),
        ev.get("source_harvester"),
        payload_json,
    )


def record_event_batch_with_conn(
    conn,
    events: list[dict[str, Any]],
) -> int:
    """Insert governance events using caller's connection (in-transaction).

    Unlike ``record_event_batch``, this does NOT manage its own connection
    or transaction.  The caller is responsible for BEGIN/COMMIT/ROLLBACK.
    Failures always propagate (no fire-and-forget mode).

    Returns the number of rows inserted.
    """
    if not events:
        return 0
    now = time.time()
    rows = [_build_row(ev, now) for ev in events]
    conn.executemany(_INSERT_SQL, rows)
    return len(rows)


def query_events(
    *,
    event_name: str | None = None,
    thread_id: str | None = None,
    candidate_id: str | None = None,
    claim_id: str | None = None,
    semantic_id: str | None = None,
    contradiction_case_id: str | None = None,
    trace_id: str | None = None,
    limit: int = 100,
    since_ts: float | None = None,
) -> list[dict[str, Any]]:
    """Query governance events with optional filters.

    Returns list of dicts (column name → value).
    """
    clauses: list[str] = []
    params: list[Any] = []
    if event_name:
        clauses.append("event_name = ?")
        params.append(event_name)
    if thread_id:
        clauses.append("thread_id = ?")
        params.append(thread_id)
    if candidate_id:
        clauses.append("candidate_id = ?")
        params.append(candidate_id)
    if claim_id:
        clauses.append("claim_id = ?")
        params.append(claim_id)
    if semantic_id:
        clauses.append("semantic_id = ?")
        params.append(semantic_id)
    if contradiction_case_id:
        clauses.append("contradiction_case_id = ?")
        params.append(contradiction_case_id)
    if trace_id:
        clauses.append("trace_id = ?")
        params.append(trace_id)
    if since_ts is not None:
        clauses.append("ts >= ?")
        params.append(since_ts)

    where = " AND ".join(clauses) if clauses else "1=1"
    sql = f"SELECT * FROM governance_events WHERE {where} ORDER BY ts DESC LIMIT ?"
    params.append(limit)

    try:
        with managed_conn() as conn:
            conn.row_factory = _dict_factory
            return conn.execute(sql, params).fetchall()
    except Exception:
        logger.debug("[GOVERNANCE_EVENT] query failed", exc_info=True)
        return []


def _dict_factory(cursor, row):
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}
