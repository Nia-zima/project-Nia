"""Tests for backend.core.niacore.shadow — shadow inference + graduation."""
from __future__ import annotations

import time
from unittest.mock import patch, MagicMock

import pytest

torch = pytest.importorskip("torch")
ncps = pytest.importorskip("ncps")

from backend.core.niacore.shadow import (
    ShadowResult,
    shadow_infer,
    check_graduation,
    reset_model,
    _GRAD_MIN_DAYS,
    _GRAD_MIN_TURNS,
)
from backend.core.niacore.model import DEPTH_LABELS


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_model()
    yield
    reset_model()


class TestShadowInfer:
    def test_basic_inference(self):
        result = shadow_infer(
            user_text="こんにちは",
            messages=[{"role": "user", "content": "hello"}],
            rule_based_depth="0",
        )
        assert result is not None
        assert isinstance(result, ShadowResult)
        assert result.niacore_selected in DEPTH_LABELS
        assert result.rule_based_depth == "D0"
        assert len(result.state_vector_blob) == 136
        assert len(result.depth_preference) == 4

    def test_deviation_detection(self):
        """If CfC selects different from rule-based, is_deviation should be True."""
        # We can't control CfC output deterministically, but we can verify the logic
        result = shadow_infer(
            user_text="test",
            messages=[],
            rule_based_depth="2",
        )
        assert result is not None
        if result.niacore_selected != "D2":
            assert result.is_deviation is True
        else:
            assert result.is_deviation is False

    def test_depth_label_normalization(self):
        """rule_based_depth "0" → "D0", "1" → "D1" etc."""
        result = shadow_infer(
            user_text="test",
            messages=[],
            rule_based_depth="1",
        )
        assert result is not None
        assert result.rule_based_depth == "D1"

    def test_returns_none_on_error(self):
        """Should return None if model fails, not raise."""
        with patch("backend.core.niacore.shadow.load_or_create_model", side_effect=RuntimeError("fail")):
            reset_model()
            result = shadow_infer(
                user_text="test",
                messages=[],
                rule_based_depth="0",
            )
            assert result is None

    def test_disabled_returns_none_when_not_called(self):
        """Verify shadow_infer is a normal function that returns ShadowResult."""
        result = shadow_infer(
            user_text="",
            messages=[],
            rule_based_depth="0",
        )
        # Even with empty input, should still work
        assert result is not None


class TestGraduation:
    def _setup_db(self, conn, *, total: int, days: int, agreements: int,
                   deviations: int = 0, deviation_successes: int = 0):
        """Insert mock rows into niacore_experience."""
        import uuid
        now = time.time()
        for i in range(total):
            depth = DEPTH_LABELS[i % 4]
            is_dev = 1 if i < deviations else 0
            is_agreement = 0 if is_dev else 1
            day_offset = (i % days) * 86400
            conn.execute(
                """INSERT INTO niacore_experience
                   (id, turn_id, session_id, timestamp,
                    rule_based_depth, niacore_selected, is_deviation,
                    review_rejected, review_checked, user_correction,
                    correction_window_closed, conversation_continued,
                    created_at)
                   VALUES (?, ?, 'sess', ?, 'D0', ?, ?, 0, 1, 0, 1, 1, ?)""",
                (
                    uuid.uuid4().hex, f"turn_{i}", now - day_offset,
                    depth, is_dev, now - day_offset,
                ),
            )

    def test_insufficient_turns(self):
        """Should not be eligible with < 500 turns."""
        status = check_graduation()
        assert status.eligible is False
        assert any("turns" in r for r in status.reasons)

    def test_graduation_status_structure(self):
        status = check_graduation()
        d = status.to_dict()
        assert "eligible" in d
        assert "days_active" in d
        assert "total_turns" in d
        assert "agreement_rate" in d
        assert "reasons" in d
