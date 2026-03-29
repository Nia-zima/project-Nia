from unittest.mock import MagicMock

import pytest


def _llm_with_usage(content: str):
    resp = MagicMock()
    resp.content = content
    resp.usage_metadata = {
        "input_tokens": 120,
        "output_tokens": 30,
        "total_tokens": 150,
    }
    resp.response_metadata = {"finish_reason": "stop"}
    resp.additional_kwargs = {}

    class _LLM:
        async def ainvoke(self, _messages):
            return resp

    return _LLM()


@pytest.mark.asyncio
async def test_depth1_records_usage(monkeypatch):
    from backend.core.agent_graph.nodes.depth_nodes import depth1_organize_and_ask

    captured: list[dict] = []
    monkeypatch.setattr(
        "backend.core.agent_graph.nodes.depth_nodes.get_depth_llm",
        lambda **kwargs: _llm_with_usage("静かに整理してみると、まだ保留でよさそう。"),
    )
    monkeypatch.setattr(
        "backend.core.agent_graph.nodes.depth_nodes.record_llm_usage_from_response",
        lambda **kwargs: captured.append(kwargs) or "usage_row",
    )
    monkeypatch.setattr(
        "backend.core.agent_graph.nodes.depth_nodes.settings.DSPY_MODE",
        "disabled",
        raising=False,
    )

    out = await depth1_organize_and_ask({
        "user_text": "今どうしたいか少し曖昧",
        "thread_id": "test_thread_depth1_usage",
        "turn_id": "turn_depth1_usage",
        "messages": [],
        "self_scope": False,
    })

    assert out["depth1_text"]
    assert captured
    row = captured[-1]
    assert row["stage"] == "depth1"
    assert row["model_profile"] == "default"
    assert row["model_provider"] == "local"
    assert row["turn_id"] == "turn_depth1_usage"


@pytest.mark.asyncio
async def test_depth2_reflective_records_usage_with_anthropic_provider(monkeypatch):
    from backend.core.agent_graph.nodes.depth_nodes import depth2_value_align_and_preview

    captured: list[dict] = []
    monkeypatch.setattr(
        "backend.core.agent_graph.nodes.depth_nodes.get_depth_llm",
        lambda **kwargs: _llm_with_usage("今日はなんとなく、そのまま残しておきたい感じがする。"),
    )
    monkeypatch.setattr(
        "backend.core.agent_graph.nodes.depth_nodes.record_llm_usage_from_response",
        lambda **kwargs: captured.append(kwargs) or "usage_row",
    )
    monkeypatch.setattr(
        "backend.core.model_adapter.settings.DEPTH2_PROVIDER",
        "anthropic",
        raising=False,
    )
    monkeypatch.setattr(
        "backend.core.agent_graph.nodes.depth_nodes.settings.ANTHROPIC_MODEL",
        "claude-sonnet-4-6",
        raising=False,
    )

    out = await depth2_value_align_and_preview({
        "user_text": "また戻ってきた感じがする",
        "thread_id": "nero_meeting_usage",
        "turn_id": "turn_depth2_usage",
        "messages": [],
        "depth2_mode": "reflective",
        "confidence": 0.6,
        "confidence_metrics": {"context_coverage": 0.7, "steering_risk": 0.1},
        "dissonance": 0.1,
    })

    assert out["depth2_text"]
    assert captured
    row = captured[-1]
    assert row["stage"] == "depth2"
    assert row["model_profile"] == "depth2_reflective"
    assert row["model_provider"] == "anthropic"
    assert row["model_name"] == "claude-sonnet-4-6"
    assert row["depth2_mode"] == "reflective"
    assert row["turn_id"] == "turn_depth2_usage"
