from collections import defaultdict
import json

from fastapi import APIRouter, Query

from backend.core.db import managed_conn
from backend.services.canonical_dataset_service import (
    export_canonical_dataset,
    summarize_canonical_dataset,
)

router = APIRouter()

_DECISION_LIMIT = 5
_CURRENT_DECISION_SCHEMA = "decision_event.v2"
_DECISION_BUCKETS = {
    "review_window": ("hold", "approve", "reject", "cancel"),
    "phase5": ("propose", "hold", "approve", "reject"),
}


def _normalize_thread_scope(thread_id: str | None) -> str | None:
    if not thread_id:
        return None
    scoped = str(thread_id).strip()
    if not scoped or scoped.lower() in {"all", "*"}:
        return None
    return scoped


def _scope_meta(thread_id: str | None) -> dict[str, str | None]:
    return {
        "thread_id": thread_id,
        "scope_label": thread_id or "all_threads",
    }


def _top_reason_codes(counts: dict[str, int], limit: int = _DECISION_LIMIT) -> list[dict[str, int | str]]:
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [{"code": code, "count": count} for code, count in ranked[:limit]]


def _blank_decision_analytics(thread_id: str | None) -> dict:
    analytics = {
        source: {decision: 0 for decision in decisions}
        for source, decisions in _DECISION_BUCKETS.items()
    }
    analytics["scope"] = _scope_meta(thread_id)
    analytics["top_reason_codes"] = []
    analytics["top_hold_reasons"] = []
    analytics["top_reject_reasons"] = []
    analytics["actor_breakdown"] = {}
    analytics["anomalies"] = {
        "review_token_mismatch": 0,
        "hold_cancelled": 0,
        "legacy_schema": 0,
        "missing_actor": 0,
        "missing_turn_id": 0,
        "missing_message_id": 0,
        "missing_stream_id": 0,
    }
    analytics["data_quality"] = {
        "schema_current": _CURRENT_DECISION_SCHEMA,
        "decision_events_total": 0,
        "v2_events": 0,
        "legacy_events": 0,
        "recommended_baseline_ts": None,
        "recommended_baseline_reason": "decision_event.v2 actor-aware telemetry",
    }
    return analytics


def _load_decision_analytics(cursor, thread_id: str | None) -> dict:
    analytics = _blank_decision_analytics(thread_id)
    sql = """
        SELECT ts, payload_json
        FROM events
        WHERE event_type = 'decision_event'
    """
    params: list[str] = []
    if thread_id:
        sql += " AND thread_id = ?"
        params.append(thread_id)
    sql += " ORDER BY id ASC"

    try:
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()
    except Exception:
        return analytics

    all_reasons: dict[str, int] = defaultdict(int)
    hold_reasons: dict[str, int] = defaultdict(int)
    reject_reasons: dict[str, int] = defaultdict(int)
    actor_breakdown: dict[str, int] = defaultdict(int)
    anomalies = analytics["anomalies"]
    quality = analytics["data_quality"]

    for row in rows:
        ts = row[0]
        payload_json = row[1]
        try:
            payload = json.loads(payload_json) if payload_json else {}
        except (json.JSONDecodeError, TypeError):
            payload = {}

        source = str(payload.get("source") or "")
        decision = str(payload.get("decision") or "")
        schema_version = str(payload.get("schema_version") or "")
        actor = str(payload.get("actor") or "").strip()
        reason_codes = payload.get("reason_codes")
        if not isinstance(reason_codes, list):
            reason_codes = []

        quality["decision_events_total"] += 1
        if schema_version == _CURRENT_DECISION_SCHEMA:
            quality["v2_events"] += 1
            if quality["recommended_baseline_ts"] is None:
                quality["recommended_baseline_ts"] = ts
        else:
            anomalies["legacy_schema"] += 1

        if source in _DECISION_BUCKETS and decision in _DECISION_BUCKETS[source]:
            analytics[source][decision] += 1

        if decision == "token_mismatch":
            anomalies["review_token_mismatch"] += 1
        if source == "review_window" and decision == "cancel":
            anomalies["hold_cancelled"] += 1

        if actor:
            actor_breakdown[actor] += 1
        else:
            anomalies["missing_actor"] += 1
            actor_breakdown["unknown"] += 1

        if actor == "gate" and not payload.get("turn_id"):
            anomalies["missing_turn_id"] += 1
        if actor == "gate" and not payload.get("message_id"):
            anomalies["missing_message_id"] += 1
        if actor == "gate" and not payload.get("stream_id"):
            anomalies["missing_stream_id"] += 1

        for code in reason_codes:
            if not code:
                continue
            text = str(code)
            all_reasons[text] += 1
            if decision == "hold":
                hold_reasons[text] += 1
            elif decision == "reject":
                reject_reasons[text] += 1

    quality["legacy_events"] = max(
        int(quality["decision_events_total"]) - int(quality["v2_events"]),
        0,
    )
    analytics["review_window"]["open_estimate"] = max(
        int(analytics["review_window"]["hold"])
        - int(analytics["review_window"]["approve"])
        - int(analytics["review_window"]["reject"])
        - int(analytics["review_window"]["cancel"]),
        0,
    )
    analytics["phase5"]["pending_estimate"] = max(
        int(analytics["phase5"]["hold"])
        - int(analytics["phase5"]["approve"])
        - int(analytics["phase5"]["reject"]),
        0,
    )
    analytics["top_reason_codes"] = _top_reason_codes(all_reasons)
    analytics["top_hold_reasons"] = _top_reason_codes(hold_reasons)
    analytics["top_reject_reasons"] = _top_reason_codes(reject_reasons)
    analytics["actor_breakdown"] = dict(sorted(actor_breakdown.items(), key=lambda item: (-item[1], item[0])))
    return analytics


