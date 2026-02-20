"""Tests for Sleep Cycle semantic extraction from episodic events (Phase G)."""
from __future__ import annotations

import json
import os
import time
import uuid

import pytest

os.environ.setdefault("RETENTION_PROFILE", "fast")

from backend.core.db import get_conn, init_schema


@pytest.fixture(autouse=True)
def _setup_db():
    """Ensure schema exists and clean tables before each test."""
    init_schema()
    conn = get_conn()
    try:
        conn.execute("DELETE FROM memory_index")
        conn.execute("DELETE FROM memory_events")
        conn.execute("DELETE FROM semantic_memories")
        conn.execute("DELETE FROM telemetry_kv")
        conn.commit()
    finally:
        conn.close()
    yield


# ── Helpers ───────────────────────────────────────────────────────

def _insert_episodic_event(
    thread_id: str,
    user_text: str,
    ai_response: str,
    created_at: float | None = None,
):
    """Insert a conversation_turn event into memory_events."""
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO memory_events
               (event_id, thread_id, event_type, payload_json, created_at, schema_version)
               VALUES (?, ?, 'conversation_turn', ?, ?, 1)""",
            (
                uuid.uuid4().hex,
                thread_id,
                json.dumps({
                    "user_text": user_text,
                    "ai_response": ai_response,
                }),
                created_at or time.time(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _set_last_sleep_at(ts: float):
    """Set last_sleep_completed_at in telemetry_kv."""
    conn = get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO telemetry_kv (k, v, updated_at) VALUES (?, ?, ?)",
            ("last_sleep_completed_at", str(ts), int(ts)),
        )
        conn.commit()
    finally:
        conn.close()


# ── Tests ─────────────────────────────────────────────────────────

class TestExtractSemanticsFromEpisodic:
    """Sleep Cycle should extract semantic memories from episodic events via LLM."""

    @pytest.mark.asyncio
    async def test_extracts_facts_from_conversations(self, monkeypatch):
        """LLM returns fact claims → inferred semantic memories created."""
        # Insert episodic events
        _insert_episodic_event("t1", "俺はコーヒーが好きなんだよね", "へー、そうなんだ")
        _insert_episodic_event("t1", "Pythonでよく開発してる", "いいね")

        # Mock call_llm to return structured facts
        async def mock_llm(messages):
            return '[{"content": "Originはコーヒーが好き"}, {"content": "OriginはPythonで開発している"}]'

        monkeypatch.setattr(
            "backend.scripts.sleep_cycle.call_llm", mock_llm
        )

        from backend.scripts.sleep_cycle import _extract_semantics_from_episodic

        count = await _extract_semantics_from_episodic()
        assert count == 2

        # Verify in DB
        conn = get_conn()
        try:
            rows = conn.execute(
                "SELECT content, status, confidence FROM semantic_memories WHERE thread_id='t1'"
            ).fetchall()
            assert len(rows) == 2
            for row in rows:
                assert row["status"] == "inferred"
                assert row["confidence"] == pytest.approx(0.5, abs=0.01)
        finally:
            conn.close()

    @pytest.mark.asyncio
    async def test_no_extraction_when_no_events(self, monkeypatch):
        """No episodic events → 0 semantic memories."""
        async def mock_llm(messages):
            raise AssertionError("LLM should not be called")

        monkeypatch.setattr(
            "backend.scripts.sleep_cycle.call_llm", mock_llm
        )

        from backend.scripts.sleep_cycle import _extract_semantics_from_episodic

        count = await _extract_semantics_from_episodic()
        assert count == 0

    @pytest.mark.asyncio
    async def test_respects_last_sleep_timestamp(self, monkeypatch):
        """Only events after last_sleep_completed_at are processed."""
        old_ts = time.time() - 200
        new_ts = time.time() - 50

        # Old event (before last sleep)
        _insert_episodic_event("t1", "古い会話", "OK", created_at=old_ts)
        # Set last sleep after old event
        _set_last_sleep_at(old_ts + 10)
        # New event (after last sleep)
        _insert_episodic_event("t1", "俺は猫が好き", "かわいいよね", created_at=new_ts)

        async def mock_llm(messages):
            # Only new conversation should be in the prompt
            prompt_text = messages[0]["content"]
            assert "猫が好き" in prompt_text
            assert "古い会話" not in prompt_text
            return '[{"content": "Originは猫が好き"}]'

        monkeypatch.setattr(
            "backend.scripts.sleep_cycle.call_llm", mock_llm
        )

        from backend.scripts.sleep_cycle import _extract_semantics_from_episodic

        count = await _extract_semantics_from_episodic()
        assert count == 1

    @pytest.mark.asyncio
    async def test_llm_returns_empty_array(self, monkeypatch):
        """LLM returns [] → no semantic memories created."""
        _insert_episodic_event("t1", "うん", "うん")

        async def mock_llm(messages):
            return "[]"

        monkeypatch.setattr(
            "backend.scripts.sleep_cycle.call_llm", mock_llm
        )

        from backend.scripts.sleep_cycle import _extract_semantics_from_episodic

        count = await _extract_semantics_from_episodic()
        assert count == 0

    @pytest.mark.asyncio
    async def test_llm_returns_invalid_json(self, monkeypatch):
        """LLM returns garbage → graceful fallback, no crash."""
        _insert_episodic_event("t1", "テスト", "テスト")

        async def mock_llm(messages):
            return "これはJSONではありません"

        monkeypatch.setattr(
            "backend.scripts.sleep_cycle.call_llm", mock_llm
        )

        from backend.scripts.sleep_cycle import _extract_semantics_from_episodic

        count = await _extract_semantics_from_episodic()
        assert count == 0

    @pytest.mark.asyncio
    async def test_caps_at_5_per_thread(self, monkeypatch):
        """Max 5 semantic memories per thread per extraction."""
        _insert_episodic_event("t1", "たくさん情報", "了解")

        async def mock_llm(messages):
            return json.dumps([
                {"content": f"fact_{i}"} for i in range(10)
            ])

        monkeypatch.setattr(
            "backend.scripts.sleep_cycle.call_llm", mock_llm
        )

        from backend.scripts.sleep_cycle import _extract_semantics_from_episodic

        count = await _extract_semantics_from_episodic()
        assert count <= 5

    @pytest.mark.asyncio
    async def test_groups_by_thread(self, monkeypatch):
        """Events from different threads get separate LLM calls."""
        _insert_episodic_event("thread_a", "コーヒー好き", "いいね")
        _insert_episodic_event("thread_b", "紅茶好き", "素敵")

        call_count = 0

        async def mock_llm(messages):
            nonlocal call_count
            call_count += 1
            return '[{"content": "テスト事実"}]'

        monkeypatch.setattr(
            "backend.scripts.sleep_cycle.call_llm", mock_llm
        )

        from backend.scripts.sleep_cycle import _extract_semantics_from_episodic

        count = await _extract_semantics_from_episodic()
        assert call_count == 2  # one per thread
        assert count == 2
