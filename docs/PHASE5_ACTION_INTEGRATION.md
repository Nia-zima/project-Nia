# Phase 5: 身体I/F（アクション統合）

## 概要

Phase 5では、Depth0/1の原則を保ちながら物理的なアクション（外部システムへの操作）を安全に統合します。
**Depthレベルと確信度に基づいたアクションゲート**を実装し、不用意な実行を防ぎます。

## アーキテクチャ

```
┌─────────────────────────────────────────────────────────────┐
│                  Action Integration System                   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │   Action     │    │   Action     │    │   Action     │  │
│  │   Request    │───▶│    Gate      │───▶│  Executor    │  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
│         ▲                   │                   │          │
│         │                   ▼                   ▼          │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │    Depth     │    │    Risk      │    │   Action     │  │
│  │   Context    │───▶│  Assessor    │    │   Registry   │  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## コンポーネント

### 1. Action型定義

アクションの基本構造を定義します。

**基本型:**

```python
# backend/core/actions/types.py

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


class RiskLevel(Enum):
    """リスクレベル"""
    SAFE = 0.0          # 完全に安全（読み取り専用）
    LOW = 0.3           # 低リスク（表示更新など）
    MEDIUM = 0.6        # 中リスク（データ変更）
    HIGH = 0.8          # 高リスク（外部通信）
    CRITICAL = 1.0      # 重大リスク（削除、課金など）


class ActionCategory(Enum):
    """アクションカテゴリ"""
    MEMORY = "memory"           # メモリ操作
    DISPLAY = "display"         # 表示更新
    COMMUNICATION = "comm"      # 外部通信
    FILE_SYSTEM = "file"        # ファイル操作
    WEB_SEARCH = "search"       # Web検索
    TOOL_CALL = "tool"          # ツール呼び出し
    SYSTEM = "system"           # システム操作


@dataclass
class Action:
    """アクション定義"""
    id: str                     # アクションID
    name: str                   # 表示名
    category: ActionCategory    # カテゴリ
    risk_level: RiskLevel      # リスクレベル
    description: str            # 説明
    payload: Dict[str, Any]     # ペイロード
    requires_confirmation: bool = False  # 確認必須か

    @property
    def risk_score(self) -> float:
        """リスクスコア（0.0-1.0）"""
        return self.risk_level.value


@dataclass
class ActionDecision:
    """アクション実行判定結果"""
    should_execute: bool         # 実行すべきか
    reason: str                  # 理由
    requires_confirmation: bool = False  # ユーザー確認が必要か
    suggested_depth: Optional[int] = None  # 推奨Depth
```

### 2. ActionGate（アクションゲート）

Depth契約と確信度に基づいてアクション実行を制御します。

**実装:**

```python
# backend/core/actions/gate.py

from typing import Optional
from backend.core.actions.types import Action, ActionDecision, RiskLevel
from backend.core.logger import logger


