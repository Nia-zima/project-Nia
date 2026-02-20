"""Tests for working_store CRUD, TTL logic, and commit integration."""
from __future__ import annotations

import time
import uuid

import pytest

from backend.core.db import get_conn, init_schema
from backend.services.memory import working_store
from backend.services.memory.commit_executor import CommitPlan, execute
from backend.services.memory.models import WorkingItem


@pytest.fixture(autouse=True)
def _setup_db():
    init_schema()
    conn = get_conn()
    try:
        conn.execute("DELETE FROM working_items")
        conn.execute("DELETE FROM semantic_memories")
        # memory_index FK → memory_events, so delete child first
        conn.execute("DELETE FROM memory_index")
        conn.execute("DELETE FROM memory_events")
    finally:
        conn.close()
    yield


def _make_item(*, id: str = None, thread_id: str = "t1", item_type: str = "question",
               content: str = "test item", priority: int = 3,
               ttl_turns: int = None, expires_at: float = None) -> WorkingItem:
    now = time.time()
    return WorkingItem(
        id=id or str(uuid.uuid4()),
        thread_id=thread_id,
        item_type=item_type,
        content=content,
        priority=priority,
        created_turn_id="turn0",
        created_at=now,
        updated_at=now,
        ttl_turns=ttl_turns,
        expires_at=expires_at,
    )


# ── CRUD ─────────────────────────────────────────────────────────


class TestAddAndGet:
    def test_add_and_get_by_id(self):
        item = _make_item(content="what is user's favorite color?")
        conn = get_conn()
        try:
            working_store.add(conn, item)
        finally:
            conn.close()

        result = working_store.get_by_id(item.id)
        assert result is not None
        assert result.content == "what is user's favorite color?"
        assert result.status == "open"

    def test_get_by_id_returns_none(self):
        assert working_store.get_by_id("nonexistent") is None


class TestListOpen:
    def test_lists_open_only(self):
        open_item = _make_item(content="open")
        closed_item = _make_item(content="closed", priority=1)
        closed_item.status = "closed"
        closed_item.close_reason = "answered"
        conn = get_conn()
        try:
            working_store.add(conn, open_item)
            working_store.add(conn, closed_item)
        finally:
            conn.close()

        results = working_store.list_open("t1")
        assert len(results) == 1
        assert results[0].content == "open"

    def test_ordered_by_priority(self):
        high = _make_item(content="high", priority=1)
        low = _make_item(content="low", priority=5)
        conn = get_conn()
        try:
            working_store.add(conn, low)
            working_store.add(conn, high)
        finally:
            conn.close()

        results = working_store.list_open("t1")
        assert results[0].content == "high"
        assert results[1].content == "low"


class TestClose:
    def test_close(self):
        item = _make_item()
        conn = get_conn()
        try:
            working_store.add(conn, item)
            ok = working_store.close(conn, item.id, "answered")
        finally:
            conn.close()

        assert ok is True
        result = working_store.get_by_id(item.id)
        assert result.status == "closed"
        assert result.close_reason == "answered"

    def test_close_already_closed(self):
        item = _make_item()
        conn = get_conn()
        try:
            working_store.add(conn, item)
            working_store.close(conn, item.id, "answered")
            ok = working_store.close(conn, item.id, "again")
        finally:
            conn.close()
        assert ok is False

    def test_close_with_merge(self):
        item = _make_item()
        conn = get_conn()
        try:
            working_store.add(conn, item)
            working_store.close(conn, item.id, "merged", merged_into_id="other-id")
        finally:
            conn.close()

        result = working_store.get_by_id(item.id)
        assert result.close_reason == "merged"
        assert result.merged_into_id == "other-id"


class TestCountOpen:
    def test_count(self):
        conn = get_conn()
        try:
            working_store.add(conn, _make_item())
            working_store.add(conn, _make_item())
        finally:
            conn.close()
        assert working_store.count_open("t1") == 2


# ── TTL Logic ────────────────────────────────────────────────────


