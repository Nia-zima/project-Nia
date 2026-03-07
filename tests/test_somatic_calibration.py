"""Tests for Somatic Calibration adaptive thresholds (Phase S.1.5).

Design doc: docs/somatic_self_awareness_design.md §6
"""
import pytest

from backend.services.memory.somatic_calibration import (
    SomaticCalibration,
    _BOUNDS,
    _INITIAL_DEFAULTS,
)


class TestCalibrationUpdate:
    """Test SomaticCalibration.update() — adaptive learning."""

    def test_no_change_below_min_samples(self):
        """Fewer than 5 samples → no change."""
        cal = SomaticCalibration()
        changed = cal.update(accuracy=0.3, sample_count=4)
        assert not changed
        assert cal.high_confidence_threshold == 0.75

    def test_raise_on_low_accuracy(self):
        """accuracy < 0.5 → thresholds increase by 0.02."""
        cal = SomaticCalibration()
        changed = cal.update(accuracy=0.4, sample_count=10)
        assert changed
        assert cal.high_confidence_threshold == pytest.approx(0.77)
        assert cal.medium_confidence_threshold == pytest.approx(0.52)
        assert cal.low_confidence_threshold == pytest.approx(0.22)

    def test_lower_on_high_accuracy(self):
        """accuracy > 0.8 → thresholds decrease by 0.02."""
        cal = SomaticCalibration()
        changed = cal.update(accuracy=0.9, sample_count=10)
        assert changed
        assert cal.high_confidence_threshold == pytest.approx(0.73)
        assert cal.medium_confidence_threshold == pytest.approx(0.48)
        assert cal.low_confidence_threshold == pytest.approx(0.18)

    def test_neutral_accuracy_no_change(self):
        """0.5 <= accuracy <= 0.8 → no change."""
        cal = SomaticCalibration()
        changed = cal.update(accuracy=0.65, sample_count=10)
        assert not changed
        assert cal.high_confidence_threshold == 0.75

    def test_shock_on_user_correction(self):
        """User correction → shock +0.04."""
        cal = SomaticCalibration()
        changed = cal.update(accuracy=0.9, sample_count=10, user_correction=True)
        assert changed
        assert cal.high_confidence_threshold == pytest.approx(0.79)
        assert cal.medium_confidence_threshold == pytest.approx(0.54)

    def test_shock_overrides_accuracy(self):
        """user_correction=True ignores accuracy (even if high)."""
        cal = SomaticCalibration()
        cal.update(accuracy=0.95, sample_count=20, user_correction=True)
        # Shock raises, doesn't lower
        assert cal.high_confidence_threshold > 0.75

    def test_bounds_upper_limit(self):
        """Cannot exceed upper bound."""
        cal = SomaticCalibration(high_confidence_threshold=0.89)
        cal.update(accuracy=0.3, sample_count=10)
        assert cal.high_confidence_threshold <= _BOUNDS["high_confidence_threshold"][1]
        assert cal.high_confidence_threshold == 0.90

    def test_bounds_lower_limit(self):
        """Cannot go below lower bound."""
        cal = SomaticCalibration(low_confidence_threshold=0.11)
        cal.update(accuracy=0.9, sample_count=10)
        assert cal.low_confidence_threshold >= _BOUNDS["low_confidence_threshold"][0]
        assert cal.low_confidence_threshold == pytest.approx(0.10)

    def test_bounds_upper_limit_medium(self):
        """Medium threshold respects its upper bound."""
        cal = SomaticCalibration(medium_confidence_threshold=0.69)
        cal.update(accuracy=0.3, sample_count=10, user_correction=True)
        assert cal.medium_confidence_threshold <= 0.70

    def test_repeated_updates_stay_bounded(self):
        """Multiple low-accuracy updates don't exceed bounds."""
        cal = SomaticCalibration()
        for _ in range(50):
            cal.update(accuracy=0.1, sample_count=10)
        assert cal.high_confidence_threshold <= 0.90
        assert cal.medium_confidence_threshold <= 0.70
        assert cal.low_confidence_threshold <= 0.35


class TestCalibrationRegress:
    """Test SomaticCalibration.regress() — homeostatic recovery."""

    def test_regress_toward_default_from_above(self):
        """Thresholds above default regress downward."""
        cal = SomaticCalibration(high_confidence_threshold=0.85)
        cal.regress(step=0.01)
        assert cal.high_confidence_threshold == pytest.approx(0.84)

    def test_regress_toward_default_from_below(self):
        """Thresholds below default regress upward."""
        cal = SomaticCalibration(high_confidence_threshold=0.65)
        cal.regress(step=0.01)
        assert cal.high_confidence_threshold == pytest.approx(0.66)

    def test_regress_at_default_no_change(self):
        """Thresholds already at default → no change."""
        cal = SomaticCalibration()
        cal.regress(step=0.01)
        assert cal.high_confidence_threshold == 0.75
        assert cal.medium_confidence_threshold == 0.50
        assert cal.low_confidence_threshold == 0.20

    def test_regress_does_not_overshoot(self):
        """Regression stops at default, doesn't cross it."""
        cal = SomaticCalibration(high_confidence_threshold=0.755)
        cal.regress(step=0.01)
        assert cal.high_confidence_threshold == 0.75

    def test_learning_bigger_than_regression(self):
        """Learning step (0.02) > regression step (0.01) — experience wins."""
        cal = SomaticCalibration()
        # Learn: raise by 0.02
        cal.update(accuracy=0.3, sample_count=10)
        assert cal.high_confidence_threshold == pytest.approx(0.77)
        # Regress: lower by 0.01
        cal.regress(step=0.01)
        assert cal.high_confidence_threshold == pytest.approx(0.76)
        # Net: still above default (0.75)
        assert cal.high_confidence_threshold > _INITIAL_DEFAULTS["high_confidence_threshold"]

    def test_multiple_regressions_converge(self):
        """After enough regressions, thresholds return to default."""
        cal = SomaticCalibration(high_confidence_threshold=0.80)
        for _ in range(10):
            cal.regress(step=0.01)
        assert cal.high_confidence_threshold == 0.75
