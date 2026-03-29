"""Tests for Phase C: history_bias → _select_diverse_history integration.

Covers:
- MergedHistoryBias reading from DB
- history_bias effect on scoring (downrank / uprank)
- history_bias cap_same_family tightening
- Gate-awareness (off → empty bias)
- End-to-end: proposal → reader → scorer
"""
from __future__ import annotations

import json
import sqlite3
import time

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from backend.core.db_migrations import ensure_conversation_adaptation_schema
from backend.services.adaptation.reader import (
    MergedHistoryBias,
    _EMPTY_BIAS,
    get_merged_history_bias,
)
from backend.services.adaptation.writer import generate_id


# ── Fixtures ────────────────────────────────────────────────────────

@pytest.fixture()
def reader_db(monkeypatch):
    """In-memory SQLite with adaptation schema for reader tests."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_conversation_adaptation_schema(conn)

    from contextlib import contextmanager

    @contextmanager
    def _mock():
        yield conn

    import backend.services.adaptation.reader as _rd
    monkeypatch.setattr(_rd, "managed_conn", _mock)
    monkeypatch.setattr(_rd, "settings", type("S", (), {"ADAPTATION_RECORD_ENABLED": True})())

    yield conn
    conn.close()


def _insert_proposal(conn, *, effect_json, thread_mode=None, status="proposed"):
    """Insert a minimal proposal for reader tests."""
    now = "2026-03-24T12:00:00+00:00"
    key = generate_id()
    conn.execute(
        """INSERT INTO conversation_adaptation_proposals
           (proposal_id, proposal_key, proposal_kind, status, scope, priority,
            trigger_type, target_layer, thread_mode,
            condition_json, trace_json, effect_json,
            first_seen_at, last_seen_at, created_at, updated_at, created_by)
           VALUES (?, ?, ?, ?, ?, ?,
                   ?, ?, ?,
                   ?, ?, ?,
                   ?, ?, ?, ?, ?)""",
        (
            generate_id(), key, "failure_policy", status, "history_only", 0,
            "repetition", "history_selection", thread_mode,
            "{}", "{}",
            json.dumps(effect_json, ensure_ascii=False),
            now, now, now, now, "test",
        ),
    )


# ── Reader Tests ────────────────────────────────────────────────────

class TestReader:
    def test_empty_db_returns_empty(self, reader_db):
        bias = get_merged_history_bias()
        assert bias.is_empty

    def test_reads_downrank_families(self, reader_db):
        _insert_proposal(reader_db, effect_json={
            "history_bias": {"downrank_families": ["quiet_atmosphere"]},
        })
        bias = get_merged_history_bias()
        assert "quiet_atmosphere" in bias.downrank_families

    def test_reads_uprank_families(self, reader_db):
        _insert_proposal(reader_db, effect_json={
            "history_bias": {"uprank_families": ["fragile_open"]},
        })
        bias = get_merged_history_bias()
        assert "fragile_open" in bias.uprank_families

    def test_reads_cap_same_family(self, reader_db):
        _insert_proposal(reader_db, effect_json={
            "history_bias": {"cap_same_family": 1},
        })
        bias = get_merged_history_bias()
        assert bias.cap_same_family == 1

    def test_merges_multiple_proposals(self, reader_db):
        _insert_proposal(reader_db, effect_json={
            "history_bias": {
                "downrank_families": ["quiet_atmosphere"],
                "cap_same_family": 2,
            },
        })
        _insert_proposal(reader_db, effect_json={
            "history_bias": {
                "downrank_families": ["heart_moves"],
                "cap_same_family": 1,
            },
        })
        bias = get_merged_history_bias()
        assert "quiet_atmosphere" in bias.downrank_families
        assert "heart_moves" in bias.downrank_families
        # Strictest cap wins
        assert bias.cap_same_family == 1

    def test_filters_by_thread_mode(self, reader_db):
        _insert_proposal(reader_db, effect_json={
            "history_bias": {"downrank_families": ["quiet_atmosphere"]},
        }, thread_mode="default_thread")
        _insert_proposal(reader_db, effect_json={
            "history_bias": {"downrank_families": ["heart_moves"]},
        }, thread_mode="meeting")

        bias_default = get_merged_history_bias("default_thread")
        assert "quiet_atmosphere" in bias_default.downrank_families
        # meeting-only proposal should not appear for default_thread
        # (NULL thread_mode proposals apply to all, but meeting-specific ones don't)

    def test_excludes_non_history_target(self, reader_db):
        """Only target_layer='history_selection' proposals are read."""
        now = "2026-03-24T12:00:00+00:00"
        conn = reader_db
        conn.execute(
            """INSERT INTO conversation_adaptation_proposals
               (proposal_id, proposal_key, proposal_kind, status, scope, priority,
                trigger_type, target_layer,
                condition_json, trace_json, effect_json,
                first_seen_at, last_seen_at, created_at, updated_at, created_by)
               VALUES (?, ?, ?, ?, ?, ?,
                       ?, ?,
                       ?, ?, ?,
                       ?, ?, ?, ?, ?)""",
            (
                generate_id(), generate_id(), "failure_policy", "proposed", "teacher_only", 0,
                "repetition", "intent_teacher",
                "{}", "{}",
                json.dumps({"history_bias": {"downrank_families": ["quiet_atmosphere"]}}),
                now, now, now, now, "test",
            ),
        )
        bias = get_merged_history_bias()
        assert bias.is_empty

    def test_excludes_rejected_proposals(self, reader_db):
        _insert_proposal(reader_db, effect_json={
            "history_bias": {"downrank_families": ["quiet_atmosphere"]},
        }, status="rejected")
        bias = get_merged_history_bias()
        assert bias.is_empty

    def test_excludes_same_day_expired(self, reader_db):
        """Proposal expired earlier today should NOT be returned."""
        from datetime import datetime, timezone, timedelta

        # Set expires_at to 2 hours ago
        past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        now_str = "2026-03-24T12:00:00+00:00"
        conn = reader_db
        conn.execute(
            """INSERT INTO conversation_adaptation_proposals
               (proposal_id, proposal_key, proposal_kind, status, scope, priority,
                trigger_type, target_layer,
                condition_json, trace_json, effect_json,
                first_seen_at, last_seen_at, expires_at,
                created_at, updated_at, created_by)
               VALUES (?, ?, ?, ?, ?, ?,
                       ?, ?,
                       ?, ?, ?,
                       ?, ?, ?,
                       ?, ?, ?)""",
            (
                generate_id(), generate_id(), "failure_policy", "proposed",
                "temp_hotfix", 2,
                "repetition", "history_selection",
                "{}", "{}",
                json.dumps({"history_bias": {"downrank_families": ["quiet_atmosphere"]},
                            "runtime_hint": {"suffix_block_allowed": True, "hint_text": "test"}}),
                now_str, now_str, past,
                now_str, now_str, "test",
            ),
        )
        bias = get_merged_history_bias()
        assert bias.is_empty, "expired proposal should not be returned"

    def test_gate_off_returns_empty(self, reader_db, monkeypatch):
        import backend.services.adaptation.reader as _rd
        monkeypatch.setattr(_rd, "settings", type("S", (), {"ADAPTATION_RECORD_ENABLED": False})())
        _insert_proposal(reader_db, effect_json={
            "history_bias": {"downrank_families": ["quiet_atmosphere"]},
        })
        bias = get_merged_history_bias()
        assert bias.is_empty


# ── Scorer Integration Tests ────────────────────────────────────────

class TestHistoryBiasScoring:
    @pytest.fixture(autouse=True)
    def _import(self):
        from backend.core.agent_graph.nodes.helpers import (
            _apply_history_bias,
            _select_diverse_history,
        )
        self.apply_bias = _apply_history_bias
        self.select = _select_diverse_history

    def test_downrank_reduces_score(self):
        bias = MergedHistoryBias(downrank_families=frozenset(["quiet_atmosphere"]))
        delta = self.apply_bias("静かな時間の中で。", bias)
        assert delta < 0

    def test_uprank_increases_score(self):
        bias = MergedHistoryBias(uprank_families=frozenset(["quiet_atmosphere"]))
        delta = self.apply_bias("静かな時間の中で。", bias)
        assert delta > 0

    def test_no_match_zero_delta(self):
        bias = MergedHistoryBias(downrank_families=frozenset(["quiet_atmosphere"]))
        delta = self.apply_bias("普通の会話。", bias)
        assert delta == 0.0

    def test_trace_match_not_applied_in_runtime(self):
        """avoid/prefer trace_match are preserved in schema but not used in runtime scorer."""
        bias = MergedHistoryBias(
            avoid_trace_match=frozenset(["same_opener_family"]),
            prefer_trace_match=frozenset(["confident_expression"]),
        )
        # These abstract labels don't affect runtime scoring
        assert self.apply_bias("same_opener_family", bias) == 0.0
        assert self.apply_bias("confident_expression", bias) == 0.0

    def test_short_history_with_bias_does_not_early_return(self):
        """Short history (< max_pairs) with active bias should NOT early return.

        Without bias, 5 pairs <= max_pairs=6 → early return (all 5).
        With bias, scoring + cap applies even on short history.
        _ANCHOR_PAIRS=3, so we need enough pairs for cap to matter.
        """
        bias = MergedHistoryBias(
            downrank_families=frozenset(["quiet_atmosphere"]),
            cap_same_family=1,
        )
        # 5 pairs: 4 quiet + 1 non-quiet. Less than max_pairs=6.
        msgs = []
        for i in range(5):
            msgs.append(HumanMessage(content=f"q{i}"))
            if i < 4:
                msgs.append(AIMessage(content="静かな時間の中で。"))
            else:
                msgs.append(AIMessage(content="普通の話題。"))

        # Without bias: early return, all 5 pairs (4 quiet)
        result_no_bias = self.select(msgs, max_pairs=6, scorer=lambda _: 0.0)
        quiet_no_bias = sum(
            1 for m in result_no_bias
            if isinstance(m, AIMessage) and "静かな時間" in getattr(m, "content", "")
        )
        assert quiet_no_bias == 4, f"no-bias should return all 4 quiet, got {quiet_no_bias}"

        # With bias: scoring + cap applies (not early return)
        result_bias = self.select(
            msgs, max_pairs=6, scorer=lambda _: 0.0, history_bias=bias,
        )
        quiet_bias = sum(
            1 for m in result_bias
            if isinstance(m, AIMessage) and "静かな時間" in getattr(m, "content", "")
        )
        # anchor=3 may contain quiet, but cap=1 on scored reduces total
        assert quiet_bias < quiet_no_bias, (
            f"bias should reduce quiet: {quiet_bias} < {quiet_no_bias}"
        )

    def test_cap_tightens_family_limit(self):
        """cap_same_family=1 should limit family pairs in selection."""
        bias = MergedHistoryBias(
            downrank_families=frozenset(["quiet_atmosphere"]),
            cap_same_family=1,
        )
        # Build history with many quiet pairs
        msgs = []
        for i in range(12):
            msgs.append(HumanMessage(content=f"q{i}"))
            if i < 6:
                msgs.append(AIMessage(content="静かな時間の中で。"))
            else:
                msgs.append(AIMessage(content=f"普通の話題{i}。"))

        result = self.select(msgs, max_pairs=5, history_bias=bias)
        ai_contents = [getattr(m, "content", "") for m in result if isinstance(m, AIMessage)]

        quiet_count = sum(1 for c in ai_contents if "静かな時間" in c)
        # cap=1 should strongly limit quiet pairs
        assert quiet_count <= 2, f"cap=1 but got {quiet_count} quiet pairs"

    def test_empty_bias_no_effect(self):
        """Empty bias should not change behavior."""
        msgs = []
        for i in range(12):
            msgs.append(HumanMessage(content=f"q{i}"))
            msgs.append(AIMessage(content=f"応答{i}"))

        result_no_bias = self.select(msgs, max_pairs=5)
        result_empty = self.select(msgs, max_pairs=5, history_bias=_EMPTY_BIAS)
        # Same selection
        no_bias_contents = [getattr(m, "content", "") for m in result_no_bias]
        empty_contents = [getattr(m, "content", "") for m in result_empty]
        assert no_bias_contents == empty_contents
