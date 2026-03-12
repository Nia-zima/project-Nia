"""Evidence Aggregator tests."""
import time
import uuid

import pytest

from backend.core.db import get_conn, init_schema
from backend.services.memory.evidence_aggregator import (
    EvidenceSignals,
    _match_candidate,
    aggregate_evidence,
)
from backend.services.memory.governance_repository import (
    count_evidence_by_candidate,
    insert_candidate,
    insert_evidence,
    list_active_candidates,
    list_evidence_by_candidate,
    update_candidate_status,
)
from backend.services.memory.models import MemoryEvidence, RawPromotionCandidate


@pytest.fixture(autouse=True)
def tmp_db():
    """Ensure schema exists; clean governance tables between tests."""
    conn = get_conn()
    try:
        for table in (
            "memory_evidence",
            "raw_promotion_candidates",
        ):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.commit()
    finally:
        conn.close()
    init_schema()
    yield


# ── Helpers ──────────────────────────────────────────────


def _make_candidate(
    kind: str = "contradiction",
    focus: str | None = "contradiction",
    status: str = "pending",
    source_ref: str | None = None,
) -> RawPromotionCandidate:
    now = time.time()
    return RawPromotionCandidate(
        candidate_id=uuid.uuid4().hex,
        candidate_kind_rough=kind,
        source_type="turn_harvester",
        source_ref=source_ref or "user: test | ai: test",
        topic_key=None,
        focus=focus,
        response_intent=None,
        question_intent=None,
        unresolved_ref=None,
        owner_agent="nia",
        memory_domain="default",
        status=status,
        thread_id="test_thread",
        turn_id="test_turn",
        created_at=now,
        updated_at=now,
    )


# ── _match_candidate tests ──────────────────────────────


class TestMatchCandidate:
    def test_e1_skeleton_focus_match(self):
        """E1: Same skeleton focus → skeleton evidence."""
        candidate = _make_candidate(focus="emotional_state")
        signals = EvidenceSignals(skeleton_focus="emotional_state")
        result = _match_candidate(candidate, signals)
        assert result is not None
        assert result[0] == "skeleton"
        assert result[1] == 0.3

    def test_e1_no_match_different_focus(self):
        candidate = _make_candidate(focus="emotional_state")
        signals = EvidenceSignals(skeleton_focus="user_goal")
        result = _match_candidate(candidate, signals)
        # E1 doesn't match, check other rules
        assert result is None or result[0] != "skeleton"

    def test_e2_repetition_reinforcement(self):
        """E2: Same kind triggered again."""
        candidate = _make_candidate(kind="surprise", focus=None)
        signals = EvidenceSignals(triggered_kinds=["surprise"])
        result = _match_candidate(candidate, signals)
        assert result is not None
        assert result[0] == "repetition"
        assert result[1] == 0.5

    def test_e2_no_match_different_kind(self):
        candidate = _make_candidate(kind="surprise", focus=None)
        signals = EvidenceSignals(triggered_kinds=["contradiction"])
        result = _match_candidate(candidate, signals)
        assert result is None

    def test_e3_disabled(self):
        """E3: retrieval reinforcement is disabled until candidate-specific matching exists."""
        candidate = _make_candidate(focus=None, source_ref="user: coffee | ai: yes")
        signals = EvidenceSignals(retrieval_top_similarity=0.6)
        result = _match_candidate(candidate, signals)
        # E3 should NOT fire — no candidate-specific matching yet
        assert result is None or result[0] != "retrieval"

    def test_e4_correction_free(self):
        """E4: Correction-free turn on accumulating contradiction candidate."""
        candidate = _make_candidate(kind="contradiction", focus=None, status="accumulating")
        signals = EvidenceSignals(correction_level="none")
        result = _match_candidate(candidate, signals)
        assert result is not None
        assert result[0] == "correction_free"

    def test_e4_only_on_accumulating(self):
        """E4: correction_free only fires on accumulating candidates."""
        candidate = _make_candidate(kind="contradiction", focus=None, status="pending")
        signals = EvidenceSignals(correction_level="none")
        result = _match_candidate(candidate, signals)
        assert result is None

    def test_e1_priority_over_e2(self):
        """E1 wins over E2 when both match."""
        candidate = _make_candidate(kind="contradiction", focus="contradiction")
        signals = EvidenceSignals(
            skeleton_focus="contradiction",
            triggered_kinds=["contradiction"],
        )
        result = _match_candidate(candidate, signals)
        assert result is not None
        assert result[0] == "skeleton"  # E1 fires first

    def test_no_match_on_empty_signals(self):
        candidate = _make_candidate()
        signals = EvidenceSignals()
        result = _match_candidate(candidate, signals)
        assert result is None


# ── Repository extension tests ───────────────────────────


