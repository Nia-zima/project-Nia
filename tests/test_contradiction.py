"""Tests for Contradiction Detection (Phase N.2)."""
from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from backend.core.db import get_conn, init_schema, managed_conn
from backend.services.memory import semantic_store, working_store
from backend.services.memory.contradiction import (
    ContradictionPair,
    _check_defeaters,
    _find_embedding_pairs,
    _llm_check_contradiction,
    _resolve_contradictions,
    expire_contradiction_holds,
    scan_contradictions,
)
from conftest import make_semantic


@pytest.fixture(autouse=True)
def _setup_db():
    init_schema()
    conn = get_conn()
    try:
        conn.execute("DELETE FROM semantic_memories")
        conn.execute("DELETE FROM working_items")
    finally:
        conn.close()
    yield


def _insert(mem):
    conn = get_conn()
    try:
        semantic_store.upsert(conn, mem)
    finally:
        conn.close()


# ── _check_defeaters ────────────────────────────────────────


class TestCheckDefeaters:
    def test_defeater_match_triggers_supersede(self):
        mem_a = make_semantic(id="a", content="コーヒーが好き")
        mem_a.defeaters = json.dumps(["紅茶を好む"])
        mem_b = make_semantic(id="b", content="紅茶を好むと言った")

        results = _check_defeaters([mem_a, mem_b])
        assert len(results) == 1
        assert results[0].mem_a_id == "a"
        assert results[0].mem_b_id == "b"
        assert results[0].resolution_type == "supersede"
        assert results[0].source == "defeater"

    def test_no_defeater_match(self):
        mem_a = make_semantic(id="a", content="コーヒーが好き")
        mem_a.defeaters = json.dumps(["紅茶を好む"])
        mem_b = make_semantic(id="b", content="猫が好き")

        results = _check_defeaters([mem_a, mem_b])
        assert len(results) == 0

    def test_empty_defeaters(self):
        mem_a = make_semantic(id="a", content="テスト")
        mem_b = make_semantic(id="b", content="テスト2")

        results = _check_defeaters([mem_a, mem_b])
        assert len(results) == 0

    def test_case_insensitive_match(self):
        mem_a = make_semantic(id="a", content="Python is best")
        mem_a.defeaters = json.dumps(["python is worst"])
        mem_b = make_semantic(id="b", content="Python is worst, actually")

        results = _check_defeaters([mem_a, mem_b])
        assert len(results) == 1

    def test_invalid_json_defeaters_skipped(self):
        """Corrupt defeaters JSON should not crash — just skip the memory."""
        mem_a = make_semantic(id="a", content="テスト")
        mem_a.defeaters = "{invalid json"
        mem_b = make_semantic(id="b", content="テスト2")

        results = _check_defeaters([mem_a, mem_b])
        assert len(results) == 0  # Skipped, no crash

    def test_none_defeaters_skipped(self):
        mem_a = make_semantic(id="a", content="テスト")
        mem_a.defeaters = None
        mem_b = make_semantic(id="b", content="テスト2")

        results = _check_defeaters([mem_a, mem_b])
        assert len(results) == 0


# ── _find_embedding_pairs ──────────────────────────────────


class TestFindEmbeddingPairs:
    def test_finds_high_similarity_pairs(self):
        vec_a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        vec_b = np.array([0.95, 0.1, 0.0], dtype=np.float32)  # high similarity to a
        vec_c = np.array([0.0, 0.0, 1.0], dtype=np.float32)  # low similarity

        mem_a = make_semantic(id="a", content="test a")
        mem_a.embedding = vec_a.tobytes()
        mem_b = make_semantic(id="b", content="test b")
        mem_b.embedding = vec_b.tobytes()
        mem_c = make_semantic(id="c", content="test c")
        mem_c.embedding = vec_c.tobytes()

        with patch("backend.core.embedding_model.cosine_similarity") as mock_sim:
            # a-b: high, a-c: low, b-c: low
            def sim(v1, v2):
                # Compute actual cosine similarity
                dot = float(np.dot(v1, v2))
                na = float(np.linalg.norm(v1))
                nb = float(np.linalg.norm(v2))
                return dot / (na * nb) if na > 0 and nb > 0 else 0.0
            mock_sim.side_effect = sim

            pairs = _find_embedding_pairs([mem_a, mem_b, mem_c], threshold=0.9)

        # Only a-b pair should be above 0.9 threshold
        assert len(pairs) >= 1
        found_ids = {(p[0].id, p[1].id) for p in pairs}
        assert ("a", "b") in found_ids or ("b", "a") in found_ids

    def test_no_pairs_below_threshold(self):
        vec_a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        vec_b = np.array([0.0, 1.0, 0.0], dtype=np.float32)

        mem_a = make_semantic(id="a", content="test a")
        mem_a.embedding = vec_a.tobytes()
        mem_b = make_semantic(id="b", content="test b")
        mem_b.embedding = vec_b.tobytes()

        with patch("backend.core.embedding_model.cosine_similarity", return_value=0.1):
            pairs = _find_embedding_pairs([mem_a, mem_b], threshold=0.7)

        assert len(pairs) == 0


