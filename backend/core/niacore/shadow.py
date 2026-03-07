"""NiaCore Shadow Inference — ルールベースと並行して CfC 推論を実行。

結果はログのみ。実行に影響しない（卒業まで）。
Design doc: docs/niacore_lnn_design.md §5
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

from backend.core.config import settings
from backend.core.db import managed_conn
from backend.core.logger import logger
from backend.core.niacore.model import (
    DEPTH_LABELS,
    NiaCoreOutput,
    StateVector,
    build_state_vector,
    load_or_create_model,
)

# Lazy singleton — initialized on first call
_model_instance = None


def _get_model():
    global _model_instance
    if _model_instance is None:
        _model_instance = load_or_create_model()
    return _model_instance


def reset_model() -> None:
    """Force reload on next inference (for testing / after training)."""
    global _model_instance
    _model_instance = None


def _set_model(model) -> None:
    """Set the singleton directly (used by trainer after learning)."""
    global _model_instance
    _model_instance = model


@dataclass
class ShadowResult:
    """Shadow 推論の結果。state に格納され、experience_writer に渡される。"""
    niacore_selected: str          # CfC が選んだ depth ("D0", "D1", "D2", "WAIT")
    rule_based_depth: str          # ルールベースが選んだ depth
    is_deviation: bool             # CfC とルールベースが異なるか
    state_vector_blob: bytes       # 136-byte binary (experience テーブル保存用)
    logits_json: str               # raw logits JSON
    depth_preference: list[float]  # softmax probabilities
    inference_ms: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "niacore_selected": self.niacore_selected,
            "rule_based_depth": self.rule_based_depth,
            "is_deviation": self.is_deviation,
            "logits_json": self.logits_json,
            "depth_preference": self.depth_preference,
            "inference_ms": self.inference_ms,
        }


def shadow_infer(
    *,
    user_text: str,
    messages: list[dict[str, Any]],
    confidence_metrics: dict[str, float] | None = None,
    surprise_score: float = 0.0,
    surprise_v: int = 0,
    somatic_senses: list[dict[str, Any]] | None = None,
    recent_depths: list[str] | None = None,
    session_start_time: float | None = None,
    time_since_last_session_hours: float = 0.0,
    thread_id: str = "",
    rule_based_depth: str = "0",
) -> ShadowResult | None:
    """ルールベースと並行して CfC 推論。結果はログのみ。

    Returns None on any failure (fire-and-forget).
    """
    try:
        model = _get_model()
        sv = build_state_vector(
            user_text=user_text,
            messages=messages,
            confidence_metrics=confidence_metrics,
            surprise_score=surprise_score,
            surprise_v=surprise_v,
            somatic_senses=somatic_senses,
            recent_depths=recent_depths,
            session_start_time=session_start_time,
            time_since_last_session_hours=time_since_last_session_hours,
        )
        output: NiaCoreOutput = model.infer(sv)

        # Normalize rule_based_depth to DEPTH_LABELS format
        rb = str(rule_based_depth)
        rb_label = {"0": "D0", "1": "D1", "2": "D2"}.get(rb, rb.upper())
        is_deviation = output.selected != rb_label

        result = ShadowResult(
            niacore_selected=output.selected,
            rule_based_depth=rb_label,
            is_deviation=is_deviation,
            state_vector_blob=sv.to_blob(),
            logits_json=output.logits_json,
            depth_preference=output.depth_preference,
            inference_ms=output.inference_ms,
        )

        logger.debug(
            "[NiaCore] shadow: rule=%s cfc=%s deviation=%s ms=%.1f",
            rb_label, output.selected, is_deviation, output.inference_ms,
        )
        return result

    except Exception:
        logger.debug("[NiaCore] shadow inference failed", exc_info=True)
        return None


# ═══════════════════════════════════════════════════════════════
# Graduation Check
# ═══════════════════════════════════════════════════════════════

@dataclass
class GraduationStatus:
    eligible: bool
    days_active: int           # 稼働日数
    total_turns: int           # 総ターン数
    agreement_rate: float      # ルールベースとの一致率
    deviation_success_rate: float  # 逸脱時の成功率
    depth_coverage: dict[str, float]  # 各 depth の選択率
    reasons: list[str]         # 不適格理由

    def to_dict(self) -> dict[str, Any]:
        return {
            "eligible": self.eligible,
            "days_active": self.days_active,
            "total_turns": self.total_turns,
            "agreement_rate": round(self.agreement_rate, 4),
            "deviation_success_rate": round(self.deviation_success_rate, 4),
            "depth_coverage": {k: round(v, 4) for k, v in self.depth_coverage.items()},
            "reasons": self.reasons,
        }


# Graduation thresholds
_GRAD_MIN_DAYS = 30
_GRAD_MIN_TURNS = 500
_GRAD_MIN_AGREEMENT = 0.85
_GRAD_MIN_DEVIATION_SUCCESS = 0.60
_GRAD_MIN_DEPTH_COVERAGE = 0.05  # Each depth must be >= 5%


def check_graduation() -> GraduationStatus:
    """卒業条件チェック。

    条件:
    1. 30日以上稼働
    2. 500ターン以上
    3. 85%以上ルールベースと一致
    4. 逸脱時の60%以上が成功（rejected/correction なし）
    5. 各 depth が 5% 以上選択されている
    """
    reasons: list[str] = []

    try:
        with managed_conn() as conn:
            # Total turns with shadow data
            row = conn.execute(
                "SELECT COUNT(*) FROM niacore_experience WHERE niacore_selected IS NOT NULL"
            ).fetchone()
            total_turns = row[0] if row else 0

            # Days active
            row = conn.execute(
                """SELECT COUNT(DISTINCT date(timestamp, 'unixepoch'))
                   FROM niacore_experience WHERE niacore_selected IS NOT NULL"""
            ).fetchone()
            days_active = row[0] if row else 0

            # Agreement rate
            row = conn.execute(
                """SELECT COUNT(*) FROM niacore_experience
                   WHERE niacore_selected IS NOT NULL
                     AND is_deviation = 0"""
            ).fetchone()
            agreements = row[0] if row else 0
            agreement_rate = agreements / max(1, total_turns)

            # Deviation success rate (outcome_known only)
            row = conn.execute(
                """SELECT COUNT(*) FROM niacore_experience
                   WHERE is_deviation = 1 AND niacore_selected IS NOT NULL
                     AND review_checked = 1 AND correction_window_closed = 1"""
            ).fetchone()
            total_deviations = row[0] if row else 0

            row = conn.execute(
                """SELECT COUNT(*) FROM niacore_experience
                   WHERE is_deviation = 1
                     AND niacore_selected IS NOT NULL
                     AND review_checked = 1 AND correction_window_closed = 1
                     AND review_rejected = 0
                     AND user_correction = 0"""
            ).fetchone()
            deviation_successes = row[0] if row else 0
            deviation_success_rate = deviation_successes / max(1, total_deviations)

            # Depth coverage
            depth_coverage: dict[str, float] = {}
            for label in DEPTH_LABELS:
                row = conn.execute(
                    """SELECT COUNT(*) FROM niacore_experience
                       WHERE niacore_selected = ?""",
                    (label,),
                ).fetchone()
                count = row[0] if row else 0
                depth_coverage[label] = count / max(1, total_turns)

    except Exception:
        logger.warning("[NiaCore] graduation check failed", exc_info=True)
        return GraduationStatus(
            eligible=False, days_active=0, total_turns=0,
            agreement_rate=0.0, deviation_success_rate=0.0,
            depth_coverage={}, reasons=["db_error"],
        )

    # Evaluate conditions
    if days_active < _GRAD_MIN_DAYS:
        reasons.append(f"days={days_active}<{_GRAD_MIN_DAYS}")
    if total_turns < _GRAD_MIN_TURNS:
        reasons.append(f"turns={total_turns}<{_GRAD_MIN_TURNS}")
    if agreement_rate < _GRAD_MIN_AGREEMENT:
        reasons.append(f"agreement={agreement_rate:.2%}<{_GRAD_MIN_AGREEMENT:.0%}")
    if total_deviations > 0 and deviation_success_rate < _GRAD_MIN_DEVIATION_SUCCESS:
        reasons.append(f"dev_success={deviation_success_rate:.2%}<{_GRAD_MIN_DEVIATION_SUCCESS:.0%}")
    for label in DEPTH_LABELS:
        cov = depth_coverage.get(label, 0.0)
        if cov < _GRAD_MIN_DEPTH_COVERAGE:
            reasons.append(f"{label}_coverage={cov:.2%}<{_GRAD_MIN_DEPTH_COVERAGE:.0%}")

    return GraduationStatus(
        eligible=len(reasons) == 0,
        days_active=days_active,
        total_turns=total_turns,
        agreement_rate=agreement_rate,
        deviation_success_rate=deviation_success_rate,
        depth_coverage=depth_coverage,
        reasons=reasons,
    )
