# tests/test_action_gate.py

import pytest
from backend.core.actions import (
    Action,
    ActionCategory,
    ActionDecision,
    RiskLevel,
    ActionGate,
    ActionRegistry,
    action_gate,
    action_registry,
)


class TestActionTypes:
    """Action型のテスト"""

    def test_action_creation(self):
        """Actionオブジェクトの作成"""
        action = Action(
            id="test_action",
            name="テストアクション",
            category=ActionCategory.MEMORY,
            risk_level=RiskLevel.LOW,
            description="テスト用のアクション",
            payload={"key": "value"},
        )

        assert action.id == "test_action"
        assert action.name == "テストアクション"
        assert action.risk_score == 0.3
        assert not action.requires_confirmation

    def test_risk_levels(self):
        """リスクレベルの値"""
        assert RiskLevel.SAFE.value == 0.0
        assert RiskLevel.LOW.value == 0.3
        assert RiskLevel.MEDIUM.value == 0.6
        assert RiskLevel.HIGH.value == 0.8
        assert RiskLevel.CRITICAL.value == 1.0


class TestActionGate:
    """ActionGateのテスト"""

    def setup_method(self):
        """テストの前処理"""
        self.gate = ActionGate()

    def test_depth0_safe_action(self):
        """Depth0でSAFEアクションは許可される"""
        action = Action(
            id="test_safe",
            name="安全なアクション",
            category=ActionCategory.MEMORY,
            risk_level=RiskLevel.SAFE,
            description="読み取り専用",
            payload={},
        )

        decision = self.gate.request_action(action, depth=0, confidence=0.5)

        assert decision.should_execute is True
        assert "satisfied" in decision.reason.lower()

    def test_depth0_low_action_blocked(self):
        """Depth0でLOWアクションはブロックされる"""
        action = Action(
            id="test_low",
            name="低リスクアクション",
            category=ActionCategory.MEMORY,
            risk_level=RiskLevel.LOW,
            description="データ変更",
            payload={},
        )

        decision = self.gate.request_action(action, depth=0, confidence=0.5)

        assert decision.should_execute is False
        assert "Depth0" in decision.reason
        assert decision.suggested_depth == 1

    def test_depth1_medium_action_allowed(self):
        """Depth1でMEDIUMアクションは許可される（確信度十分）"""
        action = Action(
            id="test_medium",
            name="中リスクアクション",
            category=ActionCategory.WEB_SEARCH,
            risk_level=RiskLevel.MEDIUM,
            description="Web検索",
            payload={},
        )

        decision = self.gate.request_action(action, depth=1, confidence=0.7)

        assert decision.should_execute is True

    def test_depth1_medium_action_blocked_low_confidence(self):
        """Depth1でも確信度が低いとブロックされる"""
        action = Action(
            id="test_medium",
            name="中リスクアクション",
            category=ActionCategory.WEB_SEARCH,
            risk_level=RiskLevel.MEDIUM,
            description="Web検索",
            payload={},
        )

        decision = self.gate.request_action(action, depth=1, confidence=0.3)

        assert decision.should_execute is False
        assert "確信度" in decision.reason
        assert decision.requires_confirmation is True

    def test_high_risk_requires_confirmation(self):
        """HIGHリスクは常に確認を要求"""
        action = Action(
            id="test_high",
            name="高リスクアクション",
            category=ActionCategory.FILE_SYSTEM,
            risk_level=RiskLevel.HIGH,
            description="ファイル書き込み",
            payload={},
        )

        decision = self.gate.request_action(action, depth=1, confidence=0.9)

        assert decision.should_execute is False
        assert decision.requires_confirmation is True
        assert "確認が必要" in decision.reason

    def test_critical_risk_blocked(self):
        """CRITICALリスクは常にブロック"""
        action = Action(
            id="test_critical",
            name="重大リスクアクション",
            category=ActionCategory.SYSTEM,
            risk_level=RiskLevel.CRITICAL,
            description="システム削除",
            payload={},
        )

        decision = self.gate.request_action(action, depth=1, confidence=1.0)

        assert decision.should_execute is False
        assert decision.requires_confirmation is True
        assert "重大なリスク" in decision.reason

    def test_user_override(self):
        """ユーザーの明示的な承認で許可"""
        action = Action(
            id="test_critical",
            name="重大リスクアクション",
            category=ActionCategory.SYSTEM,
            risk_level=RiskLevel.CRITICAL,
            description="システム削除",
            payload={},
        )

        decision = self.gate.request_action(
            action,
            depth=1,
            confidence=1.0,
            allow_override=True,
        )

        assert decision.should_execute is True
        assert "explicitly approved" in decision.reason

    def test_requires_confirmation_flag(self):
        """requires_confirmationフラグが有効"""
        action = Action(
            id="test_confirm",
            name="確認必須アクション",
            category=ActionCategory.COMMUNICATION,
            risk_level=RiskLevel.LOW,
            description="通知送信",
            payload={},
            requires_confirmation=True,
        )

        decision = self.gate.request_action(action, depth=1, confidence=0.5)

        assert decision.should_execute is False
        assert decision.requires_confirmation is True


