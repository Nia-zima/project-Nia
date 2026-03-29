"""Tests for retrieval logging (Phase M — search observability)."""
from __future__ import annotations

import json
import time
from unittest.mock import patch

import pytest

from backend.core.db import get_conn, init_schema, managed_conn
from backend.services.memory.models import SemanticMemory
from backend.services.memory.retrieval import (
    QueryIntent,
    ScoredMemory,
    _log_to_db,
)
from conftest import make_semantic


@pytest.fixture(autouse=True)
def _setup_db():
    init_schema()
    with managed_conn() as conn:
        conn.execute("DELETE FROM retrieval_logs")
    yield


def _make_scored(
    content: str = "test fact",
    score: float = 0.5,
    similarity: float = 0.4,
    confidence: float = 0.8,
    recency: float = 0.6,
    intent_bonus: float = 0.1,
) -> ScoredMemory:
    mem = make_semantic(content=content)
    return ScoredMemory(
        memory=mem,
        similarity=similarity,
        confidence=confidence,
        recency=recency,
        intent_bonus=intent_bonus,
        score=score,
    )


def _count_logs() -> int:
    with managed_conn() as conn:
        row = conn.execute("SELECT COUNT(*) FROM retrieval_logs").fetchone()
        return row[0]


def _get_last_log() -> dict:
    with managed_conn() as conn:
        row = conn.execute(
            "SELECT * FROM retrieval_logs ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return {}
        return dict(row)


# ── _log_to_db direct tests ──────────────────────────────────


class TestLogToDb:
    def test_inserts_row(self):
        intent = QueryIntent(is_temporal=True, topic_keywords=["ゲーム"])
        top_k = [_make_scored(content="猫が好き", score=0.75)]

        _log_to_db(
            thread_id="t1",
            query="猫の話",
            intent=intent,
            candidates_count=10,
            top_k=top_k,
            elapsed_ms=12.3,
        )

        assert _count_logs() == 1
        log = _get_last_log()
        assert log["thread_id"] == "t1"
        assert log["query"] == "猫の話"
        assert log["candidate_count"] == 10
        assert log["result_count"] == 1
        assert log["elapsed_ms"] == 12.3
        assert log["turn_id"] is None

    def test_intent_flags_format(self):
        # All flags set
        intent = QueryIntent(is_temporal=True, is_recall=True, is_topic_specific=True)
        _log_to_db("t1", "q", intent, 5, [], 1.0)
        assert _get_last_log()["intent_flags"] == "TRK"

        # Clear and test none set
        with managed_conn() as conn:
            conn.execute("DELETE FROM retrieval_logs")
        intent_none = QueryIntent()
        _log_to_db("t1", "q", intent_none, 5, [], 1.0)
        assert _get_last_log()["intent_flags"] == "---"

        # Partial
        with managed_conn() as conn:
            conn.execute("DELETE FROM retrieval_logs")
        intent_partial = QueryIntent(is_recall=True)
        _log_to_db("t1", "q", intent_partial, 5, [], 1.0)
        assert _get_last_log()["intent_flags"] == "-R-"

    def test_results_json_structure(self):
        top_k = [
            _make_scored(content="fact A", score=0.9, similarity=0.8, confidence=0.7, recency=0.6, intent_bonus=0.5),
        ]
        _log_to_db("t1", "q", QueryIntent(), 3, top_k, 5.0)

        log = _get_last_log()
        results = json.loads(log["results"])
        assert len(results) == 1
        entry = results[0]
        assert set(entry.keys()) == {"id", "snippet", "score", "sim", "conf", "rec", "intent"}
        assert entry["score"] == 0.9
        assert entry["sim"] == 0.8
        assert entry["conf"] == 0.7
        assert entry["rec"] == 0.6
        assert entry["intent"] == 0.5

    def test_snippet_truncation(self):
        long_content = "あ" * 200
        top_k = [_make_scored(content=long_content)]
        _log_to_db("t1", "q", QueryIntent(), 1, top_k, 1.0)

        log = _get_last_log()
        results = json.loads(log["results"])
        assert len(results[0]["snippet"]) == 60

    def test_exception_swallowed(self):
        """DB failure should not raise to caller."""
        with patch("backend.core.db.managed_conn", side_effect=Exception("boom")):
            # Should not raise
            _log_to_db("t1", "q", QueryIntent(), 0, [], 1.0)

    def test_topic_keywords_stored(self):
        intent = QueryIntent(topic_keywords=["Python", "ゲーム"])
        _log_to_db("t1", "q", intent, 0, [], 1.0)

        log = _get_last_log()
        keywords = json.loads(log["topic_keywords"])
        assert keywords == ["Python", "ゲーム"]


# ── retrieve integration tests ───────────────────────────────


class TestRetrieveLogging:
    def test_retrieve_logs_when_enabled(self):
        """retrieve() should call _log_to_db when RETRIEVAL_LOG_ENABLED=True."""
        from backend.services.memory.retrieval import retrieve

        mem = make_semantic(content="test memory", confidence=0.8)

        with patch("backend.services.memory.retrieval.settings") as mock_s:
            mock_s.RETRIEVAL_ENABLED = True
            mock_s.RETRIEVAL_LOG_ENABLED = True
            mock_s.RETRIEVAL_CANDIDATE_N = 30
            mock_s.RETRIEVAL_MIN_SCORE = 0.1
            mock_s.RETRIEVAL_W_SIM = 0.45
            mock_s.RETRIEVAL_W_CONF = 0.25
            mock_s.RETRIEVAL_W_REC = 0.15
            mock_s.RETRIEVAL_W_INTENT = 0.15

            with patch("backend.services.memory.retrieval._log_to_db") as mock_log:
                with patch("backend.services.memory.retrieval._encode_texts", return_value=None):
                    retrieve("test query", "t1", prefetched_candidates=[mem])
                mock_log.assert_called_once()

    def test_retrieve_skips_log_when_disabled(self):
        """retrieve() should NOT call _log_to_db when RETRIEVAL_LOG_ENABLED=False."""
        from backend.services.memory.retrieval import retrieve

        mem = make_semantic(content="test memory", confidence=0.8)

        with patch("backend.services.memory.retrieval.settings") as mock_s:
            mock_s.RETRIEVAL_ENABLED = True
            mock_s.RETRIEVAL_LOG_ENABLED = False
            mock_s.RETRIEVAL_CANDIDATE_N = 30
            mock_s.RETRIEVAL_MIN_SCORE = 0.1
            mock_s.RETRIEVAL_W_SIM = 0.45
            mock_s.RETRIEVAL_W_CONF = 0.25
            mock_s.RETRIEVAL_W_REC = 0.15
            mock_s.RETRIEVAL_W_INTENT = 0.15

            with patch("backend.services.memory.retrieval._log_to_db") as mock_log:
                with patch("backend.services.memory.retrieval._encode_texts", return_value=None):
                    retrieve("test query", "t1", prefetched_candidates=[mem])
                mock_log.assert_not_called()


# ── R.c: Retrieval quality evaluation ───────────────────────


class TestEvaluateRetrievalQuality:
    """Tests for R.c: _evaluate_retrieval_quality in Sleep Cycle."""

    def _insert_log(self, thread_id: str, results: list[dict], result_count: int, elapsed_ms: float = 10.0):
        import uuid
        with managed_conn() as conn:
            conn.execute(
                """INSERT INTO retrieval_logs
                   (id, thread_id, turn_id, query, intent_flags, topic_keywords,
                    candidate_count, results, result_count, elapsed_ms, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    uuid.uuid4().hex, thread_id, None, "test query", "---", "[]",
                    20, json.dumps(results, ensure_ascii=False), result_count,
                    elapsed_ms, time.time(),
                ),
            )

    def test_returns_none_when_no_logs(self):
        from backend.scripts.sleep_cycle.orchestrator import _evaluate_retrieval_quality
        result = _evaluate_retrieval_quality("t1")
        assert result is None

    def test_calculates_stats_from_logs(self):
        from backend.scripts.sleep_cycle.orchestrator import _evaluate_retrieval_quality

        # Insert two retrieval logs
        self._insert_log("t1", [
            {"id": "a", "snippet": "cat", "score": 0.8, "sim": 0.7, "conf": 0.9, "rec": 0.5, "intent": 0.1},
            {"id": "b", "snippet": "dog", "score": 0.6, "sim": 0.5, "conf": 0.7, "rec": 0.4, "intent": 0.0},
        ], result_count=2, elapsed_ms=15.0)
        self._insert_log("t1", [
            {"id": "c", "snippet": "fish", "score": 0.4, "sim": 0.3, "conf": 0.5, "rec": 0.3, "intent": 0.2},
        ], result_count=1, elapsed_ms=5.0)

        result = _evaluate_retrieval_quality("t1")

        assert result is not None
        assert result["query_count"] == 2
        assert result["avg_result_count"] == 1.5  # (2+1)/2
        assert result["zero_result_rate"] == 0.0
        # avg_similarity: (0.7 + 0.5 + 0.3) / 3 = 0.5
        assert abs(result["avg_similarity"] - 0.5) < 0.01
        assert abs(result["avg_elapsed_ms"] - 10.0) < 0.01

    def test_counts_zero_results(self):
        from backend.scripts.sleep_cycle.orchestrator import _evaluate_retrieval_quality

        self._insert_log("t1", [], result_count=0)
        self._insert_log("t1", [{"id": "a", "snippet": "x", "score": 0.5, "sim": 0.4, "conf": 0.6, "rec": 0.3, "intent": 0.0}], result_count=1)

        result = _evaluate_retrieval_quality("t1")
        assert result["zero_result_rate"] == 0.5

    def test_saves_to_telemetry_kv(self):
        from backend.scripts.sleep_cycle.orchestrator import _evaluate_retrieval_quality

        self._insert_log("t1", [
            {"id": "a", "snippet": "test", "score": 0.7, "sim": 0.6, "conf": 0.8, "rec": 0.5, "intent": 0.1},
        ], result_count=1)

        _evaluate_retrieval_quality("t1")

        conn = get_conn()
        try:
            row = conn.execute(
                "SELECT v FROM telemetry_kv WHERE k = 'retrieval_query_count'"
            ).fetchone()
            assert row is not None
            assert int(row["v"]) == 1
        finally:
            conn.close()

    def test_thread_isolation(self):
        from backend.scripts.sleep_cycle.orchestrator import _evaluate_retrieval_quality

        self._insert_log("t1", [{"id": "a", "snippet": "x", "score": 0.5, "sim": 0.4, "conf": 0.5, "rec": 0.3, "intent": 0.0}], result_count=1)
        self._insert_log("t2", [{"id": "b", "snippet": "y", "score": 0.5, "sim": 0.4, "conf": 0.5, "rec": 0.3, "intent": 0.0}], result_count=1)

        result = _evaluate_retrieval_quality("t1")
        assert result["query_count"] == 1