class ActionGate:
    """
    アクション実行のゲート
    Depth0/1の原則を守りながらアクションを制御
    """

    # Depth別の許可リスクレベル
    DEPTH_RISK_THRESHOLDS = {
        0: RiskLevel.SAFE,      # Depth0: 読み取りのみ
        1: RiskLevel.MEDIUM,    # Depth1: データ変更まで
    }

    def request_action(
        self,
        action: Action,
        depth: int,
        confidence: float,
        *,
        allow_override: bool = False,
    ) -> ActionDecision:
        """
        アクション実行を判断

        Args:
            action: 実行するアクション
            depth: 現在のDepthレベル（0 or 1）
            confidence: 確信度（0.0-1.0）
            allow_override: ユーザーが明示的に許可した場合True

        Returns:
            ActionDecision: 実行判定結果
        """
        # ユーザーが明示的に許可した場合は実行
        if allow_override:
            logger.info(f"✅ Action APPROVED by user override: {action.id}")
            return ActionDecision(
                should_execute=True,
                reason="User explicitly approved",
            )

        # 1. Depthベースの判定
        depth_check = self._check_depth_constraint(action, depth)
        if not depth_check.should_execute:
            return depth_check

        # 2. 確信度ベースの判定
        confidence_check = self._check_confidence_constraint(action, depth, confidence)
        if not confidence_check.should_execute:
            return confidence_check

        # 3. リスクベースの判定
        risk_check = self._check_risk_constraint(action, confidence)
        if not risk_check.should_execute:
            return risk_check

        # 全てのチェックをパス
        logger.info(f"✅ Action APPROVED: {action.id} (depth={depth}, conf={confidence:.2f})")
        return ActionDecision(
            should_execute=True,
            reason="All constraints satisfied",
        )

    def _check_depth_constraint(self, action: Action, depth: int) -> ActionDecision:
        """
        Depth制約のチェック

        原則:
        - Depth0: 読み取りのみ（SAFE）
        - Depth1: データ変更まで（MEDIUM以下）
        """
        max_risk = self.DEPTH_RISK_THRESHOLDS.get(depth, RiskLevel.SAFE)

        if action.risk_score > max_risk.value:
            logger.warning(
                f"🚫 Action BLOCKED by depth constraint: {action.id} "
                f"(depth={depth}, risk={action.risk_level.name})"
            )
            return ActionDecision(
                should_execute=False,
                reason=f"Depth{depth}では{action.risk_level.name}リスクのアクションは実行できません",
                suggested_depth=1 if depth == 0 else None,
            )

        return ActionDecision(should_execute=True, reason="Depth constraint satisfied")

    def _check_confidence_constraint(
        self,
        action: Action,
        depth: int,
        confidence: float,
    ) -> ActionDecision:
        """
        確信度制約のチェック

        原則:
        - Depth1でも確信度が低い場合は保留
        - リスクが高いほど高い確信度を要求
        """
        # リスクレベルに応じた最低確信度
        required_confidence = {
            RiskLevel.SAFE: 0.0,      # 常に許可
            RiskLevel.LOW: 0.3,       # 低確信でOK
            RiskLevel.MEDIUM: 0.6,    # 中程度の確信が必要
            RiskLevel.HIGH: 0.8,      # 高確信が必要
            RiskLevel.CRITICAL: 0.95, # ほぼ確実でなければNG
        }

        min_conf = required_confidence.get(action.risk_level, 0.8)

        if confidence < min_conf:
            logger.warning(
                f"🚫 Action BLOCKED by confidence constraint: {action.id} "
                f"(conf={confidence:.2f}, required={min_conf:.2f})"
            )
            return ActionDecision(
                should_execute=False,
                reason=f"確信度が不足しています（現在: {confidence:.2f}, 必要: {min_conf:.2f}）",
                requires_confirmation=True,  # 確認を求める
            )

        return ActionDecision(should_execute=True, reason="Confidence constraint satisfied")

    def _check_risk_constraint(self, action: Action, confidence: float) -> ActionDecision:
        """
        リスク制約のチェック

        原則:
        - HIGH以上のリスクは必ずユーザー確認を要求
        - CRITICAL リスクは常にブロック（明示的な承認のみ）
        """
        if action.risk_level == RiskLevel.CRITICAL:
            logger.warning(f"🚫 Action BLOCKED (CRITICAL risk): {action.id}")
            return ActionDecision(
                should_execute=False,
                reason="重大なリスクがあるため、明示的な承認が必要です",
                requires_confirmation=True,
            )

        if action.risk_level == RiskLevel.HIGH or action.requires_confirmation:
            logger.info(f"⏸️  Action REQUIRES CONFIRMATION: {action.id}")
            return ActionDecision(
                should_execute=False,
                reason="リスクが高いため、ユーザー確認が必要です",
                requires_confirmation=True,
            )

        return ActionDecision(should_execute=True, reason="Risk constraint satisfied")


# グローバルインスタンス
action_gate = ActionGate()
```

### 3. ActionRegistry（アクションレジストリ）

利用可能なアクションを管理します。

```python
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
```

### 4. ActionExecutor（アクション実行器）

ゲートを通過したアクションを実際に実行します。

```python
# backend/core/actions/executor.py

from typing import Any, Dict, Optional
from backend.core.actions.types import Action
from backend.core.logger import logger