# ── _llm_check_contradiction ───────────────────────────────


class TestLlmCheckContradiction:
    @pytest.mark.asyncio
    async def test_contradiction_detected_hold(self):
        response = json.dumps({
            "contradiction": True,
            "resolution_type": "hold",
            "reason": "両立不可能",
        })
        with patch("backend.services.llm_client.call_llm", new_callable=AsyncMock, return_value=response):
            result = await _llm_check_contradiction("コーヒーが好き", "コーヒーが嫌い")

        assert result is not None
        assert result.resolution_type == "hold"
        assert result.reason == "両立不可能"

    @pytest.mark.asyncio
    async def test_contradiction_detected_supersede(self):
        response = json.dumps({
            "contradiction": True,
            "resolution_type": "supersede",
            "reason": "時間的変化",
        })
        with patch("backend.services.llm_client.call_llm", new_callable=AsyncMock, return_value=response):
            result = await _llm_check_contradiction("昔はコーヒー派", "今は紅茶派")

        assert result is not None
        assert result.resolution_type == "supersede"

    @pytest.mark.asyncio
    async def test_compatible_returns_none(self):
        response = json.dumps({
            "contradiction": False,
            "resolution_type": "compatible",
            "reason": "補完関係",
        })
        with patch("backend.services.llm_client.call_llm", new_callable=AsyncMock, return_value=response):
            result = await _llm_check_contradiction("猫が好き", "犬も好き")

        assert result is None

    @pytest.mark.asyncio
    async def test_llm_failure_returns_none(self):
        with patch("backend.services.llm_client.call_llm", new_callable=AsyncMock, return_value=None):
            result = await _llm_check_contradiction("a", "b")
        assert result is None

    @pytest.mark.asyncio
    async def test_json_parse_failure_returns_none(self):
        with patch("backend.services.llm_client.call_llm", new_callable=AsyncMock, return_value="not json"):
            result = await _llm_check_contradiction("a", "b")
        assert result is None


# ── _resolve_contradictions ─────────────────────────────────


class TestResolveContradictions:
    def test_supersede_revokes_older(self):
        now = time.time()
        mem_old = make_semantic(id="old", content="古い事実")
        mem_old.created_at = now - 86400
        mem_new = make_semantic(id="new", content="新しい事実")
        mem_new.created_at = now

        _insert(mem_old)
        _insert(mem_new)

        pair = ContradictionPair(
            mem_a_id="old", mem_b_id="new",
            similarity=0.8, resolution_type="supersede",
            reason="時間的変化", source="llm",
        )

        result = _resolve_contradictions([pair], [mem_old, mem_new], "t1")
        assert result["revoked"] == 1

        # Verify the older memory is revoked
        with managed_conn() as conn:
            row = conn.execute("SELECT status, revoked_by_id, note FROM semantic_memories WHERE id='old'").fetchone()
            assert row["status"] == "revoked"
            assert row["revoked_by_id"] == "new"
            assert "矛盾検出" in (row["note"] or "")

    def test_hold_creates_working_item(self):
        mem_a = make_semantic(id="a", content="事実A")
        mem_b = make_semantic(id="b", content="事実B")

        _insert(mem_a)
        _insert(mem_b)

        pair = ContradictionPair(
            mem_a_id="a", mem_b_id="b",
            similarity=0.8, resolution_type="hold",
            reason="両立不可能", source="llm",
        )

        with patch("backend.services.memory.contradiction.settings") as mock_s:
            mock_s.CONTRADICTION_HOLD_TTL_DAYS = 3
            result = _resolve_contradictions([pair], [mem_a, mem_b], "t1")

        assert result["held"] == 1

        # Verify working item was created
        with managed_conn() as conn:
            row = conn.execute(
                "SELECT * FROM working_items WHERE item_type='contradiction_hold'"
            ).fetchone()
            assert row is not None
            assert "矛盾" in row["content"]
            linked = json.loads(row["linked_semantic_ids"])
            assert "a" in linked and "b" in linked
            assert row["expires_at"] > time.time()


