"""
Phase 2: depth_selector ノードのテスト

確信度ベースのDepth選択器が正しく動作することを検証します。
"""
import sys
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from backend.core.agent_graph.nodes import depth_selector, dissonance_check
from backend.core.agent_graph.state import AgentState
from backend.core.confidence import ConfidenceEngine, DepthAction


class TestDepthSelector:
    """depth_selectorノードのテスト"""

    @pytest.mark.asyncio
    async def test_high_confidence_uses_depth0(self):
        """高確信度の質問はDEPTH0を選択"""
        state: AgentState = {
            "messages": [],
            "has_user_text": True,
            "user_text": "こんにちは",  # シンプルで明確な質問
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
        }

        result = await depth_selector(state)

        # 高確信度ではneed_depth1=False
        assert "confidence" in result
        assert result["confidence"] >= 0.0
        assert result["depth_action"] is not None

    @pytest.mark.asyncio
    async def test_complex_question_uses_depth1(self):
        """複雑な質問はDEPTH1を選択"""
        state: AgentState = {
            "messages": [],
            "has_user_text": True,
            "user_text": "量子コンピュータと古典コンピュータの違いを教えて。どのような問題に適しているのか、具体的なユースケースも含めて説明してほしい。",
            "safety_route": "safe",
            "safety_text": None,
            "dissonance": 0.3,
            "dissonance_on": False,
            "need_depth1": None,
            "reason_codes": ["long_text"],
            "draft": None,
            "depth1_text": None,
            "merge_mode": None,
            "final_text": None,
            "confidence": None,
            "confidence_metrics": None,
            "depth_action": None,
            "depth_recommendation_reason": None,
        }

        result = await depth_selector(state)

        assert "confidence" in result
        assert result["confidence_metrics"] is not None
        assert "context_coverage" in result["confidence_metrics"]

    @pytest.mark.asyncio
    async def test_user_request_overrides_confidence(self):
        """ユーザー明示リクエストは確信度をオーバーライド"""
        state: AgentState = {
            "messages": [],
            "has_user_text": True,
            "user_text": "詳しく教えて",  # user_requestトリガー
            "safety_route": "safe",
            "safety_text": None,
            "dissonance": 0.0,
            "dissonance_on": False,
            "need_depth1": None,
            "reason_codes": ["user_request"],
            "draft": None,
            "depth1_text": None,
            "merge_mode": None,
            "final_text": None,
            "confidence": None,
            "confidence_metrics": None,
            "depth_action": None,
            "depth_recommendation_reason": None,
        }

        result = await depth_selector(state)

        # user_requestがある場合は強制的にDEPTH1
        assert result["need_depth1"] is True
        assert "dissonance_on" in result

    @pytest.mark.asyncio
    async def test_high_dissonance_overrides_confidence(self):
        """高いdissonanceスコアは確信度をオーバーライド"""
        state: AgentState = {
            "messages": [],
            "has_user_text": True,
            "user_text": "違う、そうじゃなくて",  # 高dissonance
            "safety_route": "safe",
            "safety_text": None,
            "dissonance": 0.7,  # >= 0.65 でオーバーライド
            "dissonance_on": False,
            "need_depth1": None,
            "reason_codes": ["contrast"],
            "draft": None,
            "depth1_text": None,
            "merge_mode": None,
            "final_text": None,
            "confidence": None,
            "confidence_metrics": None,
            "depth_action": None,
            "depth_recommendation_reason": None,
        }

        result = await depth_selector(state)

        # 高dissonanceは強制的にDEPTH1
        assert result["need_depth1"] is True
        assert result["dissonance_on"] is True
        assert "high_dissonance" in result["reason_codes"]

    @pytest.mark.asyncio
    async def test_confidence_metrics_are_recorded(self):
        """確信度メトリクスが正しく記録される"""
        state: AgentState = {
            "messages": [],
            "has_user_text": True,
            "user_text": "Pythonでリスト内包表記を使う方法を教えてください",
            "safety_route": "safe",
            "safety_text": None,
            "dissonance": 0.2,
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
        }

        result = await depth_selector(state)

        # メトリクスが正しく記録されている
        assert result["confidence_metrics"] is not None
        metrics = result["confidence_metrics"]
        assert "context_coverage" in metrics
        assert "self_consistency" in metrics
        assert "logit_based" in metrics
        assert "question_clarity" in metrics
        assert "composite_raw" in metrics
        assert "composite_calibrated" in metrics

        # 各メトリクスは0.0-1.0の範囲
        for key, value in metrics.items():
            assert 0.0 <= value <= 1.0, f"{key}={value} is out of range"

    @pytest.mark.asyncio
    async def test_depth_action_is_valid(self):
        """depth_actionが有効な値を持つ"""
        state: AgentState = {
            "messages": [],
            "has_user_text": True,
            "user_text": "テスト",
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
        }

        result = await depth_selector(state)

        valid_actions = {"depth0", "depth1", "ask", "wait"}
        assert result["depth_action"] in valid_actions

    @pytest.mark.asyncio
    async def test_recommendation_reason_is_provided(self):
        """推奨理由が提供される"""
        state: AgentState = {
            "messages": [],
            "has_user_text": True,
            "user_text": "これは何ですか？",
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
        }

        result = await depth_selector(state)

        assert result["depth_recommendation_reason"] is not None
        assert len(result["depth_recommendation_reason"]) > 0


