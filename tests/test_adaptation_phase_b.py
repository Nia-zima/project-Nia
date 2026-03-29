"""Tests for Phase B: signal detection + proposal generation.

Covers:
- FailureSignalSummary / SuccessSignalSummary population from DB
- Proposal generation thresholds
- Family repetition detection
- Proposal dedupe via proposal_key
- End-to-end: signals → proposals → save
"""
from __future__ import annotations

import sqlite3
import time

import pytest

from backend.core.db_migrations import (
    ensure_conversation_adaptation_schema,
    ensure_conversation_skeleton_schema,
    ensure_expression_observations_schema,
)
from backend.services.adaptation.proposal_generator import (
    _CORRECTION_STRONG_MIN,
    _FAMILY_REPEAT_RATE,
    _HIGH_HEDGE_RATE,
    _MIN_TURNS_FOR_PROPOSAL,
    _SUCCESS_MIN_TURNS,
    generate_proposals,
)
from backend.services.adaptation.signal_detector import (
    FailureSignalSummary,
    SuccessSignalSummary,
    detect_failure_signals,
    detect_family_repetition,
    detect_success_signals,
)
from backend.services.adaptation.schema import (
    ConversationAdaptationProposal,
    EffectPayload,
    HistoryBias,
    TracePayload,
)
from backend.services.adaptation.writer import generate_id, save_proposal


# ── Fixtures ────────────────────────────────────────────────────────

@pytest.fixture()
def phase_b_db(monkeypatch):
    """In-memory SQLite with all required tables for Phase B testing."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")

    # Create required tables
    ensure_expression_observations_schema(conn)
    ensure_conversation_skeleton_schema(conn)
    ensure_conversation_adaptation_schema(conn)

    # niacore_experience (minimal schema matching production)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS niacore_experience (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            user_correction BOOLEAN DEFAULT 0,
            created_at REAL NOT NULL
        )
    """)

    # memory_events (used by family repetition detection)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memory_events (
            event_id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            turn_id TEXT,
            message_id TEXT,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            schema_version INTEGER NOT NULL DEFAULT 1
        )
    """)

    from contextlib import contextmanager

    @contextmanager
    def _mock_conn():
        yield conn

    import backend.services.adaptation.signal_detector as _sd
    import backend.services.adaptation.writer as _wr
    monkeypatch.setattr(_sd, "managed_conn", _mock_conn)
    monkeypatch.setattr(_wr, "managed_conn", _mock_conn)

    yield conn
    conn.close()


def _insert_expression_rows(conn, n, *, thread_id="default_thread", hedge_ratio=0.1, event_kind="spoken", user_correction=0):
    now = time.time()
    for i in range(n):
        conn.execute(
            """INSERT INTO expression_observations
               (id, turn_id, thread_id, timestamp, hedge_ratio, assertion_ratio,
                event_kind, user_correction, retrieval_hit, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (generate_id(), f"turn_{i}", thread_id, now - i * 60,
             hedge_ratio, 0.3, event_kind, user_correction, 0, now - i * 60),
        )


