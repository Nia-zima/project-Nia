from __future__ import annotations

import pytest

from backend.services.agent_orchestrator import DefaultAgentOrchestrator
from backend.services.chat_history_store import chat_history_store


class _NoopTelemetry:
    async def event(self, thread_id: str, event_type: str, payload: dict) -> None:
        return None


class _FailingStreamOrchestrator(DefaultAgentOrchestrator):
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
    ):
        yield {"type": "text", "content": "これは保存されるべき応答"}
        raise RuntimeError("client disconnected")


@pytest.mark.asyncio
async def test_stream_error_still_saves_assistant_message(monkeypatch):
    calls: list[dict] = []

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

    monkeypatch.setattr(chat_history_store, "get_next_turn_id", _fake_get_next_turn_id)
    monkeypatch.setattr(chat_history_store, "append_message", _fake_append_message)

    orch = _FailingStreamOrchestrator(
        memory=object(),
        thought=object(),
        history=object(),
        inner_monologue=object(),
        tools=object(),
        checkpointer=object(),
        memory_capture=object(),
        capture_builder=object(),
        vector_store=object(),
        telemetry=_NoopTelemetry(),
        tts=object(),
        vision=object(),
    )

    events = []
    async for sse in orch.stream_sse(
        input_text="テスト入力",
        thread_id="test_thread",
        voice_id="14",
        image_data=None,
        mode="normal",
        stream_id="s1",
        message_id="m1",
    ):
        events.append(sse)

    assistant_calls = [c for c in calls if c["role"] == "assistant"]
    assert assistant_calls, "stream_error時でもassistantメッセージを保存する必要がある"
    saved = assistant_calls[-1]
    assert saved["thread_id"] == "test_thread"
    assert "保存されるべき応答" in str(saved["content"].get("text") or "")
    assert saved["content"].get("meta", {}).get("error") is True
    assert any('"type": "done"' in ev for ev in events)
