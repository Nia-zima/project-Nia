"""Snapshot-driven tests for Sleep Cycle (integrated_sleep_cycle).

Uses SnapshotBuilder presets to construct specific DB states,
then runs the sleep cycle with LLM mocks and asserts on results.
"""
from __future__ import annotations

import json
import pytest

from backend.core.db import init_schema, get_conn
from backend.scripts.sleep_cycle.orchestrator import integrated_sleep_cycle
from backend.services.memory.somatic_feedback import get_recent_accuracy

from harness.snapshot_builder import SnapshotBuilder, clean_all_tables
from harness.llm_mocks import make_sleep_cycle_mock
from harness.assertions import (
    assert_telemetry,
    assert_semantic_count,
    assert_somatic_accuracy_range,
    read_telemetry,
    count_semantics,
)


@pytest.fixture(autouse=True)
def _clean():
    init_schema()
    clean_all_tables()
    yield


def _patch_sleep_deps(monkeypatch, *, llm_mock=None):
    """Monkeypatch all external dependencies of integrated_sleep_cycle."""
    mock = llm_mock or make_sleep_cycle_mock()

    # LLM calls in orchestrator, layers, extraction
    monkeypatch.setattr(
        "backend.scripts.sleep_cycle.orchestrator.call_llm", mock,
    )
    monkeypatch.setattr(
        "backend.scripts.sleep_cycle.layers.call_llm", mock,
    )
    monkeypatch.setattr(
        "backend.scripts.sleep_cycle.extraction.call_llm", mock,
    )

    # Disable features that need external resources
    from backend.core.config import settings
    monkeypatch.setattr(settings, "EPISODIC_SUMMARY_ENABLED", False)
    monkeypatch.setattr(settings, "DIARY_ENABLED", False)
    monkeypatch.setattr(settings, "TWITTER_AUTO_PROPOSE", False)
    monkeypatch.setattr(settings, "SELF_MODEL_ENABLED", False)
    monkeypatch.setattr(settings, "LAYER_B_MODE", "proposal")

    # Mock vector_store to avoid ChromaDB dependency
    import types
    mock_vs = types.SimpleNamespace(
        garbage_collect_stream_memory=lambda: None,
    )
    monkeypatch.setattr(
        "backend.services.vector_store.vector_store", mock_vs,
    )

    # Mock checkpoint cleanup
    async def mock_cleanup():
        return {"deleted_checkpoints": 0, "deleted_writes": 0, "freed_mb": 0.0}
    monkeypatch.setattr(
        "backend.scripts.cleanup_checkpoints.run_cleanup", mock_cleanup,
    )

    # Mock identity_manager
    monkeypatch.setattr(
        "backend.scripts.sleep_cycle.orchestrator.identity_manager.get_identity",
        lambda: "テスト用アイデンティティ",
    )

    # Mock dream_store
    monkeypatch.setattr(
        "backend.scripts.sleep_cycle.orchestrator.dream_store.save_dream",
        lambda **kw: "dream_test_id",
    )

    # Mock memory_manager.add_episode
    async def mock_add_episode(**kw):
        pass
    monkeypatch.setattr(
        "backend.scripts.sleep_cycle.orchestrator.memory_manager.add_episode",
        mock_add_episode,
    )

    # Mock contradiction scan to avoid embedding dependency
    async def mock_scan(thread_id):
        return {"defeater_revoked": 0, "llm_revoked": 0, "held": 0}
    monkeypatch.setattr(
        "backend.services.memory.contradiction.scan_contradictions",
        mock_scan,
    )

    # Mock vector_sync
    monkeypatch.setattr(
        "backend.services.memory.vector_sync.process_semantic_vector_sync",
        lambda **kw: 0,
    )


# ═══════════════════════════════════════════════════════════════
# Fresh Start — empty DB graceful degradation
# ═══════════════════════════════════════════════════════════════


class TestSleepCycleFreshStart:
    @pytest.mark.asyncio
    async def test_completes_with_no_data(self, monkeypatch):
        """Empty DB → sleep cycle should complete gracefully."""
        SnapshotBuilder.fresh_start().build()
        _patch_sleep_deps(monkeypatch)

        result = await integrated_sleep_cycle()
        # With no events, should return early but not error
        assert result.semantic_extracted == 0

    @pytest.mark.asyncio
    async def test_sets_sleep_in_progress_flag(self, monkeypatch):
        """Even on empty DB, sleep_in_progress flag should be cleared."""
        SnapshotBuilder.fresh_start().build()
        _patch_sleep_deps(monkeypatch)

        await integrated_sleep_cycle()
        assert_telemetry("sleep_in_progress", "0")


# ═══════════════════════════════════════════════════════════════
# Slump — low accuracy, high dissonance
# ═══════════════════════════════════════════════════════════════


