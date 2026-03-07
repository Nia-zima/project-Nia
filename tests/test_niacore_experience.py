"""Tests for NiaCore Experience Replay Buffer (Steps 3, 2, 1)."""
from __future__ import annotations

import uuid

import pytest

from backend.core.db import managed_conn, init_schema
from backend.core.niacore.experience_writer import (
    record_turn_experience,
    close_correction_window,
)


# ── Step 3: basic recording ──────────────────────────────────────


class TestRecordTurnExperience:
    def test_record_basic(self):
        """Insert a row and read it back."""
        turn_id = uuid.uuid4().hex
        row_id = record_turn_experience(
            turn_id=turn_id,
            session_id="sess_test",
            rule_based_depth="1",
        )
        assert row_id is not None

        with managed_conn() as conn:
            row = conn.execute(
                "SELECT turn_id, session_id, rule_based_depth, "
                "review_rejected, review_checked, user_correction, "
                "correction_window_closed "
                "FROM niacore_experience WHERE id = ?",
                (row_id,),
            ).fetchone()

        assert row is not None
        assert row[0] == turn_id
        assert row[1] == "sess_test"
        assert row[2] == "1"
        # Defaults
        assert row[3] == 0  # review_rejected
        assert row[4] == 1  # review_checked (default True)
        assert row[5] == 0  # user_correction
        assert row[6] == 0  # correction_window_closed

    def test_review_rejected_recorded(self):
        """Step 2: review_rejected=True is persisted."""
        turn_id = uuid.uuid4().hex
        row_id = record_turn_experience(
            turn_id=turn_id,
            rule_based_depth="0",
            review_rejected=True,
        )
        assert row_id is not None

        with managed_conn() as conn:
            row = conn.execute(
                "SELECT review_rejected FROM niacore_experience WHERE id = ?",
                (row_id,),
            ).fetchone()

        assert row[0] == 1

    def test_review_not_rejected(self):
        """Step 2: review_rejected defaults to False."""
        turn_id = uuid.uuid4().hex
        row_id = record_turn_experience(
            turn_id=turn_id,
            rule_based_depth="0",
        )

        with managed_conn() as conn:
            row = conn.execute(
                "SELECT review_rejected FROM niacore_experience WHERE id = ?",
                (row_id,),
            ).fetchone()

        assert row[0] == 0

    def test_multiple_rows_same_turn_id(self):
        """Multiple experience rows with the same turn_id are allowed."""
        turn_id = uuid.uuid4().hex
        id1 = record_turn_experience(turn_id=turn_id, rule_based_depth="0")
        id2 = record_turn_experience(turn_id=turn_id, rule_based_depth="1")
        assert id1 != id2


# ── Step 1: correction window ────────────────────────────────────


class TestCloseCorrectionWindow:
    def test_close_with_correction(self):
        """close_correction_window sets user_correction and closes window."""
        turn_id = uuid.uuid4().hex
        row_id = record_turn_experience(
            turn_id=turn_id,
            rule_based_depth="0",
        )

        updated = close_correction_window(turn_id, user_correction=True)
        assert updated is True

        with managed_conn() as conn:
            row = conn.execute(
                "SELECT user_correction, correction_window_closed "
                "FROM niacore_experience WHERE id = ?",
                (row_id,),
            ).fetchone()

        assert row[0] == 1  # user_correction
        assert row[1] == 1  # correction_window_closed

    def test_close_without_correction(self):
        """close_correction_window with no correction still closes the window."""
        turn_id = uuid.uuid4().hex
        row_id = record_turn_experience(
            turn_id=turn_id,
            rule_based_depth="1",
        )

        updated = close_correction_window(turn_id, user_correction=False)
        assert updated is True

        with managed_conn() as conn:
            row = conn.execute(
                "SELECT user_correction, correction_window_closed "
                "FROM niacore_experience WHERE id = ?",
                (row_id,),
            ).fetchone()

        assert row[0] == 0  # user_correction
        assert row[1] == 1  # correction_window_closed

    def test_close_idempotent(self):
        """Closing an already-closed window returns False (no update)."""
        turn_id = uuid.uuid4().hex
        record_turn_experience(turn_id=turn_id, rule_based_depth="0")
        close_correction_window(turn_id, user_correction=False)

        # Second close should not update
        updated = close_correction_window(turn_id, user_correction=True)
        assert updated is False

    def test_close_nonexistent_turn(self):
        """Closing a window for a nonexistent turn returns False."""
        updated = close_correction_window("nonexistent", user_correction=True)
        assert updated is False


# ── DB failure resilience ────────────────────────────────────────


class TestDbResilience:
    def test_record_failure_returns_none(self, monkeypatch):
        """record_turn_experience returns None on DB failure, no exception."""
        from backend.core.niacore import experience_writer

        def _boom():
            raise RuntimeError("DB gone")

        monkeypatch.setattr(experience_writer, "managed_conn", _boom)
        result = record_turn_experience(
            turn_id="fail", rule_based_depth="0",
        )
        assert result is None

    def test_close_failure_returns_false(self, monkeypatch):
        """close_correction_window returns False on DB failure."""
        from backend.core.niacore import experience_writer

        def _boom():
            raise RuntimeError("DB gone")

        monkeypatch.setattr(experience_writer, "managed_conn", _boom)
        result = close_correction_window("fail", user_correction=True)
        assert result is False
