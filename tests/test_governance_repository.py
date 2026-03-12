"""Tests for governance_repository — Step 2 skeleton tables + single writer."""
from __future__ import annotations

import time
import uuid

import pytest

from backend.core.db import get_conn, init_schema
from backend.services.memory.governance_repository import (
    get_candidate,
    get_claim,
    get_lineage_by_semantic,
    get_semantic_state,
    get_tombstone,
    insert_candidate,
    insert_claim,
    insert_evidence,
    insert_lineage,
    insert_promotion_review,
    insert_semantic_review,
    insert_tombstone,
    list_evidence,
    list_semantic_states,
    record_transition,
    upsert_semantic_bundle,
    upsert_semantic_state,
)
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


@pytest.fixture(autouse=True)
def _setup_db():
    """Ensure schema exists with latest columns; clean governance tables."""
    # DROP + re-create to pick up new columns (CREATE TABLE IF NOT EXISTS
    # won't add columns to existing tables)
    conn = get_conn()
    try:
        for table in (
            "semantic_transitions",
            "semantic_reviews",
            "semantic_tombstones",
            "semantic_lineage",
            "promotion_reviews",
            "memory_evidence",
            "memory_claims",
            "raw_promotion_candidates",
            "semantic_state",
        ):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.commit()
    finally:
        conn.close()
    init_schema()
    yield


# ── DDL verification ─────────────────────────────────


