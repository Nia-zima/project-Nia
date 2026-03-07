"""Snapshot-driven tests for N.2 Contradiction Detection.

Uses SnapshotBuilder.contradiction_overload() to pre-populate
contradicting semantic memories, then tests the scan pipeline.
"""
from __future__ import annotations

import json
import pytest

from backend.core.db import init_schema, get_conn
from backend.services.memory.contradiction import (
    _check_defeaters,
    scan_contradictions,
    expire_contradiction_holds,
)
from backend.services.memory import semantic_store

from harness.snapshot_builder import SnapshotBuilder, clean_all_tables
from harness.assertions import (
    assert_semantic_status,
    assert_semantic_count,
    assert_working_has_type,
    assert_no_working_type,
    count_working_open,
)


@pytest.fixture(autouse=True)
def _clean():
    init_schema()
    clean_all_tables()
    yield


# ═══════════════════════════════════════════════════════════════
# Step 1: Defeater check (no LLM)
# ═══════════════════════════════════════════════════════════════


class TestDefeaterCheck:
    def test_contradiction_overload_has_defeaters(self):
        """Preset: each pair has cross-referencing defeaters."""
        SnapshotBuilder.contradiction_overload().build()
        active = semantic_store.search_active("default_thread", limit=200)
        assert len(active) == 20  # 10 pairs

    def test_defeater_finds_matches(self):
        """Step 1 should find defeater matches from the preset."""
        SnapshotBuilder.contradiction_overload().build()
        active = semantic_store.search_active("default_thread", limit=200)
        results = _check_defeaters(active)
        # Each pair has mutual defeaters → expect multiple matches
        assert len(results) > 0
        assert all(r.source == "defeater" for r in results)
        assert all(r.resolution_type == "supersede" for r in results)

    def test_no_defeaters_in_clean_db(self):
        """Fresh DB with simple memories → no defeaters."""
        (SnapshotBuilder()
            .with_semantic("事実A", defeaters="[]")
            .with_semantic("事実B", defeaters="[]")
            .build())
        active = semantic_store.search_active("default_thread", limit=200)
        results = _check_defeaters(active)
        assert len(results) == 0


# ═══════════════════════════════════════════════════════════════
# Full scan (Steps 1-4)
# ═══════════════════════════════════════════════════════════════


class TestScanContradictions:
    @pytest.mark.asyncio
    async def test_defeater_revokes_in_full_scan(self, monkeypatch):
        """Full scan on contradiction_overload → defeater_revoked > 0."""
        SnapshotBuilder.contradiction_overload().build()

        # Mock LLM to avoid actual calls (step 3)
        # Also mock embedding pairs to return empty (no embeddings in snapshot)
        monkeypatch.setattr(
            "backend.services.memory.contradiction._find_embedding_pairs",
            lambda *a, **kw: [],
        )
        monkeypatch.setattr(
            "backend.services.memory.contradiction._llm_check_contradiction",
            _mock_llm_compatible,
        )

        result = await scan_contradictions("default_thread")
        assert result["defeater_revoked"] > 0

    @pytest.mark.asyncio
    async def test_revoked_memories_change_status(self, monkeypatch):
        """After scan, revoked memories should have status='revoked'."""
        SnapshotBuilder.contradiction_overload().build()

        monkeypatch.setattr(
            "backend.services.memory.contradiction._find_embedding_pairs",
            lambda *a, **kw: [],
        )
        monkeypatch.setattr(
            "backend.services.memory.contradiction._llm_check_contradiction",
            _mock_llm_compatible,
        )

        await scan_contradictions("default_thread")

        # At least some memories should now be revoked
        assert_semantic_count(1, status="revoked", compare="gte")

    @pytest.mark.asyncio
    async def test_scan_with_fewer_than_two_memories(self, monkeypatch):
        """Scan on < 2 active memories should return zeros."""
        SnapshotBuilder().with_semantic("唯一の記憶").build()

        result = await scan_contradictions("default_thread")
        assert result == {"defeater_revoked": 0, "llm_revoked": 0, "held": 0}

    @pytest.mark.asyncio
    async def test_fresh_start_scan(self, monkeypatch):
        """Empty DB → graceful zero result."""
        SnapshotBuilder.fresh_start().build()

        result = await scan_contradictions("default_thread")
        assert result == {"defeater_revoked": 0, "llm_revoked": 0, "held": 0}


# ═══════════════════════════════════════════════════════════════
# TTL Expiry
# ═══════════════════════════════════════════════════════════════


class TestContradictionHoldExpiry:
    def test_expired_hold_creates_revocation(self):
        """A contradiction_hold past TTL should revoke the older memory."""
        import time
        now = time.time()

        (SnapshotBuilder()
            .with_semantic("古い事実", id="old_mem", confidence=0.7)
            .with_semantic("新しい事実", id="new_mem", confidence=0.7)
            .with_working(
                "矛盾: 古い事実 vs 新しい事実",
                item_type="contradiction_hold",
                id="hold_1",
            )
            .build())

        # Manually set expires_at in the past and linked_semantic_ids
        conn = get_conn()
        try:
            conn.execute(
                "UPDATE working_items SET expires_at = ?, linked_semantic_ids = ? WHERE id = ?",
                (now - 100, json.dumps(["old_mem", "new_mem"]), "hold_1"),
            )
            conn.commit()
        finally:
            conn.close()

        count = expire_contradiction_holds("default_thread")
        assert count == 1

        # old_mem should be revoked
        assert_semantic_status("古い事実", "revoked")

    def test_non_expired_hold_untouched(self):
        """A hold that hasn't expired should remain open."""
        import time
        now = time.time()

        (SnapshotBuilder()
            .with_semantic("事実A", id="mem_a")
            .with_semantic("事実B", id="mem_b")
            .with_working(
                "矛盾保留",
                item_type="contradiction_hold",
                id="hold_future",
            )
            .build())

        # Set expires_at in the future
        conn = get_conn()
        try:
            conn.execute(
                "UPDATE working_items SET expires_at = ?, linked_semantic_ids = ? WHERE id = ?",
                (now + 86400, json.dumps(["mem_a", "mem_b"]), "hold_future"),
            )
            conn.commit()
        finally:
            conn.close()

        count = expire_contradiction_holds("default_thread")
        assert count == 0

        # Both memories should remain confirmed
        assert_semantic_status("事実A", "confirmed")
        assert_semantic_status("事実B", "confirmed")


# ── Mock helpers ─────────────────────────────────────────────


async def _mock_llm_compatible(content_a, content_b):
    """Mock: always return compatible (no contradiction)."""
    return None
