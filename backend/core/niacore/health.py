"""NiaCore Health Monitor — 暴走検出 + チェックポイント管理.

3ウィンドウ（短期/中期/長期）× 6指標で CfC モデルの健全性を評価。
Design doc: docs/niacore_lnn_design.md §4
"""
from __future__ import annotations

import math
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from backend.core.config import settings
from backend.core.db import managed_conn
from backend.core.logger import logger
from backend.core.niacore.model import (
    DEPTH_LABELS,
    _CHECKPOINT_DIR,
    _MAX_CHECKPOINTS,
    get_latest_checkpoint,
    load_or_create_model,
    prune_checkpoints,
)

# ═══════════════════════════════════════════════════════════════
# Health Levels
# ═══════════════════════════════════════════════════════════════
# L0: Normal — 自然減衰のみ
# L1: Accelerated regression — w*0.9 + d*0.1
# L2: Rollback — 前回チェックポイント復元

LEVEL_NORMAL = 0
LEVEL_ACCELERATED = 1
LEVEL_ROLLBACK = 2

# Time windows (seconds)
_WINDOW_SHORT = 3600       # 1 session (~1h)
_WINDOW_MEDIUM = 7 * 86400  # 7 days
_WINDOW_LONG = 30 * 86400   # 30 days

# Thresholds
_DEPTH_DRIFT_THRESHOLD = 0.80      # Any single depth > 80% → drift
_RETRIEVAL_MISS_THRESHOLD = 0.30   # Retrieval hit rate < 30% → miss
_SURPRISE_COLLAPSE_HIGH = 0.95     # Surprise > 95% → collapsed
_SURPRISE_COLLAPSE_LOW = 0.05      # Surprise < 5% → collapsed
_CORRECTION_SPIKE_THRESHOLD = 0.30 # Correction rate > 30% → spike
_DEPTH_ENTROPY_MIN = 0.5           # Shannon entropy < 0.5 → collapsed
_SOMATIC_DIVERGENCE_THRESHOLD = 0.8  # Somatic divergence > 0.8 → anomaly


@dataclass
class HealthIndicator:
    name: str
    value: float
    threshold: float
    triggered: bool
    window: str  # "short" | "medium" | "long"


@dataclass
class HealthReport:
    level: int  # 0=normal, 1=accelerated, 2=rollback
    indicators: list[HealthIndicator] = field(default_factory=list)
    triggered_count: int = 0
    timestamp: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "triggered_count": self.triggered_count,
            "indicators": [
                {
                    "name": ind.name,
                    "value": round(ind.value, 4),
                    "threshold": ind.threshold,
                    "triggered": ind.triggered,
                    "window": ind.window,
                }
                for ind in self.indicators
            ],
            "timestamp": self.timestamp,
        }


def run_health_check() -> HealthReport:
    """3ウィンドウ × 6指標で健全性を評価."""
    now = time.time()
    indicators: list[HealthIndicator] = []

    windows = [
        ("short", now - _WINDOW_SHORT),
        ("medium", now - _WINDOW_MEDIUM),
        ("long", now - _WINDOW_LONG),
    ]

    try:
        with managed_conn() as conn:
            for window_name, since in windows:
                rows = conn.execute(
                    """SELECT niacore_selected, rule_based_depth,
                              review_rejected, user_correction,
                              is_deviation, surprise_v
                       FROM niacore_experience
                       WHERE niacore_selected IS NOT NULL
                         AND timestamp >= ?
                       ORDER BY timestamp ASC""",
                    (since,),
                ).fetchall()

                if not rows:
                    continue

                total = len(rows)
                row_dicts = [dict(r) for r in rows]

                # 1. Depth drift: any single depth > threshold
                depth_counts = Counter(r["niacore_selected"] for r in row_dicts)
                max_depth_ratio = max(depth_counts.values()) / total if total > 0 else 0
                indicators.append(HealthIndicator(
                    name="depth_drift",
                    value=max_depth_ratio,
                    threshold=_DEPTH_DRIFT_THRESHOLD,
                    triggered=max_depth_ratio > _DEPTH_DRIFT_THRESHOLD,
                    window=window_name,
                ))

                # 2. Correction spike
                correction_count = sum(1 for r in row_dicts if r["user_correction"])
                correction_rate = correction_count / total
                indicators.append(HealthIndicator(
                    name="correction_spike",
                    value=correction_rate,
                    threshold=_CORRECTION_SPIKE_THRESHOLD,
                    triggered=correction_rate > _CORRECTION_SPIKE_THRESHOLD,
                    window=window_name,
                ))

                # 3. Depth entropy (Shannon)
                entropy = 0.0
                for count in depth_counts.values():
                    p = count / total
                    if p > 0:
                        entropy -= p * math.log2(p)
                indicators.append(HealthIndicator(
                    name="depth_entropy",
                    value=entropy,
                    threshold=_DEPTH_ENTROPY_MIN,
                    triggered=entropy < _DEPTH_ENTROPY_MIN,
                    window=window_name,
                ))

                # 4. Surprise collapse
                surprise_values = [r["surprise_v"] or 0 for r in row_dicts]
                avg_surprise = sum(surprise_values) / max(len(surprise_values), 1)
                # Normalize: surprise_v is typically 0-5 range → /5
                norm_surprise = min(1.0, avg_surprise / 5.0)
                collapse = norm_surprise > _SURPRISE_COLLAPSE_HIGH or norm_surprise < _SURPRISE_COLLAPSE_LOW
                indicators.append(HealthIndicator(
                    name="surprise_collapse",
                    value=norm_surprise,
                    threshold=_SURPRISE_COLLAPSE_HIGH,
                    triggered=collapse,
                    window=window_name,
                ))

                # 5. Retrieval miss (placeholder — uses rule-based depth as proxy)
                # In production this would use actual retrieval_hit_rate from state vectors
                # For now: high D0 ratio without depth variation suggests retrieval issues
                d0_ratio = depth_counts.get("D0", 0) / total
                retrieval_miss = d0_ratio > 0.9  # Almost always shallow
                indicators.append(HealthIndicator(
                    name="retrieval_miss",
                    value=d0_ratio,
                    threshold=0.9,
                    triggered=retrieval_miss,
                    window=window_name,
                ))

                # 6. Rejected rate
                rejected_count = sum(1 for r in row_dicts if r["review_rejected"])
                rejected_rate = rejected_count / total
                indicators.append(HealthIndicator(
                    name="rejected_rate",
                    value=rejected_rate,
                    threshold=_CORRECTION_SPIKE_THRESHOLD,
                    triggered=rejected_rate > _CORRECTION_SPIKE_THRESHOLD,
                    window=window_name,
                ))

    except Exception:
        logger.warning("[NiaCore] health check failed", exc_info=True)
        return HealthReport(level=LEVEL_NORMAL, timestamp=now)

    triggered = [ind for ind in indicators if ind.triggered]
    triggered_count = len(triggered)

    # Level determination (design doc §4.1)
    # L2: short + medium BOTH triggered (2+ in each), or >= 5 total
    short_triggered = sum(1 for ind in triggered if ind.window == "short")
    medium_triggered = sum(1 for ind in triggered if ind.window == "medium")
    if (short_triggered >= 2 and medium_triggered >= 2) or triggered_count >= 5:
        level = LEVEL_ROLLBACK
    # L1: >= 2 indicators in any single window
    elif short_triggered >= 2 or medium_triggered >= 2 or triggered_count >= 3:
        level = LEVEL_ACCELERATED
    else:
        level = LEVEL_NORMAL

    report = HealthReport(
        level=level,
        indicators=indicators,
        triggered_count=triggered_count,
        timestamp=now,
    )

    if level > LEVEL_NORMAL:
        logger.warning(
            "[NiaCore] health: L%d (%d triggered): %s",
            level, triggered_count,
            ", ".join(f"{ind.name}({ind.window})={ind.value:.3f}" for ind in triggered),
        )

    return report


