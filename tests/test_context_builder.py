"""Tests for context_builder (Phase D)."""
from __future__ import annotations

import time
import uuid

import pytest

from backend.core.db import get_conn, init_schema
from backend.services.memory import semantic_store, working_store
from backend.services.memory.context_builder import (
    build_memory_context,
    format_memory_sections,
    _build_pinned,
    _build_patterns,
    _build_working,
    _build_short_term,
    _build_long_term,
)
from backend.services.memory.models import SemanticMemory, WorkingItem
from conftest import make_semantic as _make_semantic, make_working as _make_working


@pytest.fixture(autouse=True)
def _setup_db():
    init_schema()
    conn = get_conn()
    try:
        conn.execute("DELETE FROM working_items")
        conn.execute("DELETE FROM semantic_memories")
        conn.execute("DELETE FROM memory_index")
        conn.execute("DELETE FROM memory_events")
    finally:
        conn.close()
    yield


def _insert_semantic(mem: SemanticMemory):
    conn = get_conn()
    try:
        semantic_store.upsert(conn, mem)
    finally:
        conn.close()


def _insert_working(item: WorkingItem):
    conn = get_conn()
    try:
        working_store.add(conn, item)
    finally:
        conn.close()


# ── _build_pinned ──────────────────────────────────────────────


def _search_active(thread_id: str, limit: int = 20):
    """Helper to get active memories for the new _build_pinned / _build_long_term signatures."""
    return semantic_store.search_active(thread_id, limit=limit)


class TestBuildPinned:
    def test_empty_when_no_data(self):
        assert _build_pinned(_search_active("t1")) == ""

    def test_includes_confirmed_high_confidence(self):
        _insert_semantic(_make_semantic(content="user likes cats", confidence=0.9))
        result = _build_pinned(_search_active("t1"))
        assert "user likes cats" in result

    def test_excludes_inferred(self):
        _insert_semantic(_make_semantic(content="maybe likes dogs", status="inferred", confidence=0.9))
        result = _build_pinned(_search_active("t1"))
        assert result == ""

    def test_excludes_low_confidence(self):
        _insert_semantic(_make_semantic(content="uncertain fact", confidence=0.3))
        result = _build_pinned(_search_active("t1"))
        assert result == ""

    def test_respects_limit(self):
        for i in range(10):
            _insert_semantic(_make_semantic(content=f"fact {i}", confidence=0.9))
        result = _build_pinned(_search_active("t1"), limit=3)
        assert result.count("- ") == 3


# ── _build_patterns ───────────────────────────────────────────


class TestBuildPatterns:
    def test_empty_when_no_insights(self):
        """No state_tag='insight' memories → empty string."""
        _insert_semantic(_make_semantic(content="regular fact", state_tag="origin"))
        assert _build_patterns(_search_active("t1")) == ""

    def test_extracts_insight_memories(self):
        """state_tag='insight' memories are extracted."""
        _insert_semantic(_make_semantic(
            content="Originは設計を先に固める",
            state_tag="insight", confidence=0.6, status="inferred",
        ))
        result = _build_patterns(_search_active("t1"))
        assert "設計を先に固める" in result

    def test_includes_both_confirmed_and_inferred(self):
        """Both inferred and confirmed insights are included."""
        _insert_semantic(_make_semantic(
            content="inferred pattern", state_tag="insight",
            confidence=0.5, status="inferred",
        ))
        _insert_semantic(_make_semantic(
            content="confirmed pattern", state_tag="insight",
            confidence=0.8, status="confirmed",
        ))
        result = _build_patterns(_search_active("t1"))
        assert "inferred pattern" in result
        assert "confirmed pattern" in result

    def test_respects_limit(self):
        """Default limit=3 is respected."""
        for i in range(5):
            _insert_semantic(_make_semantic(
                content=f"pattern {i}", state_tag="insight",
                confidence=0.5 + i * 0.05, status="inferred",
            ))
        result = _build_patterns(_search_active("t1"), limit=3)
        assert result.count("- ") == 3

    def test_empty_when_no_data(self):
        assert _build_patterns(_search_active("t1")) == ""


# ── _build_working ─────────────────────────────────────────────


