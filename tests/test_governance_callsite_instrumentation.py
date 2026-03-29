"""Tests for Phase M0 governance callsite instrumentation.

Pure unit tests — no real DB, no embeddings, no live transactions.
Verifies that retrieval_completed, context_build_completed,
semantic_promoted, and decay_sweep_completed pass correct provenance
keys and handle empty/zero cases.
"""
from __future__ import annotations

import time
import uuid
from contextlib import contextmanager

import pytest


# ── Shared helpers ───────────────────────────────────────


def _capture_factory():
    """Return (captured_dict, capture_func) for monkeypatching record_event."""
    captured: dict = {}

    def _capture(**kwargs):
        captured.update(kwargs)
        return "fake_id"

    return captured, _capture


def _capture_list_factory():
    """Return (captured_list, capture_func) for monkeypatching batch_with_conn."""
    captured: list = []

    def _capture(conn, events):
        captured.append({"conn": conn, "events": list(events)})
        return len(list(events))

    return captured, _capture


# ── retrieval_completed ──────────────────────────────────


class TestRetrievalGovernanceEvent:
    def _patch_retrieval_deps(self, monkeypatch):
        """Stub out search_active and semantic_search to avoid DB/embedding."""
        from backend.services.memory.retrieval import ScoredMemory
        from backend.services.memory.models import SemanticMemory

        now = time.time()
        fake_mem = SemanticMemory(
            id="fake_mem", thread_id="t", content="何か",
            valid_from=now, status="inferred", confidence=0.5,
            created_at=now, updated_at=now,
        )
        fake_scored = ScoredMemory(memory=fake_mem, similarity=0.3, score=0.3)

        # Bypass DB: return prefetched candidates via search_active stub
        monkeypatch.setattr(
            "backend.services.memory.retrieval.semantic_store.search_active",
            lambda *a, **kw: [fake_mem],
        )
        # Bypass embedding: return deterministic scored list
        monkeypatch.setattr(
            "backend.services.memory.retrieval.semantic_search",
            lambda q, candidates: [
                ScoredMemory(memory=m, similarity=0.3, score=0.3)
                for m in candidates
            ],
        )
        return fake_mem

    def test_provenance_keys_passed(self, monkeypatch):
        """retrieve_with_scores should pass turn_id/message_id/stream_id/trace_id."""
        monkeypatch.setattr("backend.core.config.settings.GOVERNANCE_OBSERVE_ENABLED", True)
        monkeypatch.setattr("backend.core.config.settings.RETRIEVAL_ENABLED", True)
        self._patch_retrieval_deps(monkeypatch)

        captured, capture_fn = _capture_factory()
        monkeypatch.setattr(
            "backend.services.memory.governance_event_writer.record_event", capture_fn,
        )

        from backend.services.memory.retrieval import retrieve_with_scores
        retrieve_with_scores(
            "テスト", "thread_1",
            turn_id="turn_x", message_id="msg_x",
            stream_id="stream_x", trace_id="trace_x",
        )

        assert captured["event_name"] == "retrieval_completed"
        assert captured["thread_id"] == "thread_1"
        assert captured["turn_id"] == "turn_x"
        assert captured["message_id"] == "msg_x"
        assert captured["stream_id"] == "stream_x"
        assert captured["trace_id"] == "trace_x"

    def test_zero_top_k_still_records(self, monkeypatch):
        """Candidates exist but all below threshold → adopted_count=0, event still fires."""
        monkeypatch.setattr("backend.core.config.settings.GOVERNANCE_OBSERVE_ENABLED", True)
        monkeypatch.setattr("backend.core.config.settings.RETRIEVAL_ENABLED", True)
        monkeypatch.setattr("backend.core.config.settings.RETRIEVAL_MIN_SCORE", 999.0)
        self._patch_retrieval_deps(monkeypatch)

        captured, capture_fn = _capture_factory()
        monkeypatch.setattr(
            "backend.services.memory.governance_event_writer.record_event", capture_fn,
        )

        from backend.services.memory.retrieval import retrieve_with_scores
        memories, scored, intent = retrieve_with_scores("テスト", "thread_empty")

        assert captured["event_name"] == "retrieval_completed"
        payload = captured["payload"]
        assert payload["adopted_count"] == 0
        assert payload["candidates_count"] == 1

    def test_no_event_when_flag_off(self, monkeypatch):
        """GOVERNANCE_OBSERVE_ENABLED=False should not call record_event."""
        monkeypatch.setattr("backend.core.config.settings.GOVERNANCE_OBSERVE_ENABLED", False)
        monkeypatch.setattr("backend.core.config.settings.RETRIEVAL_ENABLED", True)
        self._patch_retrieval_deps(monkeypatch)

        captured, capture_fn = _capture_factory()
        monkeypatch.setattr(
            "backend.services.memory.governance_event_writer.record_event", capture_fn,
        )

        from backend.services.memory.retrieval import retrieve_with_scores
        retrieve_with_scores("テスト", "thread_off")

        assert captured == {}


