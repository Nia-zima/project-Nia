"""Tests for Query-Aware Memory Retrieval (Phase M.1)."""
from __future__ import annotations

import time
import uuid
from unittest.mock import patch

import numpy as np
import pytest

from backend.core.db import get_conn, init_schema
from backend.services.memory import semantic_store
from backend.services.memory.models import SemanticMemory
from backend.services.memory.retrieval import (
    QueryIntent,
    ScoredMemory,
    detect_intent,
    semantic_search,
    hybrid_rank,
    select_top_k,
    retrieve,
)


@pytest.fixture(autouse=True)
def _setup_db():
    init_schema()
    conn = get_conn()
    try:
        conn.execute("DELETE FROM semantic_memories")
    finally:
        conn.close()
    yield


def _make_semantic(
    *,
    id: str = None,
    thread_id: str = "t1",
    content: str = "test fact",
    status: str = "confirmed",
    confidence: float = 0.8,
    updated_at: float = None,
) -> SemanticMemory:
    now = time.time()
    return SemanticMemory(
        id=id or str(uuid.uuid4()),
        thread_id=thread_id,
        content=content,
        valid_from=now,
        created_at=now,
        updated_at=updated_at or now,
        status=status,
        confidence=confidence,
    )


def _insert(mem: SemanticMemory):
    conn = get_conn()
    try:
        semantic_store.upsert(conn, mem)
    finally:
        conn.close()


# ── detect_intent ────────────────────────────────────────────────


class TestDetectIntent:
    def test_empty_query(self):
        intent = detect_intent("")
        assert not intent.is_temporal
        assert not intent.is_recall
        assert not intent.is_topic_specific

    def test_temporal_yesterday(self):
        intent = detect_intent("昨日話したこと")
        assert intent.is_temporal
        assert intent.temporal_hint == "yesterday"

    def test_temporal_recent(self):
        intent = detect_intent("さっきの話")
        assert intent.is_temporal
        assert intent.temporal_hint == "recent"

    def test_temporal_before(self):
        intent = detect_intent("前に話したこと")
        assert intent.is_temporal
        assert intent.temporal_hint == "old"

    def test_recall_dakke(self):
        intent = detect_intent("好きな食べ物だっけ？")
        assert intent.is_recall

    def test_recall_itteta(self):
        intent = detect_intent("ゲームについてって言ってた")
        assert intent.is_recall

    def test_recall_oboeteru(self):
        intent = detect_intent("覚えてる？")
        assert intent.is_recall

    def test_topic_keywords(self):
        intent = detect_intent("ゲームについて")
        assert intent.is_topic_specific
        assert "ゲーム" in intent.topic_keywords

    def test_combined_temporal_and_recall(self):
        intent = detect_intent("昨日の好きな食べ物だっけ？")
        assert intent.is_temporal
        assert intent.is_recall

    def test_no_short_keywords(self):
        # Single-char tokens should be filtered
        intent = detect_intent("あ い う")
        assert not intent.is_topic_specific


# ── semantic_search ──────────────────────────────────────────────


class TestSemanticSearch:
    def test_empty_query(self):
        assert semantic_search("", []) == []

    def test_empty_candidates(self):
        assert semantic_search("test query", []) == []

    def test_returns_scored_memories(self):
        mems = [
            _make_semantic(content="猫が好き"),
            _make_semantic(content="犬も好き"),
        ]
        # Mock embedding to return predictable vectors
        fake_vecs = np.array([
            [1.0, 0.0, 0.0],  # query
            [0.9, 0.1, 0.0],  # "猫が好き" - similar
            [0.1, 0.9, 0.0],  # "犬も好き" - less similar
        ], dtype=np.float32)
        # Normalize
        fake_vecs = fake_vecs / np.linalg.norm(fake_vecs, axis=1, keepdims=True)

        with patch("backend.services.memory.retrieval._encode_texts") as mock_encode:
            # First call: query encoding
            mock_encode.side_effect = [
                fake_vecs[:1],   # query vec
                fake_vecs[1:],   # candidate vecs
            ]
            scored = semantic_search("猫の話", mems)

        assert len(scored) == 2
        # First should have higher similarity
        assert scored[0].similarity > scored[1].similarity

    def test_handles_embedding_failure(self):
        mems = [_make_semantic(content="test")]
        with patch("backend.services.memory.retrieval._encode_texts", return_value=None):
            result = semantic_search("query", mems)
        assert result == []


