import json
import time

from backend.core.db import get_conn, init_schema
from backend.services.canonical_dataset_service import (
    export_canonical_dataset,
    summarize_canonical_dataset,
)


def _seed_event(event_type: str, thread_id: str, payload: dict):
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO events (thread_id, event_type, payload_json) VALUES (?, ?, ?)",
            (thread_id, event_type, json.dumps(payload, ensure_ascii=False)),
        )
    finally:
        conn.close()


def _seed_x_post(
    *,
    proposal_id: str,
    thread_id: str,
    source: str,
    status: str,
    created_at: float,
    turn_id: str | None = None,
    message_id: str | None = None,
    stream_id: str | None = None,
):
    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT INTO x_post_proposals (
                proposal_id, thread_id, turn_id, message_id, stream_id, source, source_ref, status,
                candidate_text, approved_text, posted_text, tweet_id, actor,
                reason_codes_json, metadata_json, failure_reason, idempotency_key,
                created_at, updated_at, approved_at, rejected_at, posted_at
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, '[]', '{}', NULL, NULL, ?, ?, ?, ?, ?)
            """,
            (
                proposal_id,
                thread_id,
                turn_id,
                message_id,
                stream_id,
                source,
                status,
                "candidate",
                "approved" if status in {"approved", "posting", "posted"} else None,
                "posted" if status == "posted" else None,
                "tweet-1" if status == "posted" else None,
                "user",
                created_at,
                created_at,
                created_at if status in {"approved", "posting", "posted"} else None,
                created_at if status == "rejected" else None,
                created_at if status == "posted" else None,
            ),
        )
    finally:
        conn.close()


def setup_function():
    init_schema()
    conn = get_conn()
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("DELETE FROM memory_events")
        conn.execute("DELETE FROM events")
        conn.execute("DELETE FROM x_post_proposals")
        conn.execute("PRAGMA foreign_keys = ON")
    finally:
        conn.close()


def test_export_canonical_dataset_joins_review_commit_and_x_posts():
    tid = f"canon_{int(time.time() * 1000)}"
    now = time.time()

    _seed_event(
        "commit_log",
        tid,
        {
            "schema_version": "commit_log.v2",
            "line": "[COMMIT] say:1 rejected:0 D:0.10->0.10 hold:ask reasons:keyword_memory",
            "decision": "approve",
            "actor": "user",
            "review_token": "tok-review",
            "thread_id": tid,
            "turn_id": "turn-1",
            "message_id": "msg-1",
            "stream_id": "stream-1",
            "reason_codes": ["keyword_memory"],
            "ts": now,
        },
    )
    _seed_event(
        "decision_event",
        tid,
        {
            "schema_version": "decision_event.v2",
            "source": "review_window",
            "decision": "approve",
            "status": "applied",
            "actor": "user",
            "review_token": "tok-review",
            "turn_id": "turn-1",
            "message_id": "msg-1",
            "stream_id": "stream-1",
            "reason_codes": ["keyword_memory"],
            "ts": now,
        },
    )
    _seed_event(
        "decision_event",
        tid,
        {
            "schema_version": "decision_event.v2",
            "source": "phase5",
            "decision": "reject",
            "status": "rejected_by_user",
            "actor": "user",
            "turn_id": "turn-2",
            "message_id": "msg-2",
            "stream_id": "stream-2",
            "pending_id": "p1",
            "action_id": "search_memory",
            "reason_codes": ["keyword_public"],
            "ts": now + 1,
        },
    )
    _seed_event(
        "decision_event",
        tid,
        {
            "schema_version": "decision_event.v2",
            "source": "review_window",
            "decision": "cancel",
            "status": "cancelled",
            "actor": "system",
            "review_token": "tok-cancel",
            "turn_id": "turn-3",
            "message_id": "msg-3",
            "stream_id": "stream-3",
            "reason_codes": ["system_hold_cancelled_new_input"],
            "ts": now + 2,
        },
    )
    _seed_x_post(
        proposal_id="xp-phase5",
        thread_id=tid,
        source="phase5_action",
        status="posted",
        created_at=now + 3,
        turn_id="turn-2",
        message_id="msg-2",
        stream_id="stream-2",
    )
    _seed_x_post(
        proposal_id="xp-reflection",
        thread_id=tid,
        source="reflection_daily_log",
        status="rejected",
        created_at=now + 4,
    )

    rows = export_canonical_dataset(thread_id=tid)
    review = next(item for item in rows if item["sample_kind"] == "review_decision" and item["decision"] == "approve")
    phase5 = next(item for item in rows if item["sample_kind"] == "phase5_decision")
    cancel = next(item for item in rows if item["sample_kind"] == "review_decision" and item["decision"] == "cancel")
    x_phase5 = next(item for item in rows if item["sample_id"] == "x_post:xp-phase5")
    x_reflection = next(item for item in rows if item["sample_id"] == "x_post:xp-reflection")

    assert review["matched_commit_log"] is True
    assert review["commit_log_line"].startswith("[COMMIT]")
    assert review["high_confidence"] is True
    assert review["training_label"] == "positive"

    assert phase5["high_confidence"] is True
    assert phase5["training_label"] == "negative"

    assert cancel["eligible_for_training"] is False
    assert cancel["exclude_reason"] == "cancelled_flow"

    assert x_phase5["high_confidence"] is True
    assert x_phase5["training_label"] == "positive"
    assert x_reflection["high_confidence"] is True
    assert x_reflection["training_label"] == "negative"

    summary = summarize_canonical_dataset(rows, thread_id=tid)
    assert summary["eligible_samples"] == 4
    assert summary["high_confidence_samples"] == 4
    assert summary["training_ready_samples"] == 4
    assert summary["excluded_samples"] >= 1
    assert summary["x_post_status_breakdown"]["posted"] == 1
    assert summary["x_post_status_breakdown"]["rejected"] == 1
    assert any(item["source"] == "phase5_action" for item in summary["source_audit"])


def test_export_canonical_dataset_marks_low_confidence_missing_joins_and_commit():
    tid = f"canon_low_{int(time.time() * 1000)}"
    now = time.time()

    _seed_event(
        "decision_event",
        tid,
        {
            "schema_version": "decision_event.v2",
            "source": "review_window",
            "decision": "approve",
            "status": "applied",
            "actor": "user",
            "review_token": "tok-low",
            "reason_codes": ["keyword_memory"],
            "ts": now,
        },
    )

    rows = export_canonical_dataset(thread_id=tid)
    review = next(item for item in rows if item["sample_kind"] == "review_decision")

    assert review["eligible_for_training"] is True
    assert review["high_confidence"] is False
    assert "missing_turn_id" in review["confidence_issues"]
    assert "missing_message_id" in review["confidence_issues"]
    assert "missing_stream_id" in review["confidence_issues"]
    assert "missing_commit_log" in review["confidence_issues"]

    summary = summarize_canonical_dataset(rows, thread_id=tid)
    assert summary["eligible_samples"] == 1
    assert summary["low_confidence_samples"] == 1
    assert summary["training_ready_samples"] == 0
    assert summary["join_completeness"]["eligible_join_samples"] == 1
    assert summary["join_completeness"]["full_triplet_present"] == 0
