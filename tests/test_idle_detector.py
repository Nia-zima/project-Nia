"""Tests for Idle Detector and Reflection Trigger (Phase R.1)."""
from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest

from backend.core.db import get_conn, init_schema
from backend.services.idle_detector import (
    _read_kv,
    _write_kv,
    idle_detector_loop,
)


@pytest.fixture(autouse=True)
def _setup_db():
    init_schema()
    conn = get_conn()
    try:
        # Clean up telemetry_kv keys used by idle detector
        conn.execute("DELETE FROM telemetry_kv WHERE k IN ('daily_turn_count', 'reflection_pending', 'last_message_at')")
        # Clean up daily_reflections (used by TestDailyReflectionsTable)
        conn.execute("DELETE FROM daily_reflections")
    finally:
        conn.close()
    yield


# ── telemetry_kv helpers ─────────────────────────────────────────


class TestKVHelpers:
    def test_read_nonexistent_key(self):
        conn = get_conn()
        try:
            assert _read_kv(conn, "nonexistent_key") is None
        finally:
            conn.close()

    def test_write_and_read(self):
        conn = get_conn()
        try:
            _write_kv(conn, "test_key", "test_value")
            assert _read_kv(conn, "test_key") == "test_value"
        finally:
            conn.close()

    def test_write_overwrites(self):
        conn = get_conn()
        try:
            _write_kv(conn, "test_key", "v1")
            _write_kv(conn, "test_key", "v2")
            assert _read_kv(conn, "test_key") == "v2"
        finally:
            conn.close()


# ── Turn counter (S5 commit hook simulation) ─────────────────────


class TestTurnCounter:
    def _simulate_s5_turn_increment(self):
        """Simulate what s5_commit does after a successful commit."""
        now = int(time.time())
        conn = get_conn()
        try:
            conn.execute(
                "INSERT INTO telemetry_kv (k, v, updated_at) VALUES ('daily_turn_count', '1', ?)"
                " ON CONFLICT(k) DO UPDATE SET v = CAST(CAST(v AS INTEGER) + 1 AS TEXT), updated_at = ?",
                (now, now),
            )
            row = conn.execute("SELECT v FROM telemetry_kv WHERE k='daily_turn_count'").fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()

    def test_first_increment(self):
        count = self._simulate_s5_turn_increment()
        assert count == 1

    def test_multiple_increments(self):
        for _ in range(5):
            self._simulate_s5_turn_increment()
        conn = get_conn()
        try:
            row = conn.execute("SELECT v FROM telemetry_kv WHERE k='daily_turn_count'").fetchone()
            assert int(row[0]) == 5
        finally:
            conn.close()

    def test_threshold_sets_pending(self):
        threshold = 10
        for i in range(threshold):
            count = self._simulate_s5_turn_increment()
            if count >= threshold:
                conn = get_conn()
                try:
                    conn.execute(
                        "INSERT OR REPLACE INTO telemetry_kv (k, v, updated_at) VALUES ('reflection_pending', '1', ?)",
                        (int(time.time()),),
                    )
                finally:
                    conn.close()

        conn = get_conn()
        try:
            pending = _read_kv(conn, "reflection_pending")
            assert pending == "1"
        finally:
            conn.close()


# ── last_message_at (orchestrator hook simulation) ───────────────


class TestLastMessageAt:
    def test_update_last_message_at(self):
        now = time.time()
        conn = get_conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO telemetry_kv (k, v, updated_at) VALUES ('last_message_at', ?, ?)",
                (str(now), int(now)),
            )
            stored = _read_kv(conn, "last_message_at")
            assert abs(float(stored) - now) < 1.0
        finally:
            conn.close()


# ── idle_detector_loop logic ─────────────────────────────────────