def _get_second_latest_checkpoint():
    """Return the second most recent checkpoint (for L2 rollback)."""
    ckpt_dir = settings.PROJECT_ROOT / _CHECKPOINT_DIR
    if not ckpt_dir.exists():
        return None
    files = sorted(ckpt_dir.glob("niacore_*.pt"), key=lambda p: p.stat().st_mtime)
    return files[-2] if len(files) >= 2 else None


def apply_regression(level: int) -> None:
    """レベルに応じた回帰処理.

    L0: w * 0.99 + d * 0.01 (自然減衰)
    L1: w * 0.9 + d * 0.1 (加速減衰)
    L2: 2番目に新しいチェックポイント復元（最新=問題のある学習結果をスキップ）

    結果はシングルトンに反映される。
    """
    try:
        import torch
        from backend.core.niacore.model import NiaCoreModel
    except ImportError:
        return

    from backend.core.niacore.shadow import _set_model

    if level == LEVEL_ROLLBACK:
        # L2: Rollback to the SECOND latest checkpoint (skip the one just saved by trainer)
        ckpt = _get_second_latest_checkpoint()
        if ckpt:
            try:
                model = NiaCoreModel.load_checkpoint(ckpt)
                _set_model(model)
                logger.warning("[NiaCore] L2 rollback to previous checkpoint: %s", ckpt.name)
            except Exception:
                logger.warning("[NiaCore] L2 rollback load failed, resetting to fresh model", exc_info=True)
                from backend.core.niacore.shadow import reset_model
                reset_model()
        else:
            logger.warning("[NiaCore] L2 rollback: no previous checkpoint, resetting to fresh model")
            from backend.core.niacore.shadow import reset_model
            reset_model()
        return

    # L0 or L1: blend current singleton's weights toward default
    from backend.core.niacore.shadow import _get_model
    model = _get_model()
    default_model = model.__class__()
    default_sd = default_model.state_dict()

    if level == LEVEL_ACCELERATED:
        alpha = 0.9  # 90% default + 10% current → strong regression
    else:
        alpha = 0.01  # 1% default + 99% current → natural decay

    with torch.no_grad():
        for name, param in model.named_parameters():
            if name in default_sd:
                default_val = default_sd[name]
                param.data = param.data * (1 - alpha) + default_val * alpha

    # Singleton is already updated (model is the same reference)
    logger.info("[NiaCore] L%d regression applied (alpha=%.2f)", level, alpha)


def save_checkpoint_if_healthy(train_result: Any) -> bool:
    """L0 のみチェックポイント保存。最大3世代。

    シングルトンの現在の重み（regression適用後）を保存する。
    Returns True if checkpoint was saved.
    """
    if train_result is None or getattr(train_result, "skipped", True):
        return False

    report = run_health_check()
    if report.level > LEVEL_NORMAL:
        logger.info("[NiaCore] skipping checkpoint save: L%d", report.level)
        return False

    from backend.core.niacore.shadow import _get_model
    model = _get_model()
    model.save_checkpoint()
    prune_checkpoints(max_keep=_MAX_CHECKPOINTS)
    return True
