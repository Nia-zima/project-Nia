"""Tests for Metacognitive Check (Phase N.1)."""
from __future__ import annotations

import time
from unittest.mock import patch

import numpy as np
import pytest

from backend.core.db import get_conn, init_schema
from backend.services.memory import semantic_store
from backend.services.memory.metacognition import (
    MetaCogResult,
    SankaiFlags,
    metacognitive_check,
    _check_three_precepts,
    _clamp,
)
from conftest import make_semantic


@pytest.fixture(autouse=True)
def _setup_db():
    init_schema()
    conn = get_conn()
    try:
        conn.execute("DELETE FROM semantic_memories")
    finally:
        conn.close()
    yield


def _insert(mem):
    conn = get_conn()
    try:
        semantic_store.upsert(conn, mem)
    finally:
        conn.close()


# ── _clamp ──────────────────────────────────────────────────


class TestClamp:
    def test_within_range(self):
        assert _clamp(0.5) == 0.5

    def test_below(self):
        assert _clamp(-0.1) == 0.0

    def test_above(self):
        assert _clamp(1.5) == 1.0


# ── _check_three_precepts ──────────────────────────────────


class TestThreePrecepts:
    def test_fabrication_risk_high_confidence_no_grounding(self):
        flags = _check_three_precepts(raw_confidence=0.9, grounding_hits=0, user_query="test")
        assert flags.fabrication_risk is True

    def test_no_fabrication_risk_with_grounding(self):
        flags = _check_three_precepts(raw_confidence=0.9, grounding_hits=3, user_query="test")
        assert flags.fabrication_risk is False

    def test_no_fabrication_risk_low_confidence(self):
        flags = _check_three_precepts(raw_confidence=0.5, grounding_hits=0, user_query="test")
        assert flags.fabrication_risk is False

    def test_false_memory_risk_with_recall_cue(self):
        flags = _check_three_precepts(raw_confidence=0.5, grounding_hits=0, user_query="前に話した猫の名前")
        assert flags.false_memory_risk is True

    def test_no_false_memory_risk_with_grounding(self):
        flags = _check_three_precepts(raw_confidence=0.5, grounding_hits=2, user_query="前に話した猫の名前")
        assert flags.false_memory_risk is False

    def test_no_false_memory_risk_no_recall_cue(self):
        flags = _check_three_precepts(raw_confidence=0.5, grounding_hits=0, user_query="猫が好き")
        assert flags.false_memory_risk is False

    def test_recall_cue_dakke(self):
        flags = _check_three_precepts(raw_confidence=0.5, grounding_hits=0, user_query="好きだっけ")
        assert flags.false_memory_risk is True


# ── metacognitive_check ────────────────────────────────────