def _insert_skeleton_rows(conn, n, *, session_id="default_thread", focus="user_goal", response_intent="receive"):
    now = time.time()
    for i in range(n):
        conn.execute(
            """INSERT INTO conversation_skeletons
               (id, turn_id, session_id, focus, response_intent, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (generate_id(), f"turn_{i}", session_id, focus, response_intent, now - i * 60),
        )


def _insert_correction_rows(conn, n, *, thread_id="default_thread", level="strong"):
    now = time.time()
    for i in range(n):
        # user_correction=1 for strong, 0 for weak/none
        user_corr = 1 if level == "strong" else 0
        conn.execute(
            """INSERT INTO niacore_experience
               (id, session_id, user_correction, created_at)
               VALUES (?, ?, ?, ?)""",
            (generate_id(), thread_id, user_corr, now - i * 60),
        )


def _insert_episodic_rows(conn, texts, *, thread_id="default_thread"):
    import json
    now = time.time()
    for i, text in enumerate(texts):
        payload = json.dumps({"ai_response": text, "user_text": "test"})
        conn.execute(
            """INSERT INTO memory_events
               (event_id, thread_id, event_type, payload_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (generate_id(), thread_id, "conversation_turn", payload, now - i * 60),
        )


def _make_proposal_for_save(
    *,
    last_seen_at: str = "2026-03-24T10:00:00+00:00",
    first_seen_at: str | None = None,
    **overrides,
) -> ConversationAdaptationProposal:
    """Create a minimal proposal for writer-level watermark tests."""
    now = "2026-03-24T09:00:00+00:00"
    defaults = dict(
        proposal_id=generate_id(),
        proposal_kind="failure_policy",
        trigger_type="directness",
        target_layer="history_selection",
        condition_json={"expression_state": {"avg_hedge_ratio": 0.7, "high_hedge_rate": 1.0}},
        trace_json=TracePayload(
            axes={"expressive_diversity": 0.2},
            observed_patterns=["hedge_dense"],
        ),
        effect_json=EffectPayload(
            history_bias=HistoryBias(avoid_trace_match=["hedge_dense"]),
        ),
        first_seen_at=first_seen_at or now,
        last_seen_at=last_seen_at,
        created_at=now,
        updated_at=now,
        created_by="sleep_failure_to_policy_v0",
    )
    defaults.update(overrides)
    return ConversationAdaptationProposal(**defaults)


# ── Signal Detector Tests ──────────────────────────────────────────

class TestFailureSignalDetector:
    def test_empty_db_returns_zero_summary(self, phase_b_db):
        summary = detect_failure_signals()
        assert summary.total_turns == 0
        assert summary.correction_strong_count == 0

    def test_counts_expression_failures(self, phase_b_db):
        _insert_expression_rows(phase_b_db, 10, hedge_ratio=0.6)
        summary = detect_failure_signals()
        assert summary.total_turns == 10
        assert summary.high_hedge_turn_count == 10
        assert summary.avg_hedge_ratio == pytest.approx(0.6, abs=0.01)

    def test_counts_hold_and_wait(self, phase_b_db):
        _insert_expression_rows(phase_b_db, 3, event_kind="hold")
        _insert_expression_rows(phase_b_db, 2, event_kind="wait")
        _insert_expression_rows(phase_b_db, 5, event_kind="spoken")
        summary = detect_failure_signals()
        assert summary.hold_count == 3
        assert summary.wait_count == 2

    def test_counts_corrections(self, phase_b_db):
        _insert_expression_rows(phase_b_db, 5)  # need expression rows for total_turns
        _insert_correction_rows(phase_b_db, 3, level="strong")
        _insert_correction_rows(phase_b_db, 1, level="weak")  # weak = user_correction=0, not counted
        summary = detect_failure_signals()
        assert summary.correction_strong_count == 3
        # weak corrections are user_correction=0 in niacore_experience,
        # so they are not counted. strong/weak distinction requires
        # somatic_feedback.detect_correction_level() which is not persisted per-turn.
        assert summary.correction_weak_count == 0

    def test_counts_skeleton_failures(self, phase_b_db):
        _insert_expression_rows(phase_b_db, 5)
        _insert_skeleton_rows(phase_b_db, 2, focus="contradiction")
        _insert_skeleton_rows(phase_b_db, 1, response_intent="hold")
        summary = detect_failure_signals()
        assert summary.contradiction_focus_count == 2
        assert summary.hold_intent_count == 1


class TestSuccessSignalDetector:
    def test_empty_db_returns_zero_summary(self, phase_b_db):
        summary = detect_success_signals()
        assert summary.total_turns == 0

    def test_counts_confident_turns(self, phase_b_db):
        # hedge_ratio < 0.2 and assertion_ratio > 0.3
        _insert_expression_rows(phase_b_db, 10, hedge_ratio=0.1)
        summary = detect_success_signals()
        assert summary.total_turns == 10
        assert summary.low_hedge_turn_count == 10

    def test_counts_skeleton_successes(self, phase_b_db):
        _insert_expression_rows(phase_b_db, 5)
        _insert_skeleton_rows(phase_b_db, 2, focus="returning_theme")
        _insert_skeleton_rows(phase_b_db, 1, response_intent="offer_fragile_self_observation")
        summary = detect_success_signals()
        assert summary.returning_theme_count == 2
        assert summary.fragile_observation_count == 1


class TestFamilyRepetition:
    def test_empty_returns_empty(self, phase_b_db):
        counts, total, _ts = detect_family_repetition()
        assert counts == {}
        assert total == 0

    def test_detects_quiet_atmosphere(self, phase_b_db):
        _insert_episodic_rows(phase_b_db, [
            "静かな時間の中で何かを感じる",
            "穏やかな気持ち",
            "落ち着いた雰囲気",
            "今日は天気がいい",
        ])
        counts, total, _ts = detect_family_repetition()
        assert "quiet_atmosphere" in counts
        assert counts["quiet_atmosphere"] >= 3
        assert total == 4

    def test_no_family_in_normal_text(self, phase_b_db):
        _insert_episodic_rows(phase_b_db, [
            "プログラミングについて話しましょう",
            "Pythonのテストの書き方",
            "FastAPIのルーティング",
        ])
        counts, total, _ts = detect_family_repetition()
        assert sum(counts.values()) == 0
        assert total == 3


# ── Proposal Generator Tests ───────────────────────────────────────

class TestProposalGenerator:
    def test_no_proposals_below_min_turns(self, phase_b_db):
        _insert_expression_rows(phase_b_db, 2)
        proposals = generate_proposals()
        assert len(proposals) == 0

    def test_family_repetition_generates_proposal(self, phase_b_db):
        n = max(_MIN_TURNS_FOR_PROPOSAL, 10)
        _insert_expression_rows(phase_b_db, n)
        # Insert enough family-matching episodic rows
        texts = ["静かな時間の中で"] * (n // 2) + ["普通の会話"] * (n // 2)
        _insert_episodic_rows(phase_b_db, texts)

        proposals = generate_proposals()
        family_proposals = [p for p in proposals if p.trigger_type == "repetition"]
        assert len(family_proposals) >= 1
        assert family_proposals[0].proposal_kind == "failure_policy"
        assert "quiet_atmosphere" in family_proposals[0].effect_json.history_bias.downrank_families

    def test_correction_generates_proposal(self, phase_b_db):
        _insert_expression_rows(phase_b_db, 10)
        _insert_correction_rows(phase_b_db, _CORRECTION_STRONG_MIN + 1, level="strong")

        proposals = generate_proposals()
        correction_proposals = [p for p in proposals if p.trigger_type == "correction"]
        assert len(correction_proposals) == 1
        assert correction_proposals[0].proposal_kind == "failure_policy"

    def test_hedge_generates_proposal(self, phase_b_db):
        _insert_expression_rows(phase_b_db, 10, hedge_ratio=0.7)

        proposals = generate_proposals()
        hedge_proposals = [p for p in proposals if p.trigger_type == "directness"]
        assert len(hedge_proposals) == 1

    def test_success_diversity_generates_proposal(self, phase_b_db):
        # Low hedge + high assertion = confident expression
        _insert_expression_rows(phase_b_db, _SUCCESS_MIN_TURNS + 5, hedge_ratio=0.1)

        proposals = generate_proposals()
        success_proposals = [p for p in proposals if p.proposal_kind == "success_preference"]
        assert len(success_proposals) >= 1

    def test_success_relational_generates_proposal(self, phase_b_db):
        _insert_expression_rows(phase_b_db, _SUCCESS_MIN_TURNS + 5, hedge_ratio=0.1)
        # Need enough skeleton rows to meet _SUCCESS_MIN_TURNS threshold
        _insert_skeleton_rows(phase_b_db, _SUCCESS_MIN_TURNS - 3)
        _insert_skeleton_rows(phase_b_db, 3, focus="returning_theme")

        proposals = generate_proposals()
        relational = [
            p for p in proposals
            if p.proposal_kind == "success_preference"
            and any("relational" in pat for pat in p.trace_json.observed_patterns)
        ]
        assert len(relational) == 1

    def test_proposals_have_valid_schema(self, phase_b_db):
        _insert_expression_rows(phase_b_db, 10, hedge_ratio=0.7)
        _insert_correction_rows(phase_b_db, 3, level="strong")
        texts = ["静かな時間の中で"] * 5 + ["会話"] * 5
        _insert_episodic_rows(phase_b_db, texts)

        proposals = generate_proposals()
        for p in proposals:
            # All proposals should pass Pydantic validation (already validated by construction)
            assert p.proposal_id
            assert p.proposal_key
            assert p.proposal_kind in ("failure_policy", "success_preference")
            assert p.trigger_type
            assert p.target_layer == "history_selection"
            assert p.created_by.startswith("sleep_")

    def test_proposals_save_to_db(self, phase_b_db):
        _insert_expression_rows(phase_b_db, 10, hedge_ratio=0.7)

        proposals = generate_proposals()
        assert len(proposals) > 0

        for p in proposals:
            result = save_proposal(p)
            assert result is not None

        row = phase_b_db.execute(
            "SELECT COUNT(*) FROM conversation_adaptation_proposals"
        ).fetchone()
        assert row[0] == len(proposals)

    def test_dedupe_on_second_run(self, phase_b_db):
        """Same signals → same proposal_key → merge, not duplicate."""
        _insert_expression_rows(phase_b_db, 10, hedge_ratio=0.7)

        proposals_1 = generate_proposals()
        for p in proposals_1:
            save_proposal(p)

        proposals_2 = generate_proposals()
        for p in proposals_2:
            save_proposal(p)

        row = phase_b_db.execute(
            "SELECT COUNT(*) FROM conversation_adaptation_proposals"
        ).fetchone()
        # Should be same count as first run due to dedupe
        assert row[0] == len(proposals_1)

    def test_same_watermark_does_not_inflate_support(self, phase_b_db):
        """save_proposal with identical last_seen_at must not increment support."""
        p1 = _make_proposal_for_save(last_seen_at="2026-03-24T10:00:00+00:00")
        save_proposal(p1)

        # Same last_seen_at → no support increment
        p2 = _make_proposal_for_save(last_seen_at="2026-03-24T10:00:00+00:00")
        save_proposal(p2)

        row = phase_b_db.execute(
            "SELECT support_count FROM conversation_adaptation_proposals LIMIT 1"
        ).fetchone()
        assert row["support_count"] == 0

    def test_advanced_watermark_increments_support(self, phase_b_db):
        """save_proposal with later last_seen_at must increment support."""
        p1 = _make_proposal_for_save(last_seen_at="2026-03-24T10:00:00+00:00")
        save_proposal(p1)

        # Later last_seen_at → support + 1
        p2 = _make_proposal_for_save(last_seen_at="2026-03-24T11:00:00+00:00")
        save_proposal(p2)

        row = phase_b_db.execute(
            "SELECT support_count FROM conversation_adaptation_proposals LIMIT 1"
        ).fetchone()
        assert row["support_count"] == 1

    def test_default_and_meeting_produce_separate_proposals(self, phase_b_db):
        """default_thread and nero_meeting should not merge into the same proposal."""
        _insert_expression_rows(phase_b_db, 10, hedge_ratio=0.7, thread_id="default_thread")
        _insert_expression_rows(phase_b_db, 10, hedge_ratio=0.7, thread_id="nero_meeting_001")

        proposals_default = generate_proposals("default_thread")
        proposals_meeting = generate_proposals("nero_meeting_001")

        for p in proposals_default + proposals_meeting:
            save_proposal(p)

        row = phase_b_db.execute(
            "SELECT COUNT(*) FROM conversation_adaptation_proposals"
        ).fetchone()
        # Should have separate rows for default and meeting
        assert row[0] >= 2

        # Verify thread_mode is set correctly
        rows = phase_b_db.execute(
            "SELECT DISTINCT thread_mode, conversation_role FROM conversation_adaptation_proposals"
        ).fetchall()
        modes = {r["thread_mode"] for r in rows}
        assert "default_thread" in modes
        assert "meeting" in modes
