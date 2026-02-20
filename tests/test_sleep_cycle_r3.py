"""Tests for Sleep Cycle R.3 refactor (daily_reflections input + semantic extraction skip)."""
from __future__ import annotations

import json
import os
import time
import uuid

os.environ.setdefault("RETENTION_PROFILE", "fast")

import pytest

from backend.core.db import get_conn, init_schema


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _setup_db():
    init_schema()
    conn = get_conn()
    try:
        conn.execute("DELETE FROM memory_index")
        conn.execute("DELETE FROM memory_events")
        conn.execute("DELETE FROM semantic_memories")
        conn.execute("DELETE FROM daily_reflections")
        conn.execute("DELETE FROM telemetry_kv")
    finally:
        conn.close()
    yield


# ── Helpers ───────────────────────────────────────────────────────


def _insert_daily_reflection(
    thread_id: str,
    reflection_date: str,
    session_index: int,
    phase: str,
    content: dict,
    turn_count: int = 5,
):
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO daily_reflections
               (id, thread_id, reflection_date, session_index, phase,
                content_json, turn_count, token_count, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)""",
            (
                uuid.uuid4().hex,
                thread_id,
                reflection_date,
                session_index,
                phase,
                json.dumps(content, ensure_ascii=False),
                turn_count,
                time.time(),
            ),
        )
    finally:
        conn.close()


def _insert_event(thread_id: str, user_text: str, ai_response: str, *, created_at: float | None = None):
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO memory_events
               (event_id, thread_id, event_type, payload_json, created_at, schema_version)
               VALUES (?, ?, 'conversation_turn', ?, ?, 1)""",
            (
                uuid.uuid4().hex,
                thread_id,
                json.dumps({"user_text": user_text, "ai_response": ai_response}),
                created_at or time.time(),
            ),
        )
    finally:
        conn.close()


SAMPLE_DAILY_LOG = {
    "summary": "Memory Retrievalの設計を進めた。Query-Awareのアーキテクチャを議論。",
    "key_topics": ["Memory Retrieval", "Query-Aware Retrieval"],
    "emotional_moments": ["設計が決まった時にOriginが満足していた"],
    "unresolved": ["Phase M.2 の Pinned Reorder"],
}


# ── Tests ─────────────────────────────────────────────────────────


class TestBuildMemoryBlockFromReflections:
    def test_basic_output(self):
        """_build_memory_block_from_reflections produces summary/topics/moments."""
        from backend.scripts.sleep_cycle import _build_memory_block_from_reflections

        daily_logs = [
            {"content_json": json.dumps(SAMPLE_DAILY_LOG, ensure_ascii=False)},
        ]
        result = _build_memory_block_from_reflections(daily_logs)

        assert "Memory Retrieval" in result
        assert "Query-Aware Retrieval" in result
        assert "話題:" in result
        assert "印象:" in result

    def test_multiple_sessions(self):
        """Multiple daily_logs combine into one memory_block."""
        from backend.scripts.sleep_cycle import _build_memory_block_from_reflections

        log2 = {
            "summary": "Minecraftボットの実装を進めた。",
            "key_topics": ["Minecraft", "mineflayer"],
            "emotional_moments": [],
            "unresolved": [],
        }
        daily_logs = [
            {"content_json": json.dumps(SAMPLE_DAILY_LOG, ensure_ascii=False)},
            {"content_json": json.dumps(log2, ensure_ascii=False)},
        ]
        result = _build_memory_block_from_reflections(daily_logs)

        assert "Memory Retrieval" in result
        assert "Minecraft" in result

    def test_empty_input(self):
        """Empty list returns empty string."""
        from backend.scripts.sleep_cycle import _build_memory_block_from_reflections
        assert _build_memory_block_from_reflections([]) == ""

    def test_malformed_json_skipped(self):
        """Malformed content_json is skipped gracefully."""
        from backend.scripts.sleep_cycle import _build_memory_block_from_reflections

        daily_logs = [
            {"content_json": "not valid json"},
            {"content_json": json.dumps(SAMPLE_DAILY_LOG, ensure_ascii=False)},
        ]
        result = _build_memory_block_from_reflections(daily_logs)
        # First entry skipped, second processed
        assert "Memory Retrieval" in result


