"""Tests for backend.core.niacore.health — runaway detection + regression."""
from __future__ import annotations

import time
import uuid

import pytest

torch = pytest.importorskip("torch")
ncps = pytest.importorskip("ncps")

from backend.core.niacore.health import (
    LEVEL_NORMAL,
    LEVEL_ACCELERATED,
    LEVEL_ROLLBACK,
    HealthReport,
    run_health_check,
    apply_regression,
    save_checkpoint_if_healthy,
)


@pytest.fixture(autouse=True)
def _clean_niacore_table():
    """Clean niacore_experience between tests."""
    from backend.core.db import managed_conn
    with managed_conn() as conn:
        conn.execute("DELETE FROM niacore_experience")
    yield
    with managed_conn() as conn:
        conn.execute("DELETE FROM niacore_experience")


def _insert_health_row(conn, **overrides):
    """Insert a test row for health checks."""
    row_id = uuid.uuid4().hex
    now = time.time()
    defaults = {
        "id": row_id,
        "turn_id": f"turn_{row_id[:8]}",
        "session_id": "health_test",
        "timestamp": now,
        "rule_based_depth": "0",
        "state_vector": None,
        "niacore_selected": "D0",
        "niacore_logits": None,
        "is_deviation": 0,
        "review_rejected": 0,
        "review_checked": 1,
        "user_correction": 0,
        "correction_window_closed": 1,
        "conversation_continued": 1,
        "surprise_v": 2,
        "reward": 0.1,
        "used_in_training": 0,
        "created_at": now,
    }
    defaults.update(overrides)
    cols = ", ".join(defaults.keys())
    placeholders = ", ".join("?" * len(defaults))
    conn.execute(
        f"INSERT INTO niacore_experience ({cols}) VALUES ({placeholders})",
        tuple(defaults.values()),
    )
    return row_id


class TestHealthCheck:
    def test_empty_db_returns_normal(self):
        report = run_health_check()
        assert report.level == LEVEL_NORMAL

    def test_healthy_distribution(self):
        """Balanced depth distribution should be L0."""
        from backend.core.db import managed_conn
        labels = ["D0", "D1", "D2", "WAIT"]
        with managed_conn() as conn:
            for i in range(40):
                _insert_health_row(conn, niacore_selected=labels[i % 4])
        report = run_health_check()
        assert report.level == LEVEL_NORMAL

    def test_depth_drift_triggers(self):
        """All-D0 distribution should trigger depth_drift."""
        from backend.core.db import managed_conn
        with managed_conn() as conn:
            for _ in range(50):
                _insert_health_row(conn, niacore_selected="D0")
        report = run_health_check()
        drift_indicators = [ind for ind in report.indicators if ind.name == "depth_drift"]
        assert any(ind.triggered for ind in drift_indicators)

    def test_correction_spike_triggers(self):
        """High correction rate should trigger."""
        from backend.core.db import managed_conn
        with managed_conn() as conn:
            for _ in range(40):
                _insert_health_row(conn, user_correction=1, niacore_selected="D0")
        report = run_health_check()
        spike_indicators = [ind for ind in report.indicators if ind.name == "correction_spike"]
        assert any(ind.triggered for ind in spike_indicators)

    def test_report_to_dict(self):
        report = run_health_check()
        d = report.to_dict()
        assert "level" in d
        assert "triggered_count" in d
        assert "indicators" in d

    def test_multiple_triggers_escalate(self):
        """Many anomalies should escalate to L1 or L2."""
        from backend.core.db import managed_conn
        with managed_conn() as conn:
            for _ in range(50):
                _insert_health_row(
                    conn,
                    niacore_selected="D0",      # depth drift
                    user_correction=1,           # correction spike
                    review_rejected=1,           # rejected rate
                )
        report = run_health_check()
        assert report.level >= LEVEL_ACCELERATED


class TestRegression:
    def test_l0_natural_decay(self):
        """L0 should apply minimal regression without error."""
        apply_regression(LEVEL_NORMAL)

    def test_l1_accelerated(self):
        """L1 should apply stronger regression without error."""
        apply_regression(LEVEL_ACCELERATED)

    def test_l2_rollback_no_checkpoint(self):
        """L2 with no checkpoint should log warning but not raise."""
        apply_regression(LEVEL_ROLLBACK)


class TestCheckpointSave:
    def test_skipped_training_no_save(self):
        from backend.core.niacore.trainer import TrainingResult
        result = TrainingResult(rows_used=0, epochs=0, final_loss=0.0,
                                elapsed_sec=0.0, skipped=True)
        assert save_checkpoint_if_healthy(result) is False

    def test_none_result_no_save(self):
        assert save_checkpoint_if_healthy(None) is False