class TestBuildWorking:
    def test_empty_when_no_data(self):
        assert _build_working("t1") == ""

    def test_includes_open_items(self):
        _insert_working(_make_working(content="what is favorite color?"))
        result = _build_working("t1")
        assert "what is favorite color?" in result

    def test_shows_item_type_prefix(self):
        _insert_working(_make_working(item_type="hypothesis", content="might prefer tea"))
        result = _build_working("t1")
        assert "[hypothesis]" in result

    def test_respects_limit(self):
        for i in range(10):
            _insert_working(_make_working(content=f"item {i}"))
        result = _build_working("t1", limit=2)
        assert result.count("- ") == 2


# ── _build_short_term ──────────────────────────────────────────


class TestBuildShortTerm:
    def test_empty_with_none(self):
        assert _build_short_term(None) == ""

    def test_empty_with_empty_list(self):
        assert _build_short_term([]) == ""

    def test_formats_dicts(self):
        result = _build_short_term([
            {"content": "recent message"},
            {"content": "another message"},
        ])
        assert "- recent message" in result
        assert "- another message" in result

    def test_skips_empty_content(self):
        result = _build_short_term([
            {"content": ""},
            {"content": "valid"},
        ])
        assert result == "- valid"


# ── _build_long_term ───────────────────────────────────────────


class TestBuildLongTerm:
    def test_empty_when_no_data(self):
        result = _build_long_term(_search_active("t1"))
        assert result == ""

    def test_includes_semantic_memories(self):
        _insert_semantic(_make_semantic(content="likes coffee", status="confirmed"))
        _insert_semantic(_make_semantic(content="maybe likes tea", status="inferred", confidence=0.6))
        result = _build_long_term(_search_active("t1"))
        assert "(confirmed)" in result
        assert "(inferred)" in result

    def test_deduplicates(self):
        _insert_semantic(_make_semantic(content="same fact", confidence=0.9))
        result = _build_long_term(_search_active("t1"))
        assert result.count("same fact") == 1

    def test_respects_limit(self):
        for i in range(15):
            _insert_semantic(_make_semantic(content=f"fact {i}"))
        result = _build_long_term(_search_active("t1"), limit=5)
        lines = [l for l in result.split("\n") if l.strip()]
        assert len(lines) <= 5


# ── build_memory_context (integration) ─────────────────────────


class TestBuildMemoryContext:
    def test_returns_all_keys(self):
        result = build_memory_context(thread_id="t1")
        assert "pinned" in result
        assert "patterns" in result
        assert "working" in result
        assert "short_term" in result
        assert "long_term" in result

    def test_with_data(self):
        _insert_semantic(_make_semantic(content="confirmed fact", confidence=0.9))
        _insert_semantic(_make_semantic(
            content="cross-day pattern", state_tag="insight",
            confidence=0.6, status="inferred",
        ))
        _insert_working(_make_working(content="open question"))
        result = build_memory_context(
            thread_id="t1",
            short_mem=[{"content": "recent"}],
        )
        assert "confirmed fact" in result["pinned"]
        assert "cross-day pattern" in result["patterns"]
        assert "open question" in result["working"]
        assert "recent" in result["short_term"]


# ── format_memory_sections ─────────────────────────────────────


class TestFormatMemorySections:
    def test_empty_sections(self):
        sections = {"pinned": "", "patterns": "", "working": "", "short_term": "", "long_term": ""}
        result = format_memory_sections(sections)
        assert "=== MEMORY ===" in result
        assert "PINNED" not in result
        assert "PATTERNS" not in result
        assert "WORKING" not in result

    def test_all_sections(self):
        sections = {
            "pinned": "- fact 1",
            "patterns": "- pattern 1",
            "working": "- question 1",
            "short_term": "- recent 1",
            "long_term": "- old 1",
        }
        result = format_memory_sections(sections)
        assert "=== PINNED FACTS ===" in result
        assert "=== PATTERNS ===" in result
        assert "=== WORKING ===" in result
        assert "=== MEMORY ===" in result
        assert "Short Term:" in result
        assert "Long Term:" in result

    def test_patterns_after_pinned_before_working(self):
        """PATTERNS appears after PINNED FACTS and before WORKING."""
        sections = {
            "pinned": "- fact",
            "patterns": "- pattern",
            "working": "- question",
            "short_term": "",
            "long_term": "",
        }
        result = format_memory_sections(sections)
        pinned_pos = result.index("PINNED FACTS")
        patterns_pos = result.index("PATTERNS")
        working_pos = result.index("WORKING")
        assert pinned_pos < patterns_pos < working_pos

    def test_partial_sections(self):
        sections = {"pinned": "", "patterns": "", "working": "- q1", "short_term": "", "long_term": "- m1"}
        result = format_memory_sections(sections)
        assert "PINNED" not in result
        assert "PATTERNS" not in result
        assert "=== WORKING ===" in result
        assert "Long Term:" in result