class ActionExecutor:
    """アクション実行器"""

    async def execute(self, action: Action) -> Dict[str, Any]:
        """
        アクションを実行

        Args:
            action: 実行するアクション

        Returns:
            実行結果
        """
        try:
            logger.info(f"🔧 Executing action: {action.id}")

            # アクションIDに基づいて実行
            handler = self._get_handler(action.id)
            if handler is None:
                return {
                    "status": "error",
                    "message": f"Unknown action: {action.id}",
                }

            result = await handler(action.payload)

            logger.info(f"✅ Action completed: {action.id}")
            return {
                "status": "success",
                "result": result,
            }

        except Exception as e:
            logger.error(f"❌ Action failed: {action.id} - {e}", exc_info=True)
            return {
                "status": "error",
                "message": str(e),
            }

    def _get_handler(self, action_id: str):
        """アクションハンドラーを取得"""
        handlers = {
            "search_memory": self._handle_search_memory,
            "save_memory": self._handle_save_memory,
            "save_episode": self._handle_save_episode,
            "update_obs_text": self._handle_update_obs_text,
            "update_emotion_display": self._handle_update_emotion_display,
            "see_screen": self._handle_see_screen,
            "web_search": self._handle_web_search,
            "read_file": self._handle_read_file,
            "write_file": self._handle_write_file,
            "text_to_speech": self._handle_text_to_speech,
            "get_system_info": self._handle_get_system_info,
            "send_notification": self._handle_send_notification,
            "log_observation": self._handle_log_observation,
        }
        return handlers.get(action_id)

    # ハンドラー実装（例）
    async def _handle_search_memory(self, payload: Dict[str, Any]) -> Any:
        from backend.services.memory_manager import memory_manager
        query = payload.get("query", "")
        return await memory_manager.recall_memories(query=query, limit=5)

    async def _handle_save_memory(self, payload: Dict[str, Any]) -> Any:
        from backend.services.memory_manager import memory_manager
        content = payload.get("content", "")
        await memory_manager.register_thought(text=content, confidence=0.8, source="manual_save")
        return {"saved": True}

    async def _handle_save_episode(self, payload: Dict[str, Any]) -> Any:
        from backend.services.memory_manager import memory_manager
        summary = payload.get("summary", "")
        category = payload.get("category", "general")
        details = payload.get("details", "")
        await memory_manager.add_episode(summary=summary, category=category, details=details)
        return {"saved": True}

    async def _handle_update_obs_text(self, payload: Dict[str, Any]) -> Any:
        from backend.services.public_status import update_public_status
        update_public_status(payload, allowed_keys={"note"})
        return {"updated": True}

    async def _handle_update_emotion_display(self, payload: Dict[str, Any]) -> Any:
        # TODO: 感情表示更新の実装
        emotion = payload.get("emotion", "neutral")
        return {"emotion": emotion}

    async def _handle_see_screen(self, payload: Dict[str, Any]) -> Any:
        # TODO: 画面認識の実装（tools.py参照）
        return {"message": "Screen capture not implemented"}

    async def _handle_web_search(self, payload: Dict[str, Any]) -> Any:
        # TODO: Web検索の実装
        query = payload.get("query", "")
        return {"results": [], "query": query}

    async def _handle_read_file(self, payload: Dict[str, Any]) -> Any:
        import os
        file_path = payload.get("file_path", "")
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        with open(file_path, "r", encoding="utf-8") as f:
            return {"content": f.read()}

    async def _handle_write_file(self, payload: Dict[str, Any]) -> Any:
        file_path = payload.get("file_path", "")
        content = payload.get("content", "")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return {"written": True}

    async def _handle_text_to_speech(self, payload: Dict[str, Any]) -> Any:
        # TODO: VOICEVOX連携の実装
        text = payload.get("text", "")
        return {"synthesized": False, "text": text}

    async def _handle_get_system_info(self, payload: Dict[str, Any]) -> Any:
        import platform
        return {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        }

    async def _handle_send_notification(self, payload: Dict[str, Any]) -> Any:
        # TODO: デスクトップ通知の実装
        title = payload.get("title", "")
        message = payload.get("message", "")
        return {"sent": False, "title": title, "message": message}

    async def _handle_log_observation(self, payload: Dict[str, Any]) -> Any:
        observation = payload.get("observation", "")
        logger.info(f"📝 Observation: {observation}")
        return {"logged": True}