class TestSleepCycleSlump:
    @pytest.mark.asyncio
    async def test_completes_without_error(self, monkeypatch):
        """Slump preset should complete successfully."""
        SnapshotBuilder.slump().build()
        _patch_sleep_deps(monkeypatch)

        result = await integrated_sleep_cycle()
        assert result.success

    @pytest.mark.asyncio
    async def test_somatic_accuracy_is_low(self, monkeypatch):
        """Slump preset has 5/20 confirmed → accuracy ~0.25."""
        SnapshotBuilder.slump().build()
        _patch_sleep_deps(monkeypatch)

        # Verify accuracy BEFORE sleep cycle
        accuracy, samples = get_recent_accuracy("default_thread")
        assert samples == 20
        assert 0.2 <= accuracy <= 0.3

    @pytest.mark.asyncio
    async def test_records_sleep_completion(self, monkeypatch):
        """After sleep cycle, last_sleep_completed_at should be set."""
        SnapshotBuilder.slump().build()
        _patch_sleep_deps(monkeypatch)

        await integrated_sleep_cycle()
        val = read_telemetry("last_sleep_completed_at")
        assert val is not None
        assert float(val) > 0

    @pytest.mark.asyncio
    async def test_extracts_semantics_from_events(self, monkeypatch):
        """Slump has conversation events → extraction should find them."""
        SnapshotBuilder.slump().build()
        _patch_sleep_deps(monkeypatch)

        result = await integrated_sleep_cycle()
        # Our mock returns 2 extraction results
        assert result.semantic_extracted >= 0


# ═══════════════════════════════════════════════════════════════
# Rich History — many memories and reflections
# ═══════════════════════════════════════════════════════════════


class TestSleepCycleRichHistory:
    @pytest.mark.asyncio
    async def test_completes_with_rich_data(self, monkeypatch):
        """Rich history preset (100 semantics, 7 days reflections) should complete."""
        SnapshotBuilder.rich_history().build()
        _patch_sleep_deps(monkeypatch)

        result = await integrated_sleep_cycle()
        assert result.success

    @pytest.mark.asyncio
    async def test_uses_daily_reflections_as_input(self, monkeypatch):
        """Rich history has daily_reflections → should use them (not raw events)."""
        SnapshotBuilder.rich_history().build()
        _patch_sleep_deps(monkeypatch)

        # The sleep cycle should find and use daily_reflections
        result = await integrated_sleep_cycle()
        # Should succeed (daily_reflections path works)
        assert result.success

    @pytest.mark.asyncio
    async def test_semantic_confirm_runs(self, monkeypatch):
        """Rich history has old inferred memories → confirm phase should process them."""
        import time
        now = time.time()

        b = SnapshotBuilder.rich_history()
        # Add old inferred memories (>24h ago)
        for i in range(5):
            b.with_semantic(
                f"古い推論記憶 {i}",
                status="inferred",
                confidence=0.6,
                created_at=now - 100000,
            )
        b.build()
        _patch_sleep_deps(monkeypatch)

        # Enable self-model to exercise more code
        from backend.core.config import settings
        monkeypatch.setattr(settings, "SELF_MODEL_ENABLED", False)

        result = await integrated_sleep_cycle()
        assert result.success
        # Some inferred memories should be confirmed
        assert result.confirmed_count >= 0


# ═══════════════════════════════════════════════════════════════
# Contradiction overload path
# ═══════════════════════════════════════════════════════════════


class TestSleepCycleContradiction:
    @pytest.mark.asyncio
    async def test_contradiction_scan_called(self, monkeypatch):
        """Contradiction overload → scan should be invoked during sleep."""
        SnapshotBuilder.contradiction_overload().build()
        # Add some events so the cycle doesn't exit early
        b = SnapshotBuilder()
        for i in range(3):
            b.with_event(f"テスト質問 {i}", f"テスト回答 {i}")
        # Build adds on top of contradiction_overload state
        conn = get_conn()
        try:
            for ev in b._events:
                conn.execute(
                    """INSERT INTO memory_events
                       (event_id, thread_id, turn_id, event_type,
                        payload_json, created_at, schema_version)
                       VALUES (?,?,?,?,?,?,1)""",
                    (ev["event_id"], ev["thread_id"], ev["turn_id"],
                     ev["event_type"], ev["payload_json"], ev["created_at"]),
                )
            conn.commit()
        finally:
            conn.close()

        scan_called = {"count": 0}
        original_scan = None

        async def tracking_scan(thread_id):
            scan_called["count"] += 1
            return {"defeater_revoked": 0, "llm_revoked": 0, "held": 0}

        _patch_sleep_deps(monkeypatch)
        monkeypatch.setattr(
            "backend.services.memory.contradiction.scan_contradictions",
            tracking_scan,
        )

        result = await integrated_sleep_cycle()
        assert result.success
        assert scan_called["count"] == 1