# ── R.d: Pinned sort mode ────────────────────────────────────


class TestPinnedSortMode:
    """Tests for R.d: PINNED_SORT_MODE configuration."""

    def test_confidence_mode_preserves_order(self):
        """PINNED_SORT_MODE=confidence keeps confidence DESC order (default from DB)."""
        from unittest.mock import patch

        _insert_semantic(_make_semantic(content="low conf", confidence=0.75))
        _insert_semantic(_make_semantic(content="high conf", confidence=0.95))

        with patch("backend.services.memory.context_builder.settings") as mock_s:
            mock_s.PINNED_SORT_MODE = "confidence"
            mock_s.CONTEXT_MAX_PINNED = 5
            result = _build_pinned(_search_active("t1"), user_query="test")

        lines = result.strip().split("\n")
        assert len(lines) == 2
        # confidence DESC order from search_active
        assert "high conf" in lines[0]
        assert "low conf" in lines[1]

    def test_relevance_mode_reorders_by_similarity(self):
        """PINNED_SORT_MODE=relevance reorders by query similarity."""
        from unittest.mock import patch
        import numpy as np

        # Create memories with embeddings
        cat_vec = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        dog_vec = np.array([0.0, 1.0, 0.0], dtype=np.float32)

        mem_cat = _make_semantic(content="user likes cats", confidence=0.8)
        mem_cat.embedding = cat_vec.tobytes()
        mem_dog = _make_semantic(content="user has a dog", confidence=0.9)
        mem_dog.embedding = dog_vec.tobytes()

        _insert_semantic(mem_cat)
        _insert_semantic(mem_dog)

        active = _search_active("t1")

        # Query embedding similar to cat
        query_vec = np.array([[0.9, 0.1, 0.0]], dtype=np.float32)
        with patch("backend.services.memory.context_builder.settings") as mock_s:
            mock_s.PINNED_SORT_MODE = "relevance"
            with patch("backend.core.embedding_model.encode", return_value=query_vec):
                result = _build_pinned(active, user_query="cats are great")

        lines = result.strip().split("\n")
        assert len(lines) == 2
        # cat should be first (higher similarity)
        assert "cats" in lines[0]

    def test_random_mode_returns_all_items(self):
        """PINNED_SORT_MODE=random returns all pinned items (order varies)."""
        from unittest.mock import patch

        for i in range(5):
            _insert_semantic(_make_semantic(content=f"random fact {i}", confidence=0.9))

        with patch("backend.services.memory.context_builder.settings") as mock_s:
            mock_s.PINNED_SORT_MODE = "random"
            result = _build_pinned(_search_active("t1"), limit=5)

        assert result.count("- ") == 5

    def test_fallback_on_embedding_failure(self):
        """When embedding fails in relevance mode, falls back to default order."""
        from unittest.mock import patch

        _insert_semantic(_make_semantic(content="fact A", confidence=0.9))
        _insert_semantic(_make_semantic(content="fact B", confidence=0.8))

        with patch("backend.services.memory.context_builder.settings") as mock_s:
            mock_s.PINNED_SORT_MODE = "relevance"
            with patch("backend.core.embedding_model.encode", return_value=None):
                result = _build_pinned(_search_active("t1"), user_query="test query")

        assert "fact A" in result
        assert "fact B" in result

    def test_relevance_mode_topic_intent_boost(self):
        """M.2: Topic keyword in query boosts matching pinned facts."""
        from unittest.mock import patch
        import numpy as np
        from backend.services.memory.retrieval import QueryIntent

        # Two memories with identical similarity but different content
        vec = np.array([0.5, 0.5, 0.0], dtype=np.float32)
        mem_game = _make_semantic(content="ゲームが好き", confidence=0.8)
        mem_game.embedding = vec.tobytes()
        mem_other = _make_semantic(content="コーヒーが好き", confidence=0.85)
        mem_other.embedding = vec.tobytes()

        _insert_semantic(mem_game)
        _insert_semantic(mem_other)
        active = _search_active("t1")

        # Mock detect_intent to ensure "ゲーム" is extracted as keyword
        # (janome may not be available in test environment)
        mock_intent = QueryIntent(is_topic_specific=True, topic_keywords=["ゲーム"])

        # Query about "ゲーム" — both have same cosine sim, but game gets intent bonus
        query_vec = np.array([[0.5, 0.5, 0.0]], dtype=np.float32)
        with patch("backend.services.memory.context_builder.settings") as mock_s:
            mock_s.PINNED_SORT_MODE = "relevance"
            with patch("backend.core.embedding_model.encode", return_value=query_vec), \
                 patch("backend.services.memory.retrieval.detect_intent", return_value=mock_intent):
                result = _build_pinned(active, user_query="ゲームについて教えて")

        lines = result.strip().split("\n")
        assert len(lines) == 2
        # Game fact should come first due to topic keyword bonus
        assert "ゲーム" in lines[0]

    def test_relevance_mode_temporal_intent_boost(self):
        """M.2: Temporal query boosts recently updated facts."""
        from unittest.mock import patch
        import numpy as np

        vec = np.array([0.5, 0.5, 0.0], dtype=np.float32)
        now = time.time()

        # Recent memory (1 hour ago)
        mem_recent = _make_semantic(content="recent fact", confidence=0.8)
        mem_recent.embedding = vec.tobytes()
        mem_recent.updated_at = now - 3600  # 1h ago

        # Old memory (10 days ago)
        mem_old = _make_semantic(content="old fact", confidence=0.85)
        mem_old.embedding = vec.tobytes()
        mem_old.updated_at = now - 864000  # 10d ago

        _insert_semantic(mem_recent)
        _insert_semantic(mem_old)
        active = _search_active("t1")

        # Query with "昨日" — temporal bonus for recent facts
        query_vec = np.array([[0.5, 0.5, 0.0]], dtype=np.float32)
        with patch("backend.services.memory.context_builder.settings") as mock_s:
            mock_s.PINNED_SORT_MODE = "relevance"
            with patch("backend.core.embedding_model.encode", return_value=query_vec):
                result = _build_pinned(active, user_query="昨日の話なんだけど")

        lines = result.strip().split("\n")
        assert len(lines) == 2
        # Recent fact should come first due to temporal bonus ("昨日" ≤ 48h)
        assert "recent" in lines[0]

    def test_relevance_mode_no_intent_pure_similarity(self):
        """M.2: Without temporal/topic intent, uses pure similarity."""
        from unittest.mock import patch
        import numpy as np

        # High similarity memory
        hi_vec = np.array([0.9, 0.1, 0.0], dtype=np.float32)
        # Low similarity memory
        lo_vec = np.array([0.1, 0.9, 0.0], dtype=np.float32)

        mem_hi = _make_semantic(content="similar to query", confidence=0.8)
        mem_hi.embedding = hi_vec.tobytes()
        mem_lo = _make_semantic(content="different topic", confidence=0.9)
        mem_lo.embedding = lo_vec.tobytes()

        _insert_semantic(mem_hi)
        _insert_semantic(mem_lo)
        active = _search_active("t1")

        # Generic query (no temporal, no specific topic keywords)
        query_vec = np.array([[0.9, 0.1, 0.0]], dtype=np.float32)
        with patch("backend.services.memory.context_builder.settings") as mock_s:
            mock_s.PINNED_SORT_MODE = "relevance"
            with patch("backend.core.embedding_model.encode", return_value=query_vec):
                result = _build_pinned(active, user_query="hi")

        lines = result.strip().split("\n")
        assert len(lines) == 2
        # Higher similarity should be first
        assert "similar" in lines[0]