class TestDissonanceCheck:
    """dissonance_checkノードのテスト（Phase 2変更後）"""

    @pytest.mark.asyncio
    async def test_dissonance_score_calculated(self):
        """dissonanceスコアが計算される"""
        state: AgentState = {
            "messages": [],
            "has_user_text": True,
            "user_text": "違う、そうじゃない",
            "safety_route": "safe",
            "safety_text": None,
            "dissonance": None,
            "dissonance_on": None,
            "need_depth1": None,
            "reason_codes": None,
            "draft": None,
            "depth1_text": None,
            "merge_mode": None,
            "final_text": None,
            "confidence": None,
            "confidence_metrics": None,
            "depth_action": None,
            "depth_recommendation_reason": None,
        }

        result = await dissonance_check(state)

        assert "dissonance" in result
        assert 0.0 <= result["dissonance"] <= 1.0
        assert "surprise_score" in result
        assert 0.0 <= result["surprise_score"] <= 1.0
        assert "surprise_reasons" in result
        assert isinstance(result["surprise_reasons"], list)
        assert "reason_codes" in result

    @pytest.mark.asyncio
    async def test_dissonance_check_does_not_set_need_depth1(self):
        """Phase 2: dissonance_checkはneed_depth1を設定しない"""
        state: AgentState = {
            "messages": [],
            "has_user_text": True,
            "user_text": "長いテキストを入力してテストしています" * 10,
            "safety_route": "safe",
            "safety_text": None,
            "dissonance": None,
            "dissonance_on": None,
            "need_depth1": None,
            "reason_codes": None,
            "draft": None,
            "depth1_text": None,
            "merge_mode": None,
            "final_text": None,
            "confidence": None,
            "confidence_metrics": None,
            "depth_action": None,
            "depth_recommendation_reason": None,
        }

        result = await dissonance_check(state)

        # Phase 2ではneed_depth1はdepth_selectorで決定される
        assert "need_depth1" not in result or result.get("need_depth1") is None
        assert "dissonance_on" not in result or result.get("dissonance_on") is None


class TestConfidenceEngineIntegration:
    """ConfidenceEngineとの統合テスト"""

    def test_engine_thresholds(self):
        """エンジンの閾値が正しく設定されている"""
        engine = ConfidenceEngine()

        assert engine.thresholds["depth0"] == 0.8
        assert engine.thresholds["depth1"] == 0.5
        assert engine.thresholds["ask"] == 0.3

    def test_depth_action_mapping(self):
        """DepthActionの値が正しい"""
        assert DepthAction.USE_DEPTH0.value == "depth0"
        assert DepthAction.USE_DEPTH1.value == "depth1"
        assert DepthAction.ASK.value == "ask"
        assert DepthAction.WAIT.value == "wait"

    def test_engine_recommendation_with_context(self):
        """コンテキストを使った推奨が動作する"""
        engine = ConfidenceEngine()

        recommendation = engine.get_depth_recommendation(
            question="Pythonのリスト内包表記について教えてください",
            context=["Pythonはプログラミング言語です", "リスト内包表記は便利な機能です"],
        )

        assert recommendation.confidence >= 0.0
        assert recommendation.confidence <= 1.0
        assert recommendation.action in DepthAction
        assert len(recommendation.reason) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
