# backend/core/actions/registry.py

from typing import Dict, List, Optional
from backend.core.actions.types import Action, ActionCategory, RiskLevel


class ActionRegistry:
    """アクションレジストリ"""

    def __init__(self):
        self._actions: Dict[str, Action] = {}
        self._register_builtin_actions()

    def register(self, action: Action) -> None:
        """アクションを登録"""
        self._actions[action.id] = action

    def get(self, action_id: str) -> Optional[Action]:
        """アクションを取得"""
        return self._actions.get(action_id)

    def list_by_category(self, category: ActionCategory) -> List[Action]:
        """カテゴリ別にアクションを取得"""
        return [a for a in self._actions.values() if a.category == category]

    def list_by_max_risk(self, max_risk: RiskLevel) -> List[Action]:
        """最大リスクレベル以下のアクションを取得"""
        return [a for a in self._actions.values() if a.risk_score <= max_risk.value]

    def list_all(self) -> List[Action]:
        """全アクションを取得"""
        return list(self._actions.values())

    def _register_builtin_actions(self):
        """組み込みアクションを登録"""
        # 1. メモリ操作（SAFE - LOW）
        self.register(Action(
            id="search_memory",
            name="記憶検索",
            category=ActionCategory.MEMORY,
            risk_level=RiskLevel.SAFE,
            description="過去の記憶を検索（読み取り専用）",
            payload={},
        ))

        self.register(Action(
            id="save_memory",
            name="記憶保存",
            category=ActionCategory.MEMORY,
            risk_level=RiskLevel.LOW,
            description="新しい記憶を保存",
            payload={},
        ))

        self.register(Action(
            id="save_episode",
            name="エピソード保存",
            category=ActionCategory.MEMORY,
            risk_level=RiskLevel.LOW,
            description="重要なエピソードを保存",
            payload={},
        ))

        # 2. 表示更新（SAFE - LOW）
        self.register(Action(
            id="update_obs_text",
            name="OBS表示更新",
            category=ActionCategory.DISPLAY,
            risk_level=RiskLevel.LOW,
            description="OBS表示テキストを更新",
            payload={},
        ))

        self.register(Action(
            id="update_emotion_display",
            name="感情表示更新",
            category=ActionCategory.DISPLAY,
            risk_level=RiskLevel.SAFE,
            description="アバターの感情表示を更新",
            payload={},
        ))

        # 3. 画面認識（SAFE）
        self.register(Action(
            id="see_screen",
            name="画面認識",
            category=ActionCategory.TOOL_CALL,
            risk_level=RiskLevel.SAFE,
            description="デスクトップ画面を認識（読み取り専用）",
            payload={},
        ))

        # 4. Web検索（MEDIUM）
        self.register(Action(
            id="web_search",
            name="Web検索",
            category=ActionCategory.WEB_SEARCH,
            risk_level=RiskLevel.MEDIUM,
            description="Webで情報を検索",
            payload={},
            requires_confirmation=True,
        ))

        # 5. ファイル読み取り（SAFE）
        self.register(Action(
            id="read_file",
            name="ファイル読み取り",
            category=ActionCategory.FILE_SYSTEM,
            risk_level=RiskLevel.SAFE,
            description="ローカルファイルを読み取り",
            payload={},
        ))

        # 6. ファイル書き込み（HIGH）
        self.register(Action(
            id="write_file",
            name="ファイル書き込み",
            category=ActionCategory.FILE_SYSTEM,
            risk_level=RiskLevel.HIGH,
            description="ローカルファイルに書き込み",
            payload={},
            requires_confirmation=True,
        ))

        # 7. 音声合成（LOW）
        self.register(Action(
            id="text_to_speech",
            name="音声合成",
            category=ActionCategory.TOOL_CALL,
            risk_level=RiskLevel.LOW,
            description="テキストを音声に変換",
            payload={},
        ))

        # 8. システム情報取得（SAFE）
        self.register(Action(
            id="get_system_info",
            name="システム情報取得",
            category=ActionCategory.SYSTEM,
            risk_level=RiskLevel.SAFE,
            description="システム情報を取得（読み取り専用）",
            payload={},
        ))

        # 9. 通知送信（MEDIUM）
        self.register(Action(
            id="send_notification",
            name="通知送信",
            category=ActionCategory.COMMUNICATION,
            risk_level=RiskLevel.MEDIUM,
            description="デスクトップ通知を送信",
            payload={},
        ))

        # 10. ログ記録（SAFE）
        self.register(Action(
            id="log_observation",
            name="観察ログ記録",
            category=ActionCategory.SYSTEM,
            risk_level=RiskLevel.SAFE,
            description="観察内容をログに記録",
            payload={},
        ))


# グローバルインスタンス
action_registry = ActionRegistry()
