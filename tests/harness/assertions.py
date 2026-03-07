"""State assertion helpers for snapshot and playbook tests.

Reads telemetry_kv, semantic_memories, somatic_log, working_items
and provides expressive assert functions.
"""
from __future__ import annotations

import json
from typing import Any

from backend.core.db import get_conn
from backend.services.idle_detector import should_trigger_reflection


# ── telemetry_kv ─────────────────────────────────────────────


def read_telemetry(key: str) -> str | None:
    """Read a single telemetry_kv value."""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT v FROM telemetry_kv WHERE k=?", (key,)
        ).fetchone()
        return row["v"] if row else None
    finally:
        conn.close()


def assert_telemetry(key: str, expected: Any, *, compare: str = "eq") -> None:
    """Assert a telemetry_kv value.

    compare: "eq", "gt", "gte", "lt", "lte", "contains"
    """
    actual = read_telemetry(key)
    assert actual is not None, f"telemetry_kv[{key!r}] not found"

    if compare == "eq":
        assert actual == str(expected), (
            f"telemetry_kv[{key!r}]: expected {expected!r}, got {actual!r}"
        )
    elif compare == "gt":
        assert float(actual) > float(expected), (
            f"telemetry_kv[{key!r}]: expected > {expected}, got {actual}"
        )
    elif compare == "gte":
        assert float(actual) >= float(expected), (
            f"telemetry_kv[{key!r}]: expected >= {expected}, got {actual}"
        )
    elif compare == "lt":
        assert float(actual) < float(expected), (
            f"telemetry_kv[{key!r}]: expected < {expected}, got {actual}"
        )
    elif compare == "lte":
        assert float(actual) <= float(expected), (
            f"telemetry_kv[{key!r}]: expected <= {expected}, got {actual}"
        )
    elif compare == "contains":
        assert str(expected) in actual, (
            f"telemetry_kv[{key!r}]: expected to contain {expected!r}, got {actual!r}"
        )
    else:
        raise ValueError(f"Unknown compare mode: {compare!r}")


def assert_telemetry_range(key: str, low: float, high: float) -> None:
    """Assert telemetry_kv value is within [low, high]."""
    actual = read_telemetry(key)
    assert actual is not None, f"telemetry_kv[{key!r}] not found"
    val = float(actual)
    assert low <= val <= high, (
        f"telemetry_kv[{key!r}]: expected {low}..{high}, got {val}"
    )


def assert_telemetry_absent(key: str) -> None:
    """Assert telemetry_kv key does not exist."""
    actual = read_telemetry(key)
    assert actual is None, (
        f"telemetry_kv[{key!r}]: expected absent, got {actual!r}"
    )


# ── semantic_memories ────────────────────────────────────────


def count_semantics(
    *,
    status: str | None = None,
    state_tag: str | None = None,
    thread_id: str = "default_thread",
) -> int:
    """Count semantic memories matching filters."""
    conn = get_conn()
    try:
        clauses = ["thread_id = ?"]
        params: list[Any] = [thread_id]
        if status:
            clauses.append("status = ?")
            params.append(status)
        if state_tag:
            clauses.append("state_tag = ?")
            params.append(state_tag)
        where = " AND ".join(clauses)
        row = conn.execute(
            f"SELECT COUNT(*) FROM semantic_memories WHERE {where}",  # noqa: S608
            params,
        ).fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def assert_semantic_count(
    expected: int,
    *,
    status: str | None = None,
    state_tag: str | None = None,
    thread_id: str = "default_thread",
    compare: str = "eq",
) -> None:
    """Assert count of semantic memories."""
    actual = count_semantics(
        status=status, state_tag=state_tag, thread_id=thread_id,
    )
    if compare == "eq":
        assert actual == expected, (
            f"semantic count: expected {expected}, got {actual} "
            f"(status={status}, state_tag={state_tag})"
        )
    elif compare == "gte":
        assert actual >= expected, (
            f"semantic count: expected >= {expected}, got {actual}"
        )
    elif compare == "gt":
        assert actual > expected, (
            f"semantic count: expected > {expected}, got {actual}"
        )
    else:
        raise ValueError(f"Unknown compare: {compare!r}")


def assert_semantic_status(content_pattern: str, expected_status: str) -> None:
    """Assert that a semantic memory matching the content pattern has the expected status."""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT status FROM semantic_memories WHERE content LIKE ?",
            (f"%{content_pattern}%",),
        ).fetchone()
        assert row is not None, (
            f"No semantic memory matching {content_pattern!r}"
        )
        assert row["status"] == expected_status, (
            f"Semantic [{content_pattern}]: expected status {expected_status!r}, "
            f"got {row['status']!r}"
        )
    finally:
        conn.close()


