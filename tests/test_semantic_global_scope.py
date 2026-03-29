"""Tests for D案: Semantic Memory Global Scope.

semantic_memories はニアの「知識」であり、どのスレッドで学んだかに関係なく
グローバルにアクセスできる。このテストファイルはその設計意図を保護する。

- semantic_memories: グローバル（thread_id フィルタなし）
- working_items: スレッドスコープ（thread_id フィルタあり）
- memory_events: スレッドスコープ（変更なし）
"""
from __future__ import annotations

import time
import uuid
from unittest.mock import patch

import numpy as np
import pytest

from backend.core.db import get_conn, init_schema
from backend.services.memory import semantic_store, working_store
from backend.services.memory.models import SemanticMemory, WorkingItem
from conftest import make_semantic as _make_semantic, make_working as _make_working


@pytest.fixture(autouse=True)
def _setup_db():
    init_schema()
    conn = get_conn()
    try:
        conn.execute("DELETE FROM semantic_memories")
        conn.execute("DELETE FROM working_items")
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


# ── search_active: グローバル ──────────────────────────────────


class TestSearchActiveGlobal:
    """search_active() はスレッド横断で全 semantic memories を返す。"""

    def test_returns_memories_from_all_threads(self):
        _insert_semantic(_make_semantic(content="Jun learned this", thread_id="default_thread"))
        _insert_semantic(_make_semantic(content="Nero learned this", thread_id="nero_meeting_001"))

        results = semantic_store.search_active("default_thread")
        contents = [m.content for m in results]
        assert "Jun learned this" in contents
        assert "Nero learned this" in contents

    def test_returns_same_results_regardless_of_caller_thread(self):
        _insert_semantic(_make_semantic(content="shared knowledge", thread_id="default_thread"))

        from_default = semantic_store.search_active("default_thread")
        from_nero = semantic_store.search_active("nero_meeting_001")
        from_empty = semantic_store.search_active("")

        assert len(from_default) == len(from_nero) == len(from_empty) == 1
        assert from_default[0].content == from_nero[0].content == from_empty[0].content

    def test_thread_id_preserved_as_provenance(self):
        """thread_id はクエリには使われないが出典として保存される。"""
        _insert_semantic(_make_semantic(content="from nero", thread_id="nero_meeting_001"))

        results = semantic_store.search_active("default_thread")
        assert len(results) == 1
        assert results[0].thread_id == "nero_meeting_001"

    def test_filters_by_status(self):
        _insert_semantic(_make_semantic(content="active", status="confirmed", thread_id="t1"))
        _insert_semantic(_make_semantic(content="revoked", status="revoked", thread_id="t2"))

        results = semantic_store.search_active("t1")
        contents = [m.content for m in results]
        assert "active" in contents
        assert "revoked" not in contents

    def test_many_threads(self):
        for i in range(5):
            _insert_semantic(_make_semantic(
                content=f"knowledge from thread {i}",
                thread_id=f"thread_{i}",
            ))

        results = semantic_store.search_active("thread_0")
        assert len(results) == 5


# ── search_by_tag: グローバル ──────────────────────────────────


class TestSearchByTagGlobal:
    """search_by_tag() もスレッド横断でタグ検索する。"""

    def test_returns_tagged_memories_from_all_threads(self):
        _insert_semantic(_make_semantic(
            content="Jun insight", state_tag="insight", thread_id="default_thread",
        ))
        _insert_semantic(_make_semantic(
            content="Nero insight", state_tag="insight", thread_id="nero_meeting_002",
        ))

        results = semantic_store.search_by_tag("default_thread", "insight")
        contents = [m.content for m in results]
        assert "Jun insight" in contents
        assert "Nero insight" in contents

    def test_tag_filter_still_works(self):
        _insert_semantic(_make_semantic(content="origin fact", state_tag="origin", thread_id="t1"))
        _insert_semantic(_make_semantic(content="insight fact", state_tag="insight", thread_id="t2"))

        origin_results = semantic_store.search_by_tag("t1", "origin")
        insight_results = semantic_store.search_by_tag("t1", "insight")

        assert len(origin_results) == 1
        assert origin_results[0].content == "origin fact"
        assert len(insight_results) == 1
        assert insight_results[0].content == "insight fact"


# ── working_items: スレッドスコープ維持 ────────────────────────


class TestWorkingItemsThreadScoped:
    """working_items はスレッドスコープのまま。D案の影響なし。"""

    def test_working_items_isolated_by_thread(self):
        from backend.services.memory.context_builder import _build_working

        _insert_working(_make_working(content="Jun question", thread_id="default_thread"))
        _insert_working(_make_working(content="Nero question", thread_id="nero_meeting_001"))

        jun_result = _build_working("default_thread")
        nero_result = _build_working("nero_meeting_001")

        assert "Jun question" in jun_result
        assert "Nero question" not in jun_result
        assert "Nero question" in nero_result
        assert "Jun question" not in nero_result