class TestMetacognitiveCheck:
    def test_disabled_returns_passthrough(self):
        """When METACOG_ENABLED=False, confidence passes through unchanged."""
        with patch("backend.services.memory.metacognition.settings") as mock_s:
            mock_s.METACOG_ENABLED = False
            result = metacognitive_check(
                raw_confidence=0.8, user_query="test", thread_id="t1",
            )
        assert result.adjusted_confidence == 0.8
        assert result.grounding_hits == 0
        assert result.sankai_flags.fabrication_risk is False

    def test_high_confidence_no_grounding_lowered(self):
        """High confidence + no grounding → confidence lowered."""
        with patch("backend.services.memory.metacognition.settings") as mock_s:
            mock_s.METACOG_ENABLED = True
            mock_s.METACOG_GROUNDING_THRESHOLD = 0.4
            mock_s.SANKAI_CHECK_ENABLED = True
            result = metacognitive_check(
                raw_confidence=0.9, user_query="test query", thread_id="t1",
                prefetched_active=[],  # no memories
            )
        # No grounding (score < 0.2) + high confidence (> 0.7) → * 0.7
        assert result.adjusted_confidence < result.raw_confidence
        assert result.grounding_score == 0.0
        assert result.grounding_hits == 0

    def test_fabrication_risk_caps_at_04(self):
        """fabrication_risk=True → confidence capped at 0.4."""
        with patch("backend.services.memory.metacognition.settings") as mock_s:
            mock_s.METACOG_ENABLED = True
            mock_s.METACOG_GROUNDING_THRESHOLD = 0.4
            mock_s.SANKAI_CHECK_ENABLED = True
            result = metacognitive_check(
                raw_confidence=0.95, user_query="test", thread_id="t1",
                prefetched_active=[],
            )
        assert result.sankai_flags.fabrication_risk is True
        assert result.adjusted_confidence <= 0.4

    def test_with_grounding_raises_confidence(self):
        """Strong grounding + low confidence → confidence raised."""
        # Create memories with embeddings
        fake_vec = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        mem1 = make_semantic(content="cat fact", confidence=0.9, status="confirmed")
        mem1.embedding = fake_vec.tobytes()
        mem2 = make_semantic(content="dog fact", confidence=0.8, status="confirmed")
        mem2.embedding = fake_vec.tobytes()
        mem3 = make_semantic(content="fish fact", confidence=0.85, status="confirmed")
        mem3.embedding = fake_vec.tobytes()

        query_vec = np.array([[0.9, 0.1, 0.0]], dtype=np.float32)

        with patch("backend.services.memory.metacognition.settings") as mock_s:
            mock_s.METACOG_ENABLED = True
            mock_s.METACOG_GROUNDING_THRESHOLD = 0.3
            mock_s.SANKAI_CHECK_ENABLED = True
            with patch("backend.core.embedding_model.encode", return_value=query_vec):
                result = metacognitive_check(
                    raw_confidence=0.3, user_query="cat query", thread_id="t1",
                    prefetched_active=[mem1, mem2, mem3],
                )

        # Should have grounding from 3 confirmed memories with high sim
        assert result.grounding_hits == 3
        assert result.grounding_score > 0.6
        assert result.adjusted_confidence > result.raw_confidence

    def test_contradiction_caps_confidence(self):
        """Contradicting memories cap confidence at 0.5."""
        # Create memories with very different embeddings
        vec_a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        vec_b = np.array([0.0, 0.0, 1.0], dtype=np.float32)

        mem1 = make_semantic(content="likes cats", confidence=0.9, status="confirmed")
        mem1.embedding = vec_a.tobytes()
        mem2 = make_semantic(content="hates cats", confidence=0.9, status="confirmed")
        mem2.embedding = vec_b.tobytes()

        query_vec = np.array([[0.7, 0.1, 0.5]], dtype=np.float32)

        with patch("backend.services.memory.metacognition.settings") as mock_s:
            mock_s.METACOG_ENABLED = True
            mock_s.METACOG_GROUNDING_THRESHOLD = 0.1  # low threshold to include both
            mock_s.SANKAI_CHECK_ENABLED = True
            with patch("backend.core.embedding_model.encode", return_value=query_vec):
                result = metacognitive_check(
                    raw_confidence=0.8, user_query="cats", thread_id="t1",
                    prefetched_active=[mem1, mem2],
                )

        assert result.contradiction_detected is True
        assert result.adjusted_confidence <= 0.5

    def test_false_memory_risk_flagged(self):
        """Recall cue + no grounding → false_memory_risk=True."""
        with patch("backend.services.memory.metacognition.settings") as mock_s:
            mock_s.METACOG_ENABLED = True
            mock_s.METACOG_GROUNDING_THRESHOLD = 0.4
            mock_s.SANKAI_CHECK_ENABLED = True
            result = metacognitive_check(
                raw_confidence=0.5, user_query="前に話した猫の名前だっけ",
                thread_id="t1", prefetched_active=[],
            )
        assert result.sankai_flags.false_memory_risk is True

    def test_prefetched_skips_db_query(self):
        """prefetched_active prevents DB query."""
        with patch("backend.services.memory.metacognition.settings") as mock_s:
            mock_s.METACOG_ENABLED = True
            mock_s.METACOG_GROUNDING_THRESHOLD = 0.4
            mock_s.SANKAI_CHECK_ENABLED = True
            with patch("backend.services.memory.semantic_store.search_active") as mock_sa:
                result = metacognitive_check(
                    raw_confidence=0.5, user_query="test", thread_id="t1",
                    prefetched_active=[],
                )
                mock_sa.assert_not_called()

    def test_embedding_failure_graceful(self):
        """Embedding failure doesn't crash — returns 0 grounding."""
        mem = make_semantic(content="test", confidence=0.8)

        with patch("backend.services.memory.metacognition.settings") as mock_s:
            mock_s.METACOG_ENABLED = True
            mock_s.METACOG_GROUNDING_THRESHOLD = 0.4
            mock_s.SANKAI_CHECK_ENABLED = True
            with patch("backend.core.embedding_model.encode", return_value=None):
                result = metacognitive_check(
                    raw_confidence=0.6, user_query="test", thread_id="t1",
                    prefetched_active=[mem],
                )

        assert result.grounding_hits == 0
        assert result.adjusted_confidence == result.raw_confidence  # no change