class TestSleepCycleR3Integration:
    """Integration tests verifying sleep_cycle uses daily_reflections when available."""

    @pytest.mark.asyncio
    async def test_uses_daily_reflections_when_available(self, monkeypatch):
        """When daily_reflections exist, sleep_cycle uses them instead of memory_events."""
        from datetime import date

        today = date.today().isoformat()
        _insert_daily_reflection(
            "default_thread", today, 0, "daily_log", SAMPLE_DAILY_LOG, turn_count=3,
        )

        captured_block = {}

        # Mock layer_a to capture memory_block
        original_layer_a = None

        async def mock_layer_a(identity, memory_block):
            captured_block["memory_block"] = memory_block
            return {"impressions": [], "mood": "neutral", "surprise": None}

        # Mock everything that sleep_cycle calls
        monkeypatch.setattr("backend.scripts.sleep_cycle.layer_a_impression_record", mock_layer_a)
        monkeypatch.setattr(
            "backend.scripts.sleep_cycle.identity_manager",
            type("FakeIM", (), {"get_identity": staticmethod(lambda: "fake identity")})(),
        )

        # Mock layer_b to prevent actual LLM calls
        async def mock_layer_b(identity, memory_block):
            return (False, {}, 0, 0)

        monkeypatch.setattr("backend.scripts.sleep_cycle.layer_b_guardian_proposal", mock_layer_b)
        monkeypatch.setattr("backend.scripts.sleep_cycle.layer_b_guardian_adaptive", mock_layer_b)

        # Prevent semantic extraction, confirm, etc.
        monkeypatch.setattr("backend.scripts.sleep_cycle._extract_semantics_from_episodic", lambda: None)

        from backend.scripts.sleep_cycle import integrated_sleep_cycle
        await integrated_sleep_cycle()

        # Verify memory_block came from daily_reflections
        assert "memory_block" in captured_block
        assert "Memory Retrieval" in captured_block["memory_block"]

    @pytest.mark.asyncio
    async def test_falls_back_to_memory_events(self, monkeypatch):
        """When no daily_reflections exist, sleep_cycle falls back to memory_events."""
        _insert_event("default_thread", "テスト会話", "テスト回答")

        captured_block = {}

        async def mock_layer_a(identity, memory_block):
            captured_block["memory_block"] = memory_block
            return {"impressions": [], "mood": "neutral", "surprise": None}

        monkeypatch.setattr("backend.scripts.sleep_cycle.layer_a_impression_record", mock_layer_a)
        monkeypatch.setattr(
            "backend.scripts.sleep_cycle.identity_manager",
            type("FakeIM", (), {"get_identity": staticmethod(lambda: "fake identity")})(),
        )

        async def mock_layer_b(identity, memory_block):
            return (False, {}, 0, 0)

        monkeypatch.setattr("backend.scripts.sleep_cycle.layer_b_guardian_proposal", mock_layer_b)
        monkeypatch.setattr("backend.scripts.sleep_cycle.layer_b_guardian_adaptive", mock_layer_b)
        monkeypatch.setattr("backend.scripts.sleep_cycle._extract_semantics_from_episodic", lambda: None)

        from backend.scripts.sleep_cycle import integrated_sleep_cycle
        await integrated_sleep_cycle()

        assert "memory_block" in captured_block
        assert "テスト会話" in captured_block["memory_block"]

    @pytest.mark.asyncio
    async def test_skips_semantic_extraction_with_reflections(self, monkeypatch, caplog):
        """When daily_reflections exist, _extract_semantics_from_episodic is NOT called."""
        from datetime import date
        import logging

        today = date.today().isoformat()
        _insert_daily_reflection(
            "default_thread", today, 0, "daily_log", SAMPLE_DAILY_LOG, turn_count=3,
        )

        extract_called = {"count": 0}

        async def mock_extract():
            extract_called["count"] += 1
            return 0

        monkeypatch.setattr("backend.scripts.sleep_cycle._extract_semantics_from_episodic", mock_extract)

        async def mock_layer_a(identity, memory_block):
            return {"impressions": [], "mood": "neutral", "surprise": None}

        monkeypatch.setattr("backend.scripts.sleep_cycle.layer_a_impression_record", mock_layer_a)
        monkeypatch.setattr(
            "backend.scripts.sleep_cycle.identity_manager",
            type("FakeIM", (), {"get_identity": staticmethod(lambda: "fake identity")})(),
        )

        async def mock_layer_b(identity, memory_block):
            return (False, {}, 0, 0)

        monkeypatch.setattr("backend.scripts.sleep_cycle.layer_b_guardian_proposal", mock_layer_b)
        monkeypatch.setattr("backend.scripts.sleep_cycle.layer_b_guardian_adaptive", mock_layer_b)

        with caplog.at_level(logging.INFO):
            from backend.scripts.sleep_cycle import integrated_sleep_cycle
            await integrated_sleep_cycle()

        assert extract_called["count"] == 0
        assert "handled by Idle Reflection" in caplog.text
