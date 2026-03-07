import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from backend.core.agent_graph.review_window import (
    apply_review_decision,
    cancel_review_on_new_input,
    build_hold_request_event,
    get_review_token,
)
from backend.core.agent_graph.nodes import merge_output
from backend.controllers.api import review_router
from backend.services.agent_orchestrator import _should_emit_text_event


def test_review_token_mismatch_ignored():
    state = {
        "merge_mode": "review:expected_token",
        "draft": "hello",
        "reason_codes": [],
    }
    out = apply_review_decision(state, token="wrong_token", decision="approve")
    assert "final_text" not in out
    assert "merge_mode" not in out
    assert not out


def test_cancel_on_new_user_input():
    state = {
        "merge_mode": "review:pending_token",
        "reason_codes": [],
    }
    out = cancel_review_on_new_input(state, user_text="new input")
    assert out.get("final_text") == "WAIT"
    assert out.get("merge_mode") == "wait"
    assert "system_hold_cancelled_new_input" in (out.get("reason_codes") or [])
    merged = dict(state)
    merged.update(out)
    assert get_review_token(merged) is None


def test_hold_opens_review_token_and_wait(monkeypatch):
    from backend.core import config as _cfg
    monkeypatch.setattr(_cfg.settings, "HOLD_POLICY", "strict")
    state = {
        "safety_route": "safe",
        "draft": "hello",
        "depth1_text": "",
        "dissonance_on": True,
        "need_depth1": False,
        "user_text": "short input",
        "reason_codes": [],
    }
    out = merge_output(state)
    assert out.get("final_text") == "WAIT"
    assert isinstance(out.get("merge_mode"), str)
    merged = dict(state)
    merged.update(out)
    assert get_review_token(merged)


def test_hold_request_event_includes_token():
    update = {
        "review_token": "abc123",
        "hold_kind": "speech_preview",
        "pending_actions": [{"kind": "say", "text": "preview", "risk": "med"}],
        "reason_codes": ["risk_dissonance_on"],
    }
    ev = build_hold_request_event(update)
    assert ev and ev.get("name") == "hold_request"
    payload = ev.get("payload") or {}
    assert payload.get("review_token") == "abc123"
    assert payload.get("hold_kind") == "speech_preview"
    assert payload.get("preview_text") == "preview"
    pending = payload.get("pending_actions") or []
    assert pending and pending[0].get("kind") == "say"


def test_commit_log_emitted_on_approve():
    line = review_router.build_commit_log_line(
        say_applied=1,
        rejected=0,
        before_d=0.12,
        after_d=0.12,
        hold="ask",
        reasons=["system_review_window"],
    )
    assert "say:1" in line
    assert "rejected:0" in line
    assert "hold:ask" in line

    calls = []

    class _TelemetryStub:
        async def event(self, thread_id, event_type, payload=None):
            calls.append((thread_id, event_type, payload))

    async def _run():
        await review_router.emit_commit_log("t1", line, telemetry_sink=_TelemetryStub())

    import asyncio

    asyncio.run(_run())
    assert len(calls) == 1
    assert calls[0][1] == "commit_log"


def test_wait_passthrough_reason():
    state = {
        "safety_route": "safe",
        "draft": "WAIT",
        "depth1_text": "",
        "dissonance_on": False,
        "need_depth1": False,
        "user_text": "short input",
        "reason_codes": [],
    }
    out = merge_output(state)
    assert out.get("final_text") == "WAIT"
    assert "system_wait_passthrough" in (out.get("reason_codes") or [])


def test_long_text_triggers_hold(monkeypatch):
    from backend.core import config as _cfg
    monkeypatch.setattr(_cfg.settings, "HOLD_POLICY", "strict")
    state = {
        "safety_route": "safe",
        "draft": "短い返答",
        "depth1_text": "",
        "dissonance_on": False,
        "need_depth1": False,
        "user_text": "a" * 130,
        "reason_codes": [],
    }
    out = merge_output(state)
    assert out.get("final_text") == "WAIT"
    assert "review:" in (out.get("merge_mode") or "")
    assert "risk_long_text" in (out.get("reason_codes") or [])


def test_keyword_triggers_hold(monkeypatch):
    from backend.core import config as _cfg
    monkeypatch.setattr(_cfg.settings, "HOLD_POLICY", "strict")
    state = {
        "safety_route": "safe",
        "draft": "わかったよ",
        "depth1_text": "",
        "dissonance_on": False,
        "need_depth1": False,
        "user_text": "これ覚えておいて",
        "reason_codes": [],
    }
    out = merge_output(state)
    assert out.get("final_text") == "WAIT"
    assert "keyword_memory" in (out.get("reason_codes") or [])


def test_review_token_mismatch_logs_reason():
    calls = []

    class _TelemetryStub:
        async def event(self, thread_id, event_type, payload=None):
            calls.append((thread_id, event_type, payload))

    class _DummyState:
        def __init__(self, values):
            self.values = values

    class _DummyApp:
        def __init__(self, values):
            self._values = values
            self.updated = None

        async def aget_state(self, config):
            return _DummyState(self._values)

        async def aupdate_state(self, config, update, as_node=None):
            self.updated = update

    class _DummyCtx:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    values = {"merge_mode": "review:expected", "dissonance": 0.12}
    dummy_app = _DummyApp(values)

    from unittest import mock

    with mock.patch.object(review_router, "telemetry", _TelemetryStub()):
        with mock.patch.object(review_router.workflow, "compile", lambda checkpointer: dummy_app):
            with mock.patch.object(review_router.checkpointer_service, "get_async_checkpointer_conn", lambda: _DummyCtx()):
                import asyncio
                res = asyncio.run(review_router._apply_review("t1", "wrong_token", "approve"))
                assert res.get("reason") == "token_mismatch"

    assert calls
    assert any("system_review_token_mismatch" in (c[2] or {}).get("line", "") for c in calls)


def test_reject_increases_dissonance_and_wait():
    state = {
        "merge_mode": "review:tok",
        "draft": "preview",
        "dissonance": 0.1,
        "reason_codes": [],
    }
    out = apply_review_decision(state, token="tok", decision="reject")
    assert out.get("final_text") == "WAIT"
    assert out.get("dissonance") and out.get("dissonance") > 0.1


def test_text_event_final_flag_behavior():
    assert _should_emit_text_event({"type": "text", "content": "a"}) is True
    assert _should_emit_text_event({"type": "text", "content": "a", "final": True}) is True
    assert _should_emit_text_event({"type": "text", "content": "a", "final": False}) is False
