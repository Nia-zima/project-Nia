import asyncio

import pytest

from backend.controllers.api import review_router
from backend.core.db import get_conn, init_schema


class _DummyState:
    def __init__(self, values):
        self.values = values


class _DummyApp:
    def __init__(self, values):
        self._values = values
        self.updates = []

    async def aget_state(self, config):
        return _DummyState(self._values)

    async def aupdate_state(self, config, update, as_node=None):
        self.updates.append((update, as_node))


class _DummyCtx:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.fixture(autouse=True)
def _setup_db():
    init_schema()
    conn = get_conn()
    try:
        conn.execute("DELETE FROM memory_index")
        conn.execute("DELETE FROM memory_events")
        conn.execute("DELETE FROM semantic_memories")
        conn.execute("DELETE FROM working_items")
        conn.commit()
    finally:
        conn.close()
    yield


def test_apply_review_approve_runs_s5_commit(monkeypatch):
    values = {
        "merge_mode": "review:tok",
        "review_token": "tok",
        "review_pending_actions": [{"kind": "say", "text": "承認後の発話", "risk": "med"}],
        "reason_codes": ["keyword_memory"],
        "dissonance": 0.10,
        "user_text": "Originはコーヒーが好き",
        "hold_required": True,
        "turn_id": "turn-1",
        "message_id": "msg-1",
        "stream_id": "stream-1",
    }
    dummy_app = _DummyApp(values)
    captured = {}
    telemetry_calls = []

    async def _noop_emit_commit_log(thread_id: str, line: str, **kwargs):
        return None

    async def _fake_s5_commit(state):
        captured["state"] = state
        return {"orchestrator_stage": "S5", "commit_result": {"success": True}}

    async def _fake_telemetry_event(thread_id: str, event_type: str, payload: dict):
        telemetry_calls.append((thread_id, event_type, payload))

    monkeypatch.setattr(review_router.workflow, "compile", lambda checkpointer: dummy_app)
    monkeypatch.setattr(review_router.checkpointer_service, "get_async_checkpointer_conn", lambda: _DummyCtx())
    monkeypatch.setattr(review_router, "emit_commit_log", _noop_emit_commit_log)
    monkeypatch.setattr(review_router, "s5_commit", _fake_s5_commit)
    monkeypatch.setattr(review_router.telemetry, "event", _fake_telemetry_event)

    res = asyncio.run(review_router._apply_review("t1", "tok", "approve"))
    assert res.get("ok") is True
    assert res.get("applied") is True

    assert captured["state"]["final_text"] == "承認後の発話"
    assert captured["state"]["hold_required"] is False
    assert captured["state"]["thread_id"] == "t1"

    assert [node for _, node in dummy_app.updates] == ["merge", "s5_commit"]
    decision_events = [payload for _, event_type, payload in telemetry_calls if event_type == "decision_event"]
    assert decision_events and decision_events[-1]["decision"] == "approve"
    assert decision_events[-1]["source"] == "review_window"
    assert decision_events[-1]["actor"] == "user"
    assert decision_events[-1]["turn_id"] == "turn-1"
    assert decision_events[-1]["message_id"] == "msg-1"
    assert decision_events[-1]["stream_id"] == "stream-1"


def test_apply_review_approve_persists_memory_events(monkeypatch):
    values = {
        "merge_mode": "review:tok",
        "review_token": "tok",
        "review_pending_actions": [{"kind": "say", "text": "承認後の発話", "risk": "med"}],
        "reason_codes": ["keyword_memory"],
        "dissonance": 0.10,
        "user_text": "Originはコーヒーが好き",
        "hold_required": True,
        "thread_id": "t1",
    }
    dummy_app = _DummyApp(values)

    async def _noop_emit_commit_log(thread_id: str, line: str, **kwargs):
        return None

    monkeypatch.setattr(
        "backend.core.agent_graph.nodes.settings.ORCHESTRATOR_S5_ENABLED",
        True,
    )
    monkeypatch.setattr(review_router.workflow, "compile", lambda checkpointer: dummy_app)
    monkeypatch.setattr(review_router.checkpointer_service, "get_async_checkpointer_conn", lambda: _DummyCtx())
    monkeypatch.setattr(review_router, "emit_commit_log", _noop_emit_commit_log)

    res = asyncio.run(review_router._apply_review("t1", "tok", "approve"))
    assert res.get("ok") is True
    assert res.get("applied") is True

    conn = get_conn()
    try:
        events = conn.execute(
            "SELECT event_type, payload_json FROM memory_events WHERE thread_id=? ORDER BY created_at DESC",
            ("t1",),
        ).fetchall()
        assert events, "approve後にmemory_eventsが永続化されていない"
        assert any(row["event_type"] == "conversation_turn" for row in events)
    finally:
        conn.close()


def test_build_commit_log_payload_is_structured():
    payload = review_router.build_commit_log_payload(
        say_applied=1,
        rejected=0,
        before_d=0.1,
        after_d=0.1,
        hold="ask",
        reasons=["keyword_memory"],
        decision="approve",
        actor="user",
        review_token="tok",
        thread_id="t1",
        turn_id="turn-1",
        message_id="msg-1",
        stream_id="stream-1",
        ts=123.0,
    )

    assert payload["schema_version"] == "commit_log.v2"
    assert payload["line"].startswith("[COMMIT]")
    assert payload["decision"] == "approve"
    assert payload["actor"] == "user"
    assert payload["review_token"] == "tok"
    assert payload["thread_id"] == "t1"
    assert payload["turn_id"] == "turn-1"
    assert payload["message_id"] == "msg-1"
    assert payload["stream_id"] == "stream-1"
    assert payload["reason_codes"] == ["keyword_memory"]
