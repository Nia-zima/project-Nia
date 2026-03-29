import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from backend.core.db import init_schema, managed_conn
from backend.controllers.stats import summary_router as sr


def _seed_chat_event(thread_id: str):
    with managed_conn() as conn:
        conn.execute(
            "INSERT INTO events (thread_id, event_type, payload_json) VALUES (?, ?, ?)",
            (thread_id, "chat_received", "{}"),
        )


def _seed_memory_event(thread_id: str, event_type: str, payload_json: str = "{}", event_id: str | None = None):
    with managed_conn() as conn:
        if event_id:
            conn.execute(
                "INSERT INTO memory_events (event_id, thread_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (event_id, thread_id, event_type, payload_json, float(time.time())),
            )
        else:
            conn.execute(
                "INSERT INTO memory_events (thread_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?)",
                (thread_id, event_type, payload_json, float(time.time())),
            )


def _seed_decision_event(thread_id: str, payload: dict):
    with managed_conn() as conn:
        conn.execute(
            "INSERT INTO events (thread_id, event_type, payload_json) VALUES (?, ?, ?)",
            (thread_id, "decision_event", json.dumps(payload, ensure_ascii=False)),
        )


def _seed_commit_log(thread_id: str, payload: dict):
    with managed_conn() as conn:
        conn.execute(
            "INSERT INTO events (thread_id, event_type, payload_json) VALUES (?, ?, ?)",
            (thread_id, "commit_log", json.dumps(payload, ensure_ascii=False)),
        )


def _seed_x_post_proposal(
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
    with managed_conn() as conn:
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
                "tweet candidate",
                "tweet approved" if status in {"approved", "posting", "posted"} else None,
                "tweet posted" if status == "posted" else None,
                "tweet-1" if status == "posted" else None,
                "user",
                created_at,
                created_at,
                created_at if status in {"approved", "posting", "posted"} else None,
                created_at if status == "rejected" else None,
                created_at if status == "posted" else None,
            ),
        )


def test_stats_summary_uses_memory_events_for_memory_counts():
    init_schema()
    tid = f"stats_{int(time.time() * 1000)}"

    _seed_chat_event(tid)
    _seed_chat_event(tid)

    _seed_memory_event(tid, "capture_recorded")
    p1 = f"{tid}_p1"
    p2 = f"{tid}_p2"
    _seed_memory_event(tid, "memory_pending", event_id=p1)
    _seed_memory_event(tid, "memory_pending", event_id=p2)
    _seed_memory_event(tid, "memory_approved", payload_json=f'{{"ref_event_id":"{p1}"}}')
    _seed_memory_event(tid, "memory_rejected", payload_json='{"ref_event_id":"unknown"}')
    _seed_memory_event(tid, "thought_registered")
    _seed_memory_event(tid, "episode_added")

    stats = sr.get_stats_summary()

    assert stats.get("total_chats", 0) >= 2
    assert stats.get("today_chats", 0) >= 2
    assert stats.get("memory_candidates", 0) >= 3  # capture_recorded + 2 pending
    assert stats.get("memory_pending", 0) >= 1     # p2 is unresolved
    assert stats.get("memory_approved", 0) >= 1
    assert stats.get("memory_rejected", 0) >= 1
    assert stats.get("memory_written", 0) >= 2     # thought_registered + episode_added


