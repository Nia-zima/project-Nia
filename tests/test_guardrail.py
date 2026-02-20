"""Tests for Phase E Guardrail checks + stale_turn_count tracking."""
from __future__ import annotations

import time
import uuid

import pytest

from backend.core.db import get_conn, init_schema
from backend.services.memory import semantic_store, working_store
from backend.services.memory.guardrail import (
    GuardrailResult,
    check_citation_needed,
    check_contradiction,
    check_provenance,
    check_summary_mismatch,
    check_thin_retrieval,
    check_working_stagnation,
    run_guardrails,
    _extract_fact_claims,
    _looks_strong_conclusion,
)
from backend.services.memory.models import SemanticMemory, WorkingItem
from backend.services.memory.commit_executor import CommitPlan, execute


@pytest.fixture(autouse=True)
def _setup_db():
    init_schema()
    conn = get_conn()
    try:
        conn.execute("DELETE FROM working_items")
        conn.execute("DELETE FROM semantic_memories")
        conn.execute("DELETE FROM memory_index")
        conn.execute("DELETE FROM memory_events")
    finally:
        conn.close()
    yield


def _make_semantic(
    *,
    id: str = None,
    thread_id: str = "t1",
    content: str = "test fact",
    status: str = "confirmed",
    confidence: float = 0.8,
    supersedes_id: str = None,
) -> SemanticMemory:
    now = time.time()
    return SemanticMemory(
        id=id or str(uuid.uuid4()),
        thread_id=thread_id,
        content=content,
        valid_from=now,
        created_at=now,
        updated_at=now,
        status=status,
        confidence=confidence,
        supersedes_id=supersedes_id,
    )


def _make_working(
    *,
    id: str = None,
    thread_id: str = "t1",
    item_type: str = "question",
    content: str = "pending question",
    priority: int = 3,
    stale_turn_count: int = 0,
) -> WorkingItem:
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
        stale_turn_count=stale_turn_count,
    )


def _insert_semantic(mem: SemanticMemory):
    conn = get_conn()
    try:
        semantic_store.upsert(conn, mem)
    finally:
        conn.close()


def _insert_working(item: WorkingItem):
    conn = get_conn()
    try:
        working_store.add(conn, item)
    finally:
        conn.close()


# ── Helper tests ───────────────────────────────────────────────


class TestExtractFactClaims:
    def test_detects_preference_claim(self):
        claims = _extract_fact_claims("あなたはコーヒーが好きだよね")
        assert len(claims) >= 1

    def test_detects_memory_claim(self):
        claims = _extract_fact_claims("前に言ってたよね、猫が好きって")
        assert len(claims) >= 1

    def test_no_claims_in_general_text(self):
        claims = _extract_fact_claims("今日はいい天気だね")
        assert len(claims) == 0

    def test_empty_text(self):
        assert _extract_fact_claims("") == []


class TestLooksStrongConclusion:
    def test_detects_strong_patterns(self):
        assert _looks_strong_conclusion("正解はAだ") is True
        assert _looks_strong_conclusion("絶対にそうだ") is True
        assert _looks_strong_conclusion("間違いなくそうだと思う") is True

    def test_soft_language_passes(self):
        assert _looks_strong_conclusion("たぶんそうかもしれない") is False
        assert _looks_strong_conclusion("") is False


# ── G1: Provenance ─────────────────────────────────────────────


class TestG1Provenance:
    def test_no_alert_with_backing(self):
        """Claim has matching semantic memory → no alert."""
        _insert_semantic(_make_semantic(content="ユーザーはコーヒーが好き"))
        result = check_provenance("あなたはコーヒーが好きだよね", "t1")
        assert result is None

    def test_hold_without_backing(self):
        """Claim about user with no semantic backing → HOLD."""
        result = check_provenance("あなたは猫が好きだよね", "t1")
        assert result is not None
        assert result.severity == "hold"
        assert result.condition == "G1_no_provenance"

    def test_no_alert_for_general_text(self):
        """General text without user-specific claims → no alert."""
        result = check_provenance("今日は天気がいいね", "t1")
        assert result is None

    def test_no_alert_for_empty(self):
        result = check_provenance("", "t1")
        assert result is None