class TestRepositoryExtensions:
    def test_insert_evidence_with_candidate_id(self, tmp_db):
        """Evidence can be inserted with candidate_id and no claim_id."""
        from backend.core.db import managed_conn
        now = time.time()

        with managed_conn() as conn:
            candidate = _make_candidate()
            insert_candidate(conn, candidate)

            evidence = MemoryEvidence(
                evidence_id=uuid.uuid4().hex,
                candidate_id=candidate.candidate_id,
                claim_id=None,
                source_type="skeleton",
                source_ref="turn:test",
                evidence_date="2026-03-12",
                reliability=0.3,
                created_at=now,
            )
            insert_evidence(conn, evidence)

        result = list_evidence_by_candidate(candidate.candidate_id)
        assert len(result) == 1
        assert result[0].candidate_id == candidate.candidate_id
        assert result[0].claim_id is None

    def test_count_evidence_by_candidate(self, tmp_db):
        from backend.core.db import managed_conn
        now = time.time()

        candidate = _make_candidate()
        with managed_conn() as conn:
            insert_candidate(conn, candidate)
            for i in range(3):
                insert_evidence(conn, MemoryEvidence(
                    evidence_id=uuid.uuid4().hex,
                    candidate_id=candidate.candidate_id,
                    source_type="skeleton",
                    created_at=now + i,
                ))
            count = count_evidence_by_candidate(conn, candidate.candidate_id)
        assert count == 3

    def test_update_candidate_status(self, tmp_db):
        from backend.core.db import managed_conn

        candidate = _make_candidate(status="pending")
        with managed_conn() as conn:
            insert_candidate(conn, candidate)
            update_candidate_status(conn, candidate.candidate_id, "accumulating")

        from backend.services.memory.governance_repository import get_candidate
        updated = get_candidate(candidate.candidate_id)
        assert updated is not None
        assert updated.status == "accumulating"

    def test_list_active_candidates(self, tmp_db):
        from backend.core.db import managed_conn

        c1 = _make_candidate(status="pending")
        c2 = _make_candidate(status="accumulating")
        c3 = _make_candidate(status="ready_for_normalization")  # not active
        with managed_conn() as conn:
            insert_candidate(conn, c1)
            insert_candidate(conn, c2)
            insert_candidate(conn, c3)

        active = list_active_candidates()
        active_ids = {c.candidate_id for c in active}
        assert c1.candidate_id in active_ids
        assert c2.candidate_id in active_ids
        assert c3.candidate_id not in active_ids


# ── Integration: aggregate_evidence ──────────────────────


class TestAggregateEvidence:
    def test_skeleton_match_creates_evidence(self, tmp_db):
        """Matching skeleton focus creates evidence and transitions to accumulating."""
        from backend.core.db import managed_conn

        candidate = _make_candidate(kind="emotional_pattern", focus="emotional_state")
        with managed_conn() as conn:
            insert_candidate(conn, candidate)

        signals = EvidenceSignals(
            skeleton_focus="emotional_state",
            turn_id="turn_001",
            thread_id="test_thread",
        )
        inserted = aggregate_evidence(signals)
        assert inserted == 1

        evidence = list_evidence_by_candidate(candidate.candidate_id)
        assert len(evidence) == 1
        assert evidence[0].source_type == "skeleton"
        assert evidence[0].candidate_id == candidate.candidate_id

        # Status should transition to accumulating
        from backend.services.memory.governance_repository import get_candidate
        updated = get_candidate(candidate.candidate_id)
        assert updated.status == "accumulating"

    def test_no_match_creates_no_evidence(self, tmp_db):
        from backend.core.db import managed_conn

        candidate = _make_candidate(kind="surprise", focus=None)
        with managed_conn() as conn:
            insert_candidate(conn, candidate)

        signals = EvidenceSignals(
            skeleton_focus="user_goal",
            turn_id="turn_001",
        )
        inserted = aggregate_evidence(signals)
        assert inserted == 0

    def test_ready_for_normalization_transition(self, tmp_db):
        """After enough evidence, candidate transitions to ready_for_normalization."""
        from backend.core.db import managed_conn

        candidate = _make_candidate(kind="emotional_pattern", focus="emotional_state")
        with managed_conn() as conn:
            insert_candidate(conn, candidate)

        # Accumulate 3 turns of matching evidence
        for i in range(3):
            signals = EvidenceSignals(
                skeleton_focus="emotional_state",
                turn_id=f"turn_{i:03d}",
                thread_id="test_thread",
            )
            aggregate_evidence(signals)

        from backend.services.memory.governance_repository import get_candidate
        updated = get_candidate(candidate.candidate_id)
        assert updated.status == "ready_for_normalization"

        evidence = list_evidence_by_candidate(candidate.candidate_id)
        assert len(evidence) == 3

    def test_terminal_candidates_not_matched(self, tmp_db):
        """ready_for_normalization candidates are not in active pool."""
        from backend.core.db import managed_conn

        candidate = _make_candidate(
            kind="emotional_pattern",
            focus="emotional_state",
            status="ready_for_normalization",
        )
        with managed_conn() as conn:
            insert_candidate(conn, candidate)

        signals = EvidenceSignals(
            skeleton_focus="emotional_state",
            turn_id="turn_001",
        )
        inserted = aggregate_evidence(signals)
        assert inserted == 0

    def test_never_raises(self, tmp_db, monkeypatch):
        """aggregate_evidence never raises even on DB errors."""
        import backend.services.memory.evidence_aggregator as mod
        monkeypatch.setattr(mod, "list_active_candidates", lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))
        result = aggregate_evidence(EvidenceSignals())
        assert result == 0