# ── hybrid_rank ──────────────────────────────────────────────────


class TestHybridRank:
    def test_empty_candidates(self):
        assert hybrid_rank([], QueryIntent(), time.time()) == []

    def test_scores_calculated(self):
        now = time.time()
        mem = _make_semantic(content="test", confidence=0.8, updated_at=now)
        candidates = [ScoredMemory(memory=mem, similarity=0.7)]
        ranked = hybrid_rank(candidates, QueryIntent(), now)
        assert len(ranked) == 1
        assert ranked[0].score > 0

    def test_recall_weights_sim_higher(self):
        now = time.time()
        mem = _make_semantic(content="test", confidence=0.5, updated_at=now)
        intent_recall = QueryIntent(is_recall=True)
        intent_default = QueryIntent()

        candidates_r = [ScoredMemory(memory=mem, similarity=0.9)]
        candidates_d = [ScoredMemory(memory=mem, similarity=0.9)]

        ranked_r = hybrid_rank(candidates_r, intent_recall, now)
        ranked_d = hybrid_rank(candidates_d, intent_default, now)

        # Recall should produce higher score for same similarity (sim weight 0.55 vs 0.45)
        assert ranked_r[0].score > ranked_d[0].score

    def test_temporal_weights_recency_higher(self):
        now = time.time()
        # Recent memory
        mem_new = _make_semantic(content="new", confidence=0.5, updated_at=now)
        # Old memory
        mem_old = _make_semantic(content="old", confidence=0.5, updated_at=now - 86400 * 14)

        intent = QueryIntent(is_temporal=True, temporal_hint="yesterday")

        candidates = [
            ScoredMemory(memory=mem_new, similarity=0.5),
            ScoredMemory(memory=mem_old, similarity=0.5),
        ]
        ranked = hybrid_rank(candidates, intent, now)

        # New memory should score higher due to recency weight
        scores = {sm.memory.content: sm.score for sm in ranked}
        assert scores["new"] > scores["old"]

    def test_confidence_affects_score(self):
        now = time.time()
        mem_high = _make_semantic(content="high conf", confidence=0.9, updated_at=now)
        mem_low = _make_semantic(content="low conf", confidence=0.2, updated_at=now)

        candidates = [
            ScoredMemory(memory=mem_high, similarity=0.5),
            ScoredMemory(memory=mem_low, similarity=0.5),
        ]
        ranked = hybrid_rank(candidates, QueryIntent(), now)
        scores = {sm.memory.content: sm.score for sm in ranked}
        assert scores["high conf"] > scores["low conf"]


# ── select_top_k ─────────────────────────────────────────────────


class TestSelectTopK:
    def test_empty_list(self):
        assert select_top_k([]) == []

    def test_respects_k_limit(self):
        mems = []
        for i in range(10):
            m = _make_semantic(content=f"fact {i}")
            sm = ScoredMemory(memory=m, score=0.5 + i * 0.01)
            mems.append(sm)
        result = select_top_k(mems, k=3)
        assert len(result) == 3

    def test_deduplicates_by_id(self):
        mem = _make_semantic(id="same-id", content="same")
        scored = [
            ScoredMemory(memory=mem, score=0.9),
            ScoredMemory(memory=mem, score=0.8),
        ]
        result = select_top_k(scored)
        assert len(result) == 1

    def test_filters_below_min_score(self):
        mem = _make_semantic(content="low score")
        scored = [ScoredMemory(memory=mem, score=0.05)]
        result = select_top_k(scored, min_score=0.1)
        assert len(result) == 0

    def test_sorted_by_score_desc(self):
        mems = []
        for i, score in enumerate([0.3, 0.9, 0.6]):
            m = _make_semantic(content=f"fact {i}")
            mems.append(ScoredMemory(memory=m, score=score))
        result = select_top_k(mems)
        assert result[0].score == 0.9
        assert result[-1].score == 0.3


