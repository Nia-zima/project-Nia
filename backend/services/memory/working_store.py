"""
Working Items CRUD + TTL/close logic.

Write methods accept a `conn` parameter for use inside S5 Commit transactions.
Read methods manage their own connections.

TTL priority (from design doc 9.6):
  1. expires_at (absolute, if set)
  2. ttl_turns  (fallback, decremented per user utterance)
  3. both null  → no TTL, lives until explicitly closed
"""
from __future__ import annotations

import time
from typing import Optional

from backend.core.db import get_conn
from backend.core.logger import logger
from backend.services.memory.models import WorkingItem

_COLUMNS = (
    "id", "thread_id", "item_type", "content", "priority", "status",
    "close_reason", "linked_semantic_ids", "linked_event_ids",
    "merged_into_id", "ttl_turns", "expires_at", "stale_turn_count",
    "created_turn_id", "created_at", "updated_at",
)


def _row_to_model(row) -> WorkingItem:
    d = dict(row)
    return WorkingItem(**{k: d[k] for k in _COLUMNS})


# ── Write (require conn for transaction use) ─────────────────────


def add(conn, item: WorkingItem) -> None:
    conn.execute(
        """
        INSERT INTO working_items (
            id, thread_id, item_type, content, priority, status,
            close_reason, linked_semantic_ids, linked_event_ids,
            merged_into_id, ttl_turns, expires_at, stale_turn_count,
            created_turn_id, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            content=excluded.content,
            priority=excluded.priority,
            status=excluded.status,
            close_reason=excluded.close_reason,
            linked_semantic_ids=excluded.linked_semantic_ids,
            linked_event_ids=excluded.linked_event_ids,
            merged_into_id=excluded.merged_into_id,
            ttl_turns=excluded.ttl_turns,
            expires_at=excluded.expires_at,
            stale_turn_count=excluded.stale_turn_count,
            updated_at=excluded.updated_at
        """,
        (
            item.id, item.thread_id, item.item_type, item.content,
            item.priority, item.status,
            item.close_reason, item.linked_semantic_ids, item.linked_event_ids,
            item.merged_into_id, item.ttl_turns, item.expires_at,
            item.stale_turn_count,
            item.created_turn_id, item.created_at, item.updated_at,
        ),
    )


def add_batch(conn, items: list[WorkingItem]) -> int:
    if not items:
        return 0
    conn.executemany(
        """
        INSERT INTO working_items (
            id, thread_id, item_type, content, priority, status,
            close_reason, linked_semantic_ids, linked_event_ids,
            merged_into_id, ttl_turns, expires_at, stale_turn_count,
            created_turn_id, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            content=excluded.content,
            priority=excluded.priority,
            status=excluded.status,
            close_reason=excluded.close_reason,
            linked_semantic_ids=excluded.linked_semantic_ids,
            linked_event_ids=excluded.linked_event_ids,
            merged_into_id=excluded.merged_into_id,
            ttl_turns=excluded.ttl_turns,
            expires_at=excluded.expires_at,
            stale_turn_count=excluded.stale_turn_count,
            updated_at=excluded.updated_at
        """,
        [
            (
                item.id, item.thread_id, item.item_type, item.content,
                item.priority, item.status,
                item.close_reason, item.linked_semantic_ids, item.linked_event_ids,
                item.merged_into_id, item.ttl_turns, item.expires_at,
                item.stale_turn_count,
                item.created_turn_id, item.created_at, item.updated_at,
            )
            for item in items
        ],
    )
    return len(items)


def close(conn, id: str, reason: str, *, merged_into_id: Optional[str] = None) -> bool:
    now = time.time()
    cur = conn.execute(
        """
        UPDATE working_items
        SET status='closed', close_reason=?, merged_into_id=?, updated_at=?
        WHERE id=? AND status='open'
        """,
        (reason, merged_into_id, now, id),
    )
    return cur.rowcount > 0


