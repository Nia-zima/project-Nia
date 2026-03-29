from __future__ import annotations

import pytest

from backend.services.agent_orchestrator import DefaultAgentOrchestrator
from backend.services.chat_history_store import chat_history_store


class _RecordingTelemetry:
    def __init__(self) -> None:
        self.calls: list[tuple[str | None, str, dict]] = []

    async def event(self, thread_id: str | None, event_type: str, payload: dict) -> None:
        self.calls.append((thread_id, event_type, dict(payload)))


class _TestModeOrchestrator(DefaultAgentOrchestrator):
    async def stream_chat(
        self,
        *,
        input_text: str,
        thread_id: str,
        voice_id: str,
        image_data: str | None,
        mode: str,
        stream_id: str | None,
        message_id: str | None,
        turn_id: str | None = None,
        test_mode: bool = False,
    ):
        yield {"type": "text", "content": "これはテスト応答です"}
        yield {"type": "done"}


def _make_orchestrator(telemetry: _RecordingTelemetry) -> _TestModeOrchestrator:
    return _TestModeOrchestrator(
        memory=object(),
        thought=object(),
        history=object(),
        inner_monologue=object(),
        tools=object(),
        checkpointer=object(),
        memory_capture=object(),
        capture_builder=object(),
        vector_store=object(),
        telemetry=telemetry,
        tts=object(),
        vision=object(),
    )


@pytest.mark.asyncio
async def test_stream_sse_test_mode_keeps_history_but_skips_telemetry_and_dream(monkeypatch):
    calls: list[dict] = []
    dream_calls = {"count": 0}

    async def _fake_get_next_turn_id(thread_id: str) -> int:
        return 1

    async def _fake_append_message(*, thread_id: str, turn_id: int, role: str, content: dict, attachments: list):
        calls.append(
            {
                "thread_id": thread_id,
                "turn_id": turn_id,
                "role": role,
                "content": content,
                "attachments": attachments,
            }
        )
        return f"id-{len(calls)}"

    def _fake_claim_unread_dream():
        dream_calls["count"] += 1
        return None

    monkeypatch.setattr(chat_history_store, "get_next_turn_id", _fake_get_next_turn_id)
    monkeypatch.setattr(chat_history_store, "append_message", _fake_append_message)
    monkeypatch.setattr("backend.services.dream_store.claim_unread_dream", _fake_claim_unread_dream)

    telemetry = _RecordingTelemetry()
    orch = _make_orchestrator(telemetry)

    events = []
    async for sse in orch.stream_sse(
        input_text="テスト入力",
        thread_id="test_mode_thread",
        voice_id="14",
        image_data=None,
        mode="normal",
        stream_id="s1",
        message_id="m1",
        test_mode=True,
    ):
        events.append(sse)

    assert dream_calls["count"] == 0
    assert telemetry.calls == []
    assert [c["role"] for c in calls] == ["user", "assistant"]
    assert calls[0]["content"]["meta"]["test_mode"] is True
    assert calls[1]["content"]["meta"]["test_mode"] is True
    assert any('"type": "done"' in ev for ev in events)


@pytest.mark.asyncio
async def test_action_processing_skips_side_effects_in_test_mode():
    from backend.core.agent_graph.nodes.actions import action_processing

    result = await action_processing(
        {
            "test_mode": True,
            "selected_depth": 1,
            "confidence": 0.8,
            "final_text": "検索して保存して",
            "user_text": "これをツイートして",
            "thread_id": "test_thread",
        }
    )

    assert result == {
        "proposed_actions": [],
        "approved_actions": [],
        "pending_actions": [],
        "rejected_actions": [],
        "action_results": [],
    }


def test_merge_output_skips_turn_observation_in_test_mode(monkeypatch):
    monkeypatch.setattr(
        "backend.core.agent_graph.nodes.merge.settings",
        type("S", (), {"GUARDRAIL_V2_ENABLED": False, "EXPERIMENT_MODE": True})(),
    )

    called = {"count": 0}

    def _fake_log(*args, **kwargs):
        called["count"] += 1

    monkeypatch.setattr("backend.core.agent_graph.nodes.merge.log_turn_observation", _fake_log)

    from backend.core.agent_graph.nodes.merge import merge_output

    result = merge_output(
        {
            "test_mode": True,
            "draft": "WAIT",
            "depth1_text": "",
            "depth2_text": "",
            "thread_id": "test_thread",
            "dissonance": 0.0,
            "surprise_score": 0.0,
            "selected_depth": 0,
            "reason_codes": [],
            "pending_actions": [],
            "hold_required": False,
        }
    )

    assert result["final_text"] == "WAIT"
    assert called["count"] == 0