# ── context_build_completed ──────────────────────────────


class TestContextBuilderGovernanceEvent:
    def _patch_ctx_deps(self, monkeypatch):
        """Stub out search_active to avoid DB."""
        monkeypatch.setattr(
            "backend.services.memory.context_builder.semantic_store.search_active",
            lambda *a, **kw: [],
        )

    def test_provenance_keys_passed(self, monkeypatch):
        """build_memory_context should pass turn_id/message_id/stream_id/trace_id."""
        monkeypatch.setattr("backend.core.config.settings.GOVERNANCE_OBSERVE_ENABLED", True)
        self._patch_ctx_deps(monkeypatch)

        captured, capture_fn = _capture_factory()
        monkeypatch.setattr(
            "backend.services.memory.governance_event_writer.record_event", capture_fn,
        )

        from backend.services.memory.context_builder import build_memory_context
        build_memory_context(
            thread_id="thread_2", user_query="テスト",
            turn_id="turn_y", message_id="msg_y",
            stream_id="stream_y", trace_id="trace_y",
        )

        assert captured["event_name"] == "context_build_completed"
        assert captured["turn_id"] == "turn_y"
        assert captured["message_id"] == "msg_y"
        assert captured["stream_id"] == "stream_y"
        assert captured["trace_id"] == "trace_y"

    def test_empty_active_memories_still_records(self, monkeypatch):
        """0 active memories → event still fires with active_count=0."""
        monkeypatch.setattr("backend.core.config.settings.GOVERNANCE_OBSERVE_ENABLED", True)
        self._patch_ctx_deps(monkeypatch)

        captured, capture_fn = _capture_factory()
        monkeypatch.setattr(
            "backend.services.memory.governance_event_writer.record_event", capture_fn,
        )

        from backend.services.memory.context_builder import build_memory_context
        build_memory_context(thread_id="thread_empty_ctx")

        assert captured["event_name"] == "context_build_completed"
        assert captured["payload"]["active_count"] == 0

    def test_no_event_when_flag_off(self, monkeypatch):
        monkeypatch.setattr("backend.core.config.settings.GOVERNANCE_OBSERVE_ENABLED", False)
        self._patch_ctx_deps(monkeypatch)

        captured, capture_fn = _capture_factory()
        monkeypatch.setattr(
            "backend.services.memory.governance_event_writer.record_event", capture_fn,
        )

        from backend.services.memory.context_builder import build_memory_context
        build_memory_context(thread_id="thread_off_ctx")

        assert captured == {}


# ── semantic_promoted (in-transaction) ───────────────────


