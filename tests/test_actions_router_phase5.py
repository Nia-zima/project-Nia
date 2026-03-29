import pytest

from backend.controllers.api import actions_router
from backend.core.agent_graph.state_normalizer import normalize_checkpoint_state


class _DummyPhase5App:
    def __init__(self):
        self.updates = []

    async def aupdate_state(self, config, update, as_node=None):
        self.updates.append((dict(update), as_node))


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
        return None, None, normalize_checkpoint_state(values)

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
        return None, None, normalize_checkpoint_state(values)

    monkeypatch.setattr(actions_router, "_load_state", _fake_load_state)

    result = await actions_router.list_phase5_pending_actions(thread_id="thread-legacy")

    assert result["review_token"] == "tok"
    assert len(result["items"]) == 1
    assert result["items"][0]["kind"] == "say"
    assert result["items"][0]["review_token"] == "tok"


@pytest.mark.asyncio
async def test_reject_phase5_action_keeps_review_rejections_separate_and_emits_decision_event(monkeypatch):
    app = _DummyPhase5App()
    values = {
        "pending_actions": [{
            "action_id": "search_memory",
            "pending_id": "p1",
            "name": "Search Memory",
            "turn_id": "turn-1",
            "message_id": "msg-1",
            "stream_id": "stream-1",
        }],
        "review_rejected_actions": [{"kind": "say", "text": "旧プレビュー", "token": "tok"}],
        "rejected_actions": [],
    }
    telemetry_calls = []

    async def _fake_load_state(thread_id: str):
        return app, {"configurable": {"thread_id": thread_id}}, values

    async def _fake_telemetry_event(thread_id: str, event_type: str, payload: dict):
        telemetry_calls.append((thread_id, event_type, payload))

    monkeypatch.setattr(actions_router, "_load_state", _fake_load_state)
    monkeypatch.setattr(actions_router.telemetry, "event", _fake_telemetry_event)

    result = await actions_router.reject_phase5_action(
        "search_memory",
        actions_router.Phase5ActionDecisionRequest(thread_id="thread-1", pending_id="p1", reason="user_rejected"),
    )

    assert result == {"ok": True}
    assert app.updates[-1][0]["pending_actions"] == []
    assert len(app.updates[-1][0]["rejected_actions"]) == 1
    assert "review_rejected_actions" not in app.updates[-1][0]
    decision_events = [payload for _, event_type, payload in telemetry_calls if event_type == "decision_event"]
    assert decision_events and decision_events[-1]["decision"] == "reject"
    assert decision_events[-1]["source"] == "phase5"
    assert decision_events[-1]["actor"] == "user"
    assert decision_events[-1]["turn_id"] == "turn-1"
    assert decision_events[-1]["message_id"] == "msg-1"
    assert decision_events[-1]["stream_id"] == "stream-1"


@pytest.mark.asyncio
async def test_approve_phase5_action_emits_decision_event(monkeypatch):
    app = _DummyPhase5App()
    values = {
        "pending_actions": [{
            "action_id": "search_memory",
            "pending_id": "p1",
            "name": "Search Memory",
            "payload": {},
            "turn_id": "turn-1",
            "message_id": "msg-1",
            "stream_id": "stream-1",
        }],
        "approved_actions": [],
        "action_results": [],
    }
    telemetry_calls = []

    async def _fake_load_state(thread_id: str):
        return app, {"configurable": {"thread_id": thread_id}}, values

    async def _fake_execute(action_instance):
        return {"status": "ok"}

    async def _fake_telemetry_event(thread_id: str, event_type: str, payload: dict):
        telemetry_calls.append((thread_id, event_type, payload))

    monkeypatch.setattr(actions_router, "_load_state", _fake_load_state)
    monkeypatch.setattr(actions_router.action_executor, "execute", _fake_execute)
    monkeypatch.setattr(actions_router.telemetry, "event", _fake_telemetry_event)

    result = await actions_router.approve_phase5_action(
        "search_memory",
        actions_router.Phase5ActionDecisionRequest(thread_id="thread-1", pending_id="p1"),
    )

    assert result["ok"] is True
    decision_events = [payload for _, event_type, payload in telemetry_calls if event_type == "decision_event"]
    assert decision_events and decision_events[-1]["decision"] == "approve"
    assert decision_events[-1]["source"] == "phase5"
    assert decision_events[-1]["actor"] == "user"
    assert decision_events[-1]["turn_id"] == "turn-1"
    assert decision_events[-1]["message_id"] == "msg-1"
    assert decision_events[-1]["stream_id"] == "stream-1"
