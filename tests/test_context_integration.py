"""Tests for Phase G: Context Builder integration into depth nodes."""
from __future__ import annotations

import os
import time
import uuid

import pytest

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
        conn.execute("DELETE FROM working_items")
        conn.commit()
    finally:
        conn.close()
    yield


# ── Helpers ───────────────────────────────────────────────────────

def _insert_semantic(thread_id: str, content: str, *, status: str = "confirmed", confidence: float = 0.8):
    """Insert a semantic memory for testing."""
    conn = get_conn()
    try:
        now = time.time()
        conn.execute(
            """INSERT INTO semantic_memories
               (id, thread_id, content, status, confidence, valid_from,
                seed_retention, vector_sync_pending, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 0.5, 0, ?, ?)""",
            (uuid.uuid4().hex, thread_id, content, status, confidence, now, now, now),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_working(thread_id: str, content: str, *, item_type: str = "question"):
    """Insert a working item for testing."""
    conn = get_conn()
    try:
        now = time.time()
        conn.execute(
            """INSERT INTO working_items
               (id, thread_id, item_type, content, priority, status,
                created_turn_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, 3, 'open', 'test_turn', ?, ?)""",
            (uuid.uuid4().hex, thread_id, item_type, content, now, now),
        )
        conn.commit()
    finally:
        conn.close()


# ── Tests: thread_id propagation ─────────────────────────────────

class TestThreadIdPropagation:
    """safety_interrupt should propagate thread_id from config to state."""

    @pytest.mark.asyncio
    async def test_thread_id_from_config(self, monkeypatch):
        """thread_id in config.configurable should appear in state output."""
        from langchain_core.messages import HumanMessage
        from backend.core.agent_graph.nodes import safety_interrupt

        state = {
            "messages": [HumanMessage(content="こんにちは")],
            "has_user_text": True,
        }
        config = {"configurable": {"thread_id": "my_thread_123"}}

        result = await safety_interrupt(state, config=config)
        assert result["thread_id"] == "my_thread_123"

    @pytest.mark.asyncio
    async def test_thread_id_default(self, monkeypatch):
        """Missing thread_id should default to 'default'."""
        from langchain_core.messages import HumanMessage
        from backend.core.agent_graph.nodes import safety_interrupt

        state = {
            "messages": [HumanMessage(content="テスト")],
            "has_user_text": True,
        }

        result = await safety_interrupt(state, config=None)
        assert result["thread_id"] == "default"


# ── Tests: depth_selector memory context ─────────────────────────

class TestDepthSelectorMemoryContext:
    """depth_selector should build memory context and store it in state."""

    @pytest.mark.asyncio
    async def test_memory_context_populated(self, monkeypatch):
        """When semantic memories exist, memory_context should be non-empty."""
        _insert_semantic("test_thread", "Originはコーヒーが好き")
        _insert_working("test_thread", "次回の話題確認")

        # Mock LLM to avoid actual API call
        from unittest.mock import AsyncMock, MagicMock
        mock_resp = MagicMock()
        mock_resp.content = "テスト応答"

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_resp)
        monkeypatch.setattr(
            "backend.core.agent_graph.nodes.helpers.get_depth_llm",
            lambda **kwargs: mock_llm,
        )

        from backend.core.agent_graph.nodes import depth_selector

        state = {
            "user_text": "テスト",
            "thread_id": "test_thread",
            "has_user_text": True,
            "confidence": 0.7,
            "need_depth1": False,
            "need_depth2": False,
            "reason_codes": [],
            "dissonance": 0.0,
            "dissonance_on": False,
            "surprise_score": 0.0,
        }
        result = await depth_selector(state)
        assert "memory_context" in result
        assert "コーヒーが好き" in result["memory_context"]

    @pytest.mark.asyncio
    async def test_memory_context_empty_when_no_data(self, monkeypatch):
        """No memory data → memory_context should be empty or minimal."""
        from unittest.mock import AsyncMock, MagicMock
        mock_resp = MagicMock()
        mock_resp.content = "テスト応答"

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_resp)
        monkeypatch.setattr(
            "backend.core.agent_graph.nodes.helpers.get_depth_llm",
            lambda **kwargs: mock_llm,
        )

        from backend.core.agent_graph.nodes import depth_selector

        state = {
            "user_text": "テスト",
            "thread_id": "empty_thread",
            "has_user_text": True,
            "confidence": 0.7,
            "need_depth1": False,
            "need_depth2": False,
            "reason_codes": [],
            "dissonance": 0.0,
            "dissonance_on": False,
            "surprise_score": 0.0,
        }
        result = await depth_selector(state)
        assert "memory_context" in result
        # Should still have at least the === MEMORY === header
        assert isinstance(result["memory_context"], str)

    @pytest.mark.asyncio
    async def test_memory_context_survives_error(self, monkeypatch):
        """If context_builder throws, memory_context should be '' (not crash)."""
        from unittest.mock import AsyncMock, MagicMock
        mock_resp = MagicMock()
        mock_resp.content = "テスト応答"

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_resp)
        monkeypatch.setattr(
            "backend.core.agent_graph.nodes.helpers.get_depth_llm",
            lambda **kwargs: mock_llm,
        )

        # Force context builder to fail
        def _broken_build(**kw):
            raise RuntimeError("context builder broken")

        monkeypatch.setattr(
            "backend.core.agent_graph.nodes.routing.build_memory_context",
            _broken_build,
        )

        from backend.core.agent_graph.nodes import depth_selector

        state = {
            "user_text": "テスト",
            "thread_id": "test_thread",
            "has_user_text": True,
            "confidence": 0.7,
            "need_depth1": False,
            "need_depth2": False,
            "reason_codes": [],
            "dissonance": 0.0,
            "dissonance_on": False,
            "surprise_score": 0.0,
        }
        result = await depth_selector(state)
        assert result["memory_context"] == ""