# グローバルインスタンス
action_executor = ActionExecutor()
```

## LangGraphへの統合

ActionGateをLangGraphノードに統合します。

### アクション提案ノード

```python
# backend/core/agent_graph/nodes.py に追加

from backend.core.actions.gate import action_gate
from backend.core.actions.registry import action_registry
from backend.core.actions.executor import action_executor
from backend.core.actions.types import Action, RiskLevel

async def action_proposal_node(state: NiaState):
    """
    アクション提案ノード

    LLMの出力からアクション提案を抽出し、ゲートで判定
    """
    # LLMがアクションを提案したかチェック
    proposed_actions = state.get("proposed_actions", [])

    if not proposed_actions:
        return state

    # 現在のDepthと確信度を取得
    depth = state.get("selected_depth", 0)
    confidence = state.get("depth_confidence", 0.5)

    # 各アクションをゲートに通す
    approved_actions = []
    pending_actions = []
    rejected_actions = []

    for action_request in proposed_actions:
        action_id = action_request.get("action_id")
        action = action_registry.get(action_id)

        if action is None:
            logger.warning(f"Unknown action: {action_id}")
            rejected_actions.append({
                "action_id": action_id,
                "reason": "Unknown action",
            })
            continue

        # ペイロードを設定
        action.payload = action_request.get("payload", {})

        # ゲートで判定
        decision = action_gate.request_action(action, depth, confidence)

        if decision.should_execute:
            approved_actions.append(action)
        elif decision.requires_confirmation:
            pending_actions.append({
                "action": action,
                "decision": decision,
            })
        else:
            rejected_actions.append({
                "action_id": action_id,
                "reason": decision.reason,
            })

    # 承認されたアクションを実行
    action_results = []
    for action in approved_actions:
        result = await action_executor.execute(action)
        action_results.append({
            "action_id": action.id,
            "result": result,
        })

    # 状態を更新
    state["approved_actions"] = approved_actions
    state["pending_actions"] = pending_actions
    state["rejected_actions"] = rejected_actions
    state["action_results"] = action_results

    return state
```

## テスト

### テストファイル

[tests/test_action_gate.py](../tests/test_action_gate.py)

### 実行方法

```bash
# Phase 5テストのみ
python -m pytest tests/test_action_gate.py -v

# 全Phaseテスト
python -m pytest tests/test_contracts.py tests/test_confidence.py tests/test_depth_selector.py tests/test_policy.py tests/test_dspy.py tests/test_action_gate.py -v
```

## 成功指標

| 指標 | 目標 |
|------|------|
| アクション種類数 | ≥ 10種類 |
| Depth0での不適切実行率 | < 1% |
| 高リスクアクションの確認要求率 | 100% |
| アクション実行成功率 | > 95% |
| ユーザーテスト安全性スコア | > 4.5/5.0 |

## ファイル構成

```
backend/core/actions/
├── __init__.py         # エクスポート
├── types.py            # 型定義
├── gate.py             # ActionGate
├── registry.py         # ActionRegistry
└── executor.py         # ActionExecutor

tests/
└── test_action_gate.py # テスト

docs/
└── PHASE5_ACTION_INTEGRATION.md  # このドキュメント
```

## 実装手順

### ステップ1: 基本構造の実装

1. 型定義の作成（`types.py`）
2. ActionGateの実装（`gate.py`）
3. ActionRegistryの実装（`registry.py`）
4. ActionExecutorの実装（`executor.py`）

### ステップ2: LangGraph統合

1. アクション提案ノードの追加
2. グラフへの統合
3. 状態管理の更新

### ステップ3: テスト実装

1. ユニットテストの作成
2. 統合テストの作成
3. E2Eテストの作成

### ステップ4: ドキュメント最終化

1. APIドキュメントの作成
2. 使用例の追加
3. トラブルシューティングガイドの作成

## 次のステップ（Phase 6+）

Phase 5完了後の拡張:

- より高度なリスク評価（機械学習ベース）
- アクション履歴の学習
- ユーザー別のアクション許可設定
- アクション組み合わせの安全性評価

詳細は将来のロードマップで検討。