class TestTTLTurns:
    def test_decrement_and_expire(self):
        item = _make_item(ttl_turns=2)
        conn = get_conn()
        try:
            working_store.add(conn, item)

            # First decrement: 2 → 1
            expired = working_store.decrement_ttl(conn, "t1")
            assert expired == []

            # Second decrement: 1 → 0 (expired)
            expired = working_store.decrement_ttl(conn, "t1")
            assert item.id in expired
        finally:
            conn.close()

    def test_no_ttl_not_decremented(self):
        item = _make_item()  # no ttl_turns
        conn = get_conn()
        try:
            working_store.add(conn, item)
            expired = working_store.decrement_ttl(conn, "t1")
            assert expired == []
        finally:
            conn.close()

    def test_expires_at_takes_priority_over_ttl_turns(self):
        """Items with expires_at should NOT be decremented by ttl_turns logic."""
        future = time.time() + 99999
        item = _make_item(ttl_turns=1, expires_at=future)
        conn = get_conn()
        try:
            working_store.add(conn, item)
            expired = working_store.decrement_ttl(conn, "t1")
            assert expired == []
        finally:
            conn.close()

        # ttl_turns should NOT have been decremented
        result = working_store.get_by_id(item.id)
        assert result.ttl_turns == 1


class TestExpiresAt:
    def test_expired_by_time(self):
        past = time.time() - 100
        item = _make_item(expires_at=past)
        conn = get_conn()
        try:
            working_store.add(conn, item)
            expired_ids = working_store.collect_expired(conn, "t1")
            assert item.id in expired_ids
        finally:
            conn.close()

    def test_not_expired_yet(self):
        future = time.time() + 99999
        item = _make_item(expires_at=future)
        conn = get_conn()
        try:
            working_store.add(conn, item)
            expired_ids = working_store.collect_expired(conn, "t1")
            assert expired_ids == []
        finally:
            conn.close()


class TestCloseExpired:
    def test_auto_close(self):
        past = time.time() - 100
        item = _make_item(expires_at=past)
        conn = get_conn()
        try:
            working_store.add(conn, item)
            closed = working_store.close_expired(conn, "t1")
        finally:
            conn.close()

        assert closed == 1
        result = working_store.get_by_id(item.id)
        assert result.status == "closed"
        assert result.close_reason == "stale"


# ── Commit Integration ───────────────────────────────────────────


class TestCommitWithWorking:
    def test_working_add_via_commit(self):
        item = _make_item(content="pending question")
        plan = CommitPlan(working_add=[item])
        result = execute(plan, thread_id="t1", turn_id="turn1")

        assert result.success is True
        assert result.added_working == 1

        stored = working_store.get_by_id(item.id)
        assert stored is not None
        assert stored.content == "pending question"

    def test_working_close_via_commit(self):
        item = _make_item(id="wk-1")
        conn = get_conn()
        try:
            working_store.add(conn, item)
        finally:
            conn.close()

        plan = CommitPlan(
            working_close=[{"id": "wk-1", "reason": "answered"}]
        )
        result = execute(plan, thread_id="t1")
        assert result.success is True
        assert result.closed_working == 1

    def test_commit_auto_closes_expired(self):
        past = time.time() - 100
        item = _make_item(expires_at=past)
        conn = get_conn()
        try:
            working_store.add(conn, item)
        finally:
            conn.close()

        # Empty commit still triggers TTL check
        plan = CommitPlan(
            episodic=[{"event_type": "episode", "payload": {"text": "hi"}}]
        )
        result = execute(plan, thread_id="t1")
        assert result.success is True
        assert result.closed_working >= 1

    def test_commit_decrements_ttl_turns(self):
        item = _make_item(ttl_turns=2, expires_at=None)
        conn = get_conn()
        try:
            working_store.add(conn, item)
        finally:
            conn.close()

        plan = CommitPlan(
            episodic=[{"event_type": "episode", "payload": {"text": "hi"}}]
        )
        result = execute(plan, thread_id="t1")
        assert result.success is True

        stored = working_store.get_by_id(item.id)
        assert stored is not None
        assert stored.ttl_turns == 1

    def test_full_commit_with_all_fields(self):
        from backend.services.memory.models import SemanticMemory

        now = time.time()
        sem = SemanticMemory(
            id="sem-1", thread_id="t1", content="fact",
            valid_from=now, created_at=now, updated_at=now,
        )
        wk = _make_item(content="follow-up question")

        plan = CommitPlan(
            episodic=[{"event_type": "episode", "payload": {"text": "context"}}],
            semantic_upsert=[sem],
            working_add=[wk],
        )
        result = execute(plan, thread_id="t1", turn_id="turn1")
        assert result.success is True
        assert result.inserted_episodic == 1
        assert result.upserted_semantic == 1
        assert result.added_working == 1