def _fetch_count(cursor, sql: str, params: tuple = ()) -> int:
    cursor.execute(sql, params)
    row = cursor.fetchone()
    return int(row[0] or 0) if row else 0


@router.get("/summary")
def get_stats_summary(thread_id: str | None = None):
    """会話統計サマリーを取得"""
    scoped_thread_id = _normalize_thread_scope(thread_id)

    with managed_conn() as conn:
        cursor = conn.cursor()

        stats = {"scope": _scope_meta(scoped_thread_id)}

        events_where = "WHERE 1=1"
        events_params: list[str] = []
        if scoped_thread_id:
            events_where += " AND thread_id = ?"
            events_params.append(scoped_thread_id)

        memory_where = "WHERE 1=1"
        memory_params: list[str] = []
        if scoped_thread_id:
            memory_where += " AND thread_id = ?"
            memory_params.append(scoped_thread_id)

        stats["total_events"] = _fetch_count(
            cursor,
            f"SELECT COUNT(*) FROM events {events_where}",
            tuple(events_params),
        )
        stats["today_chats"] = _fetch_count(
            cursor,
            f"""
            SELECT COUNT(*) FROM events
            {events_where}
              AND event_type = 'chat_received'
              AND date(ts) = date('now')
            """,
            tuple(events_params),
        )
        stats["total_chats"] = _fetch_count(
            cursor,
            f"SELECT COUNT(*) FROM events {events_where} AND event_type = 'chat_received'",
            tuple(events_params),
        )

        try:
            stats["memory_candidates"] = _fetch_count(
                cursor,
                f"""
                SELECT COUNT(*)
                FROM memory_events
                {memory_where}
                  AND event_type IN ('capture_recorded', 'memory_pending')
                """,
                tuple(memory_params),
            )
        except Exception:
            stats["memory_candidates"] = 0

        try:
            unresolved_sql = """
                SELECT COUNT(*)
                FROM memory_events p
                WHERE p.event_type = 'memory_pending'
            """
            unresolved_params: list[str] = []
            if scoped_thread_id:
                unresolved_sql += " AND p.thread_id = ?"
                unresolved_params.append(scoped_thread_id)
            unresolved_sql += """
                  AND p.event_id NOT IN (
                    SELECT COALESCE(CAST(json_extract(a.payload_json, '$.ref_event_id') AS TEXT), '')
                    FROM memory_events a
                    WHERE a.event_type IN ('memory_approved', 'memory_rejected')
            """
            if scoped_thread_id:
                unresolved_sql += " AND a.thread_id = ?"
                unresolved_params.append(scoped_thread_id)
            unresolved_sql += """
                      AND json_extract(a.payload_json, '$.ref_event_id') IS NOT NULL
                  )
            """
            stats["memory_pending"] = _fetch_count(cursor, unresolved_sql, tuple(unresolved_params))
        except Exception:
            stats["memory_pending"] = 0

        try:
            stats["memory_approved"] = _fetch_count(
                cursor,
                f"SELECT COUNT(*) FROM memory_events {memory_where} AND event_type = 'memory_approved'",
                tuple(memory_params),
            )
        except Exception:
            stats["memory_approved"] = 0

        try:
            stats["memory_rejected"] = _fetch_count(
                cursor,
                f"SELECT COUNT(*) FROM memory_events {memory_where} AND event_type = 'memory_rejected'",
                tuple(memory_params),
            )
        except Exception:
            stats["memory_rejected"] = 0

        try:
            stats["memory_written"] = _fetch_count(
                cursor,
                f"""
                SELECT COUNT(*)
                FROM memory_events
                {memory_where}
                  AND event_type IN ('thought_registered', 'episode_added')
                """,
                tuple(memory_params),
            )
        except Exception:
            stats["memory_written"] = 0

        last_chat_sql = """
            SELECT ts FROM events
            WHERE event_type = 'chat_received'
        """
        last_chat_params: list[str] = []
        if scoped_thread_id:
            last_chat_sql += " AND thread_id = ?"
            last_chat_params.append(scoped_thread_id)
        last_chat_sql += " ORDER BY id DESC LIMIT 1"
        cursor.execute(last_chat_sql, tuple(last_chat_params))
        row = cursor.fetchone()
        stats["last_chat_time"] = row[0] if row else None

        stats["decision_analytics"] = _load_decision_analytics(cursor, scoped_thread_id)
        dataset_samples = export_canonical_dataset(
            thread_id=scoped_thread_id,
            include_excluded=True,
            high_confidence_only=False,
        )
        stats["dataset_analytics"] = summarize_canonical_dataset(
            dataset_samples,
            thread_id=scoped_thread_id,
        )
        return stats


