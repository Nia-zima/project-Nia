from unittest.mock import MagicMock

import pytest


def _capturing_llm(calls: list[str], content: str = "静かに受け取ってる。"):
    mock_resp = MagicMock()
    mock_resp.content = content
    mock_resp.additional_kwargs = {}
    mock_resp.response_metadata = {}

    class _LLM:
        async def ainvoke(self, messages):
            calls.append(str(messages[0].content))
            return mock_resp

    return _LLM()


@pytest.mark.asyncio
async def test_depth1_meeting_turn_role_injects_prompt_hint(monkeypatch):
    from backend.core.agent_graph.nodes.depth_nodes import depth1_organize_and_ask

    calls: list[str] = []
    monkeypatch.setattr(
        "backend.core.agent_graph.nodes.depth_nodes.get_depth_llm",
        lambda **kwargs: _capturing_llm(calls),
    )
    monkeypatch.setattr(
        "backend.core.agent_graph.nodes.depth_nodes.settings.DSPY_MODE",
        "disabled",
        raising=False,
    )

    state = {
        "user_text": "また戻ってきた感じがする",
        "thread_id": "nero_meeting_prompt_role",
        "messages": [],
        "self_scope": False,
        "turn_role": "connect",
    }
    out = await depth1_organize_and_ask(state)

    assert out["depth1_text"]
    assert calls
    prompt = calls[-1]
    assert "=== TURN ROLE HINT ===" in prompt
    assert "current_turn_role: connect" in prompt
    assert "つながりを一つだけ示す" in prompt


@pytest.mark.asyncio
async def test_depth1_default_thread_does_not_inject_turn_role_hint(monkeypatch):
    from backend.core.agent_graph.nodes.depth_nodes import depth1_organize_and_ask

    calls: list[str] = []
    monkeypatch.setattr(
        "backend.core.agent_graph.nodes.depth_nodes.get_depth_llm",
        lambda **kwargs: _capturing_llm(calls),
    )
    monkeypatch.setattr(
        "backend.core.agent_graph.nodes.depth_nodes.settings.DSPY_MODE",
        "disabled",
        raising=False,
    )

    state = {
        "user_text": "今日はどうしよう",
        "thread_id": "default_thread",
        "messages": [],
        "self_scope": False,
        "turn_role": "connect",
    }
    await depth1_organize_and_ask(state)

    assert calls
    prompt = calls[-1]
    assert "=== TURN ROLE HINT ===" not in prompt


@pytest.mark.asyncio
async def test_depth2_meeting_turn_role_injects_prompt_hint(monkeypatch):
    from backend.core.agent_graph.nodes.depth_nodes import depth2_value_align_and_preview

    calls: list[str] = []
    monkeypatch.setattr(
        "backend.core.agent_graph.nodes.depth_nodes.get_depth_llm",
        lambda **kwargs: _capturing_llm(calls, content="静かなまま繋がってる気がする。"),
    )

    state = {
        "user_text": "また戻ってきた感じがする",
        "thread_id": "nero_meeting_prompt_role",
        "messages": [],
        "turn_role": "ask",
        "depth2_mode": "reflective",
        "confidence": 0.6,
        "confidence_metrics": {"context_coverage": 0.7, "steering_risk": 0.1},
        "dissonance": 0.1,
    }
    out = await depth2_value_align_and_preview(state)

    assert out["depth2_text"]
    assert calls
    prompt = calls[-1]
    assert "=== TURN ROLE HINT ===" in prompt
    assert "current_turn_role: ask" in prompt
    assert "開いた問いを一つだけ置く" in prompt


@pytest.mark.asyncio
async def test_depth2_risk_does_not_inject_turn_role_hint(monkeypatch):
    from backend.core.agent_graph.nodes.depth_nodes import depth2_value_align_and_preview

    calls: list[str] = []
    monkeypatch.setattr(
        "backend.core.agent_graph.nodes.depth_nodes.get_depth_llm",
        lambda **kwargs: _capturing_llm(calls, content="1) いまの見立て: まだ保留\n2) 迷っている点: 判断材料が足りない\n3) 暫定方針: まずは保留\n4) 確認したいこと: どこを優先する？"),
    )

    state = {
        "user_text": "配信で今後の呼び方と方針を決めたい",
        "thread_id": "nero_meeting_prompt_role",
        "messages": [],
        "turn_role": "ask",
        "depth2_mode": "risk",
        "confidence": 0.6,
        "confidence_metrics": {"context_coverage": 0.7, "steering_risk": 0.4},
        "dissonance": 0.4,
    }
    out = await depth2_value_align_and_preview(state)

    assert out["depth2_text"]
    assert calls
    prompt = calls[-1]
    assert "=== TURN ROLE HINT ===" not in prompt


@pytest.mark.asyncio
async def test_depth2_risk_fallback_does_not_inject_turn_role_hint(monkeypatch):
    from backend.core.agent_graph.nodes.depth_nodes import _depth1_fallback

    calls: list[str] = []
    monkeypatch.setattr(
        "backend.core.agent_graph.nodes.depth_nodes.get_depth_llm",
        lambda **kwargs: _capturing_llm(calls, content="整理してみると、まだ保留でよさそう。"),
    )

    state = {
        "user_text": "配信で今後の呼び方と方針を決めたい",
        "thread_id": "nero_meeting_prompt_role",
        "messages": [],
        "turn_role": "ask",
        "depth2_mode": "risk",
    }
    text = await _depth1_fallback(state)

    assert text
    assert calls
    prompt = calls[-1]
    assert "=== TURN ROLE HINT ===" not in prompt
