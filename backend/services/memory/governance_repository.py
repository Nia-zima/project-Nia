"""Governance Repository — state-side repository for Memory Governance.

Step 2 の「器」。semantic_state および周辺 governance テーブル
(candidates, claims, evidence, reviews, lineage, tombstones, transitions)
の CRUD を提供する。

将来の single writer 化:
  upsert_semantic_bundle(conn, memory, state) で semantic_memories と
  semantic_state を同一 transaction で原子的に更新する口を提供する。
  既存 semantic_store.py の直書きをここへ寄せるのは M0 観測後。

設計書: docs/memory_promotion_redesign.md §6, docs/memory_decay_redesign.md §15
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Optional

from backend.core.db import managed_conn
from backend.services.memory.models import (
    MemoryClaim,
    MemoryEvidence,
    PromotionReview,
    RawPromotionCandidate,
    SemanticLineage,
    SemanticMemory,
    SemanticReview,
    SemanticState,
    SemanticTombstone,
)


# ── Semantic State ─────────────────────────────────────


def upsert_semantic_state(
    conn,
    state: SemanticState,
) -> None:
    """Insert or update semantic_state row (in caller's transaction)."""
    conn.execute(
        """
        INSERT INTO semantic_state (
            semantic_id, owner_agent, memory_domain,
            memory_strength, confidence, seed_retention,
            last_reinforced_at, retrieval_count,
            contradiction_score, deprecation_score, merge_score,
            state, promotion_path, decay_path,
            created_at, updated_at
        ) VALUES (?,?,?, ?,?,?, ?,?, ?,?,?, ?,?,?, ?,?)
        ON CONFLICT(semantic_id) DO UPDATE SET
            owner_agent = excluded.owner_agent,
            memory_domain = excluded.memory_domain,
            memory_strength = excluded.memory_strength,
            confidence = excluded.confidence,
            seed_retention = excluded.seed_retention,
            last_reinforced_at = excluded.last_reinforced_at,
            retrieval_count = excluded.retrieval_count,
            contradiction_score = excluded.contradiction_score,
            deprecation_score = excluded.deprecation_score,
            merge_score = excluded.merge_score,
            state = excluded.state,
            promotion_path = excluded.promotion_path,
            decay_path = excluded.decay_path,
            updated_at = excluded.updated_at
        """,
        (
            state.semantic_id, state.owner_agent, state.memory_domain,
            state.memory_strength, state.confidence, state.seed_retention,
            state.last_reinforced_at, state.retrieval_count,
            state.contradiction_score, state.deprecation_score, state.merge_score,
            state.state, state.promotion_path, state.decay_path,
            state.created_at, state.updated_at,
        ),
    )


def upsert_semantic_bundle(
    conn,
    memory: SemanticMemory,
    state: SemanticState,
) -> None:
    """Atomically upsert semantic_memories + semantic_state in caller's transaction.

    将来の single writer 口。semantic_store.upsert_batch の代替として使う。
    semantic_memories と semantic_state を同一 conn (= 同一 transaction) で
    書くことで、両テーブルの整合性を保証する。
    """
    if memory.id != state.semantic_id:
        raise ValueError(
            "upsert_semantic_bundle requires matching ids: "
            f"memory.id={memory.id} state.semantic_id={state.semantic_id}"
        )

    # 1. semantic_memories upsert
    conn.execute(
        """
        INSERT INTO semantic_memories (
            id, thread_id, content, status, confidence, state_tag,
            supersedes_id, revoked_by_id, revoke_reason,
            valid_from, valid_to, staleness_days,
            source_turn_ids, source_event_ids, note,
            seed_retention, vector_sync_pending, embedding, defeaters,
            created_at, updated_at
        ) VALUES (?,?,?,?,?,?, ?,?,?, ?,?,?, ?,?,?, ?,?,?,?, ?,?)
        ON CONFLICT(id) DO UPDATE SET
            content = excluded.content,
            status = excluded.status,
            confidence = excluded.confidence,
            state_tag = excluded.state_tag,
            supersedes_id = excluded.supersedes_id,
            revoked_by_id = excluded.revoked_by_id,
            revoke_reason = excluded.revoke_reason,
            valid_to = excluded.valid_to,
            staleness_days = excluded.staleness_days,
            source_turn_ids = excluded.source_turn_ids,
            source_event_ids = excluded.source_event_ids,
            note = excluded.note,
            seed_retention = excluded.seed_retention,
            vector_sync_pending = excluded.vector_sync_pending,
            embedding = excluded.embedding,
            defeaters = excluded.defeaters,
            updated_at = excluded.updated_at
        """,
        (
            memory.id, memory.thread_id, memory.content,
            memory.status, memory.confidence, memory.state_tag,
            memory.supersedes_id, memory.revoked_by_id, memory.revoke_reason,
            memory.valid_from, memory.valid_to, memory.staleness_days,
            memory.source_turn_ids, memory.source_event_ids, memory.note,
            memory.seed_retention, memory.vector_sync_pending,
            memory.embedding, memory.defeaters,
            memory.created_at, memory.updated_at,
        ),
    )
    # 2. semantic_state upsert
    upsert_semantic_state(conn, state)


def get_semantic_state(semantic_id: str) -> Optional[SemanticState]:
    """Fetch semantic_state by id."""
    with managed_conn() as conn:
        conn.row_factory = _dict_factory
        row = conn.execute(
            "SELECT * FROM semantic_state WHERE semantic_id = ?",
            (semantic_id,),
        ).fetchone()
    if not row:
        return None
    return _row_to_semantic_state(row)


def list_semantic_states(
    *,
    state: Optional[str] = None,
    owner_agent: Optional[str] = None,
    limit: int = 100,
) -> list[SemanticState]:
    """Query semantic_state with optional filters."""
    clauses: list[str] = []
    params: list[Any] = []
    if state:
        clauses.append("state = ?")
        params.append(state)
    if owner_agent:
        clauses.append("owner_agent = ?")
        params.append(owner_agent)
    where = " AND ".join(clauses) if clauses else "1=1"
    params.append(limit)
    with managed_conn() as conn:
        conn.row_factory = _dict_factory
        rows = conn.execute(
            f"SELECT * FROM semantic_state WHERE {where} ORDER BY updated_at DESC LIMIT ?",
            params,
        ).fetchall()
    return [_row_to_semantic_state(r) for r in rows]


def record_transition(
    conn,
    *,
    semantic_id: str,
    from_state: str,
    to_state: str,
    trigger_type: str,
    trigger_ref: Optional[str] = None,
) -> str:
    """Insert a semantic_transitions row (in caller's transaction)."""
    tid = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO semantic_transitions
            (transition_id, semantic_id, from_state, to_state,
             trigger_type, trigger_ref, created_at)
        VALUES (?,?,?,?, ?,?,?)
        """,
        (tid, semantic_id, from_state, to_state,
         trigger_type, trigger_ref, time.time()),
    )
    return tid


# ── Raw Promotion Candidates ──────────────────────────


def insert_candidate(conn, candidate: RawPromotionCandidate) -> None:
    """Insert a raw_promotion_candidates row (in caller's transaction)."""
    conn.execute(
        """
        INSERT INTO raw_promotion_candidates (
            candidate_id, candidate_kind_rough, source_type, source_ref,
            topic_key, focus, response_intent, question_intent,
            unresolved_ref, owner_agent, memory_domain, status,
            thread_id, turn_id, message_id, stream_id, trace_id,
            created_at, updated_at
        ) VALUES (?,?,?,?, ?,?,?,?, ?,?,?,?, ?,?,?,?,?, ?,?)
        """,
        (
            candidate.candidate_id, candidate.candidate_kind_rough,
            candidate.source_type, candidate.source_ref,
            candidate.topic_key, candidate.focus,
            candidate.response_intent, candidate.question_intent,
            candidate.unresolved_ref, candidate.owner_agent,
            candidate.memory_domain, candidate.status,
            candidate.thread_id, candidate.turn_id,
            candidate.message_id, candidate.stream_id, candidate.trace_id,
            candidate.created_at, candidate.updated_at,
        ),
    )


def get_candidate(candidate_id: str) -> Optional[RawPromotionCandidate]:
    """Fetch a raw_promotion_candidates row by id."""
    with managed_conn() as conn:
        conn.row_factory = _dict_factory
        row = conn.execute(
            "SELECT * FROM raw_promotion_candidates WHERE candidate_id = ?",
            (candidate_id,),
        ).fetchone()
    if not row:
        return None
    return _row_to_candidate(row)


# ── Memory Claims ─────────────────────────────────────


def insert_claim(conn, claim: MemoryClaim) -> None:
    """Insert a memory_claims row (in caller's transaction)."""
    conn.execute(
        """
        INSERT INTO memory_claims (
            claim_id, claim_type, subject, predicate, object_json,
            scope, status, owner_agent, memory_domain, semantic_ref,
            thread_id, turn_id, message_id, stream_id, trace_id,
            created_at, updated_at
        ) VALUES (?,?,?,?,?, ?,?,?,?,?, ?,?,?,?,?, ?,?)
        """,
        (
            claim.claim_id, claim.claim_type, claim.subject,
            claim.predicate, claim.object_json,
            claim.scope, claim.status, claim.owner_agent,
            claim.memory_domain, claim.semantic_ref,
            claim.thread_id, claim.turn_id,
            claim.message_id, claim.stream_id, claim.trace_id,
            claim.created_at, claim.updated_at,
        ),
    )


def get_claim(claim_id: str) -> Optional[MemoryClaim]:
    """Fetch a memory_claims row by id."""
    with managed_conn() as conn:
        conn.row_factory = _dict_factory
        row = conn.execute(
            "SELECT * FROM memory_claims WHERE claim_id = ?",
            (claim_id,),
        ).fetchone()
    if not row:
        return None
    return _row_to_claim(row)


# ── Memory Evidence ───────────────────────────────────


def insert_evidence(conn, evidence: MemoryEvidence) -> None:
    """Insert a memory_evidence row (in caller's transaction).

    candidate_id と claim_id は両方 nullable。
    candidate 段階では candidate_id のみ、claim 正規化後に claim_id を backfill。
    """
    conn.execute(
        """
        INSERT INTO memory_evidence (
            evidence_id, candidate_id, claim_id,
            source_type, source_ref,
            evidence_date, reliability,
            thread_id, turn_id, message_id, stream_id, trace_id,
            created_at
        ) VALUES (?,?,?, ?,?, ?,?, ?,?,?,?,?, ?)
        """,
        (
            evidence.evidence_id, evidence.candidate_id, evidence.claim_id,
            evidence.source_type, evidence.source_ref,
            evidence.evidence_date, evidence.reliability,
            evidence.thread_id, evidence.turn_id,
            evidence.message_id, evidence.stream_id, evidence.trace_id,
            evidence.created_at,
        ),
    )


def list_evidence(claim_id: str) -> list[MemoryEvidence]:
    """Fetch all evidence for a claim."""
    with managed_conn() as conn:
        conn.row_factory = _dict_factory
        rows = conn.execute(
            "SELECT * FROM memory_evidence WHERE claim_id = ? ORDER BY created_at",
            (claim_id,),
        ).fetchall()
    return [_row_to_evidence(r) for r in rows]


def list_evidence_by_candidate(candidate_id: str) -> list[MemoryEvidence]:
    """Fetch all evidence for a candidate."""
    with managed_conn() as conn:
        conn.row_factory = _dict_factory
        rows = conn.execute(
            "SELECT * FROM memory_evidence WHERE candidate_id = ? ORDER BY created_at",
            (candidate_id,),
        ).fetchall()
    return [_row_to_evidence(r) for r in rows]


def count_evidence_by_candidate(conn, candidate_id: str) -> int:
    """Count evidence records for a candidate (in caller's transaction)."""
    row = conn.execute(
        "SELECT COUNT(*) FROM memory_evidence WHERE candidate_id = ?",
        (candidate_id,),
    ).fetchone()
    return row[0] if row else 0


def update_candidate_status(
    conn,
    candidate_id: str,
    new_status: str,
    now: float | None = None,
) -> None:
    """Update a candidate's status (in caller's transaction)."""
    if now is None:
        now = time.time()
    conn.execute(
        "UPDATE raw_promotion_candidates SET status = ?, updated_at = ? WHERE candidate_id = ?",
        (new_status, now, candidate_id),
    )


def list_candidates_by_kind(
    kind: str,
    statuses: list[str] | None = None,
    limit: int = 100,
) -> list[RawPromotionCandidate]:
    """Fetch candidates by kind, optionally filtered by status."""
    with managed_conn() as conn:
        conn.row_factory = _dict_factory
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            rows = conn.execute(
                f"SELECT * FROM raw_promotion_candidates "
                f"WHERE candidate_kind_rough = ? AND status IN ({placeholders}) "
                f"ORDER BY created_at DESC LIMIT ?",
                (kind, *statuses, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM raw_promotion_candidates "
                "WHERE candidate_kind_rough = ? ORDER BY created_at DESC LIMIT ?",
                (kind, limit),
            ).fetchall()
    return [_row_to_candidate(r) for r in rows]


def list_active_candidates(
    limit: int = 200,
) -> list[RawPromotionCandidate]:
    """Fetch all non-terminal candidates (pending or accumulating)."""
    with managed_conn() as conn:
        conn.row_factory = _dict_factory
        rows = conn.execute(
            "SELECT * FROM raw_promotion_candidates "
            "WHERE status IN ('pending', 'accumulating') "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_row_to_candidate(r) for r in rows]


# ── Promotion Reviews ────────────────────────────────


def insert_promotion_review(conn, review: PromotionReview) -> None:
    """Insert a promotion_reviews row (in caller's transaction)."""
    conn.execute(
        """
        INSERT INTO promotion_reviews (
            review_id, claim_id, reviewer_type, decision,
            reason, owner_agent,
            thread_id, turn_id, message_id, stream_id, trace_id,
            created_at
        ) VALUES (?,?,?,?, ?,?, ?,?,?,?,?, ?)
        """,
        (
            review.review_id, review.claim_id,
            review.reviewer_type, review.decision,
            review.reason, review.owner_agent,
            review.thread_id, review.turn_id,
            review.message_id, review.stream_id, review.trace_id,
            review.created_at,
        ),
    )


# ── Semantic Lineage ─────────────────────────────────


def insert_lineage(conn, lineage: SemanticLineage) -> None:
    """Insert a semantic_lineage row (in caller's transaction)."""
    conn.execute(
        """
        INSERT INTO semantic_lineage (
            lineage_id, claim_id, semantic_id,
            evidence_snapshot_json, owner_agent,
            thread_id, turn_id, message_id, stream_id, trace_id,
            promoted_at
        ) VALUES (?,?,?, ?,?, ?,?,?,?,?, ?)
        """,
        (
            lineage.lineage_id, lineage.claim_id, lineage.semantic_id,
            lineage.evidence_snapshot_json, lineage.owner_agent,
            lineage.thread_id, lineage.turn_id, lineage.message_id,
            lineage.stream_id, lineage.trace_id,
            lineage.promoted_at,
        ),
    )


def get_lineage_by_semantic(semantic_id: str) -> Optional[SemanticLineage]:
    """Fetch lineage for a semantic memory."""
    with managed_conn() as conn:
        conn.row_factory = _dict_factory
        row = conn.execute(
            "SELECT * FROM semantic_lineage WHERE semantic_id = ?",
            (semantic_id,),
        ).fetchone()
    if not row:
        return None
    return _row_to_lineage(row)


# ── Semantic Reviews ─────────────────────────────────


def insert_semantic_review(conn, review: SemanticReview) -> None:
    """Insert a semantic_reviews row (in caller's transaction)."""
    conn.execute(
        """
        INSERT INTO semantic_reviews (
            review_id, semantic_id, reviewer_type, decision,
            reason, evidence_snapshot_json,
            thread_id, turn_id, message_id, stream_id, trace_id,
            created_at
        ) VALUES (?,?,?,?, ?,?, ?,?,?,?,?, ?)
        """,
        (
            review.review_id, review.semantic_id,
            review.reviewer_type, review.decision,
            review.reason, review.evidence_snapshot_json,
            review.thread_id, review.turn_id, review.message_id,
            review.stream_id, review.trace_id,
            review.created_at,
        ),
    )


# ── Semantic Tombstones ──────────────────────────────


def insert_tombstone(conn, tombstone: SemanticTombstone) -> None:
    """Insert a semantic_tombstones row (in caller's transaction)."""
    conn.execute(
        """
        INSERT INTO semantic_tombstones (
            tombstone_id, semantic_id, claim_ref,
            owner_agent, memory_domain, retirement_reason,
            replaced_by, archived_at, notes
        ) VALUES (?,?,?, ?,?,?, ?,?,?)
        """,
        (
            tombstone.tombstone_id, tombstone.semantic_id, tombstone.claim_ref,
            tombstone.owner_agent, tombstone.memory_domain,
            tombstone.retirement_reason,
            tombstone.replaced_by, tombstone.archived_at, tombstone.notes,
        ),
    )


def get_tombstone(semantic_id: str) -> Optional[SemanticTombstone]:
    """Fetch tombstone for a semantic memory."""
    with managed_conn() as conn:
        conn.row_factory = _dict_factory
        row = conn.execute(
            "SELECT * FROM semantic_tombstones WHERE semantic_id = ?",
            (semantic_id,),
        ).fetchone()
    if not row:
        return None
    return _row_to_tombstone(row)


# ── Row Converters ───────────────────────────────────


def _dict_factory(cursor, row):
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def _row_to_semantic_state(r: dict) -> SemanticState:
    return SemanticState(
        semantic_id=r["semantic_id"],
        owner_agent=r["owner_agent"],
        memory_domain=r["memory_domain"],
        memory_strength=r["memory_strength"],
        confidence=r["confidence"],
        seed_retention=r["seed_retention"],
        last_reinforced_at=r["last_reinforced_at"],
        retrieval_count=r["retrieval_count"],
        contradiction_score=r["contradiction_score"],
        deprecation_score=r["deprecation_score"],
        merge_score=r["merge_score"],
        state=r["state"],
        promotion_path=r["promotion_path"],
        decay_path=r["decay_path"],
        created_at=r["created_at"],
        updated_at=r["updated_at"],
    )


def _row_to_candidate(r: dict) -> RawPromotionCandidate:
    return RawPromotionCandidate(
        candidate_id=r["candidate_id"],
        candidate_kind_rough=r["candidate_kind_rough"],
        source_type=r["source_type"],
        source_ref=r["source_ref"],
        topic_key=r["topic_key"],
        focus=r["focus"],
        response_intent=r["response_intent"],
        question_intent=r["question_intent"],
        unresolved_ref=r["unresolved_ref"],
        owner_agent=r["owner_agent"],
        memory_domain=r["memory_domain"],
        status=r["status"],
        thread_id=r.get("thread_id"),
        turn_id=r.get("turn_id"),
        message_id=r.get("message_id"),
        stream_id=r.get("stream_id"),
        trace_id=r.get("trace_id"),
        created_at=r["created_at"],
        updated_at=r["updated_at"],
    )


def _row_to_claim(r: dict) -> MemoryClaim:
    return MemoryClaim(
        claim_id=r["claim_id"],
        claim_type=r["claim_type"],
        subject=r["subject"],
        predicate=r["predicate"],
        object_json=r["object_json"],
        scope=r["scope"],
        status=r["status"],
        owner_agent=r["owner_agent"],
        memory_domain=r["memory_domain"],
        semantic_ref=r["semantic_ref"],
        thread_id=r.get("thread_id"),
        turn_id=r.get("turn_id"),
        message_id=r.get("message_id"),
        stream_id=r.get("stream_id"),
        trace_id=r.get("trace_id"),
        created_at=r["created_at"],
        updated_at=r["updated_at"],
    )


def _row_to_evidence(r: dict) -> MemoryEvidence:
    return MemoryEvidence(
        evidence_id=r["evidence_id"],
        candidate_id=r.get("candidate_id"),
        claim_id=r.get("claim_id"),
        source_type=r["source_type"],
        source_ref=r["source_ref"],
        evidence_date=r["evidence_date"],
        reliability=r["reliability"],
        thread_id=r.get("thread_id"),
        turn_id=r.get("turn_id"),
        message_id=r.get("message_id"),
        stream_id=r.get("stream_id"),
        trace_id=r.get("trace_id"),
        created_at=r["created_at"],
    )


def _row_to_lineage(r: dict) -> SemanticLineage:
    return SemanticLineage(
        lineage_id=r["lineage_id"],
        claim_id=r["claim_id"],
        semantic_id=r["semantic_id"],
        evidence_snapshot_json=r["evidence_snapshot_json"],
        owner_agent=r["owner_agent"],
        thread_id=r.get("thread_id"),
        turn_id=r.get("turn_id"),
        message_id=r.get("message_id"),
        stream_id=r.get("stream_id"),
        trace_id=r.get("trace_id"),
        promoted_at=r["promoted_at"],
    )


def _row_to_tombstone(r: dict) -> SemanticTombstone:
    return SemanticTombstone(
        tombstone_id=r["tombstone_id"],
        semantic_id=r["semantic_id"],
        claim_ref=r["claim_ref"],
        owner_agent=r["owner_agent"],
        memory_domain=r["memory_domain"],
        retirement_reason=r["retirement_reason"],
        replaced_by=r["replaced_by"],
        archived_at=r["archived_at"],
        notes=r["notes"],
    )
