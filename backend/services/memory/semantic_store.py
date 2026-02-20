"""
Semantic Memory CRUD layer.

Write methods accept a `conn` parameter for use inside S5 Commit transactions.
Read methods manage their own connections.
"""
from __future__ import annotations

import time
from typing import Optional

from backend.core.db import get_conn
from backend.core.logger import logger
from backend.services.memory.models import SemanticMemory

_COLUMNS = (
    "id", "thread_id", "content", "status", "confidence", "state_tag",
    "supersedes_id", "revoked_by_id", "revoke_reason",
    "valid_from", "valid_to", "staleness_days",
    "source_turn_ids", "source_event_ids", "note",
    "seed_retention", "vector_sync_pending", "created_at", "updated_at",
)


def _row_to_model(row) -> SemanticMemory:
    d = dict(row)
    return SemanticMemory(**{k: d[k] for k in _COLUMNS})


# ── Write (require conn for transaction use) ─────────────────────


def upsert(conn, mem: SemanticMemory) -> None:
    conn.execute(
        """
        INSERT INTO semantic_memories (
            id, thread_id, content, status, confidence, state_tag,
            supersedes_id, revoked_by_id, revoke_reason,
            valid_from, valid_to, staleness_days,
            source_turn_ids, source_event_ids, note,
            seed_retention, vector_sync_pending, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            content=excluded.content,
            status=excluded.status,
            confidence=excluded.confidence,
            state_tag=excluded.state_tag,
            supersedes_id=excluded.supersedes_id,
            revoked_by_id=excluded.revoked_by_id,
            revoke_reason=excluded.revoke_reason,
            valid_from=excluded.valid_from,
            valid_to=excluded.valid_to,
            staleness_days=excluded.staleness_days,
            source_turn_ids=excluded.source_turn_ids,
            source_event_ids=excluded.source_event_ids,
            note=excluded.note,
            seed_retention=excluded.seed_retention,
            vector_sync_pending=excluded.vector_sync_pending,
            updated_at=excluded.updated_at
        """,
        (
            mem.id, mem.thread_id, mem.content, mem.status, mem.confidence,
            mem.state_tag, mem.supersedes_id, mem.revoked_by_id, mem.revoke_reason,
            mem.valid_from, mem.valid_to, mem.staleness_days,
            mem.source_turn_ids, mem.source_event_ids, mem.note,
            mem.seed_retention, mem.vector_sync_pending,
            mem.created_at, mem.updated_at,
        ),
    )


def upsert_batch(conn, memories: list[SemanticMemory]) -> int:
    if not memories:
        return 0
    conn.executemany(
        """
        INSERT INTO semantic_memories (
            id, thread_id, content, status, confidence, state_tag,
            supersedes_id, revoked_by_id, revoke_reason,
            valid_from, valid_to, staleness_days,
            source_turn_ids, source_event_ids, note,
            seed_retention, vector_sync_pending, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            content=excluded.content,
            status=excluded.status,
            confidence=excluded.confidence,
            state_tag=excluded.state_tag,
            supersedes_id=excluded.supersedes_id,
            revoked_by_id=excluded.revoked_by_id,
            revoke_reason=excluded.revoke_reason,
            valid_from=excluded.valid_from,
            valid_to=excluded.valid_to,
            staleness_days=excluded.staleness_days,
            source_turn_ids=excluded.source_turn_ids,
            source_event_ids=excluded.source_event_ids,
            note=excluded.note,
            seed_retention=excluded.seed_retention,
            vector_sync_pending=excluded.vector_sync_pending,
            updated_at=excluded.updated_at
        """,
        [
            (
                mem.id, mem.thread_id, mem.content, mem.status, mem.confidence,
                mem.state_tag, mem.supersedes_id, mem.revoked_by_id, mem.revoke_reason,
                mem.valid_from, mem.valid_to, mem.staleness_days,
                mem.source_turn_ids, mem.source_event_ids, mem.note,
                mem.seed_retention, mem.vector_sync_pending,
                mem.created_at, mem.updated_at,
            )
            for mem in memories
        ],
    )
    return len(memories)