# ── retrieve (E2E) ──────────────────────────────────────────────


class TestRetrieve:
    def test_empty_query_returns_empty(self):
        assert retrieve("", "t1") == []

    def test_disabled_returns_empty(self):
        _insert(_make_semantic(content="test"))
        with patch("backend.services.memory.retrieval.settings") as mock_settings:
            mock_settings.RETRIEVAL_ENABLED = False
            result = retrieve("test query", "t1")
        assert result == []

    def test_no_candidates_returns_empty(self):
        result = retrieve("test query", "t1")
        assert result == []

    def test_returns_memories_with_embedding(self):
        _insert(_make_semantic(content="猫が大好き", confidence=0.8))
        _insert(_make_semantic(content="プログラミングを勉強中", confidence=0.7))

        # Mock embeddings: query "猫" should be more similar to "猫が大好き"
        def fake_encode(texts):
            vecs = []
            for t in texts:
                if "猫" in t:
                    vecs.append([0.9, 0.1, 0.0])
                else:
                    vecs.append([0.1, 0.9, 0.0])
            arr = np.array(vecs, dtype=np.float32)
            return arr / np.linalg.norm(arr, axis=1, keepdims=True)

        with patch("backend.services.memory.retrieval._encode_texts", side_effect=fake_encode):
            result = retrieve("猫の話をしよう", "t1")

        assert len(result) > 0
        # "猫が大好き" should come first (higher similarity)
        assert "猫" in result[0].content

    def test_fallback_on_embedding_failure(self):
        _insert(_make_semantic(content="test memory", confidence=0.8))

        with patch("backend.services.memory.retrieval._encode_texts", return_value=None):
            result = retrieve("test query", "t1")

        # Should still return results (SQL-only fallback with sim=0)
        assert len(result) > 0

    def test_thread_isolation(self):
        _insert(_make_semantic(content="thread1 memory", thread_id="t1"))
        _insert(_make_semantic(content="thread2 memory", thread_id="t2"))

        with patch("backend.services.memory.retrieval._encode_texts", return_value=None):
            result = retrieve("memory", "t1")

        contents = [m.content for m in result]
        assert "thread1 memory" in contents
        assert "thread2 memory" not in contents


# ── context_builder integration ──────────────────────────────────


class TestContextBuilderIntegration:
    def test_long_term_uses_retrieval_when_enabled(self):
        from backend.services.memory.context_builder import _build_long_term

        _insert(_make_semantic(content="relevant memory", confidence=0.8))
        _insert(_make_semantic(content="less relevant", confidence=0.9))

        active = semantic_store.search_active("t1", limit=20)

        # Mock to verify retrieval is called
        with patch("backend.services.memory.retrieval.retrieve") as mock_ret:
            mock_ret.return_value = [_make_semantic(content="retrieved memory")]
            result = _build_long_term(
                active, user_query="test query", thread_id="t1",
            )
            mock_ret.assert_called_once()
        assert "retrieved memory" in result

    def test_long_term_fallback_when_disabled(self):
        from backend.services.memory.context_builder import _build_long_term

        _insert(_make_semantic(content="fallback memory", confidence=0.8))
        active = semantic_store.search_active("t1", limit=20)

        with patch("backend.core.config.settings") as mock_settings:
            mock_settings.RETRIEVAL_ENABLED = False
            mock_settings.RETRIEVAL_CANDIDATE_N = 30
            mock_settings.RETRIEVAL_MIN_SCORE = 0.1
            result = _build_long_term(active, user_query="test", thread_id="t1")

        assert "fallback memory" in result

    def test_long_term_fallback_on_empty_query(self):
        from backend.services.memory.context_builder import _build_long_term

        _insert(_make_semantic(content="some memory", confidence=0.8))
        active = semantic_store.search_active("t1", limit=20)

        result = _build_long_term(active, user_query="", thread_id="t1")
        assert "some memory" in result
