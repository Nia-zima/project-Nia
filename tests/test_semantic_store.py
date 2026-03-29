"""Tests for semantic_store CRUD and commit_executor."""
from __future__ import annotations

import time
import uuid

import pytest

from backend.core.db import get_conn, init_schema
from backend.services.memory import semantic_store
from backend.services.memory.commit_executor import CommitPlan, execute
from backend.services.memory.models import SemanticMemory


@pytest.fixture(autouse=True)
def _setup_db():
    """Ensure schema exists and clean semantic_memories before each test."""
    init_schema()
    conn = get_conn()
    try:
        conn.execute("DELETE FROM semantic_memories")
    finally:
        conn.close()
    yield


def _make_mem(*, id: str = None, thread_id: str = "t1", content: str = "test",
              status: str = "inferred", confidence: float = 0.5,
              state_tag: str = None, supersedes_id: str = None,
              revoked_by_id: str = None) -> SemanticMemory:
    now = time.time()
    return SemanticMemory(
        id=id or str(uuid.uuid4()),
        thread_id=thread_id,
        content=content,
        status=status,
        confidence=confidence,
        state_tag=state_tag,
        supersedes_id=supersedes_id,
        revoked_by_id=revoked_by_id,
        valid_from=now,
        created_at=now,
        updated_at=now,
    )


# ── semantic_store CRUD ──────────────────────────────────────────


class TestUpsertAndGet:
    def test_upsert_and_get_by_id(self):
        mem = _make_mem(content="user likes cats")
        conn = get_conn()
        try:
            semantic_store.upsert(conn, mem)
        finally:
            conn.close()

        result = semantic_store.get_by_id(mem.id)
        assert result is not None
        assert result.content == "user likes cats"
        assert result.status == "inferred"

    def test_upsert_updates_existing(self):
        mem = _make_mem(content="original")
        conn = get_conn()
        try:
            semantic_store.upsert(conn, mem)
        finally:
            conn.close()

        mem.content = "updated"
        mem.updated_at = time.time()
        conn = get_conn()
        try:
            semantic_store.upsert(conn, mem)
        finally:
            conn.close()

        result = semantic_store.get_by_id(mem.id)
        assert result.content == "updated"

    def test_get_by_id_returns_none(self):
        assert semantic_store.get_by_id("nonexistent") is None


class TestRevoke:
    def test_revoke(self):
        mem = _make_mem()
        conn = get_conn()
        try:
            semantic_store.upsert(conn, mem)
            ok = semantic_store.revoke(conn, mem.id, "contradicted")
        finally:
            conn.close()

        assert ok is True
        result = semantic_store.get_by_id(mem.id)
        assert result.status == "revoked"
        assert result.revoke_reason == "contradicted"

    def test_revoke_already_revoked(self):
        mem = _make_mem(status="revoked")
        conn = get_conn()
        try:
            semantic_store.upsert(conn, mem)
            ok = semantic_store.revoke(conn, mem.id, "again")
        finally:
            conn.close()

        assert ok is False


class TestSearchActive:
    def test_excludes_revoked(self):
        m1 = _make_mem(content="active", status="confirmed")
        m2 = _make_mem(content="dead", status="revoked")
        conn = get_conn()
        try:
            semantic_store.upsert(conn, m1)
            semantic_store.upsert(conn, m2)
        finally:
            conn.close()

        results = semantic_store.search_active("t1")
        assert len(results) == 1
        assert results[0].content == "active"

    def test_includes_inferred(self):
        m1 = _make_mem(status="inferred")
        m2 = _make_mem(status="confirmed")
        conn = get_conn()
        try:
            semantic_store.upsert(conn, m1)
            semantic_store.upsert(conn, m2)
        finally:
            conn.close()

        results = semantic_store.search_active("t1")
        assert len(results) == 2


class TestGetChain:
    def test_follows_supersedes(self):
        m1 = _make_mem(id="old", content="v1", status="revoked")
        m2 = _make_mem(id="new", content="v2", supersedes_id="old")
        conn = get_conn()
        try:
            semantic_store.upsert(conn, m1)
            semantic_store.upsert(conn, m2)
        finally:
            conn.close()

        chain = semantic_store.get_chain("old")
        assert len(chain) == 2
        ids = {m.id for m in chain}
        assert ids == {"old", "new"}


class TestConfirmBatch:
    def test_confirms_inferred(self):
        m1 = _make_mem(id="a", status="inferred")
        m2 = _make_mem(id="b", status="inferred")
        m3 = _make_mem(id="c", status="confirmed")
        conn = get_conn()
        try:
            for m in [m1, m2, m3]:
                semantic_store.upsert(conn, m)
        finally:
            conn.close()

        count = semantic_store.confirm_batch(["a", "b", "c"])
        assert count == 2

        assert semantic_store.get_by_id("a").status == "confirmed"
        assert semantic_store.get_by_id("b").status == "confirmed"