def revoke(conn, id: str, reason: str, revoked_by_id: Optional[str] = None) -> bool:
    now = time.time()
    cur = conn.execute(
        """
        UPDATE semantic_memories
        SET status='revoked', revoke_reason=?, revoked_by_id=?,
            vector_sync_pending=1, updated_at=?
        WHERE id=? AND status != 'revoked'
        """,
        (reason, revoked_by_id, now, id),
    )
    return cur.rowcount > 0


def revoke_batch(conn, revocations: list[dict]) -> int:
    count = 0
    for rev in revocations:
        if revoke(conn, rev["id"], rev["reason"], rev.get("revoked_by_id")):
            count += 1
    return count


# ── Read (manage own connections) ────────────────────────────────


def get_by_id(id: str) -> Optional[SemanticMemory]:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM semantic_memories WHERE id=?", (id,)
        ).fetchone()
        return _row_to_model(row) if row else None
    finally:
        conn.close()


def get_chain(id: str) -> list[SemanticMemory]:
    """Follow supersedes_id / revoked_by_id chain in both directions."""
    visited: set[str] = set()
    chain: list[SemanticMemory] = []
    conn = get_conn()
    try:
        queue = [id]
        while queue:
            current_id = queue.pop(0)
            if current_id in visited:
                continue
            visited.add(current_id)
            row = conn.execute(
                "SELECT * FROM semantic_memories WHERE id=?", (current_id,)
            ).fetchone()
            if not row:
                continue
            mem = _row_to_model(row)
            chain.append(mem)
            if mem.supersedes_id and mem.supersedes_id not in visited:
                queue.append(mem.supersedes_id)
            if mem.revoked_by_id and mem.revoked_by_id not in visited:
                queue.append(mem.revoked_by_id)
            # reverse: find records that supersede or revoke this one
            for col in ("supersedes_id", "revoked_by_id"):
                refs = conn.execute(
                    f"SELECT id FROM semantic_memories WHERE {col}=?", (current_id,)
                ).fetchall()
                for r in refs:
                    if r["id"] not in visited:
                        queue.append(r["id"])
        return sorted(chain, key=lambda m: m.created_at)
    finally:
        conn.close()


def search_active(thread_id: str, *, limit: int = 20) -> list[SemanticMemory]:
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT * FROM semantic_memories
            WHERE thread_id=? AND status IN ('confirmed', 'inferred')
            ORDER BY confidence DESC, created_at DESC
            LIMIT ?
            """,
            (thread_id, limit),
        ).fetchall()
        return [_row_to_model(r) for r in rows]
    finally:
        conn.close()


def get_pending_vector_sync(*, limit: int = 100) -> list[SemanticMemory]:
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT * FROM semantic_memories
            WHERE vector_sync_pending = 1
            ORDER BY updated_at ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_row_to_model(r) for r in rows]
    finally:
        conn.close()


def get_inferred_older_than(age_seconds: float) -> list[SemanticMemory]:
    cutoff = time.time() - age_seconds
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT * FROM semantic_memories
            WHERE status='inferred' AND created_at < ?
            ORDER BY created_at ASC
            """,
            (cutoff,),
        ).fetchall()
        return [_row_to_model(r) for r in rows]
    finally:
        conn.close()


# ── Maintenance ──────────────────────────────────────────────────


def mark_vector_synced(ids: list[str]) -> int:
    if not ids:
        return 0
    conn = get_conn()
    try:
        now = time.time()
        placeholders = ",".join(["?"] * len(ids))
        cur = conn.execute(
            f"""
            UPDATE semantic_memories
            SET vector_sync_pending=0, updated_at=?
            WHERE id IN ({placeholders})
            """,
            (now, *ids),
        )
        return cur.rowcount
    finally:
        conn.close()


