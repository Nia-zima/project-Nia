"""
S5 Commit Executor — single-transaction batch commit.

All SQLite writes happen inside one BEGIN IMMEDIATE / COMMIT block.
ChromaDB vector sync is best-effort AFTER the SQLite transaction succeeds.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from backend.core.db import get_conn
from backend.core.logger import logger
from backend.services.memory import semantic_store
from backend.services.memory import working_store
from backend.services.memory.models import MemoryEvent, SemanticMemory, WorkingItem


@dataclass
class CommitPlan:
    episodic: list[dict] = field(default_factory=list)
    semantic_upsert: list[SemanticMemory] = field(default_factory=list)
    semantic_revoke: list[dict] = field(default_factory=list)
    working_add: list[WorkingItem] = field(default_factory=list)
    working_close: list[dict] = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)


@dataclass
class CommitResult:
    success: bool
    inserted_episodic: int = 0
    upserted_semantic: int = 0
    revoked_semantic: int = 0
    added_working: int = 0
    closed_working: int = 0
    errors: list[str] = field(default_factory=list)


def _insert_event(conn, event: MemoryEvent) -> None:
    conn.execute(
        """
        INSERT INTO memory_events (
            event_id, thread_id, turn_id, message_id,
            event_type, payload_json, created_at, schema_version
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event.event_id, event.thread_id, event.turn_id, event.message_id,
            event.event_type, event.payload_json,
            float(event.created_at), int(event.schema_version),
        ),
    )


def _validate_references(conn, memories: list[SemanticMemory]) -> list[str]:
    """Check that supersedes_id/revoked_by_id point to existing records."""
    errors: list[str] = []
    for mem in memories:
        if mem.supersedes_id:
            row = conn.execute(
                "SELECT id FROM semantic_memories WHERE id=?",
                (mem.supersedes_id,),
            ).fetchone()
            if not row:
                errors.append(
                    f"supersedes_id={mem.supersedes_id} not found for id={mem.id}"
                )
        if mem.revoked_by_id:
            row = conn.execute(
                "SELECT id FROM semantic_memories WHERE id=?",
                (mem.revoked_by_id,),
            ).fetchone()
            if not row:
                errors.append(
                    f"revoked_by_id={mem.revoked_by_id} not found for id={mem.id}"
                )
    return errors


def execute(
    plan: CommitPlan,
    *,
    thread_id: str,
    turn_id: Optional[str] = None,
) -> CommitResult:
    has_work = (
        plan.episodic or plan.semantic_upsert or plan.semantic_revoke
        or plan.working_add or plan.working_close
    )
    if not has_work:
        return CommitResult(success=True)

    conn = get_conn()
    result = CommitResult(success=False)

    try:
        conn.execute("BEGIN IMMEDIATE")

        # 1. Episodic events (batch insert via executemany)
        if plan.episodic:
            now = time.time()
            event_rows = [
                (
                    ep.get("event_id") or str(uuid.uuid4()),
                    thread_id,
                    turn_id,
                    ep.get("message_id"),
                    ep.get("event_type", "episode"),
                    json.dumps(ep.get("payload", {}), ensure_ascii=False),
                    float(ep.get("created_at") or now),
                    int(ep.get("schema_version", 1)),
                )
                for ep in plan.episodic
            ]
            conn.executemany(
                """
                INSERT INTO memory_events (
                    event_id, thread_id, turn_id, message_id,
                    event_type, payload_json, created_at, schema_version
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                event_rows,
            )
            result.inserted_episodic = len(event_rows)

        # 2. Validate semantic references
        ref_errors = _validate_references(conn, plan.semantic_upsert)
        if ref_errors:
            for err in ref_errors:
                logger.warning("[CommitExecutor] reference error: %s", err)
            result.errors.extend(ref_errors)
            conn.execute("ROLLBACK")
            return result

        # 3. Semantic upserts
        result.upserted_semantic = semantic_store.upsert_batch(
            conn, plan.semantic_upsert
        )

        # 4. Semantic revocations
        result.revoked_semantic = semantic_store.revoke_batch(
            conn, plan.semantic_revoke
        )

        # 5. Working items add
        result.added_working = working_store.add_batch(conn, plan.working_add)

        # 6. Working items close
        result.closed_working = working_store.close_batch(conn, plan.working_close)

        # 7. TTL expiry check (decrement + auto-close)
        if thread_id:
            working_store.decrement_ttl(conn, thread_id)
            expired = working_store.close_expired(conn, thread_id)
            result.closed_working += expired

        # 8. Stagnation counter increment (Phase E)
        if thread_id:
            working_store.increment_stale_counts(conn, thread_id)

        conn.execute("COMMIT")
        result.success = True

        logger.info(
            "[CommitExecutor] committed: episodic=%d sem_upsert=%d sem_revoke=%d "
            "wk_add=%d wk_close=%d",
            result.inserted_episodic,
            result.upserted_semantic,
            result.revoked_semantic,
            result.added_working,
            result.closed_working,
        )

    except Exception as e:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        logger.exception("[CommitExecutor] ROLLBACK due to error: %s", e)
        result.errors.append(str(e))

    finally:
        conn.close()

    return result