def close_batch(conn, closures: list[dict]) -> int:
    count = 0
    for c in closures:
        if close(conn, c["id"], c["reason"], merged_into_id=c.get("merged_into_id")):
            count += 1
    return count


def decrement_ttl(conn, thread_id: str) -> list[str]:
    """Decrement ttl_turns for all open items in thread. Returns IDs that expired."""
    now = time.time()
    # Decrement
    conn.execute(
        """
        UPDATE working_items
        SET ttl_turns = ttl_turns - 1, updated_at = ?
        WHERE thread_id = ? AND status = 'open'
            AND ttl_turns IS NOT NULL AND expires_at IS NULL
        """,
        (now, thread_id),
    )
    # Find expired (ttl_turns <= 0)
    rows = conn.execute(
        """
        SELECT id FROM working_items
        WHERE thread_id = ? AND status = 'open'
            AND ttl_turns IS NOT NULL AND ttl_turns <= 0 AND expires_at IS NULL
        """,
        (thread_id,),
    ).fetchall()
    return [r["id"] for r in rows]


def collect_expired(conn, thread_id: str) -> list[str]:
    """Find open items whose expires_at or ttl_turns have expired. Returns IDs."""
    now = time.time()
    rows = conn.execute(
        """
        SELECT id FROM working_items
        WHERE thread_id = ? AND status = 'open' AND (
            (expires_at IS NOT NULL AND expires_at <= ?)
            OR (expires_at IS NULL AND ttl_turns IS NOT NULL AND ttl_turns <= 0)
        )
        """,
        (thread_id, now),
    ).fetchall()
    return [r["id"] for r in rows]


def close_expired(conn, thread_id: str) -> int:
    """Close all expired items for a thread. Returns count closed."""
    expired_ids = collect_expired(conn, thread_id)
    count = 0
    for eid in expired_ids:
        if close(conn, eid, "stale"):
            count += 1
    return count


# ── Read (manage own connections) ────────────────────────────────


def get_by_id(id: str) -> Optional[WorkingItem]:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM working_items WHERE id=?", (id,)
        ).fetchone()
        return _row_to_model(row) if row else None
    finally:
        conn.close()


def list_open(thread_id: str, *, limit: int = 20) -> list[WorkingItem]:
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT * FROM working_items
            WHERE thread_id=? AND status='open'
            ORDER BY priority ASC, created_at DESC
            LIMIT ?
            """,
            (thread_id, limit),
        ).fetchall()
        return [_row_to_model(r) for r in rows]
    finally:
        conn.close()


def count_open(thread_id: str) -> int:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM working_items WHERE thread_id=? AND status='open'",
            (thread_id,),
        ).fetchone()
        return row[0]
    finally:
        conn.close()


# ── Stagnation tracking (Phase E) ────────────────────────────────


def increment_stale_counts(conn, thread_id: str) -> None:
    """Increment stale_turn_count for all open items in a thread."""
    conn.execute(
        """
        UPDATE working_items
        SET stale_turn_count = stale_turn_count + 1
        WHERE thread_id = ? AND status = 'open'
        """,
        (thread_id,),
    )


def reset_stale_count(conn, item_id: str) -> None:
    """Reset stale_turn_count to 0 (e.g. when the item's topic is mentioned)."""
    conn.execute(
        "UPDATE working_items SET stale_turn_count = 0 WHERE id = ?",
        (item_id,),
    )


def list_stagnant(thread_id: str, *, threshold: int = 3) -> list[WorkingItem]:
    """Return open items whose stale_turn_count >= threshold."""
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT * FROM working_items
            WHERE thread_id = ? AND status = 'open' AND stale_turn_count >= ?
            ORDER BY stale_turn_count DESC, priority ASC
            """,
            (thread_id, threshold),
        ).fetchall()
        return [_row_to_model(r) for r in rows]
    finally:
        conn.close()