def assert_semantic_has_defeater(mem_id: str) -> None:
    """Assert that a semantic memory has a non-empty defeaters list."""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT defeaters FROM semantic_memories WHERE id = ?",
            (mem_id,),
        ).fetchone()
        assert row is not None, f"Semantic memory {mem_id!r} not found"
        defeaters = json.loads(row["defeaters"])
        assert len(defeaters) > 0, (
            f"Semantic {mem_id!r}: expected defeaters, got empty list"
        )
    finally:
        conn.close()


def assert_no_semantic_with(
    *,
    content_pattern: str | None = None,
    status: str | None = None,
) -> None:
    """Negative assertion: no semantic memory matching criteria exists."""
    conn = get_conn()
    try:
        clauses: list[str] = []
        params: list[Any] = []
        if content_pattern:
            clauses.append("content LIKE ?")
            params.append(f"%{content_pattern}%")
        if status:
            clauses.append("status = ?")
            params.append(status)
        if not clauses:
            raise ValueError("At least one filter required")
        where = " AND ".join(clauses)
        row = conn.execute(
            f"SELECT COUNT(*) FROM semantic_memories WHERE {where}",  # noqa: S608
            params,
        ).fetchone()
        assert row[0] == 0, (
            f"Expected no semantic memory matching {content_pattern}/{status}, "
            f"found {row[0]}"
        )
    finally:
        conn.close()


# ── somatic_log ──────────────────────────────────────────────


def count_somatic_outcomes(
    *,
    outcome: str | None = None,
    thread_id: str = "default_thread",
) -> int:
    """Count somatic_log entries."""
    conn = get_conn()
    try:
        clauses = ["thread_id = ?"]
        params: list[Any] = [thread_id]
        if outcome:
            clauses.append("outcome = ?")
            params.append(outcome)
        where = " AND ".join(clauses)
        row = conn.execute(
            f"SELECT COUNT(*) FROM somatic_log WHERE {where}",  # noqa: S608
            params,
        ).fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def assert_somatic_outcome_exists(
    *,
    outcome: str,
    min_count: int = 1,
    thread_id: str = "default_thread",
) -> None:
    """Assert at least min_count somatic outcomes with given outcome."""
    actual = count_somatic_outcomes(outcome=outcome, thread_id=thread_id)
    assert actual >= min_count, (
        f"somatic_log: expected >= {min_count} with outcome={outcome!r}, "
        f"got {actual}"
    )


def assert_somatic_accuracy_range(
    low: float,
    high: float,
    *,
    thread_id: str = "default_thread",
) -> None:
    """Assert somatic accuracy is within [low, high]."""
    from backend.services.memory.somatic_feedback import get_recent_accuracy

    accuracy, sample_count = get_recent_accuracy(thread_id)
    assert low <= accuracy <= high, (
        f"somatic accuracy: expected {low}..{high}, got {accuracy} "
        f"(samples={sample_count})"
    )


# ── working_items ────────────────────────────────────────────


def count_working_open(thread_id: str = "default_thread") -> int:
    """Count open working items."""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM working_items "
            "WHERE thread_id = ? AND status = 'open'",
            (thread_id,),
        ).fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def assert_working_open_count(
    expected: int,
    *,
    thread_id: str = "default_thread",
) -> None:
    actual = count_working_open(thread_id)
    assert actual == expected, (
        f"working_items open: expected {expected}, got {actual}"
    )


def assert_working_has_type(
    item_type: str,
    *,
    thread_id: str = "default_thread",
) -> None:
    """Assert at least one open working item of the given type exists."""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM working_items "
            "WHERE thread_id = ? AND status = 'open' AND item_type = ?",
            (thread_id, item_type),
        ).fetchone()
        assert row and row[0] > 0, (
            f"No open working item with type={item_type!r}"
        )
    finally:
        conn.close()


def assert_no_working_type(
    item_type: str,
    *,
    thread_id: str = "default_thread",
) -> None:
    """Negative assertion: no open working item of given type."""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM working_items "
            "WHERE thread_id = ? AND status = 'open' AND item_type = ?",
            (thread_id, item_type),
        ).fetchone()
        assert row[0] == 0, (
            f"Expected no working item with type={item_type!r}, found {row[0]}"
        )
    finally:
        conn.close()


# ── N.4 trigger ──────────────────────────────────────────────


def assert_n4_would_trigger(
    expected: bool,
    expected_reason: str = "",
) -> None:
    """Assert whether N.4 state-driven reflection would trigger.

    Calls idle_detector.should_trigger_reflection() directly.
    """
    conn = get_conn()
    try:
        should, reason = should_trigger_reflection(conn)
        assert should == expected, (
            f"N.4 trigger: expected {expected}, got {should} "
            f"(reason={reason!r})"
        )
        if expected and expected_reason:
            assert reason == expected_reason, (
                f"N.4 reason: expected {expected_reason!r}, got {reason!r}"
            )
    finally:
        conn.close()
