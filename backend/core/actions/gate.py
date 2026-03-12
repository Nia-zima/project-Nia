# backend/core/actions/gate.py

from typing import Optional
from backend.core.actions.types import Action, ActionDecision, RiskLevel
from backend.core.logger import logger


class ActionGate:
    """
    アクション実行のゲート
    Depth0/1の原則を守りながらアクションを制御
    """

    # Depth別の許可リスクレベル（確認なしで実行可能な最大リスク）
    DEPTH_RISK_THRESHOLDS = {
        0: RiskLevel.SAFE,      # Depth0: 読み取りのみ
        1: RiskLevel.HIGH,      # Depth1: 高リスクまで（ただし確認必須）
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
        - Depth1: 高リスクまで（HIGH）、CRITICALは不可
        """
        max_risk = self.DEPTH_RISK_THRESHOLDS.get(depth, RiskLevel.SAFE)

        if action.risk_score > max_risk.value:
            logger.warning(
                f"🚫 Action BLOCKED by depth constraint: {action.id} "
                f"(depth={depth}, risk={action.risk_level.name})"
            )

            if action.requires_confirmation and action.risk_level != RiskLevel.CRITICAL:
                return ActionDecision(
                    should_execute=False,
                    reason=f"Depth{depth}では自動実行できないため、ユーザー確認が必要です",
                    suggested_depth=1 if depth == 0 else None,
                    requires_confirmation=True,
                )

            # CRITICALリスクの場合は特別なメッセージ
            if action.risk_level == RiskLevel.CRITICAL:
                reason = "重大なリスクがあるため、明示的な承認が必要です"
            else:
                reason = f"Depth{depth}では{action.risk_level.name}リスクのアクションは実行できません"

            return ActionDecision(
                should_execute=False,
                reason=reason,
                suggested_depth=1 if depth == 0 else None,
                requires_confirmation=True if action.risk_level == RiskLevel.CRITICAL else False,
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