# ── G2: Contradiction ──────────────────────────────────────────


class TestG2Contradiction:
    def test_hold_on_active_supersedes(self):
        """New record supersedes old, but old is still active → HOLD."""
        old = _make_semantic(id="old-1", content="user likes A")
        new = _make_semantic(id="new-1", content="user likes B", supersedes_id="old-1")
        _insert_semantic(old)
        _insert_semantic(new)

        result = check_contradiction("t1")
        assert result is not None
        assert result.severity == "hold"
        assert result.condition == "G2_contradiction"

    def test_no_alert_when_superseded_is_revoked(self):
        """Old record properly revoked → no alert."""
        old = _make_semantic(id="old-2", content="user likes A", status="revoked")
        new = _make_semantic(id="new-2", content="user likes B", supersedes_id="old-2")
        _insert_semantic(old)
        _insert_semantic(new)

        result = check_contradiction("t1")
        assert result is None

    def test_no_alert_when_no_supersedes(self):
        _insert_semantic(_make_semantic(content="fact 1"))
        _insert_semantic(_make_semantic(content="fact 2"))
        result = check_contradiction("t1")
        assert result is None


# ── G3: Summary mismatch ──────────────────────────────────────


class TestG3SummaryMismatch:
    def test_log_on_negation_mismatch(self):
        sections = {"pinned": "- ユーザーは猫が好き", "short_term": "- 猫が嫌いらしい"}
        result = check_summary_mismatch(sections)
        assert result is not None
        assert result.severity == "log"

    def test_no_alert_when_consistent(self):
        sections = {"pinned": "- ユーザーは猫が好き", "short_term": "- 猫の話をした"}
        result = check_summary_mismatch(sections)
        assert result is None

    def test_no_alert_when_empty(self):
        result = check_summary_mismatch({"pinned": "", "short_term": ""})
        assert result is None


# ── G4: Working stagnation ─────────────────────────────────────


class TestG4Stagnation:
    def test_log_when_stagnant(self):
        _insert_working(_make_working(content="stuck question", stale_turn_count=5))
        result = check_working_stagnation("t1")
        assert result is not None
        assert result.severity == "log"
        assert result.condition == "G4_stagnation"

    def test_no_alert_when_fresh(self):
        _insert_working(_make_working(content="fresh question", stale_turn_count=1))
        result = check_working_stagnation("t1")
        assert result is None

    def test_no_alert_when_empty(self):
        result = check_working_stagnation("t1")
        assert result is None


# ── G5: Citation needed ────────────────────────────────────────


class TestG5CitationNeeded:
    def test_log_when_no_long_term(self):
        sections = {"long_term": ""}
        result = check_citation_needed("あなたは猫が好きだよね", sections)
        assert result is not None
        assert result.severity == "log"

    def test_no_alert_with_long_term(self):
        sections = {"long_term": "- confirmed: user likes cats and other things"}
        result = check_citation_needed("あなたは猫が好きだよね", sections)
        assert result is None

    def test_no_alert_for_general_text(self):
        sections = {"long_term": ""}
        result = check_citation_needed("今日はいい天気だね", sections)
        assert result is None


# ── G6: Thin retrieval ─────────────────────────────────────────


class TestG6ThinRetrieval:
    def test_hold_on_low_coverage_and_assertion(self):
        metrics = {"context_coverage": 0.2}
        result = check_thin_retrieval("正解はAだ", metrics)
        assert result is not None
        assert result.severity == "hold"
        assert result.condition == "G6_thin_retrieval"

    def test_no_alert_with_high_coverage(self):
        metrics = {"context_coverage": 0.8}
        result = check_thin_retrieval("正解はAだ", metrics)
        assert result is None

    def test_no_alert_with_soft_language(self):
        metrics = {"context_coverage": 0.2}
        result = check_thin_retrieval("たぶんそうかもしれない", metrics)
        assert result is None

    def test_no_alert_empty(self):
        result = check_thin_retrieval("", {"context_coverage": 0.1})
        assert result is None


