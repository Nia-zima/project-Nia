import logging
from typing import Any, Dict

from backend.services.public_status import update_public_status

logger = logging.getLogger("ActionManager")

class ActionManager:
    def __init__(self):
        pass

    def propose_action(self, action_id: str, description: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        アクション提案プロトコル
        """
        # 1. リスク判定
        risk_level = self._assess_risk(action_id)
        
        logger.info(f"✋ Action Proposed: {action_id} (Risk: {risk_level})")

        # 2. 実行制御
        if risk_level == "low":
            return self._execute_action(action_id, payload)
        else:
            return self._hold_for_approval(action_id, description, payload)

    def _assess_risk(self, action_id: str) -> str:
        """アクションIDに基づいてリスクを判定"""
        # 低リスク: OBS表示更新、ログ出力
        if action_id in {"update_obs_text", "log_observation"}:
            return "low"
        # 高リスク: ファイル削除、外部投稿、設定変更
        return "high"

    def _execute_action(self, action_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """即時実行 (Low Risk)"""
        try:
            if action_id == "update_obs_text":
                # obs_writerが監視している public_status.json を更新する
                self._update_public_status(payload)
                return {"status": "executed", "msg": "OBS updated"}
            
            elif action_id == "log_observation":
                logger.info(f"📝 Observation Logged: {payload}")
                return {"status": "executed", "msg": "Logged"}

        except Exception as e:
            logger.error(f"Action Execution Failed: {e}")
            return {"status": "failed", "error": str(e)}

    def _hold_for_approval(self, action_id: str, description: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """承認待ち (High Risk)"""
        # ここで将来的に `action_proposals.json` 等に書き出す
        logger.warning(f"🔒 Action BLOCKED (Requires Approval): {description}")
        return {"status": "held", "msg": "Waiting for human approval"}

    def _update_public_status(self, payload: Dict[str, Any]) -> None:
        """Public Viewの一部を安全に更新"""
        updated = update_public_status(payload, allowed_keys={"note"})
        if updated:
            logger.info("🌍 Public View Updated via Action")

action_manager = ActionManager()
