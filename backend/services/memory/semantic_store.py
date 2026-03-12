"""
Semantic Memory CRUD layer.

Write methods accept a `conn` parameter for use inside S5 Commit transactions.
Read methods manage their own connections.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Optional

import numpy as np

from backend.core.db import managed_conn
from backend.core.logger import logger
from backend.services.memory.models import SemanticMemory


# ── Embedding helpers ────────────────────────────────────────────


def _encode_content(text: str) -> Optional[bytes]:
    """Encode text to embedding bytes. Returns None on failure."""
    try:
        from backend.core.config import settings
        if not settings.EMBEDDING_AT_SAVE:
            return None
        from backend.core import embedding_model
        vecs = embedding_model.encode([text])
        if vecs is None:
            return None
        return vecs[0].astype(np.float32).tobytes()
    except Exception:
        logger.debug("[SemanticStore] embedding encode skipped", exc_info=True)
        return None


def embedding_to_numpy(blob: Optional[bytes]) -> Optional[np.ndarray]:
    """Deserialize BLOB to numpy float32 vector."""
    if blob is None:
        return None
    return np.frombuffer(blob, dtype=np.float32).copy()

_COLUMNS = (
    "id", "thread_id", "content", "status", "confidence", "state_tag",
    "supersedes_id", "revoked_by_id", "revoke_reason",
    "valid_from", "valid_to", "staleness_days",
    "source_turn_ids", "source_event_ids", "note",
    "seed_retention", "vector_sync_pending", "embedding", "defeaters",
    "created_at", "updated_at",
)


def _row_to_model(row) -> SemanticMemory:
    d = dict(row)
    return SemanticMemory(**{k: d[k] for k in _COLUMNS})


# ── Write (require conn for transaction use) ─────────────────────


def upsert(conn, mem: SemanticMemory) -> None:
    # Encode content to embedding if not already set
    emb = mem.embedding if mem.embedding is not None else _encode_content(mem.content)
    conn.execute(
        """
        INSERT INTO semantic_memories (
            id, thread_id, content, status, confidence, state_tag,
            supersedes_id, revoked_by_id, revoke_reason,
            valid_from, valid_to, staleness_days,
            source_turn_ids, source_event_ids, note,
            seed_retention, vector_sync_pending, embedding, defeaters,
            created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
            embedding=excluded.embedding,
            defeaters=excluded.defeaters,
            updated_at=excluded.updated_at
        """,
        (
            mem.id, mem.thread_id, mem.content, mem.status, mem.confidence,
            mem.state_tag, mem.supersedes_id, mem.revoked_by_id, mem.revoke_reason,
            mem.valid_from, mem.valid_to, mem.staleness_days,
            mem.source_turn_ids, mem.source_event_ids, mem.note,
            mem.seed_retention, mem.vector_sync_pending, emb, mem.defeaters,
            mem.created_at, mem.updated_at,
        ),
    )


def upsert_batch(conn, memories: list[SemanticMemory]) -> int:
    if not memories:
        return 0
    # Pre-compute embeddings for memories that don't have one
    rows = []
    for mem in memories:
        emb = mem.embedding if mem.embedding is not None else _encode_content(mem.content)
        rows.append((
            mem.id, mem.thread_id, mem.content, mem.status, mem.confidence,
            mem.state_tag, mem.supersedes_id, mem.revoked_by_id, mem.revoke_reason,
            mem.valid_from, mem.valid_to, mem.staleness_days,
            mem.source_turn_ids, mem.source_event_ids, mem.note,
            mem.seed_retention, mem.vector_sync_pending, emb, mem.defeaters,
            mem.created_at, mem.updated_at,
        ))
    conn.executemany(
        """
        INSERT INTO semantic_memories (
            id, thread_id, content, status, confidence, state_tag,
            supersedes_id, revoked_by_id, revoke_reason,
            valid_from, valid_to, staleness_days,
            source_turn_ids, source_event_ids, note,
            seed_retention, vector_sync_pending, embedding, defeaters,
            created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
            embedding=excluded.embedding,
            defeaters=excluded.defeaters,
            updated_at=excluded.updated_at
        """,
        rows,
    )
    return len(memories)


def revoke(
    conn, id: str, reason: str,
    revoked_by_id: Optional[str] = None,
    tombstone_note: Optional[str] = None,
) -> bool:
    now = time.time()
    cur = conn.execute(
        """
        UPDATE semantic_memories
        SET status='revoked', revoke_reason=?, revoked_by_id=?,
            note=COALESCE(?, note),
            vector_sync_pending=1, updated_at=?
        WHERE id=? AND status != 'revoked'
        """,
        (reason, revoked_by_id, tombstone_note, now, id),
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
    with managed_conn() as conn:
        row = conn.execute(
            "SELECT * FROM semantic_memories WHERE id=?", (id,)
        ).fetchone()
        return _row_to_model(row) if row else None


def get_chain(id: str) -> list[SemanticMemory]:
    """Follow supersedes_id / revoked_by_id chain in both directions."""
    visited: set[str] = set()
    chain: list[SemanticMemory] = []
    with managed_conn() as conn:
        queue: deque[str] = deque([id])
        while queue:
            current_id = queue.popleft()
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


def search_active(thread_id: str = "", *, limit: int = 20) -> list[SemanticMemory]:
    """Search active semantic memories globally (thread_id kept for API compat)."""
    with managed_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM semantic_memories
            WHERE status IN ('confirmed', 'inferred')
            ORDER BY confidence DESC, created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_row_to_model(r) for r in rows]


def search_by_tag(thread_id: str = "", tag: str = "", *, limit: int = 10) -> list[SemanticMemory]:
    """Search active memories with a specific state_tag globally."""
    with managed_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM semantic_memories
            WHERE state_tag=? AND status IN ('confirmed', 'inferred')
            ORDER BY confidence DESC, created_at DESC
            LIMIT ?
            """,
            (tag, limit),
        ).fetchall()
        return [_row_to_model(r) for r in rows]


def get_pending_vector_sync(*, limit: int = 100) -> list[SemanticMemory]:
    with managed_conn() as conn:
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


def get_inferred_older_than(age_seconds: float) -> list[SemanticMemory]:
    cutoff = time.time() - age_seconds
    with managed_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM semantic_memories
            WHERE status='inferred' AND created_at < ?
            ORDER BY created_at ASC
            """,
            (cutoff,),
        ).fetchall()
        return [_row_to_model(r) for r in rows]


# ── Maintenance ──────────────────────────────────────────────────


def mark_vector_synced(ids: list[str]) -> int:
    if not ids:
        return 0
    with managed_conn() as conn:
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


def decay_by_status() -> int:
    """Apply half-life decay to semantic memories based on status.

    Half-lives (from config):
      - inferred: RETENTION_HALF_LIFE_DEFAULT (default 5 days)
      - confirmed: RETENTION_HALF_LIFE_CONSENT (default 30 days)

    Uses created_at as the decay baseline (not updated_at) to prevent
    self-resetting decay on each sweep.

    Memories whose confidence decays below 0.05 are marked 'revoked'.
    Returns the number of revoked memories.
    """
    import math
    from backend.core.config import settings as _settings

    half_life = {
        "inferred": getattr(_settings, "RETENTION_HALF_LIFE_DEFAULT", 5.0),
        "confirmed": getattr(_settings, "RETENTION_HALF_LIFE_CONSENT", 30.0),
    }
    REVOKE_THRESHOLD = 0.05
    now = time.time()

    with managed_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, status, confidence, seed_retention, created_at
            FROM semantic_memories
            WHERE status IN ('inferred', 'confirmed')
            """,
        ).fetchall()

        revoked_ids: list[str] = []
        updates: list[tuple] = []

        for row in rows:
            hl_days = half_life.get(row["status"])
            if not hl_days:
                continue
            age_days = (now - row["created_at"]) / 86400.0
            if age_days <= 0:
                continue
            decay = math.pow(0.5, age_days / hl_days)
            sr = row["seed_retention"]
            base = sr if (sr is not None and sr > 0) else row["confidence"]
            base = base if (base is not None and base > 0) else 0.5
            new_conf = base * decay

            if new_conf < REVOKE_THRESHOLD:
                revoked_ids.append(row["id"])
            else:
                # Only update if meaningfully changed (>1%)
                if abs(new_conf - row["confidence"]) >= 0.01:
                    updates.append((new_conf, now, row["id"]))

        # Wrap updates and revocations in a transaction
        conn.execute("BEGIN IMMEDIATE")
        try:
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
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        total = len(updates) + len(revoked_ids)
        if total:
            logger.info(
                "[SemanticStore] decay_by_status: updated=%d revoked=%d",
                len(updates), len(revoked_ids),
            )

        # Phase M0: governance observability — record decay sweep (空振りも記録)
        if getattr(_settings, "GOVERNANCE_OBSERVE_ENABLED", False):
            try:
                from backend.services.memory.governance_event_writer import record_event
                record_event(
                    event_name="decay_sweep_completed",
                    payload={
                        "scanned_count": len(rows),
                        "updated_count": len(updates),
                        "revoked_count": len(revoked_ids),
                        "revoked_ids": revoked_ids[:50],
                    },
                )
            except Exception:
                logger.debug("[SemanticStore] governance event failed", exc_info=True)

        return len(revoked_ids)


def confirm_batch(ids: list[str]) -> int:
    if not ids:
        return 0
    with managed_conn() as conn:
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


def scan_orphan_references() -> list[dict]:
    """Detect supersedes_id / revoked_by_id pointing to non-existent records."""
    with managed_conn() as conn:
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
