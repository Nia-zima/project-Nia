from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_tweet_request_becomes_pending_action(monkeypatch):
    from backend.core.agent_graph.nodes import action_processing

    monkeypatch.setattr("backend.services.twitter_client.twitter_client.enabled", True)
    monkeypatch.setattr(
        "backend.services.twitter_client.twitter_client.generate_tweet",
        AsyncMock(return_value="今日は設計の整理が進んだ。"),
    )

    state = {
        "messages": [],
        "thread_id": "default_thread",
        "has_user_text": True,
        "user_text": "この内容でツイートして",
        "safety_route": "safe",
        "safety_text": "",
        "dissonance": 0.1,
        "dissonance_on": False,
        "need_depth1": False,
        "reason_codes": [],
        "draft": None,
        "depth1_text": None,
        "merge_mode": "A",
        "final_text": "この内容でツイートするね",
        "confidence": 0.95,
        "confidence_metrics": {},
        "depth_action": "depth0",
        "depth_recommendation_reason": "High confidence",
        "proposed_actions": None,
        "approved_actions": None,
        "pending_actions": None,
        "rejected_actions": None,
        "action_results": None,
        "selected_depth": 0,
    }

    result = await action_processing(state)

    assert result["approved_actions"] == []
    assert len(result["pending_actions"]) == 1
    assert result["pending_actions"][0]["action_id"] == "post_tweet"
    assert result["pending_actions"][0]["decision"]["requires_confirmation"] is True
    assert result["pending_actions"][0]["payload"]["thread_id"] == "default_thread"