# ── Tests: depth1 memory injection ──────────────────────────────

class TestDepth1MemoryInjection:
    """depth1 should include full memory context in system prompt."""

    @pytest.mark.asyncio
    async def test_depth1_includes_memory_in_prompt(self, monkeypatch):
        """depth1's LLM call should include memory_context in system prompt."""
        captured_messages = []

        from unittest.mock import AsyncMock, MagicMock
        mock_resp = MagicMock()
        mock_resp.content = "整理した結果"

        async def capture_invoke(messages):
            captured_messages.extend(messages)
            return mock_resp

        mock_llm = MagicMock()
        mock_llm.ainvoke = capture_invoke
        monkeypatch.setattr(
            "backend.core.agent_graph.nodes.depth_nodes.get_depth_llm",
            lambda **kwargs: mock_llm,
        )

        from backend.core.agent_graph.nodes import depth1_organize_and_ask

        state = {
            "user_text": "テスト質問",
            "thread_id": "test_thread",
            "memory_context": "=== PINNED FACTS ===\n- Originはコーヒー好き\n\n=== MEMORY ===\nLong Term:\n- (confirmed) Originは開発者",
            "self_scope": False,
            "messages": [],
        }
        await depth1_organize_and_ask(state)

        assert len(captured_messages) >= 1
        system_content = captured_messages[0].content
        assert "コーヒー好き" in system_content
        assert "PINNED FACTS" in system_content


# ── Tests: depth0 pinned-only injection ──────────────────────────

class TestDepth0PinnedOnly:
    """depth0 should only include PINNED FACTS, not full memory."""

    @pytest.mark.asyncio
    async def test_depth0_includes_only_pinned(self, monkeypatch):
        """depth0's LLM call should include only PINNED FACTS section."""
        captured_messages = []

        from unittest.mock import AsyncMock, MagicMock
        mock_resp = MagicMock()
        mock_resp.content = "即応答"

        async def capture_invoke(messages):
            captured_messages.extend(messages)
            return mock_resp

        mock_llm = MagicMock()
        mock_llm.ainvoke = capture_invoke
        monkeypatch.setattr(
            "backend.core.agent_graph.nodes.depth_nodes.get_depth_llm",
            lambda **kwargs: mock_llm,
        )

        from backend.core.agent_graph.nodes import depth0_reflex

        state = {
            "user_text": "おはよう",
            "thread_id": "test_thread",
            "memory_context": "=== PINNED FACTS ===\n- Originは朝型人間\n\n=== WORKING ===\n- [question] 好きな飲み物確認\n\n=== MEMORY ===\nLong Term:\n- (confirmed) Originは開発者",
            "messages": [],
        }
        await depth0_reflex(state)

        assert len(captured_messages) >= 1
        system_content = captured_messages[0].content
        assert "朝型人間" in system_content
        # WORKING and Long Term should NOT be in depth0
        assert "WORKING" not in system_content
        assert "開発者" not in system_content
