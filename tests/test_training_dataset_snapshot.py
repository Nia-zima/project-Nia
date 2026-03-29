from __future__ import annotations

import json
from datetime import datetime

from backend.core.db import get_conn, init_schema
from backend.services.training_dataset_snapshot import (
    run_daily_training_dataset_snapshot_if_due,
    write_training_dataset_snapshot,
)


def _seed_x_post(
    *,
    proposal_id: str,
    thread_id: str,
    source: str = "phase5_action",
    status: str = "posted",
    created_at: float,
    turn_id: str | None = "turn-1",
    message_id: str | None = "msg-1",
    stream_id: str | None = "stream-1",
) -> None:
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


def setup_function() -> None:
    init_schema()
    conn = get_conn()
    try:
        conn.execute("DELETE FROM events")
        conn.execute("DELETE FROM x_post_proposals")
        conn.execute("DELETE FROM memory_events")
        conn.execute("DELETE FROM telemetry_kv")
    finally:
        conn.close()


def test_write_training_dataset_snapshot_writes_files_and_telemetry(tmp_path) -> None:
    now_dt = datetime.now().astimezone()
    now = now_dt.timestamp()
    thread_id = "snapshot_scope"
    _seed_x_post(
        proposal_id="xp-snapshot-1",
        thread_id=thread_id,
        created_at=now,
    )

    result = write_training_dataset_snapshot(
        thread_id=thread_id,
        snapshot_dir=tmp_path,
    )

    assert result["ok"] is True
    assert result["thread_id"] == thread_id
    assert result["row_count"] == 1
    assert result["training_ready_samples"] == 1
    assert result["high_confidence_baseline_ts"] is not None

    date_slug = now_dt.strftime("%Y-%m-%d")
    snapshot_path = tmp_path / date_slug / f"{thread_id}_training_ready.jsonl"
    latest_path = tmp_path / "latest" / f"{thread_id}_training_ready.jsonl"
    latest_summary_path = tmp_path / "latest" / f"{thread_id}_training_ready.summary.json"

    assert snapshot_path.exists()
    assert latest_path.exists()
    assert latest_summary_path.exists()

    rows = [json.loads(line) for line in latest_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    summary = json.loads(latest_summary_path.read_text(encoding="utf-8"))
    assert len(rows) == 1
    assert rows[0]["sample_id"] == "x_post:xp-snapshot-1"
    assert summary["training_ready_samples"] == 1

    conn = get_conn()
    try:
        kv = {
            row["k"]: row["v"]
            for row in conn.execute(
                "SELECT k, v FROM telemetry_kv WHERE k LIKE ?",
                (f"training_dataset_snapshot:%:{thread_id}",),
            ).fetchall()
        }
    finally:
        conn.close()

    assert kv[f"training_dataset_snapshot:last_status:{thread_id}"] == "ok"
    assert kv[f"training_dataset_snapshot:last_row_count:{thread_id}"] == "1"
    assert kv[f"training_dataset_snapshot:latest_data_path:{thread_id}"] == str(latest_path)
    assert kv[f"training_dataset_snapshot:latest_summary_path:{thread_id}"] == str(latest_summary_path)


def test_run_daily_training_dataset_snapshot_runs_once_then_skips_same_day(tmp_path) -> None:
    now = datetime.now().astimezone()
    thread_id = "snapshot_daily"
    _seed_x_post(
        proposal_id="xp-daily-1",
        thread_id=thread_id,
        created_at=now.timestamp(),
    )

    current_time = now.replace(
        hour=max(now.hour, 4),
        minute=0,
        second=0,
        microsecond=0,
    )

    first = run_daily_training_dataset_snapshot_if_due(
        thread_id=thread_id,
        snapshot_dir=tmp_path,
        current_time=current_time,
    )
    second = run_daily_training_dataset_snapshot_if_due(
        thread_id=thread_id,
        snapshot_dir=tmp_path,
        current_time=current_time,
    )
    forced = run_daily_training_dataset_snapshot_if_due(
        thread_id=thread_id,
        snapshot_dir=tmp_path,
        current_time=current_time,
        force=True,
    )

    assert first["ok"] is True
    assert first["ran"] is True
    assert first["date"] == current_time.strftime("%Y-%m-%d")
    assert second == {
        "ok": True,
        "ran": False,
        "reason": "already_snapshotted_today",
        "date": current_time.strftime("%Y-%m-%d"),
    }
    assert forced["ok"] is True
    assert forced["ran"] is True
