import pytest

from backend.controllers.api import actions_router


@pytest.mark.asyncio
async def test_list_phase5_pending_combines_review_and_phase5(monkeypatch):
    values = {
        "review_token": "tok",
        "review_pending_actions": [{"kind": "say", "text": "承認待ちプレビュー", "risk": "med"}],
        "pending_actions": [{"action_id": "save_memory", "pending_id": "p1", "name": "Save Memory"}],
        "hold_kind": "speech_preview",
        "hold_required": True,
    }

    async def _fake_load_state(thread_id: str):
        return None, None, values

    monkeypatch.setattr(actions_router, "_load_state", _fake_load_state)

    result = await actions_router.list_phase5_pending_actions(thread_id="thread-1")

    assert result["review_token"] == "tok"
    assert len(result["items"]) == 2
    assert result["items"][0]["kind"] == "say"
    assert result["items"][0]["review_token"] == "tok"
    assert result["items"][1]["action_id"] == "save_memory"


@pytest.mark.asyncio
async def test_list_phase5_pending_legacy_review_state_is_not_duplicated(monkeypatch):
    values = {
        "review_token": "tok",
        "pending_actions": [{"kind": "say", "text": "旧レビュー", "risk": "med"}],
        "hold_kind": "speech_preview",
        "hold_required": True,
    }

    async def _fake_load_state(thread_id: str):
        return None, None, values

    monkeypatch.setattr(actions_router, "_load_state", _fake_load_state)

    result = await actions_router.list_phase5_pending_actions(thread_id="thread-legacy")

    assert result["review_token"] == "tok"
    assert len(result["items"]) == 1
    assert result["items"][0]["kind"] == "say"
    assert result["items"][0]["review_token"] == "tok"
