from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.controllers.api.actions_router import router
from backend.core.db import get_conn, init_schema


@pytest.fixture(autouse=True)
def _setup_db():
    init_schema()
    conn = get_conn()
    try:
        conn.execute("DELETE FROM x_post_proposals")
        conn.execute("DELETE FROM memory_events")
        conn.execute("DELETE FROM events")
        conn.execute("DELETE FROM telemetry_kv")
    finally:
        conn.close()
    yield


def _count_rows(table: str) -> int:
    conn = get_conn()
    try:
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_generate_manual_proposal_persists_pending_row(monkeypatch):
    from backend.services.x_post_service import x_post_service

    monkeypatch.setattr("backend.services.twitter_client.twitter_client.enabled", True)
    monkeypatch.setattr(
        "backend.services.twitter_client.twitter_client.generate_tweet",
        AsyncMock(return_value="今日は設計の整理が進んだ。"),
    )

    proposal = await x_post_service.generate_manual_proposal(
        thread_id="default_thread",
        style="casual",
        task="",
        context="設計を見直した",
    )

    assert proposal["status"] == "proposed"
    assert proposal["tweet_text"] == "今日は設計の整理が進んだ。"
    assert _count_rows("x_post_proposals") == 1


@pytest.mark.asyncio
async def test_approve_proposal_posts_and_records_memory_event(monkeypatch):
    from backend.services.twitter_client import TweetResult
    from backend.services.x_post_service import x_post_service

    monkeypatch.setattr("backend.services.twitter_client.twitter_client.enabled", True)
    monkeypatch.setattr(
        "backend.services.twitter_client.twitter_client.post_tweet",
        AsyncMock(
            return_value=TweetResult(
                success=True,
                tweet_id="12345",
                tweet_text="今日は設計の整理が進んだ。",
                posted_at=time.time(),
            )
        ),
    )

    proposal = await x_post_service.create_proposal(
        thread_id="default_thread",
        turn_id="turn-1",
        message_id="msg-1",
        stream_id="stream-1",
        source="manual_generate",
        candidate_text="今日は設計の整理が進んだ。",
        actor="user",
    )
    result = await x_post_service.approve_proposal(proposal_id=proposal["proposal_id"], actor="user")

    assert result["success"] is True
    assert result["tweet_id"] == "12345"
    assert result["proposal"]["status"] == "posted"

    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT turn_id, message_id, payload_json FROM memory_events WHERE event_type = 'tweet_posted'"
        ).fetchone()
        payload = json.loads(row["payload_json"])
        assert row["turn_id"] == "turn-1"
        assert row["message_id"] == "msg-1"
        assert payload["proposal_id"] == proposal["proposal_id"]
        assert payload["tweet_id"] == "12345"
        assert payload["stream_id"] == "stream-1"
    finally:
        conn.close()


def test_pending_and_approve_routes_use_proposal_id(monkeypatch):
    from backend.services.twitter_client import TweetResult
    from backend.services.x_post_service import x_post_service

    monkeypatch.setattr("backend.services.twitter_client.twitter_client.enabled", True)
    proposal = asyncio.run(
        x_post_service.create_proposal(
            thread_id="default_thread",
            source="manual_generate",
            candidate_text="今日は設計の整理が進んだ。",
            actor="user",
        )
    )
    monkeypatch.setattr(
        "backend.services.twitter_client.twitter_client.post_tweet",
        AsyncMock(
            return_value=TweetResult(
                success=True,
                tweet_id="route-1",
                tweet_text="今日は設計の整理が進んだ。",
                posted_at=time.time(),
            )
        ),
    )

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    pending = client.get("/actions/tweet/pending?thread_id=default_thread")
    assert pending.status_code == 200
    data = pending.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["proposal_id"] == proposal["proposal_id"]

    approve = client.post("/actions/tweet/approve", json={"proposal_id": proposal["proposal_id"]})
    assert approve.status_code == 200
    assert approve.json()["ok"] is True
    assert approve.json()["tweet_id"] == "route-1"


def test_reject_route_marks_proposal_rejected(monkeypatch):
    from backend.services.x_post_service import x_post_service

    monkeypatch.setattr("backend.services.twitter_client.twitter_client.enabled", True)
    proposal = asyncio.run(
        x_post_service.create_proposal(
            thread_id="default_thread",
            source="manual_generate",
            candidate_text="今日は設計の整理が進んだ。",
            actor="user",
        )
    )

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    reject = client.post("/actions/tweet/reject", json={"proposal_id": proposal["proposal_id"]})
    assert reject.status_code == 200
    assert reject.json()["ok"] is True

    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT status FROM x_post_proposals WHERE proposal_id = ?",
            (proposal["proposal_id"],),
        ).fetchone()
        assert row["status"] == "rejected"
    finally:
        conn.close()
