# tests/test_action_integration.py

import pytest
import json
from backend.core.actions import action_registry
from backend.core.agent_graph.graph import app
from backend.core.agent_graph.state import AgentState


class TestActionIntegration:
    """ActionProcessingノードのLangGraph統合テスト"""

    def test_graph_compiles_with_action_processing(self):
        """アクション処理ノードを含むグラフが正しくコンパイルされる"""
        assert app is not None

        # グラフのノードを確認
        nodes = list(app.nodes.keys())
        assert "action_processing" in nodes

    @pytest.mark.asyncio
    async def test_action_processing_no_actions(self):
        """アクション提案がない場合、何も実行されない"""
        from backend.core.agent_graph.nodes import action_processing

        state: AgentState = {
            "messages": [],
            "has_user_text": True,
            "user_text": "こんにちは",
            "safety_route": "safe",
            "safety_text": "",
            "dissonance": 0.2,
            "dissonance_on": False,
            "need_depth1": False,
            "reason_codes": [],
            "draft": None,
            "depth1_text": None,
            "merge_mode": "A",
            "final_text": "こんにちは！",
            "confidence": 0.8,
            "confidence_metrics": {},
            "depth_action": "depth0",
            "depth_recommendation_reason": "High confidence",
            "proposed_actions": None,
            "approved_actions": None,
            "pending_actions": None,
            "rejected_actions": None,
            "action_results": None,
            "selected_depth": 0,
        }

        result = await action_processing(state)

        assert result["proposed_actions"] == []
        assert result["approved_actions"] == []
        assert result["pending_actions"] == []
        assert result["rejected_actions"] == []

    @pytest.mark.asyncio
    async def test_action_processing_with_memory_save(self):
        """記憶保存アクションが検出され、Depth0ではブロックされる"""
        from backend.core.agent_graph.nodes import action_processing

        state: AgentState = {
            "messages": [],
            "has_user_text": True,
            "user_text": "これを記憶に保存してください",
            "safety_route": "safe",
            "safety_text": "",
            "dissonance": 0.2,
            "dissonance_on": False,
            "need_depth1": False,
            "reason_codes": [],
            "draft": None,
            "depth1_text": None,
            "merge_mode": "A",
            "final_text": "記憶に保存します",
            "confidence": 0.8,
            "confidence_metrics": {},
            "depth_action": "depth0",
            "depth_recommendation_reason": "High confidence",
            "proposed_actions": None,
            "approved_actions": None,
            "pending_actions": None,
            "rejected_actions": None,
            "action_results": None,
            "selected_depth": 0,  # Depth0
        }

        result = await action_processing(state)

        # 記憶保存が提案される
        assert len(result["proposed_actions"]) > 0
        assert result["proposed_actions"][0]["action_id"] == "save_memory"

        # Depth0ではLOWリスクはブロックされる
        assert len(result["rejected_actions"]) > 0

    @pytest.mark.asyncio
    async def test_action_processing_depth1_allows_memory_save(self):
        """Depth1では記憶保存アクションが許可される"""
        from backend.core.agent_graph.nodes import action_processing

        state: AgentState = {
            "messages": [],
            "has_user_text": True,
            "user_text": "これを記憶に保存してください",
            "safety_route": "safe",
            "safety_text": "",
            "dissonance": 0.2,
            "dissonance_on": False,
            "need_depth1": True,
            "reason_codes": [],
            "draft": None,
            "depth1_text": None,
            "merge_mode": "B",
            "final_text": "記憶に保存します",
            "confidence": 0.7,
            "confidence_metrics": {},
            "depth_action": "depth1",
            "depth_recommendation_reason": "Need organization",
            "proposed_actions": None,
            "approved_actions": None,
            "pending_actions": None,
            "rejected_actions": None,
            "action_results": None,
            "selected_depth": 1,  # Depth1
        }

        result = await action_processing(state)

        # 記憶保存が提案される
        assert len(result["proposed_actions"]) > 0
        assert result["proposed_actions"][0]["action_id"] == "save_memory"

        # Depth1 + 確信度0.7では、LOWリスクは許可される
        assert len(result["approved_actions"]) > 0
        assert result["approved_actions"][0]["action_id"] == "save_memory"

    @pytest.mark.asyncio
    async def test_action_processing_search_memory(self):
        """記憶検索アクションはDepth0でも許可される（SAFE）"""
        from backend.core.agent_graph.nodes import action_processing

        state: AgentState = {
            "messages": [],
            "has_user_text": True,
            "user_text": "思い出を検索してください",
            "safety_route": "safe",
            "safety_text": "",
            "dissonance": 0.2,
            "dissonance_on": False,
            "need_depth1": False,
            "reason_codes": [],
            "draft": None,
            "depth1_text": None,
            "merge_mode": "A",
            "final_text": "思い出を検索します",
            "confidence": 0.8,
            "confidence_metrics": {},
            "depth_action": "depth0",
            "depth_recommendation_reason": "High confidence",
            "proposed_actions": None,
            "approved_actions": None,
            "pending_actions": None,
            "rejected_actions": None,
            "action_results": None,
            "selected_depth": 0,  # Depth0
        }

        result = await action_processing(state)

        # 記憶検索が提案される
        assert len(result["proposed_actions"]) > 0
        assert result["proposed_actions"][0]["action_id"] == "search_memory"

        # SAFEリスクなのでDepth0でも許可
        assert len(result["approved_actions"]) > 0
        assert result["approved_actions"][0]["action_id"] == "search_memory"

    @pytest.mark.asyncio
    async def test_action_processing_serializable(self):
        """action_processingの出力はJSONシリアライズ可能"""
        from backend.core.agent_graph.nodes import action_processing

        state: AgentState = {
            "messages": [],
            "has_user_text": True,
            "user_text": "思い出を検索してください",
            "safety_route": "safe",
            "safety_text": "",
            "dissonance": 0.1,
            "dissonance_on": False,
            "need_depth1": False,
            "reason_codes": [],
            "draft": None,
            "depth1_text": None,
            "merge_mode": "A",
            "final_text": "思い出を検索します",
            "confidence": 0.9,
            "confidence_metrics": {},
            "depth_action": "depth0",
            "depth_recommendation_reason": "High confidence",
            "proposed_actions": None,
            "approved_actions": None,
            "pending_actions": None,
            "rejected_actions": None,
            "action_results": None,
            "selected_depth": 0,
        }

        result = await action_processing(state)
        json.dumps(result)  # no exception

    @pytest.mark.asyncio
    async def test_action_processing_payload_isolation(self):
        """Actionレジストリのpayloadが汚染されない"""
        from backend.core.agent_graph.nodes import action_processing

        action = action_registry.get("save_memory")
        assert action is not None
        original_payload = dict(action.payload)

        state: AgentState = {
            "messages": [],
            "has_user_text": True,
            "user_text": "これを記憶に保存してください",
            "safety_route": "safe",
            "safety_text": "",
            "dissonance": 0.2,
            "dissonance_on": False,
            "need_depth1": True,
            "reason_codes": [],
            "draft": None,
            "depth1_text": None,
            "merge_mode": "B",
            "final_text": "記憶に保存します",
            "confidence": 0.7,
            "confidence_metrics": {},
            "depth_action": "depth1",
            "depth_recommendation_reason": "Need organization",
            "proposed_actions": None,
            "approved_actions": None,
            "pending_actions": None,
            "rejected_actions": None,
            "action_results": None,
            "selected_depth": 1,
        }

        await action_processing(state)
        action_after = action_registry.get("save_memory")
        assert action_after is not None
        assert action_after.payload == original_payload


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
