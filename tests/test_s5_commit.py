"""Tests for S5 Commit node (Phase F)."""
from __future__ import annotations

import os
import time
import uuid

import pytest

os.environ.setdefault("RETENTION_PROFILE", "fast")

from backend.core.db import get_conn, init_schema
from backend.services.memory.commit_executor import CommitPlan, execute


@pytest.fixture(autouse=True)
def _setup_db():
    """Ensure schema exists and clean tables before each test."""
    init_schema()
    conn = get_conn()
    try:
        # memory_index has FK to memory_events, delete it first
        conn.execute("DELETE FROM memory_index")
        conn.execute("DELETE FROM memory_events")
        conn.execute("DELETE FROM semantic_memories")
        conn.execute("DELETE FROM working_items")
        conn.commit()
    finally:
        conn.close()
    yield


# ── Helper: build minimal AgentState dict ─────────────────────────

def _state(
    *,
    final_text="こんにちは",
    user_text="やあ",
    hold_required=False,
    thread_id="test_thread",
    merge_mode="B",
    selected_depth=0,
    confidence=0.7,
    reason_codes=None,
):
    return {
        "final_text": final_text,
        "user_text": user_text,
        "hold_required": hold_required,
        "thread_id": thread_id,
        "merge_mode": merge_mode,
        "selected_depth": selected_depth,
        "confidence": confidence,
        "reason_codes": reason_codes or [],
    }


# ── Tests: s5_commit node function ───────────────────────────────

class TestS5CommitSkipConditions:
    """S5 should skip when disabled, hold, or WAIT."""

    def test_skip_when_disabled(self, monkeypatch):
        monkeypatch.setattr(
            "backend.core.agent_graph.nodes.settings.ORCHESTRATOR_S5_ENABLED", False
        )
        from backend.core.agent_graph.nodes import s5_commit

        result = s5_commit(_state())
        assert result["orchestrator_stage"] == "S5"
        assert result["commit_result"] is None

    def test_skip_when_hold_required(self, monkeypatch):
        monkeypatch.setattr(
            "backend.core.agent_graph.nodes.settings.ORCHESTRATOR_S5_ENABLED", True
        )
        from backend.core.agent_graph.nodes import s5_commit

        result = s5_commit(_state(hold_required=True))
        assert result["commit_result"]["skipped"] is True

    def test_skip_when_wait(self, monkeypatch):
        monkeypatch.setattr(
            "backend.core.agent_graph.nodes.settings.ORCHESTRATOR_S5_ENABLED", True
        )
        from backend.core.agent_graph.nodes import s5_commit

        result = s5_commit(_state(final_text="WAIT"))
        assert result["commit_result"]["skipped"] is True

    def test_skip_when_empty_final_text(self, monkeypatch):
        monkeypatch.setattr(
            "backend.core.agent_graph.nodes.settings.ORCHESTRATOR_S5_ENABLED", True
        )
        from backend.core.agent_graph.nodes import s5_commit

        result = s5_commit(_state(final_text=""))
        assert result["commit_result"]["skipped"] is True


class TestS5CommitEpisodic:
    """S5 should save episodic events."""

    def test_saves_episodic_event(self, monkeypatch):
        monkeypatch.setattr(
            "backend.core.agent_graph.nodes.settings.ORCHESTRATOR_S5_ENABLED", True
        )
        from backend.core.agent_graph.nodes import s5_commit

        result = s5_commit(_state(user_text="テスト入力", final_text="テスト応答"))

        assert result["commit_result"]["success"] is True
        assert result["commit_result"]["episodic"] == 1

        # Verify in DB
        conn = get_conn()
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM memory_events WHERE thread_id='test_thread'"
            ).fetchone()
            assert row[0] == 1
        finally:
            conn.close()


class TestS5CommitNoSemantic:
    """S5 should NOT generate semantic memories (deferred to Sleep Cycle)."""

    def test_no_semantic_even_with_fact_claims(self, monkeypatch):
        monkeypatch.setattr(
            "backend.core.agent_graph.nodes.settings.ORCHESTRATOR_S5_ENABLED", True
        )
        from backend.core.agent_graph.nodes import s5_commit

        result = s5_commit(_state(
            user_text="Originはコーヒーが好きだよね",
            final_text="了解した",
        ))
        assert result["commit_result"]["success"] is True
        assert result["commit_result"]["semantic_upsert"] == 0

        # Verify no semantic rows in DB
        conn = get_conn()
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM semantic_memories WHERE thread_id='test_thread'"
            ).fetchone()
            assert row[0] == 0
        finally:
            conn.close()


class TestS5CommitError:
    """S5 should handle errors gracefully."""

    def test_commit_exception_returns_error(self, monkeypatch):
        monkeypatch.setattr(
            "backend.core.agent_graph.nodes.settings.ORCHESTRATOR_S5_ENABLED", True
        )

        def _broken_execute(plan, *, thread_id, turn_id=None):
            raise RuntimeError("DB explosion")

        import backend.core.agent_graph.nodes as nodes_mod
        # Patch the import inside the function by patching the module it imports from
        monkeypatch.setattr(
            "backend.services.memory.commit_executor.execute",
            _broken_execute,
        )

        from backend.core.agent_graph.nodes import s5_commit
        result = s5_commit(_state(final_text="テスト"))

        assert result["commit_result"]["success"] is False
        assert len(result["commit_result"]["errors"]) > 0


class TestS5CommitIntegration:
    """Integration: S5 commit + working store stale counts."""

    def test_stale_counts_incremented(self, monkeypatch):
        """S5 commit increments stale_turn_count via commit_executor."""
        monkeypatch.setattr(
            "backend.core.agent_graph.nodes.settings.ORCHESTRATOR_S5_ENABLED", True
        )
        from backend.services.memory import working_store
        from backend.services.memory.models import WorkingItem

        # Pre-create an open working item
        conn = get_conn()
        try:
            item = WorkingItem(
                id="wi_test",
                thread_id="test_thread",
                item_type="question",
                content="test working item",
                created_turn_id="t0",
                created_at=time.time(),
                updated_at=time.time(),
                stale_turn_count=0,
            )
            working_store.add(conn, item)
            conn.commit()
        finally:
            conn.close()

        from backend.core.agent_graph.nodes import s5_commit
        s5_commit(_state())

        # Check stale count incremented
        wi = working_store.get_by_id("wi_test")
        assert wi is not None
        assert wi.stale_turn_count == 1