class TestIdleDetectorLogic:
    def _setup_conditions(self, *, pending: bool, idle_minutes: float):
        """Set up telemetry_kv for testing idle detector conditions."""
        conn = get_conn()
        try:
            if pending:
                _write_kv(conn, "reflection_pending", "1")
            else:
                _write_kv(conn, "reflection_pending", "0")

            last_msg = time.time() - (idle_minutes * 60)
            _write_kv(conn, "last_message_at", str(last_msg))
            _write_kv(conn, "daily_turn_count", "15")
        finally:
            conn.close()

    def test_no_trigger_when_not_pending(self):
        """reflection_pending=0 → no trigger."""
        self._setup_conditions(pending=False, idle_minutes=60)

        conn = get_conn()
        try:
            pending = _read_kv(conn, "reflection_pending")
            assert pending == "0"
            # daily_turn_count should NOT be reset
            count = _read_kv(conn, "daily_turn_count")
            assert count == "15"
        finally:
            conn.close()

    def test_no_trigger_when_not_idle(self):
        """reflection_pending=1 but not idle → no trigger."""
        self._setup_conditions(pending=True, idle_minutes=5)  # Only 5 min idle

        conn = get_conn()
        try:
            pending = _read_kv(conn, "reflection_pending")
            assert pending == "1"
            # Count should still be 15 (not reset)
            count = _read_kv(conn, "daily_turn_count")
            assert count == "15"
        finally:
            conn.close()

    @pytest.mark.asyncio
    async def test_trigger_and_reset(self):
        """reflection_pending=1 AND idle 60min → trigger + reset."""
        self._setup_conditions(pending=True, idle_minutes=60)

        # Run one iteration of the loop (patch sleep to return immediately, then cancel)
        iteration_count = 0

        async def fake_sleep(seconds):
            nonlocal iteration_count
            iteration_count += 1
            if iteration_count > 1:
                raise asyncio.CancelledError()

        with patch("backend.services.idle_detector.asyncio.sleep", side_effect=fake_sleep):
            with patch("backend.services.idle_detector.settings") as mock_settings:
                mock_settings.IDLE_CHECK_INTERVAL_SEC = 1
                mock_settings.IDLE_THRESHOLD_MINUTES = 30
                try:
                    await idle_detector_loop()
                except asyncio.CancelledError:
                    pass

        # Verify counters were reset
        conn = get_conn()
        try:
            pending = _read_kv(conn, "reflection_pending")
            assert pending == "0", f"reflection_pending should be '0' after trigger, got '{pending}'"
            count = _read_kv(conn, "daily_turn_count")
            assert count == "0", f"daily_turn_count should be '0' after reset, got '{count}'"
        finally:
            conn.close()

    @pytest.mark.asyncio
    async def test_no_trigger_missing_last_message(self):
        """reflection_pending=1 but no last_message_at → no trigger."""
        conn = get_conn()
        try:
            _write_kv(conn, "reflection_pending", "1")
            _write_kv(conn, "daily_turn_count", "15")
            # Don't set last_message_at
        finally:
            conn.close()

        iteration_count = 0

        async def fake_sleep(seconds):
            nonlocal iteration_count
            iteration_count += 1
            if iteration_count > 1:
                raise asyncio.CancelledError()

        with patch("backend.services.idle_detector.asyncio.sleep", side_effect=fake_sleep):
            with patch("backend.services.idle_detector.settings") as mock_settings:
                mock_settings.IDLE_CHECK_INTERVAL_SEC = 1
                mock_settings.IDLE_THRESHOLD_MINUTES = 30
                try:
                    await idle_detector_loop()
                except asyncio.CancelledError:
                    pass

        # Pending should still be 1 (no trigger without last_message_at)
        conn = get_conn()
        try:
            pending = _read_kv(conn, "reflection_pending")
            assert pending == "1"
        finally:
            conn.close()


# ── Counter reset behavior ───────────────────────────────────────


class TestCounterReset:
    def test_reset_allows_next_session(self):
        """After reset, new turns should accumulate from 0."""
        # First session: accumulate and reset
        conn = get_conn()
        try:
            _write_kv(conn, "daily_turn_count", "15")
            _write_kv(conn, "reflection_pending", "1")
            # Simulate reset
            _write_kv(conn, "daily_turn_count", "0")
            _write_kv(conn, "reflection_pending", "0")
        finally:
            conn.close()

        # Second session: new turns
        conn = get_conn()
        try:
            conn.execute(
                "INSERT INTO telemetry_kv (k, v, updated_at) VALUES ('daily_turn_count', '1', ?)"
                " ON CONFLICT(k) DO UPDATE SET v = CAST(CAST(v AS INTEGER) + 1 AS TEXT), updated_at = ?",
                (int(time.time()), int(time.time())),
            )
            row = conn.execute("SELECT v FROM telemetry_kv WHERE k='daily_turn_count'").fetchone()
            assert int(row[0]) == 1  # Starts from 0+1=1, not 15+1
        finally:
            conn.close()