def test_stats_summary_includes_decision_analytics():
    init_schema()
    tid = f"decision_stats_{int(time.time() * 1000)}"
    now = time.time()

    _seed_decision_event(tid, {
        "schema_version": "decision_event.v2",
        "source": "review_window",
        "decision": "hold",
        "actor": "gate",
        "turn_id": "turn-1",
        "message_id": "m1",
        "stream_id": "s1",
        "reason_codes": ["risk_long_text", "keyword_memory"],
    })
    _seed_decision_event(tid, {
        "schema_version": "decision_event.v2",
        "source": "review_window",
        "decision": "reject",
        "actor": "user",
        "reason_codes": ["keyword_memory"],
    })
    _seed_decision_event(tid, {
        "schema_version": "decision_event.v2",
        "source": "review_window",
        "decision": "cancel",
        "actor": "system",
        "message_id": "m1",
        "stream_id": "s1",
        "reason_codes": ["system_hold_cancelled_new_input"],
    })
    _seed_decision_event(tid, {
        "schema_version": "decision_event.v2",
        "source": "phase5",
        "decision": "hold",
        "actor": "gate",
        "turn_id": "turn-2",
        "message_id": "m2",
        "stream_id": "s2",
        "reason_codes": ["keyword_public"],
    })
    _seed_decision_event(tid, {
        "schema_version": "decision_event.v2",
        "source": "phase5",
        "decision": "approve",
        "actor": "user",
        "turn_id": "turn-2",
        "message_id": "m2",
        "stream_id": "s2",
        "reason_codes": [],
    })
    _seed_decision_event(tid, {
        "schema_version": "decision_event.v1",
        "source": "review_window",
        "decision": "token_mismatch",
        "reason_codes": ["system_review_token_mismatch"],
    })
    _seed_decision_event("other_thread", {
        "schema_version": "decision_event.v2",
        "source": "review_window",
        "decision": "hold",
        "actor": "gate",
        "reason_codes": ["keyword_policy"],
    })
    _seed_commit_log(tid, {
        "schema_version": "commit_log.v2",
        "line": "[COMMIT] say:1 rejected:0 D:0.10->0.10 hold:ask reasons:keyword_memory",
        "decision": "approve",
        "actor": "user",
        "review_token": "tok-approve",
        "thread_id": tid,
        "turn_id": "turn-1",
        "message_id": "m1",
        "stream_id": "s1",
        "reason_codes": ["keyword_memory"],
        "ts": now,
    })
    _seed_decision_event(tid, {
        "schema_version": "decision_event.v2",
        "source": "review_window",
        "decision": "approve",
        "actor": "user",
        "turn_id": "turn-1",
        "message_id": "m1",
        "stream_id": "s1",
        "review_token": "tok-approve",
        "reason_codes": ["keyword_memory"],
        "ts": now,
    })
    _seed_x_post_proposal(
        proposal_id="xp1",
        thread_id=tid,
        source="phase5_action",
        status="posted",
        created_at=now,
        turn_id="turn-2",
        message_id="m2",
        stream_id="s2",
    )

    stats = sr.get_stats_summary(thread_id=tid)
    analytics = stats.get("decision_analytics") or {}
    dataset = stats.get("dataset_analytics") or {}

    assert stats["scope"]["thread_id"] == tid
    assert analytics["scope"]["thread_id"] == tid
    assert analytics["review_window"]["hold"] == 1
    assert analytics["review_window"]["approve"] == 1
    assert analytics["review_window"]["reject"] == 1
    assert analytics["review_window"]["cancel"] == 1
    assert analytics["phase5"]["hold"] == 1
    assert analytics["phase5"]["approve"] == 1

    hold_codes = {item["code"] for item in analytics["top_hold_reasons"]}
    reject_codes = {item["code"] for item in analytics["top_reject_reasons"]}
    all_codes = {item["code"] for item in analytics["top_reason_codes"]}

    assert "risk_long_text" in hold_codes
    assert "keyword_memory" in reject_codes
    assert "keyword_memory" in all_codes
    assert analytics["actor_breakdown"]["gate"] == 2
    assert analytics["actor_breakdown"]["user"] == 3
    assert analytics["anomalies"]["review_token_mismatch"] == 1
    assert analytics["anomalies"]["hold_cancelled"] == 1
    assert analytics["anomalies"]["legacy_schema"] == 1
    assert analytics["anomalies"]["missing_turn_id"] == 0
    assert analytics["data_quality"]["decision_events_total"] == 7
    assert analytics["data_quality"]["v2_events"] == 6
    assert analytics["data_quality"]["legacy_events"] == 1
    assert analytics["data_quality"]["recommended_baseline_ts"] is not None
    assert dataset["total_samples"] >= 4
    assert dataset["eligible_samples"] >= 3
    assert dataset["high_confidence_samples"] >= 3
    assert dataset["training_ready_samples"] >= 3
    assert dataset["high_confidence_baseline_ts"] is not None
    assert dataset["x_post_status_breakdown"]["posted"] == 1
    assert dataset["join_completeness"]["full_triplet_present"] >= 3
    audit = sr.get_dataset_audit(thread_id=tid)
    assert audit["training_ready_samples"] >= 3
    assert audit["high_confidence_baseline_ts"] is not None
    assert any(item["source"] == "phase5_action" for item in audit["source_audit"])