class TestOrphanScan:
    def test_detects_orphan(self):
        mem = _make_mem(supersedes_id="does_not_exist")
        conn = get_conn()
        try:
            semantic_store.upsert(conn, mem)
        finally:
            conn.close()

        orphans = semantic_store.scan_orphan_references()
        assert len(orphans) == 1
        assert orphans[0]["ref_id"] == "does_not_exist"

    def test_no_orphan_when_valid(self):
        m1 = _make_mem(id="parent")
        m2 = _make_mem(supersedes_id="parent")
        conn = get_conn()
        try:
            semantic_store.upsert(conn, m1)
            semantic_store.upsert(conn, m2)
        finally:
            conn.close()

        orphans = semantic_store.scan_orphan_references()
        assert len(orphans) == 0


class TestVectorSyncPending:
    def test_get_pending_and_mark(self):
        mem = _make_mem(content="needs sync")
        conn = get_conn()
        try:
            semantic_store.upsert(conn, mem)
        finally:
            conn.close()

        pending = semantic_store.get_pending_vector_sync(limit=10)
        assert len(pending) == 1

        semantic_store.mark_vector_synced([mem.id])

        pending = semantic_store.get_pending_vector_sync(limit=10)
        assert len(pending) == 0


class TestInferredOlderThan:
    def test_returns_old_inferred(self):
        old = _make_mem(status="inferred")
        old.created_at = time.time() - 100000
        conn = get_conn()
        try:
            semantic_store.upsert(conn, old)
        finally:
            conn.close()

        results = semantic_store.get_inferred_older_than(86400)
        assert len(results) == 1

    def test_excludes_recent(self):
        recent = _make_mem(status="inferred")
        conn = get_conn()
        try:
            semantic_store.upsert(conn, recent)
        finally:
            conn.close()

        results = semantic_store.get_inferred_older_than(86400)
        assert len(results) == 0


# ── commit_executor ──────────────────────────────────────────────


class TestCommitExecutor:
    def test_empty_plan(self):
        result = execute(CommitPlan(), thread_id="t1")
        assert result.success is True

    def test_episodic_only(self):
        plan = CommitPlan(
            episodic=[
                {"event_type": "episode", "payload": {"text": "hello"}}
            ]
        )
        result = execute(plan, thread_id="t1", turn_id="turn1")
        assert result.success is True
        assert result.inserted_episodic == 1

    def test_semantic_upsert(self):
        mem = _make_mem(content="user prefers dark mode")
        plan = CommitPlan(semantic_upsert=[mem])
        result = execute(plan, thread_id="t1")
        assert result.success is True
        assert result.upserted_semantic == 1

        stored = semantic_store.get_by_id(mem.id)
        assert stored is not None
        assert stored.content == "user prefers dark mode"

    def test_semantic_revoke(self):
        mem = _make_mem(id="to-revoke")
        conn = get_conn()
        try:
            semantic_store.upsert(conn, mem)
        finally:
            conn.close()

        plan = CommitPlan(
            semantic_revoke=[{"id": "to-revoke", "reason": "user corrected"}]
        )
        result = execute(plan, thread_id="t1")
        assert result.success is True
        assert result.revoked_semantic == 1

    def test_rollback_on_bad_reference(self):
        mem = _make_mem(supersedes_id="nonexistent")
        plan = CommitPlan(
            episodic=[{"event_type": "episode", "payload": {"text": "test"}}],
            semantic_upsert=[mem],
        )
        result = execute(plan, thread_id="t1")
        assert result.success is False
        assert len(result.errors) > 0

    def test_rollback_on_bad_revoked_by_reference(self):
        mem = _make_mem(revoked_by_id="nonexistent")
        plan = CommitPlan(
            episodic=[{"event_type": "episode", "payload": {"text": "test"}}],
            semantic_upsert=[mem],
        )
        result = execute(plan, thread_id="t1")
        assert result.success is False
        assert any("revoked_by_id" in err for err in result.errors)

    def test_full_commit(self):
        parent = _make_mem(id="parent-id", content="original")
        conn = get_conn()
        try:
            semantic_store.upsert(conn, parent)
        finally:
            conn.close()

        child = _make_mem(content="updated info", supersedes_id="parent-id")
        plan = CommitPlan(
            episodic=[{"event_type": "episode", "payload": {"text": "context"}}],
            semantic_upsert=[child],
            semantic_revoke=[{"id": "parent-id", "reason": "superseded", "revoked_by_id": child.id}],
        )
        result = execute(plan, thread_id="t1", turn_id="turn1")
        assert result.success is True
        assert result.inserted_episodic == 1
        assert result.upserted_semantic == 1
        assert result.revoked_semantic == 1

        assert semantic_store.get_by_id("parent-id").status == "revoked"
        assert semantic_store.get_by_id(child.id).status == "inferred"