class TestSemanticPromotedGovernanceEvent:
    def _patch_commit_deps(self, monkeypatch):
        """Stub out real DB writes in commit_executor."""
        monkeypatch.setattr(
            "backend.services.memory.commit_executor.semantic_store.upsert_batch",
            lambda conn, memories: len(memories),
        )
        monkeypatch.setattr(
            "backend.services.memory.commit_executor.semantic_store.revoke_batch",
            lambda conn, revocations: 0,
        )
        monkeypatch.setattr(
            "backend.services.memory.commit_executor.working_store.add_batch",
            lambda conn, items: 0,
        )
        monkeypatch.setattr(
            "backend.services.memory.commit_executor.working_store.close_batch",
            lambda conn, items: 0,
        )
        monkeypatch.setattr(
            "backend.services.memory.commit_executor.working_store.decrement_ttl",
            lambda conn, tid: None,
        )
        monkeypatch.setattr(
            "backend.services.memory.commit_executor.working_store.close_expired",
            lambda conn, tid: 0,
        )
        monkeypatch.setattr(
            "backend.services.memory.commit_executor.working_store.increment_stale_counts",
            lambda conn, tid: None,
        )

    def _make_plan(self):
        from backend.services.memory.commit_executor import CommitPlan
        from backend.services.memory.models import SemanticMemory

        tag = uuid.uuid4().hex[:8]
        now = time.time()
        return CommitPlan(
            semantic_upsert=[
                SemanticMemory(
                    id=f"sem_{tag}", thread_id="thread_3", content="テスト記憶",
                    status="confirmed", confidence=0.9,
                    valid_from=now, created_at=now, updated_at=now,
                ),
            ],
        ), tag

    def test_in_transaction_with_turn_id(self, monkeypatch):
        """semantic_promoted should use record_event_batch_with_conn with turn_id."""
        monkeypatch.setattr("backend.core.config.settings.GOVERNANCE_OBSERVE_ENABLED", True)
        self._patch_commit_deps(monkeypatch)

        captured, capture_fn = _capture_list_factory()
        monkeypatch.setattr(
            "backend.services.memory.governance_event_writer.record_event_batch_with_conn",
            capture_fn,
        )

        from backend.services.memory.commit_executor import execute
        plan, tag = self._make_plan()
        result = execute(plan, thread_id="thread_3", turn_id="turn_z")

        assert result.success is True
        assert len(captured) == 1
        events = captured[0]["events"]
        assert len(events) == 1
        ev = events[0]
        assert ev["event_name"] == "semantic_promoted"
        assert ev["turn_id"] == "turn_z"
        assert ev["semantic_id"] == f"sem_{tag}"
        assert ev["thread_id"] == "thread_3"
        # Verify conn was passed (not None)
        assert captured[0]["conn"] is not None

    def test_no_events_when_flag_off(self, monkeypatch):
        """GOVERNANCE_OBSERVE_ENABLED=False → no governance writer call."""
        monkeypatch.setattr("backend.core.config.settings.GOVERNANCE_OBSERVE_ENABLED", False)
        self._patch_commit_deps(monkeypatch)

        captured, capture_fn = _capture_list_factory()
        monkeypatch.setattr(
            "backend.services.memory.governance_event_writer.record_event_batch_with_conn",
            capture_fn,
        )

        from backend.services.memory.commit_executor import execute
        plan, _ = self._make_plan()
        result = execute(plan, thread_id="thread_off")

        assert result.success is True
        assert len(captured) == 0

    def test_payload_structure(self, monkeypatch):
        """Verify payload contains status/confidence/state_tag/content_head."""
        monkeypatch.setattr("backend.core.config.settings.GOVERNANCE_OBSERVE_ENABLED", True)
        self._patch_commit_deps(monkeypatch)

        captured, capture_fn = _capture_list_factory()
        monkeypatch.setattr(
            "backend.services.memory.governance_event_writer.record_event_batch_with_conn",
            capture_fn,
        )

        from backend.services.memory.commit_executor import execute
        plan, _ = self._make_plan()
        execute(plan, thread_id="thread_payload")

        payload = captured[0]["events"][0]["payload"]
        assert payload["status"] == "confirmed"
        assert payload["confidence"] == 0.9
        assert "content_head" in payload


# ── decay_sweep_completed ────────────────────────────────


class TestDecaySweepGovernanceEvent:
    def test_sweep_records_with_scanned_count(self, monkeypatch):
        """decay_by_status should record event including scanned_count."""
        monkeypatch.setattr("backend.core.config.settings.GOVERNANCE_OBSERVE_ENABLED", True)

        # Stub managed_conn to return a fake conn with empty result set
        @contextmanager
        def _fake_conn():
            class FakeConn:
                def execute(self, sql, params=None):
                    class FakeResult:
                        def fetchall(self):
                            return []
                    return FakeResult()
            yield FakeConn()

        monkeypatch.setattr(
            "backend.services.memory.semantic_store.managed_conn", _fake_conn,
        )

        captured, capture_fn = _capture_factory()
        monkeypatch.setattr(
            "backend.services.memory.governance_event_writer.record_event", capture_fn,
        )

        from backend.services.memory.semantic_store import decay_by_status
        decay_by_status()

        assert captured["event_name"] == "decay_sweep_completed"
        payload = captured["payload"]
        assert payload["scanned_count"] == 0
        assert payload["updated_count"] == 0
        assert payload["revoked_count"] == 0
        assert payload["revoked_ids"] == []

    def test_no_event_when_flag_off(self, monkeypatch):
        monkeypatch.setattr("backend.core.config.settings.GOVERNANCE_OBSERVE_ENABLED", False)

        @contextmanager
        def _fake_conn():
            class FakeConn:
                def execute(self, sql, params=None):
                    class FakeResult:
                        def fetchall(self):
                            return []
                    return FakeResult()
            yield FakeConn()

        monkeypatch.setattr(
            "backend.services.memory.semantic_store.managed_conn", _fake_conn,
        )

        captured, capture_fn = _capture_factory()
        monkeypatch.setattr(
            "backend.services.memory.governance_event_writer.record_event", capture_fn,
        )

        from backend.services.memory.semantic_store import decay_by_status
        decay_by_status()

        assert captured == {}
