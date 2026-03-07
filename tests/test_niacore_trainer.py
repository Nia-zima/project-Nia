"""Tests for backend.core.niacore.trainer — reward computation + batch learning."""
from __future__ import annotations

import time
import uuid
from unittest.mock import patch

import pytest

from backend.core.niacore.trainer import (
    _REWARD_TABLE,
    _determine_event_type,
    compute_rewards,
    mark_conversation_continued,
)

torch = pytest.importorskip("torch")
ncps = pytest.importorskip("ncps")


@pytest.fixture(autouse=True)
def _clean_niacore_table():
    """Clean niacore_experience between tests."""
    from backend.core.db import managed_conn
    with managed_conn() as conn:
        conn.execute("DELETE FROM niacore_experience")
    yield
    with managed_conn() as conn:
        conn.execute("DELETE FROM niacore_experience")


# ── Helpers ──────────────────────────────────────────────────

def _insert_experience(conn, **overrides) -> str:
    """Insert a test row and return its id."""
    row_id = uuid.uuid4().hex
    now = time.time()
    defaults = {
        "id": row_id,
        "turn_id": f"turn_{row_id[:8]}",
        "session_id": "test_session",
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
        "conversation_continued": 0,
        "surprise_v": 0,
        "reward": None,
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


# ── Event Type Classification ────────────────────────────────

class TestDetermineEventType:
    def test_rejected(self):
        assert _determine_event_type({
            "review_rejected": True, "user_correction": False,
            "is_deviation": False, "conversation_continued": False,
        }) == "rejected"

    def test_correction(self):
        assert _determine_event_type({
            "review_rejected": False, "user_correction": True,
            "is_deviation": False, "conversation_continued": False,
        }) == "correction"

    def test_deviation_success(self):
        assert _determine_event_type({
            "review_rejected": False, "user_correction": False,
            "is_deviation": True, "conversation_continued": True,
        }) == "deviation_success"

    def test_agreement_continued(self):
        assert _determine_event_type({
            "review_rejected": False, "user_correction": False,
            "is_deviation": False, "conversation_continued": True,
        }) == "agreement_continued"

    def test_unknown(self):
        assert _determine_event_type({
            "review_rejected": False, "user_correction": False,
            "is_deviation": False, "conversation_continued": False,
        }) == "unknown"


# ── Reward Values ────────────────────────────────────────────

class TestRewardTable:
    def test_rejected_negative(self):
        assert _REWARD_TABLE["rejected"] == -1.0

    def test_correction_negative(self):
        assert _REWARD_TABLE["correction"] == -0.8

    def test_deviation_success_positive(self):
        assert _REWARD_TABLE["deviation_success"] == 1.0

    def test_agreement_small_positive(self):
        assert _REWARD_TABLE["agreement_continued"] == 0.1

    def test_unknown_zero(self):
        assert _REWARD_TABLE["unknown"] == 0.0


# ── Mark Conversation Continued ──────────────────────────────

class TestMarkConversationContinued:
    def test_marks_eligible_rows(self):
        from backend.core.db import managed_conn
        with managed_conn() as conn:
            # Eligible: window closed, not rejected, not corrected
            _insert_experience(conn, correction_window_closed=1,
                               review_rejected=0, user_correction=0,
                               conversation_continued=0, reward=None)
            # Not eligible: still rejected
            _insert_experience(conn, correction_window_closed=1,
                               review_rejected=1, user_correction=0,
                               conversation_continued=0, reward=None)

        count = mark_conversation_continued()
        assert count == 1

    def test_idempotent(self):
        from backend.core.db import managed_conn
        with managed_conn() as conn:
            _insert_experience(conn, correction_window_closed=1,
                               review_rejected=0, user_correction=0,
                               conversation_continued=0, reward=None)
        count1 = mark_conversation_continued()
        count2 = mark_conversation_continued()
        assert count1 == 1
        assert count2 == 0  # Already marked


# ── Compute Rewards ──────────────────────────────────────────

class TestComputeRewards:
    def test_basic_reward(self):
        from backend.core.db import managed_conn
        with managed_conn() as conn:
            _insert_experience(conn, correction_window_closed=1,
                               review_rejected=1, conversation_continued=0)

        rewarded = compute_rewards()
        assert rewarded == 1

        with managed_conn() as conn:
            row = conn.execute(
                "SELECT reward FROM niacore_experience WHERE reward IS NOT NULL"
            ).fetchone()
            assert row is not None
            assert row["reward"] == -1.0  # rejected

    def test_no_double_reward(self):
        from backend.core.db import managed_conn
        with managed_conn() as conn:
            _insert_experience(conn, correction_window_closed=1,
                               review_rejected=0, user_correction=0,
                               conversation_continued=1)

        rewarded1 = compute_rewards()
        rewarded2 = compute_rewards()
        assert rewarded1 == 1
        assert rewarded2 == 0  # Already rewarded


# ── Training (integration) ───────────────────────────────────

class TestRunTraining:
    @pytest.mark.asyncio
    async def test_insufficient_data_skips(self):
        from backend.core.niacore.trainer import run_training
        result = await run_training(batch_size=32)
        assert result is not None
        assert result.skipped is True
        assert "insufficient" in result.skip_reason

    @pytest.mark.asyncio
    async def test_training_with_enough_data(self):
        """Full training loop with synthetic data."""
        from backend.core.db import managed_conn
        from backend.core.niacore.model import StateVector, build_state_vector
        from backend.core.niacore.trainer import run_training

        # Insert 40 rows with state vectors
        with managed_conn() as conn:
            for i in range(40):
                sv = build_state_vector(user_text=f"test message {i}")
                _insert_experience(
                    conn,
                    state_vector=sv.to_blob(),
                    niacore_selected="D0",
                    rule_based_depth="0",
                    is_deviation=0,
                    correction_window_closed=1,
                    conversation_continued=1,
                    reward=0.1,
                    used_in_training=0,
                )

        result = await run_training(batch_size=32, epochs=2)
        assert result is not None
        assert result.skipped is False
        assert result.rows_used == 40
        assert result.epochs == 2
        assert result.final_loss >= 0

        # Verify rows marked as used
        with managed_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM niacore_experience WHERE used_in_training = 1"
            ).fetchone()
            assert row[0] >= 40