# ── context_builder: グローバル semantic でコンテキスト構築 ──────


class TestContextBuilderGlobalSemantic:
    """context_builder は全スレッドの semantic knowledge を使ってコンテキストを構築する。"""

    def test_pinned_includes_cross_thread_memories(self):
        from backend.services.memory.context_builder import _build_pinned

        _insert_semantic(_make_semantic(
            content="fact from Jun thread", confidence=0.9, thread_id="default_thread",
        ))
        _insert_semantic(_make_semantic(
            content="fact from Nero thread", confidence=0.9, thread_id="nero_meeting_001",
        ))

        active = semantic_store.search_active("default_thread")
        result = _build_pinned(active)
        assert "fact from Jun thread" in result
        assert "fact from Nero thread" in result

    def test_patterns_includes_cross_thread_insights(self):
        from backend.services.memory.context_builder import _build_patterns

        _insert_semantic(_make_semantic(
            content="Jun thread pattern", state_tag="insight",
            confidence=0.6, status="inferred", thread_id="default_thread",
        ))
        _insert_semantic(_make_semantic(
            content="Nero thread pattern", state_tag="insight",
            confidence=0.7, status="inferred", thread_id="nero_meeting_001",
        ))

        active = semantic_store.search_active("default_thread")
        result = _build_patterns(active)
        assert "Jun thread pattern" in result
        assert "Nero thread pattern" in result

    def test_long_term_includes_cross_thread_memories(self):
        from backend.services.memory.context_builder import _build_long_term

        _insert_semantic(_make_semantic(
            content="long term from Jun", confidence=0.7, thread_id="default_thread",
        ))
        _insert_semantic(_make_semantic(
            content="long term from Nero", confidence=0.7, thread_id="nero_meeting_001",
        ))

        active = semantic_store.search_active("default_thread")
        result = _build_long_term(active)
        assert "long term from Jun" in result
        assert "long term from Nero" in result

    def test_build_memory_context_integrates_global_semantic(self):
        from backend.services.memory.context_builder import build_memory_context

        _insert_semantic(_make_semantic(
            content="Nero told me about stars", confidence=0.9, thread_id="nero_meeting_001",
        ))

        result = build_memory_context(thread_id="default_thread")
        assert "Nero told me about stars" in result["pinned"]


# ── retrieval: グローバル候補プール ────────────────────────────


class TestRetrievalGlobalPool:
    """retrieve() のグローバル候補プールをテスト。"""

    def test_retrieve_finds_cross_thread_memories(self):
        from backend.services.memory.retrieval import retrieve

        _insert_semantic(_make_semantic(content="cats from Jun", thread_id="default_thread"))
        _insert_semantic(_make_semantic(content="dogs from Nero", thread_id="nero_meeting_001"))

        with patch("backend.services.memory.retrieval._encode_texts", return_value=None):
            result = retrieve("animals", "default_thread")

        contents = [m.content for m in result]
        assert "cats from Jun" in contents
        assert "dogs from Nero" in contents


# ── guardrail の search_active 利用: グローバル ────────────────


class TestGuardrailSearchActiveGlobal:
    """guardrail が使う search_active は全スレッドの記憶を返す。

    guardrail 関数自体のテストは test_guardrail.py に委譲。
    ここでは guardrail が依存する search_active のグローバル性を保証する。
    """

    def test_search_active_for_guardrail_returns_cross_thread(self):
        """guardrail が check_provenance 等で使う search_active は
        異なるスレッドの記憶も含む。"""
        _insert_semantic(_make_semantic(
            content="ネロが言ってた星の話", confidence=0.9, thread_id="nero_meeting_001",
        ))
        _insert_semantic(_make_semantic(
            content="ジュンとの会話で学んだこと", confidence=0.8, thread_id="default_thread",
        ))

        # guardrail は search_active(thread_id, limit=30) を呼ぶ
        active = semantic_store.search_active("default_thread", limit=30)
        contents = [m.content for m in active]

        assert "ネロが言ってた星の話" in contents
        assert "ジュンとの会話で学んだこと" in contents

    def test_search_active_for_guardrail_includes_both_statuses(self):
        """guardrail が参照する記憶には confirmed と inferred の両方が含まれる。"""
        _insert_semantic(_make_semantic(
            content="confirmed from nero", status="confirmed", thread_id="nero_meeting_001",
        ))
        _insert_semantic(_make_semantic(
            content="inferred from jun", status="inferred", thread_id="default_thread",
        ))

        active = semantic_store.search_active("default_thread", limit=50)
        statuses = {m.status for m in active}
        assert "confirmed" in statuses
        assert "inferred" in statuses