# ── expire_contradiction_holds ──────────────────────────────


class TestExpireContradictionHolds:
    def test_expires_past_ttl(self):
        mem_a = make_semantic(id="a", content="事実A")
        mem_b = make_semantic(id="b", content="事実B")
        _insert(mem_a)
        _insert(mem_b)

        # Create expired working item
        now = time.time()
        from backend.services.memory.models import WorkingItem
        item = WorkingItem(
            id="hold1",
            thread_id="t1",
            item_type="contradiction_hold",
            content="矛盾テスト",
            priority=2,
            linked_semantic_ids=json.dumps(["a", "b"]),
            created_turn_id="test",
            created_at=now - 86400 * 4,
            updated_at=now - 86400 * 4,
            expires_at=now - 100,  # Already expired
        )
        with managed_conn() as conn:
            working_store.add(conn, item)

        count = expire_contradiction_holds("t1")
        assert count == 1

        # Verify memory a was revoked
        with managed_conn() as conn:
            row = conn.execute("SELECT status FROM semantic_memories WHERE id='a'").fetchone()
            assert row["status"] == "revoked"
            # Verify working item was closed
            wi = conn.execute("SELECT status, close_reason FROM working_items WHERE id='hold1'").fetchone()
            assert wi["status"] == "closed"
            assert wi["close_reason"] == "ttl_expired"

    def test_does_not_expire_future_ttl(self):
        mem_a = make_semantic(id="a", content="事実A")
        _insert(mem_a)

        now = time.time()
        from backend.services.memory.models import WorkingItem
        item = WorkingItem(
            id="hold2",
            thread_id="t1",
            item_type="contradiction_hold",
            content="矛盾テスト",
            priority=2,
            linked_semantic_ids=json.dumps(["a"]),
            created_turn_id="test",
            created_at=now,
            updated_at=now,
            expires_at=now + 86400,  # Future
        )
        with managed_conn() as conn:
            working_store.add(conn, item)

        count = expire_contradiction_holds("t1")
        assert count == 0


# ── scan_contradictions (integration) ───────────────────────


class TestScanContradictions:
    @pytest.mark.asyncio
    async def test_disabled_returns_empty(self):
        with patch("backend.services.memory.contradiction.settings") as mock_s:
            mock_s.CONTRADICTION_SCAN_ENABLED = False
            result = await scan_contradictions("t1")
        assert result == {"defeater_revoked": 0, "llm_revoked": 0, "held": 0}

    @pytest.mark.asyncio
    async def test_fewer_than_two_memories_returns_empty(self):
        mem = make_semantic(content="only one")
        _insert(mem)

        with patch("backend.services.memory.contradiction.settings") as mock_s:
            mock_s.CONTRADICTION_SCAN_ENABLED = True
            result = await scan_contradictions("t1")
        assert result == {"defeater_revoked": 0, "llm_revoked": 0, "held": 0}

    @pytest.mark.asyncio
    async def test_defeater_scan_revokes(self):
        mem_a = make_semantic(id="da", content="コーヒーが好き", thread_id="t1")
        mem_a.defeaters = json.dumps(["紅茶"])
        mem_b = make_semantic(id="db", content="紅茶が最高", thread_id="t1")

        _insert(mem_a)
        _insert(mem_b)

        with patch("backend.services.memory.contradiction.settings") as mock_s:
            mock_s.CONTRADICTION_SCAN_ENABLED = True
            mock_s.CONTRADICTION_SIMILARITY_THRESHOLD = 0.7
            mock_s.CONTRADICTION_MAX_PAIRS = 10
            mock_s.CONTRADICTION_HOLD_TTL_DAYS = 3
            result = await scan_contradictions("t1")

        assert result["defeater_revoked"] == 1