def decay_by_status() -> int:
    """Apply half-life decay to semantic memories based on status.

    Half-lives:
      - inferred: 3 days
      - confirmed: 30 days

    Memories whose confidence decays below 0.05 are marked 'revoked'.
    Returns the number of revoked memories.
    """
    import math

    HALF_LIFE = {"inferred": 3.0, "confirmed": 30.0}  # days
    REVOKE_THRESHOLD = 0.05
    now = time.time()

    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT id, status, confidence, seed_retention, updated_at
            FROM semantic_memories
            WHERE status IN ('inferred', 'confirmed')
            """,
        ).fetchall()

        revoked_ids: list[str] = []
        updates: list[tuple] = []

        for row in rows:
            hl_days = HALF_LIFE.get(row["status"])
            if not hl_days:
                continue
            age_days = (now - (row["updated_at"] or row["seed_retention"] or now)) / 86400.0
            if age_days <= 0:
                continue
            decay = math.pow(0.5, age_days / hl_days)
            base = row["seed_retention"] if row["seed_retention"] else row["confidence"]
            new_conf = (base or 0.5) * decay

            if new_conf < REVOKE_THRESHOLD:
                revoked_ids.append(row["id"])
            else:
                # Only update if meaningfully changed (>1%)
                if abs(new_conf - row["confidence"]) >= 0.01:
                    updates.append((new_conf, now, row["id"]))

        if updates:
            conn.executemany(
                "UPDATE semantic_memories SET confidence=?, updated_at=? WHERE id=?",
                updates,
            )

        if revoked_ids:
            placeholders = ",".join(["?"] * len(revoked_ids))
            conn.execute(
                f"""
                UPDATE semantic_memories
                SET status='revoked', revoke_reason='half_life_decay',
                    vector_sync_pending=1, updated_at=?
                WHERE id IN ({placeholders})
                """,
                (now, *revoked_ids),
            )

        total = len(updates) + len(revoked_ids)
        if total:
            logger.info(
                "[SemanticStore] decay_by_status: updated=%d revoked=%d",
                len(updates), len(revoked_ids),
            )
        return len(revoked_ids)
    finally:
        conn.close()


def confirm_batch(ids: list[str]) -> int:
    if not ids:
        return 0
    conn = get_conn()
    try:
        now = time.time()
        placeholders = ",".join(["?"] * len(ids))
        cur = conn.execute(
            f"""
            UPDATE semantic_memories
            SET status='confirmed', updated_at=?
            WHERE id IN ({placeholders}) AND status='inferred'
            """,
            (now, *ids),
        )
        count = cur.rowcount
        if count:
            logger.info("[SemanticStore] confirmed %d inferred memories", count)
        return count
    finally:
        conn.close()


def record_skill_execution(
    skill_name: str,
    success: bool,
    error: str = "",
    retries: int = 0,
    thread_id: str = "minecraft",
) -> None:
    """Record a Minecraft skill execution as a semantic memory.

    Successful executions and notable failures are stored for future
    retrieval by the context builder / game loop.
    """
    import uuid

    now = time.time()
    if success:
        content = f"Minecraftスキル '{skill_name}' を実行して成功した"
        if retries:
            content += f"（{retries}回リトライ後）"
        state_tag = "game_skill_success"
        confidence = 0.7
    else:
        content = f"Minecraftスキル '{skill_name}' を実行したが失敗: {error[:120]}"
        state_tag = "game_skill_failure"
        confidence = 0.5

    mem = SemanticMemory(
        id=str(uuid.uuid4()),
        thread_id=thread_id,
        content=content,
        status="inferred",
        confidence=confidence,
        state_tag=state_tag,
        source_turn_ids="",
        source_event_ids="",
        note=f"auto:skill_exec:{skill_name}",
        seed_retention=confidence,
        vector_sync_pending=1,
        created_at=now,
        updated_at=now,
    )

    conn = get_conn()
    try:
        upsert(conn, mem)
        logger.info(
            "[SemanticStore] Recorded skill execution: %s (%s)",
            skill_name,
            "success" if success else "failure",
        )
    finally:
        conn.close()


def scan_orphan_references() -> list[dict]:
    """Detect supersedes_id / revoked_by_id pointing to non-existent records."""
    conn = get_conn()
    try:
        orphans: list[dict] = []
        for col in ("supersedes_id", "revoked_by_id"):
            rows = conn.execute(
                f"""
                SELECT sm.id, sm.{col} AS ref_id, '{col}' AS ref_type
                FROM semantic_memories sm
                LEFT JOIN semantic_memories ref ON sm.{col} = ref.id
                WHERE sm.{col} IS NOT NULL AND ref.id IS NULL
                """,
            ).fetchall()
            for r in rows:
                orphans.append(dict(r))
        if orphans:
            logger.warning(
                "[SemanticStore] Found %d orphan references: %s",
                len(orphans),
                orphans[:5],
            )
        return orphans
    finally:
        conn.close()