# ── contradiction: グローバルスキャン ──────────────────────────


class TestContradictionGlobalScan:
    """contradiction detection は全スレッドの semantic を横断スキャンする。"""

    def test_finds_cross_thread_embedding_pairs(self):
        """異なるスレッドの記憶間で類似度ペアが検出される。"""
        from backend.services.memory.contradiction import _find_embedding_pairs

        dim = 384  # match actual embedding model dimension
        rng = np.random.RandomState(42)
        vec_a = rng.randn(dim).astype(np.float32)
        vec_a /= np.linalg.norm(vec_a)
        # vec_b: very similar to vec_a (high cosine sim)
        vec_b = vec_a + rng.randn(dim).astype(np.float32) * 0.01
        vec_b /= np.linalg.norm(vec_b)

        mem_a = _make_semantic(id="a", content="fact A", thread_id="default_thread")
        mem_a.embedding = vec_a.tobytes()
        mem_b = _make_semantic(id="b", content="fact B", thread_id="nero_meeting_001")
        mem_b.embedding = vec_b.tobytes()

        # Pass directly to avoid DB encoding issues
        pairs = _find_embedding_pairs([mem_a, mem_b], threshold=0.9)

        assert len(pairs) >= 1
        ids_in_pairs = {(p[0].id, p[1].id) for p in pairs}
        assert ("a", "b") in ids_in_pairs or ("b", "a") in ids_in_pairs

    def test_null_embedding_skipped_not_crashed(self):
        """NULL embedding の記憶はスキップされてクラッシュしない。"""
        from backend.services.memory.contradiction import _find_embedding_pairs

        dim = 384
        vec = np.random.randn(dim).astype(np.float32)
        vec /= np.linalg.norm(vec)

        mem_with = _make_semantic(id="with_emb", content="has embedding", thread_id="t1")
        mem_with.embedding = vec.tobytes()
        mem_without = _make_semantic(id="no_emb", content="no embedding", thread_id="t2")
        # mem_without.embedding is None by default

        # Pass directly to avoid DB encoding
        pairs = _find_embedding_pairs([mem_with, mem_without], threshold=0.9)
        assert isinstance(pairs, list)

    def test_scan_input_is_global(self):
        """scan_contradictions が使う search_active は全スレッドを含む。"""
        _insert_semantic(_make_semantic(
            content="coffee lover", confidence=0.9, thread_id="default_thread",
        ))
        _insert_semantic(_make_semantic(
            content="tea preference", confidence=0.8, thread_id="nero_meeting_001",
        ))

        # scan_contradictions は内部で search_active を呼ぶ
        active = semantic_store.search_active("default_thread", limit=200)
        assert len(active) == 2
        thread_ids = {m.thread_id for m in active}
        assert "default_thread" in thread_ids
        assert "nero_meeting_001" in thread_ids


# ── metacognition: グローバル grounding ────────────────────────


class TestMetacognitionGlobalGrounding:
    """metacognition の grounding check は全スレッドの semantic を参照する。"""

    def test_grounding_sees_cross_thread_via_prefetch(self):
        """prefetched_active にクロススレッドの記憶を渡すと grounding に反映される。"""
        from backend.services.memory.metacognition import metacognitive_check

        dim = 384
        rng = np.random.RandomState(42)
        vec = rng.randn(dim).astype(np.float32)
        vec /= np.linalg.norm(vec)

        mem = _make_semantic(
            content="星の話をした", confidence=0.9, status="confirmed",
            thread_id="nero_meeting_001",
        )
        mem.embedding = vec.tobytes()

        # encode returns a vector similar to mem's embedding → high similarity → grounding hit
        query_vec = vec.copy().reshape(1, -1)
        with patch("backend.core.embedding_model.encode", return_value=query_vec), \
             patch("backend.core.embedding_model.cosine_similarity", return_value=0.9):
            result = metacognitive_check(
                raw_confidence=0.7,
                user_query="星の話",
                thread_id="default_thread",
                prefetched_active=[mem],
            )

        assert result.grounding_hits > 0
        assert result.grounding_score > 0.0

    def test_search_active_feeds_global_data_to_metacog(self):
        """metacognitive_check が内部で呼ぶ search_active は全スレッドの記憶を返す。"""
        _insert_semantic(_make_semantic(
            content="from nero thread", confidence=0.9, thread_id="nero_meeting_001",
        ))
        _insert_semantic(_make_semantic(
            content="from default thread", confidence=0.8, thread_id="default_thread",
        ))

        # metacog は search_active(thread_id, limit=10) を呼ぶ
        candidates = semantic_store.search_active("default_thread", limit=10)
        assert len(candidates) == 2
        thread_ids = {m.thread_id for m in candidates}
        assert "nero_meeting_001" in thread_ids
        assert "default_thread" in thread_ids