class TestDDL:
    """Verify all 9 governance tables exist with expected columns."""

    _EXPECTED_TABLES = [
        "semantic_state",
        "raw_promotion_candidates",
        "memory_claims",
        "memory_evidence",
        "promotion_reviews",
        "semantic_lineage",
        "semantic_reviews",
        "semantic_tombstones",
        "semantic_transitions",
    ]

    def test_tables_exist(self):
        conn = get_conn()
        try:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        finally:
            conn.close()
        for t in self._EXPECTED_TABLES:
            assert t in tables, f"table {t} missing"

    @pytest.mark.parametrize(
        "table,expected_cols",
        [
            (
                "semantic_state",
                {"semantic_id", "memory_strength", "confidence", "state",
                 "promotion_path", "decay_path", "seed_retention",
                 "retrieval_count", "contradiction_score"},
            ),
            (
                "raw_promotion_candidates",
                {"candidate_id", "candidate_kind_rough", "source_type",
                 "topic_key", "status", "owner_agent",
                 "thread_id", "turn_id", "message_id", "stream_id", "trace_id"},
            ),
            (
                "memory_claims",
                {"claim_id", "claim_type", "subject", "predicate",
                 "object_json", "scope", "status",
                 "thread_id", "turn_id", "message_id", "stream_id", "trace_id"},
            ),
            (
                "memory_evidence",
                {"evidence_id", "claim_id", "source_type", "reliability",
                 "thread_id", "turn_id", "message_id", "stream_id", "trace_id"},
            ),
            (
                "promotion_reviews",
                {"review_id", "claim_id", "reviewer_type", "decision",
                 "thread_id", "turn_id", "message_id", "stream_id", "trace_id"},
            ),
            (
                "semantic_lineage",
                {"lineage_id", "claim_id", "semantic_id",
                 "evidence_snapshot_json", "promoted_at",
                 "thread_id", "turn_id", "message_id", "stream_id", "trace_id"},
            ),
            (
                "semantic_reviews",
                {"review_id", "semantic_id", "reviewer_type", "decision",
                 "thread_id", "turn_id", "message_id", "stream_id", "trace_id"},
            ),
            (
                "semantic_tombstones",
                {"tombstone_id", "semantic_id", "retirement_reason",
                 "replaced_by", "archived_at"},
            ),
            (
                "semantic_transitions",
                {"transition_id", "semantic_id", "from_state", "to_state",
                 "trigger_type"},
            ),
        ],
    )
    def test_columns_exist(self, table, expected_cols):
        conn = get_conn()
        try:
            cols = {
                r[1]
                for r in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
        finally:
            conn.close()
        for col in expected_cols:
            assert col in cols, f"column {col} missing in {table}"


# ── Semantic State CRUD ──────────────────────────────


class TestSemanticState:
    def test_upsert_and_get(self):
        now = time.time()
        ss = SemanticState(
            semantic_id="sem_test_1",
            memory_strength=0.8,
            confidence=0.9,
            seed_retention=0.7,
            state="active",
            created_at=now,
            updated_at=now,
        )
        conn = get_conn()
        try:
            upsert_semantic_state(conn, ss)
            conn.commit()
        finally:
            conn.close()

        result = get_semantic_state("sem_test_1")
        assert result is not None
        assert result.memory_strength == 0.8
        assert result.confidence == 0.9
        assert result.state == "active"
        assert result.promotion_path == "legacy"

    def test_upsert_updates_existing(self):
        now = time.time()
        ss = SemanticState(
            semantic_id="sem_upd_1",
            memory_strength=0.5,
            confidence=0.5,
            state="active",
            created_at=now,
            updated_at=now,
        )
        conn = get_conn()
        try:
            upsert_semantic_state(conn, ss)
            conn.commit()
        finally:
            conn.close()

        ss.memory_strength = 0.3
        ss.state = "weakened"
        ss.updated_at = time.time()
        conn = get_conn()
        try:
            upsert_semantic_state(conn, ss)
            conn.commit()
        finally:
            conn.close()

        result = get_semantic_state("sem_upd_1")
        assert result.memory_strength == 0.3
        assert result.state == "weakened"

    def test_get_nonexistent(self):
        assert get_semantic_state("nonexistent") is None

    def test_list_with_filters(self):
        now = time.time()
        conn = get_conn()
        try:
            for i, st in enumerate(["active", "active", "weakened"]):
                upsert_semantic_state(
                    conn,
                    SemanticState(
                        semantic_id=f"sem_list_{i}",
                        state=st,
                        created_at=now,
                        updated_at=now + i,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

        active = list_semantic_states(state="active")
        assert len(active) == 2
        weakened = list_semantic_states(state="weakened")
        assert len(weakened) == 1


# ── Semantic Transitions ─────────────────────────────


class TestSemanticTransitions:
    def test_record_transition(self):
        conn = get_conn()
        try:
            tid = record_transition(
                conn,
                semantic_id="sem_tr_1",
                from_state="active",
                to_state="weakened",
                trigger_type="contradiction",
                trigger_ref="ev_123",
            )
            conn.commit()
        finally:
            conn.close()
        assert tid is not None
        assert len(tid) == 32

        conn = get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM semantic_transitions WHERE transition_id = ?",
                (tid,),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None


# ── Raw Promotion Candidates ─────────────────────────


class TestRawPromotionCandidates:
    def test_insert_and_get(self):
        now = time.time()
        cand = RawPromotionCandidate(
            candidate_id="cand_1",
            candidate_kind_rough="fact",
            source_type="episodic",
            source_ref="ev_abc",
            topic_key="coffee",
            created_at=now,
            updated_at=now,
        )
        conn = get_conn()
        try:
            insert_candidate(conn, cand)
            conn.commit()
        finally:
            conn.close()

        result = get_candidate("cand_1")
        assert result is not None
        assert result.candidate_kind_rough == "fact"
        assert result.source_type == "episodic"
        assert result.topic_key == "coffee"
        assert result.status == "pending"

    def test_get_nonexistent(self):
        assert get_candidate("nonexistent") is None


# ── Memory Claims ────────────────────────────────────


class TestMemoryClaims:
    def test_insert_and_get(self):
        now = time.time()
        claim = MemoryClaim(
            claim_id="cl_1",
            claim_type="fact",
            subject="Origin",
            predicate="likes",
            object_json='{"thing": "coffee"}',
            created_at=now,
            updated_at=now,
        )
        conn = get_conn()
        try:
            insert_claim(conn, claim)
            conn.commit()
        finally:
            conn.close()

        result = get_claim("cl_1")
        assert result is not None
        assert result.claim_type == "fact"
        assert result.subject == "Origin"
        assert result.predicate == "likes"
        assert result.status == "candidate"


# ── Memory Evidence ──────────────────────────────────


class TestMemoryEvidence:
    def test_insert_and_list(self):
        now = time.time()
        conn = get_conn()
        try:
            for i in range(3):
                insert_evidence(
                    conn,
                    MemoryEvidence(
                        evidence_id=f"ev_{i}",
                        claim_id="cl_ev_test",
                        source_type="episodic",
                        source_ref=f"ref_{i}",
                        evidence_date="2026-03-08",
                        reliability=0.5 + i * 0.1,
                        created_at=now + i,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

        results = list_evidence("cl_ev_test")
        assert len(results) == 3
        assert results[0].evidence_id == "ev_0"
        assert results[2].reliability == pytest.approx(0.7)

    def test_list_empty(self):
        assert list_evidence("nonexistent") == []


# ── Promotion Reviews ───────────────────────────────


class TestPromotionReviews:
    def test_insert(self):
        now = time.time()
        conn = get_conn()
        try:
            insert_promotion_review(
                conn,
                PromotionReview(
                    review_id="pr_1",
                    claim_id="cl_pr",
                    reviewer_type="rule",
                    decision="approve",
                    reason="sufficient evidence",
                    created_at=now,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        conn = get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM promotion_reviews WHERE review_id = 'pr_1'"
            ).fetchone()
        finally:
            conn.close()
        assert row is not None


# ── Semantic Lineage ─────────────────────────────────


class TestSemanticLineage:
    def test_insert_and_get(self):
        now = time.time()
        lin = SemanticLineage(
            lineage_id="lin_1",
            claim_id="cl_lin",
            semantic_id="sem_lin",
            evidence_snapshot_json='[{"ev": "snapshot"}]',
            thread_id="t_lin",
            turn_id="turn_lin",
            message_id="msg_lin",
            stream_id="stream_lin",
            trace_id="trace_lin",
            promoted_at=now,
        )
        conn = get_conn()
        try:
            insert_lineage(conn, lin)
            conn.commit()
        finally:
            conn.close()

        result = get_lineage_by_semantic("sem_lin")
        assert result is not None
        assert result.claim_id == "cl_lin"
        assert result.evidence_snapshot_json == '[{"ev": "snapshot"}]'
        assert result.turn_id == "turn_lin"
        assert result.trace_id == "trace_lin"


# ── Semantic Reviews ─────────────────────────────────


class TestSemanticReviews:
    def test_insert(self):
        now = time.time()
        conn = get_conn()
        try:
            insert_semantic_review(
                conn,
                SemanticReview(
                    review_id="sr_1",
                    semantic_id="sem_sr",
                    reviewer_type="llm",
                    decision="weaken",
                    reason="outdated info",
                    thread_id="t_sr",
                    turn_id="turn_sr",
                    message_id="msg_sr",
                    stream_id="stream_sr",
                    trace_id="trace_sr",
                    created_at=now,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        conn = get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM semantic_reviews WHERE review_id = 'sr_1'"
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row["turn_id"] == "turn_sr"
        assert row["trace_id"] == "trace_sr"


# ── Semantic Tombstones ──────────────────────────────


class TestSemanticTombstones:
    def test_insert_and_get(self):
        now = time.time()
        ts = SemanticTombstone(
            tombstone_id="tomb_1",
            semantic_id="sem_tomb",
            retirement_reason="contradicted",
            archived_at=now,
            replaced_by="sem_new",
            notes="replaced by newer info",
        )
        conn = get_conn()
        try:
            insert_tombstone(conn, ts)
            conn.commit()
        finally:
            conn.close()

        result = get_tombstone("sem_tomb")
        assert result is not None
        assert result.retirement_reason == "contradicted"
        assert result.replaced_by == "sem_new"
        assert result.notes == "replaced by newer info"

    def test_get_nonexistent(self):
        assert get_tombstone("nonexistent") is None


# ── Upsert path/domain update ────────────────────────


class TestSemanticStatePathUpdate:
    def test_upsert_updates_path_and_domain(self):
        """promotion_path/decay_path/seed_retention/owner_agent/memory_domain
        should be updatable via upsert (not silently dropped)."""
        now = time.time()
        ss = SemanticState(
            semantic_id="sem_path_1",
            promotion_path="legacy",
            decay_path="legacy_expiry",
            seed_retention=0.5,
            owner_agent="nia",
            memory_domain="default",
            state="active",
            created_at=now,
            updated_at=now,
        )
        conn = get_conn()
        try:
            upsert_semantic_state(conn, ss)
            conn.commit()
        finally:
            conn.close()

        ss.promotion_path = "tribunal_v1"
        ss.decay_path = "tribunal_v1"
        ss.seed_retention = 0.8
        ss.owner_agent = "nero"
        ss.memory_domain = "observation"
        ss.updated_at = time.time()
        conn = get_conn()
        try:
            upsert_semantic_state(conn, ss)
            conn.commit()
        finally:
            conn.close()

        result = get_semantic_state("sem_path_1")
        assert result.promotion_path == "tribunal_v1"
        assert result.decay_path == "tribunal_v1"
        assert result.seed_retention == 0.8
        assert result.owner_agent == "nero"
        assert result.memory_domain == "observation"


# ── upsert_semantic_bundle ───────────────────────────


class TestUpsertSemanticBundle:
    def test_bundle_writes_both_tables(self):
        """upsert_semantic_bundle should atomically write semantic_memories + semantic_state."""
        now = time.time()
        mem = SemanticMemory(
            id="sem_bundle_1",
            thread_id="thread_b",
            content="テスト記憶",
            status="confirmed",
            confidence=0.9,
            valid_from=now,
            created_at=now,
            updated_at=now,
        )
        st = SemanticState(
            semantic_id="sem_bundle_1",
            memory_strength=0.85,
            confidence=0.9,
            seed_retention=0.7,
            state="active",
            promotion_path="tribunal_v1",
            created_at=now,
            updated_at=now,
        )
        conn = get_conn()
        try:
            upsert_semantic_bundle(conn, mem, st)
            conn.commit()
        finally:
            conn.close()

        # Verify semantic_memories
        conn = get_conn()
        try:
            row = conn.execute(
                "SELECT content, status FROM semantic_memories WHERE id = 'sem_bundle_1'"
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row[0] == "テスト記憶"
        assert row[1] == "confirmed"

        # Verify semantic_state
        result = get_semantic_state("sem_bundle_1")
        assert result is not None
        assert result.memory_strength == 0.85
        assert result.promotion_path == "tribunal_v1"

    def test_bundle_rejects_mismatched_ids_without_writing(self):
        """Mismatched ids should raise and leave both tables untouched."""
        now = time.time()
        mem = SemanticMemory(
            id="sem_bundle_mem",
            thread_id="thread_b",
            content="不整合テスト",
            status="confirmed",
            confidence=0.9,
            valid_from=now,
            created_at=now,
            updated_at=now,
        )
        st = SemanticState(
            semantic_id="sem_bundle_state",
            memory_strength=0.85,
            confidence=0.9,
            state="active",
            created_at=now,
            updated_at=now,
        )
        conn = get_conn()
        try:
            with pytest.raises(ValueError, match="matching ids"):
                upsert_semantic_bundle(conn, mem, st)
            conn.rollback()
        finally:
            conn.close()

        conn = get_conn()
        try:
            mem_row = conn.execute(
                "SELECT id FROM semantic_memories WHERE id = ?",
                (mem.id,),
            ).fetchone()
        finally:
            conn.close()
        assert mem_row is None
        assert get_semantic_state(st.semantic_id) is None

    def test_bundle_rollback_removes_both_tables(self):
        """Caller rollback should remove both semantic_memories and semantic_state writes."""
        now = time.time()
        mem = SemanticMemory(
            id="sem_bundle_rb",
            thread_id="thread_rb",
            content="rollback test",
            status="confirmed",
            confidence=0.8,
            valid_from=now,
            created_at=now,
            updated_at=now,
        )
        st = SemanticState(
            semantic_id="sem_bundle_rb",
            memory_strength=0.75,
            confidence=0.8,
            state="active",
            created_at=now,
            updated_at=now,
        )
        conn = get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            upsert_semantic_bundle(conn, mem, st)
            conn.execute("ROLLBACK")
        finally:
            conn.close()

        conn = get_conn()
        try:
            mem_row = conn.execute(
                "SELECT id FROM semantic_memories WHERE id = ?",
                (mem.id,),
            ).fetchone()
        finally:
            conn.close()
        assert mem_row is None
        assert get_semantic_state(st.semantic_id) is None


# ── Provenance round-trip ────────────────────────────


class TestProvenanceRoundTrip:
    def test_candidate_provenance(self):
        now = time.time()
        cand = RawPromotionCandidate(
            candidate_id="cand_prov",
            candidate_kind_rough="fact",
            source_type="episodic",
            thread_id="t_prov",
            turn_id="turn_prov",
            message_id="msg_prov",
            stream_id="stream_prov",
            trace_id="trace_prov",
            created_at=now,
            updated_at=now,
        )
        conn = get_conn()
        try:
            insert_candidate(conn, cand)
            conn.commit()
        finally:
            conn.close()

        result = get_candidate("cand_prov")
        assert result.thread_id == "t_prov"
        assert result.turn_id == "turn_prov"
        assert result.message_id == "msg_prov"
        assert result.stream_id == "stream_prov"
        assert result.trace_id == "trace_prov"

    def test_claim_provenance(self):
        now = time.time()
        claim = MemoryClaim(
            claim_id="cl_prov",
            claim_type="fact",
            subject="X",
            predicate="is",
            thread_id="t_cl",
            turn_id="turn_cl",
            message_id="msg_cl",
            stream_id="stream_cl",
            trace_id="trace_cl",
            created_at=now,
            updated_at=now,
        )
        conn = get_conn()
        try:
            insert_claim(conn, claim)
            conn.commit()
        finally:
            conn.close()

        result = get_claim("cl_prov")
        assert result.thread_id == "t_cl"
        assert result.turn_id == "turn_cl"
        assert result.trace_id == "trace_cl"

    def test_evidence_provenance(self):
        now = time.time()
        conn = get_conn()
        try:
            insert_evidence(
                conn,
                MemoryEvidence(
                    evidence_id="ev_prov",
                    claim_id="cl_ev_prov",
                    source_type="episodic",
                    thread_id="t_ev",
                    turn_id="turn_ev",
                    message_id="msg_ev",
                    stream_id="stream_ev",
                    trace_id="trace_ev",
                    created_at=now,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        results = list_evidence("cl_ev_prov")
        assert len(results) == 1
        assert results[0].thread_id == "t_ev"
        assert results[0].turn_id == "turn_ev"
        assert results[0].trace_id == "trace_ev"

    def test_lineage_provenance(self):
        now = time.time()
        lin = SemanticLineage(
            lineage_id="lin_prov",
            claim_id="cl_lin_prov",
            semantic_id="sem_lin_prov",
            thread_id="t_lin_prov",
            turn_id="turn_lin_prov",
            message_id="msg_lin_prov",
            stream_id="stream_lin_prov",
            trace_id="trace_lin_prov",
            promoted_at=now,
        )
        conn = get_conn()
        try:
            insert_lineage(conn, lin)
            conn.commit()
        finally:
            conn.close()

        result = get_lineage_by_semantic("sem_lin_prov")
        assert result is not None
        assert result.thread_id == "t_lin_prov"
        assert result.turn_id == "turn_lin_prov"
        assert result.trace_id == "trace_lin_prov"

    def test_semantic_review_provenance(self):
        now = time.time()
        conn = get_conn()
        try:
            insert_semantic_review(
                conn,
                SemanticReview(
                    review_id="sr_prov",
                    semantic_id="sem_sr_prov",
                    reviewer_type="rule",
                    decision="keep",
                    thread_id="t_sr_prov",
                    turn_id="turn_sr_prov",
                    message_id="msg_sr_prov",
                    stream_id="stream_sr_prov",
                    trace_id="trace_sr_prov",
                    created_at=now,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT thread_id, turn_id, message_id, stream_id, trace_id "
                "FROM semantic_reviews WHERE review_id = 'sr_prov'"
            ).fetchone()
        finally:
            conn.close()

        assert row is not None
        assert row["thread_id"] == "t_sr_prov"
        assert row["turn_id"] == "turn_sr_prov"
        assert row["trace_id"] == "trace_sr_prov"

    def test_lineage_provenance(self):
        now = time.time()
        lin = SemanticLineage(
            lineage_id="lin_prov",
            claim_id="cl_lin_prov",
            semantic_id="sem_lin_prov",
            thread_id="t_lin_prov",
            turn_id="turn_lin_prov",
            message_id="msg_lin_prov",
            stream_id="stream_lin_prov",
            trace_id="trace_lin_prov",
            promoted_at=now,
        )
        conn = get_conn()
        try:
            insert_lineage(conn, lin)
            conn.commit()
        finally:
            conn.close()

        result = get_lineage_by_semantic("sem_lin_prov")
        assert result is not None
        assert result.thread_id == "t_lin_prov"
        assert result.turn_id == "turn_lin_prov"
        assert result.trace_id == "trace_lin_prov"

    def test_semantic_review_provenance(self):
        now = time.time()
        conn = get_conn()
        try:
            insert_semantic_review(
                conn,
                SemanticReview(
                    review_id="sr_prov",
                    semantic_id="sem_sr_prov",
                    reviewer_type="rule",
                    decision="keep",
                    thread_id="t_sr_prov",
                    turn_id="turn_sr_prov",
                    message_id="msg_sr_prov",
                    stream_id="stream_sr_prov",
                    trace_id="trace_sr_prov",
                    created_at=now,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT thread_id, turn_id, message_id, stream_id, trace_id "
                "FROM semantic_reviews WHERE review_id = 'sr_prov'"
            ).fetchone()
        finally:
            conn.close()

        assert row is not None
        assert row["thread_id"] == "t_sr_prov"
        assert row["turn_id"] == "turn_sr_prov"
        assert row["trace_id"] == "trace_sr_prov"