# ── run_guardrails (integration) ───────────────────────────────


class TestRunGuardrails:
    def test_returns_empty_when_disabled(self, monkeypatch):
        monkeypatch.setattr("backend.services.memory.guardrail.settings.GUARDRAIL_V2_ENABLED", False)
        result = run_guardrails(
            say_candidate="あなたは猫が好きだよね",
            thread_id="t1",
            state={},
        )
        assert result.alerts == []
        assert result.hold_required is False

    def test_aggregates_multiple_alerts(self, monkeypatch):
        monkeypatch.setattr("backend.services.memory.guardrail.settings.GUARDRAIL_V2_ENABLED", True)
        # G1 will fire (no semantic backing) + G6 will fire (low coverage + strong assertion)
        result = run_guardrails(
            say_candidate="あなたは猫が好きだよね。正解はこれだ",
            thread_id="t1",
            state={"confidence_metrics": {"context_coverage": 0.1}},
        )
        assert result.hold_required is True
        conditions = {a.condition for a in result.alerts}
        assert "G1_no_provenance" in conditions

    def test_hold_reason_codes(self, monkeypatch):
        monkeypatch.setattr("backend.services.memory.guardrail.settings.GUARDRAIL_V2_ENABLED", True)
        result = run_guardrails(
            say_candidate="あなたは猫が好きだよね",
            thread_id="t1",
            state={},
        )
        assert "guardrail_no_provenance" in result.reason_codes

    def test_log_only_does_not_hold(self, monkeypatch):
        monkeypatch.setattr("backend.services.memory.guardrail.settings.GUARDRAIL_V2_ENABLED", True)
        # Only G4 can fire with stagnant items (LOG severity)
        _insert_working(_make_working(content="stuck", stale_turn_count=10))
        result = run_guardrails(
            say_candidate="今日はいい天気だね",
            thread_id="t1",
            state={"confidence_metrics": {"context_coverage": 0.9}},
        )
        assert result.hold_required is False
        conditions = {a.condition for a in result.alerts}
        assert "G4_stagnation" in conditions


# ── Stale turn count tracking ──────────────────────────────────


class TestStaleTurnCount:
    def test_increment_stale_counts(self):
        item = _make_working(stale_turn_count=0)
        _insert_working(item)

        conn = get_conn()
        try:
            working_store.increment_stale_counts(conn, "t1")
        finally:
            conn.close()

        result = working_store.get_by_id(item.id)
        assert result.stale_turn_count == 1

    def test_reset_stale_count(self):
        item = _make_working(stale_turn_count=5)
        _insert_working(item)

        conn = get_conn()
        try:
            working_store.reset_stale_count(conn, item.id)
        finally:
            conn.close()

        result = working_store.get_by_id(item.id)
        assert result.stale_turn_count == 0

    def test_list_stagnant(self):
        fresh = _make_working(content="fresh", stale_turn_count=1)
        stale = _make_working(content="stale", stale_turn_count=5)
        _insert_working(fresh)
        _insert_working(stale)

        results = working_store.list_stagnant("t1", threshold=3)
        assert len(results) == 1
        assert results[0].content == "stale"

    def test_commit_increments_stale(self):
        item = _make_working(stale_turn_count=0)
        conn = get_conn()
        try:
            working_store.add(conn, item)
        finally:
            conn.close()

        plan = CommitPlan(
            episodic=[{"event_type": "episode", "payload": {"text": "hi"}}]
        )
        result = execute(plan, thread_id="t1", turn_id="turn1")
        assert result.success is True

        updated = working_store.get_by_id(item.id)
        assert updated.stale_turn_count == 1

    def test_closed_items_not_incremented(self):
        item = _make_working(stale_turn_count=0)
        item.status = "closed"
        item.close_reason = "answered"
        _insert_working(item)

        conn = get_conn()
        try:
            working_store.increment_stale_counts(conn, "t1")
        finally:
            conn.close()

        result = working_store.get_by_id(item.id)
        assert result.stale_turn_count == 0