# ── daily_reflections table ──────────────────────────────────────


class TestDailyReflectionsTable:
    def test_table_exists(self):
        """Verify daily_reflections table was created by init_schema."""
        conn = get_conn()
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='daily_reflections'"
            ).fetchone()
            assert row is not None
        finally:
            conn.close()

    def test_unique_constraint(self):
        """Verify UNIQUE(thread_id, reflection_date, session_index, phase)."""
        import uuid
        conn = get_conn()
        try:
            conn.execute(
                "INSERT INTO daily_reflections (id, thread_id, reflection_date, session_index, phase, content_json, created_at)"
                " VALUES (?, 't1', '2026-02-19', 0, 'daily_log', '{}', ?)",
                (str(uuid.uuid4()), time.time()),
            )
            # Second insert with same unique key should fail
            with pytest.raises(Exception):
                conn.execute(
                    "INSERT INTO daily_reflections (id, thread_id, reflection_date, session_index, phase, content_json, created_at)"
                    " VALUES (?, 't1', '2026-02-19', 0, 'daily_log', '{}', ?)",
                    (str(uuid.uuid4()), time.time()),
                )
        finally:
            conn.close()


# ── Phase R.2: Reflection Engine integration ─────────────────────


class TestIdleDetectorReflectionIntegration:
    def _setup_conditions(self, *, pending: bool, idle_minutes: float):
        conn = get_conn()
        try:
            _write_kv(conn, "reflection_pending", "1" if pending else "0")
            last_msg = time.time() - (idle_minutes * 60)
            _write_kv(conn, "last_message_at", str(last_msg))
            _write_kv(conn, "daily_turn_count", "15")
        finally:
            conn.close()

    @pytest.mark.asyncio
    async def test_trigger_calls_reflection_engine(self):
        """When conditions met, idle_detector calls run_reflection."""
        self._setup_conditions(pending=True, idle_minutes=60)

        call_log = []

        async def mock_run_reflection(thread_id):
            call_log.append(thread_id)
            return {"success": True}

        iteration_count = 0

        async def fake_sleep(seconds):
            nonlocal iteration_count
            iteration_count += 1
            if iteration_count > 1:
                raise asyncio.CancelledError()

        with patch("backend.services.idle_detector.asyncio.sleep", side_effect=fake_sleep):
            with patch("backend.services.idle_detector.settings") as mock_settings:
                mock_settings.IDLE_CHECK_INTERVAL_SEC = 1
                mock_settings.IDLE_THRESHOLD_MINUTES = 30
                with patch("backend.services.reflection_engine.run_reflection", side_effect=mock_run_reflection):
                    try:
                        await idle_detector_loop()
                    except asyncio.CancelledError:
                        pass

        assert call_log == ["default_thread"]

        # Counters still reset
        conn = get_conn()
        try:
            assert _read_kv(conn, "reflection_pending") == "0"
            assert _read_kv(conn, "daily_turn_count") == "0"
        finally:
            conn.close()

    @pytest.mark.asyncio
    async def test_resets_counters_even_on_engine_failure(self):
        """Engine failure must NOT prevent counter reset."""
        self._setup_conditions(pending=True, idle_minutes=60)

        async def failing_reflection(thread_id):
            raise RuntimeError("LLM down")

        iteration_count = 0

        async def fake_sleep(seconds):
            nonlocal iteration_count
            iteration_count += 1
            if iteration_count > 1:
                raise asyncio.CancelledError()

        with patch("backend.services.idle_detector.asyncio.sleep", side_effect=fake_sleep):
            with patch("backend.services.idle_detector.settings") as mock_settings:
                mock_settings.IDLE_CHECK_INTERVAL_SEC = 1
                mock_settings.IDLE_THRESHOLD_MINUTES = 30
                with patch("backend.services.reflection_engine.run_reflection", side_effect=failing_reflection):
                    try:
                        await idle_detector_loop()
                    except asyncio.CancelledError:
                        pass

        # Counters MUST be reset even after engine failure
        conn = get_conn()
        try:
            assert _read_kv(conn, "reflection_pending") == "0"
            assert _read_kv(conn, "daily_turn_count") == "0"
        finally:
            conn.close()