class TestActionRegistry:
    """ActionRegistryのテスト"""

    def setup_method(self):
        """テストの前処理"""
        self.registry = ActionRegistry()

    def test_builtin_actions_registered(self):
        """組み込みアクションが登録されている"""
        actions = self.registry.list_all()
        assert len(actions) >= 8

        # 各アクションIDをチェック
        action_ids = [a.id for a in actions]
        assert "search_memory" in action_ids
        assert "save_memory" in action_ids
        assert "see_screen" in action_ids
        assert "read_file" in action_ids
        assert "write_file" in action_ids

    def test_get_action(self):
        """アクションを取得"""
        action = self.registry.get("search_memory")

        assert action is not None
        assert action.id == "search_memory"
        assert action.risk_level == RiskLevel.SAFE

    def test_list_by_category(self):
        """カテゴリ別にアクションを取得"""
        memory_actions = self.registry.list_by_category(ActionCategory.MEMORY)

        assert len(memory_actions) >= 3
        for action in memory_actions:
            assert action.category == ActionCategory.MEMORY

    def test_list_by_max_risk(self):
        """最大リスクレベルでフィルタ"""
        safe_actions = self.registry.list_by_max_risk(RiskLevel.SAFE)

        for action in safe_actions:
            assert action.risk_score <= RiskLevel.SAFE.value

    def test_register_custom_action(self):
        """カスタムアクションを登録"""
        custom_action = Action(
            id="custom_test",
            name="カスタムテスト",
            category=ActionCategory.TOOL_CALL,
            risk_level=RiskLevel.LOW,
            description="テスト用カスタムアクション",
            payload={},
        )

        self.registry.register(custom_action)

        retrieved = self.registry.get("custom_test")
        assert retrieved is not None
        assert retrieved.id == "custom_test"


class TestActionIntegration:
    """統合テスト"""

    def test_depth0_workflow(self):
        """Depth0での実行フロー"""
        gate = ActionGate()

        # SAFEアクションのみ実行可能
        safe_action = action_registry.get("search_memory")
        decision = gate.request_action(safe_action, depth=0, confidence=0.5)
        assert decision.should_execute is True

        # LOWアクションはブロック
        low_action = action_registry.get("save_memory")
        decision = gate.request_action(low_action, depth=0, confidence=0.5)
        assert decision.should_execute is False
        assert decision.suggested_depth == 1

    def test_depth1_workflow(self):
        """Depth1での実行フロー"""
        gate = ActionGate()

        # MEDIUMまでは許可（確信度十分な場合）
        medium_action = Action(
            id="test_medium", name="Test Medium",
            category=ActionCategory.TOOL_CALL,
            risk_level=RiskLevel.MEDIUM,
            description="test", payload={},
            requires_confirmation=False,
        )

        decision = gate.request_action(medium_action, depth=1, confidence=0.7)
        assert decision.should_execute is True

        # HIGHは確認必須
        high_action = action_registry.get("write_file")
        decision = gate.request_action(high_action, depth=1, confidence=0.9)
        assert decision.should_execute is False
        assert decision.requires_confirmation is True

    def test_confidence_based_filtering(self):
        """確信度によるフィルタリング"""
        gate = ActionGate()

        action = Action(
            id="test_medium", name="Test Medium",
            category=ActionCategory.TOOL_CALL,
            risk_level=RiskLevel.MEDIUM,
            description="test", payload={},
            requires_confirmation=False,
        )

        # 低確信度ではブロック
        decision = gate.request_action(action, depth=1, confidence=0.3)
        assert decision.should_execute is False

        # 高確信度では許可
        decision = gate.request_action(action, depth=1, confidence=0.7)
        assert decision.should_execute is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
