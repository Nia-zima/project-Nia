"""
Somatic Calibration — threshold persistence for somatic translator.

Phase S.1a: read-only (load defaults or from file).
Phase S.1.5: update() enables adaptive learning.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

from backend.core.logger import logger

_CALIBRATION_PATH = Path("data/somatic_calibration.json")

# Hard bounds (design doc §6)
_BOUNDS = {
    "high_confidence_threshold": (0.60, 0.90),
    "medium_confidence_threshold": (0.35, 0.70),
    "low_confidence_threshold": (0.10, 0.35),
}


_INITIAL_DEFAULTS = {
    "high_confidence_threshold": 0.75,
    "medium_confidence_threshold": 0.50,
    "low_confidence_threshold": 0.20,
}


@dataclass
class SomaticCalibration:
    """Threshold set for somatic sense generation.

    Initial values are v0.1 defaults.  Phase S.1.5 makes them adaptive.
    """

    high_confidence_threshold: float = 0.75
    medium_confidence_threshold: float = 0.50
    low_confidence_threshold: float = 0.20

    def update(
        self,
        accuracy: float,
        sample_count: int,
        user_correction: bool = False,
    ) -> bool:
        """S.1.5: Adjust thresholds based on somatic feedback accuracy.

        Returns True if any threshold was changed.
        Minimum 5 samples required to avoid noisy updates.
        """
        if sample_count < 5:
            return False

        step = 0.0
        if user_correction:
            step = +0.04  # shock: user corrected → raise thresholds (more cautious)
        elif accuracy < 0.5:
            step = +0.02  # mostly wrong → raise thresholds
        elif accuracy > 0.8:
            step = -0.02  # mostly right → lower thresholds
        else:
            return False

        changed = False
        for field_name, (lo, hi) in _BOUNDS.items():
            old = getattr(self, field_name)
            new = max(lo, min(hi, old + step))
            if new != old:
                setattr(self, field_name, round(new, 4))
                changed = True
        return changed

    def regress(self, step: float = 0.01) -> None:
        """S.1.5: Regress thresholds toward initial defaults.

        Called once per Sleep Cycle. Learning step (0.02) > regression (0.01)
        ensures experience dominates over time — "寝たら少し楽になった".
        """
        for field_name, default in _INITIAL_DEFAULTS.items():
            current = getattr(self, field_name)
            if current > default:
                setattr(self, field_name, round(max(default, current - step), 4))
            elif current < default:
                setattr(self, field_name, round(min(default, current + step), 4))


def load_calibration() -> SomaticCalibration:
    """Load calibration from disk, falling back to defaults."""
    try:
        if _CALIBRATION_PATH.exists():
            raw = json.loads(_CALIBRATION_PATH.read_text(encoding="utf-8"))
            return SomaticCalibration(
                high_confidence_threshold=float(raw.get("high_confidence_threshold", 0.75)),
                medium_confidence_threshold=float(raw.get("medium_confidence_threshold", 0.50)),
                low_confidence_threshold=float(raw.get("low_confidence_threshold", 0.20)),
            )
    except Exception:
        logger.warning("[SOMATIC_CAL] failed to load calibration, using defaults", exc_info=True)
    return SomaticCalibration()


def save_calibration(cal: SomaticCalibration) -> None:
    """Persist calibration to disk (called by Sleep Cycle only)."""
    try:
        _CALIBRATION_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "high_confidence_threshold": cal.high_confidence_threshold,
            "medium_confidence_threshold": cal.medium_confidence_threshold,
            "low_confidence_threshold": cal.low_confidence_threshold,
        }
        _CALIBRATION_PATH.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        logger.warning("[SOMATIC_CAL] failed to save calibration", exc_info=True)