@router.get("/dataset_export")
def get_dataset_export(
    thread_id: str | None = None,
    limit: int = Query(200, ge=1, le=2000),
    include_excluded: bool = Query(True),
    high_confidence_only: bool = Query(False),
):
    scoped_thread_id = _normalize_thread_scope(thread_id)
    items = export_canonical_dataset(
        thread_id=scoped_thread_id,
        limit=limit,
        include_excluded=include_excluded,
        high_confidence_only=high_confidence_only,
    )
    return {
        "scope": _scope_meta(scoped_thread_id),
        "items": items,
        "summary": summarize_canonical_dataset(items, thread_id=scoped_thread_id),
    }


@router.get("/dataset_audit")
def get_dataset_audit(thread_id: str | None = None):
    scoped_thread_id = _normalize_thread_scope(thread_id)
    items = export_canonical_dataset(
        thread_id=scoped_thread_id,
        include_excluded=True,
        high_confidence_only=False,
    )
    summary = summarize_canonical_dataset(items, thread_id=scoped_thread_id)
    return {
        "scope": _scope_meta(scoped_thread_id),
        "training_policy": summary.get("training_policy"),
        "training_ready_samples": summary.get("training_ready_samples"),
        "high_confidence_baseline_ts": summary.get("high_confidence_baseline_ts"),
        "join_completeness": summary.get("join_completeness"),
        "source_audit": summary.get("source_audit"),
        "exclude_reasons": summary.get("exclude_reasons"),
        "confidence_issues": summary.get("confidence_issues"),
    }
