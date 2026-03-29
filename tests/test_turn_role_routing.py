import pytest

from backend.core.agent_graph.nodes import depth_selector


@pytest.mark.asyncio
async def test_depth_selector_emits_turn_role(monkeypatch):
    monkeypatch.setattr(
        "backend.core.agent_graph.nodes.routing._run_skeleton_build",
        lambda **kwargs: {
            "focus": "returning_theme",
            "response_intent": "organize",
            "question_intent": None,
            "source": "nia_internal",
            "confidence": 0.8,
            "rule_trace": ["RM1_returning_theme"],
        },
    )
    monkeypatch.setattr(
        "backend.core.agent_graph.nodes.routing._run_turn_role_build",
        lambda **kwargs: {
            "turn_role": "connect",
            "turn_role_source": "skeleton_rule",
        },
    )

    state = {
        "messages": [],
        "has_user_text": True,
        "user_text": "また戻ってきた気がする",
        "safety_route": "safe",
        "safety_text": None,
        "dissonance": 0.0,
        "dissonance_on": False,
        "need_depth1": None,
        "reason_codes": [],
        "draft": None,
        "depth1_text": None,
        "merge_mode": None,
        "final_text": None,
        "confidence": None,
        "confidence_metrics": None,
        "depth_action": None,
        "depth_recommendation_reason": None,
        "thread_id": "nero_meeting_turn_role",
    }

    result = await depth_selector(state)

    assert result["turn_role"] == "connect"
    assert result["turn_role_source"] == "skeleton_rule"
