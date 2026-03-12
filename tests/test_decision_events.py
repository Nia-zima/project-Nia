import asyncio

import pytest

from backend.core.agent_stream_handlers import _handle_action_end, _handle_merge_end, _handle_safety_end


class _DummyTelemetry:
    def __init__(self):
        self.calls = []

    async def event(self, thread_id, event_type, payload):
        self.calls.append((thread_id, event_type, payload))


class _DummyCtx:
    def __init__(self):
        self.output_queue = asyncio.Queue()
        self.thread_id = "thread_stats"
        self.turn_id = "turn-1"
        self.ports = {"telemetry": _DummyTelemetry()}
        self.hold_request_sent = False
        self.hold_cancelled_sent = False
        self.prev_review_token = "tok123"
        self.prev_merge_mode = "review:tok123"
        self.current_voice_id = "14"
        self.message_id = "msg-1"
        self.stream_id = "stream-1"
        self.tts_enqueued = False
        self.tts_enqueued_stream_ids = set()
        self.last_tts_task = None
        self.merge_final_text = ""
        self.final_result_emitted = False


@pytest.mark.asyncio
async def test_handle_action_end_emits_standardized_payloads():
    ctx = _DummyCtx()
    data = {
        "output": {
            "proposed_actions": [{"action_id": "search_memory", "name": "Search Memory", "risk_level": "SAFE"}],
            "action_results": [{"action_id": "search_memory", "status": "success", "result": {"ok": True}}],
            "pending_actions": [{
                "pending_id": "p1",
                "action_id": "save_memory",
                "name": "Save Memory",
                "risk_level": "LOW",
                "decision": {"reason": "needs_confirmation", "requires_confirmation": True},
            }],
            "rejected_actions": [{
                "pending_id": "p2",
                "action_id": "post_tweet",
                "name": "Post Tweet",
                "risk_level": "HIGH",
                "reason": "blocked",
            }],
        }
    }

    await _handle_action_end(ctx, data)

    events = []
    while not ctx.output_queue.empty():
        events.append(await ctx.output_queue.get())

    proposed = next(event["payload"] for event in events if event["name"] == "action_proposed")
    approved = next(event["payload"] for event in events if event["name"] == "action_approved")
    blocked = [event["payload"] for event in events if event["name"] == "action_blocked"]

    assert proposed["schema_version"] == "decision_event.v2"
    assert proposed["source"] == "phase5"
    assert proposed["decision"] == "propose"
    assert proposed["actor"] == "gate"
    assert proposed["turn_id"] == "turn-1"
    assert proposed["message_id"] == "msg-1"
    assert proposed["stream_id"] == "stream-1"

    assert approved["schema_version"] == "decision_event.v2"
    assert approved["source"] == "phase5"
    assert approved["decision"] == "approve"
    assert approved["actor"] == "gate"

    assert blocked[0]["decision"] == "hold"
    assert blocked[0]["status"] == "pending_confirmation"
    assert blocked[1]["decision"] == "reject"

    telemetry_calls = ctx.ports["telemetry"].calls
    assert len(telemetry_calls) == 4
    assert all(event_type == "decision_event" for _, event_type, _ in telemetry_calls)


@pytest.mark.asyncio
async def test_handle_merge_end_persists_hold_request_telemetry():
    ctx = _DummyCtx()
    data = {
        "output": {
            "hold_required": True,
            "final_text": "WAIT",
            "review_token": "tok123",
            "hold_kind": "speech_preview",
            "review_pending_actions": [{"kind": "say", "text": "preview"}],
            "reason_codes": ["risk_long_text"],
            "merge_mode": "review:tok123",
        }
    }

    await _handle_merge_end(ctx, data)

    telemetry_calls = ctx.ports["telemetry"].calls
    assert telemetry_calls
    payload = telemetry_calls[-1][2]
    assert payload["source"] == "review_window"
    assert payload["decision"] == "hold"
    assert payload["review_token"] == "tok123"
    assert payload["actor"] == "gate"
    assert payload["turn_id"] == "turn-1"
    assert payload["message_id"] == "msg-1"
    assert payload["stream_id"] == "stream-1"


@pytest.mark.asyncio
async def test_handle_safety_end_persists_hold_cancel_telemetry():
    ctx = _DummyCtx()
    data = {"output": {"reason_codes": ["system_hold_cancelled_new_input"]}}

    await _handle_safety_end(ctx, data)

    telemetry_calls = ctx.ports["telemetry"].calls
    assert telemetry_calls
    payload = telemetry_calls[-1][2]
    assert payload["source"] == "review_window"
    assert payload["decision"] == "cancel"
    assert payload["review_token"] == "tok123"
    assert payload["actor"] == "system"
    assert payload["turn_id"] == "turn-1"
    assert payload["message_id"] == "msg-1"
    assert payload["stream_id"] == "stream-1"
