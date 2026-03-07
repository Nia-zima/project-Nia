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
    }
    dummy_app = _DummyApp(values)
    captured = {}

    async def _noop_emit_commit_log(thread_id: str, line: str, **kwargs):
        return None

    async def _fake_s5_commit(state):
        captured["state"] = state
        return {"orchestrator_stage": "S5", "commit_result": {"success": True}}

    monkeypatch.setattr(review_router.workflow, "compile", lambda checkpointer: dummy_app)
    monkeypatch.setattr(review_router.checkpointer_service, "get_async_checkpointer_conn", lambda: _DummyCtx())
    monkeypatch.setattr(review_router, "emit_commit_log", _noop_emit_commit_log)
    monkeypatch.setattr(review_router, "s5_commit", _fake_s5_commit)

    res = asyncio.run(review_router._apply_review("t1", "tok", "approve"))
    assert res.get("ok") is True
    assert res.get("applied") is True

    assert captured["state"]["final_text"] == "承認後の発話"
    assert captured["state"]["hold_required"] is False
    assert captured["state"]["thread_id"] == "t1"

    assert [node for _, node in dummy_app.updates] == ["merge", "s5_commit"]


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
