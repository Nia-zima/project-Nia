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

        # 4. ファイル読み取り（SAFE）
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

        # 7. システム情報取得（SAFE）
        self.register(Action(
            id="get_system_info",
            name="システム情報取得",
            category=ActionCategory.SYSTEM,
            risk_level=RiskLevel.SAFE,
            description="システム情報を取得（読み取り専用）",
            payload={},
        ))

        # 8. ログ記録（SAFE）
        self.register(Action(
            id="log_observation",
            name="観察ログ記録",
            category=ActionCategory.SYSTEM,
            risk_level=RiskLevel.SAFE,
            description="観察内容をログに記録",
            payload={},
        ))

        # 9. Minecraft ゲームアクション
        self.register(Action(
            id="mc_chat",
            name="ゲーム内チャット",
            category=ActionCategory.GAME,
            risk_level=RiskLevel.SAFE,
            description="Minecraftゲーム内でチャットメッセージを送信",
            payload={},
        ))
        self.register(Action(
            id="mc_move",
            name="移動",
            category=ActionCategory.GAME,
            risk_level=RiskLevel.SAFE,
            description="指定座標に移動",
            payload={},
        ))
        self.register(Action(
            id="mc_mine",
            name="ブロック採掘",
            category=ActionCategory.GAME,
            risk_level=RiskLevel.LOW,
            description="指定位置のブロックを採掘",
            payload={},
        ))
        self.register(Action(
            id="mc_place",
            name="ブロック設置",
            category=ActionCategory.GAME,
            risk_level=RiskLevel.LOW,
            description="指定位置にブロックを設置",
            payload={},
        ))
        self.register(Action(
            id="mc_craft",
            name="クラフト",
            category=ActionCategory.GAME,
            risk_level=RiskLevel.LOW,
            description="アイテムをクラフト",
            payload={},
        ))
        self.register(Action(
            id="mc_attack",
            name="攻撃",
            category=ActionCategory.GAME,
            risk_level=RiskLevel.MEDIUM,
            description="近くのエンティティを攻撃",
            payload={},
        ))

        # 10. Twitter (X) Post
        self.register(Action(
            id="post_tweet",
            name="ツイート投稿",
            category=ActionCategory.COMMUNICATION,
            risk_level=RiskLevel.MEDIUM,
            description="X (Twitter) にニアのツイートを投稿",
            payload={},
            requires_confirmation=True,
        ))


# グローバルインスタンス
action_registry = ActionRegistry()
