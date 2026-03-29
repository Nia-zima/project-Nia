"""Tests for candidate_harvester — rule-based promotion candidate extraction."""
from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest

from backend.services.memory.candidate_harvester import (
    HarvestSignals,
    _should_harvest,
    _build_candidate,
    harvest_candidates,
)


# ── Rule tests (_should_harvest) ──────────────────────────


class TestShouldHarvest:
    def test_no_signals_no_candidates(self):
        signals = HarvestSignals()
        assert _should_harvest(signals) == []

    def test_h1_correction_strong(self):
        signals = HarvestSignals(correction_level="strong")
        result = _should_harvest(signals)
        assert any(k == "contradiction" and "H1" in r for k, r in result)

    def test_h1_correction_weak_no_candidate(self):
        signals = HarvestSignals(correction_level="weak")
        result = _should_harvest(signals)
        assert not any("H1" in r for _, r in result)

    def test_h2_dissonance(self):
        signals = HarvestSignals(dissonance_on=True)
        result = _should_harvest(signals)
        assert any(k == "dissonance" and "H2" in r for k, r in result)

    def test_h3_high_surprise(self):
        signals = HarvestSignals(surprise_score=0.7)
        result = _should_harvest(signals)
        assert any(k == "surprise" and "H3" in r for k, r in result)

    def test_h3_low_surprise_no_candidate(self):
        signals = HarvestSignals(surprise_score=0.3)
        result = _should_harvest(signals)
        assert not any("H3" in r for _, r in result)

    def test_h4_depth2(self):
        signals = HarvestSignals(selected_depth=2)
        result = _should_harvest(signals)
        assert any(k == "deep_processing" and "H4" in r for k, r in result)

    def test_h4_depth0_no_candidate(self):
        signals = HarvestSignals(selected_depth=0)
        result = _should_harvest(signals)
        assert not any("H4" in r for _, r in result)

    def test_h5_skeleton_contradiction(self):
        signals = HarvestSignals(skeleton_focus="contradiction")
        result = _should_harvest(signals)
        assert any(k == "contradiction" and "H5" in r for k, r in result)

    def test_h5_dedup_with_h1(self):
        """H5 should not fire if H1 already produced a contradiction."""
        signals = HarvestSignals(
            correction_level="strong",
            skeleton_focus="contradiction",
        )
        result = _should_harvest(signals)
        contradiction_rules = [r for k, r in result if k == "contradiction"]
        # H1 fires, H5 should be suppressed
        assert len(contradiction_rules) == 1
        assert "H1" in contradiction_rules[0]

    def test_h6_emotional_surprise(self):
        signals = HarvestSignals(
            skeleton_focus="emotional_state",
            surprise_score=0.4,
        )
        result = _should_harvest(signals)
        assert any(k == "emotional_pattern" and "H6" in r for k, r in result)

    def test_h6_emotional_low_surprise_no_candidate(self):
        signals = HarvestSignals(
            skeleton_focus="emotional_state",
            surprise_score=0.1,
        )
        result = _should_harvest(signals)
        assert not any("H6" in r for _, r in result)

    def test_multiple_rules_fire(self):
        """Multiple rules can fire on the same turn."""
        signals = HarvestSignals(
            dissonance_on=True,
            surprise_score=0.8,
            selected_depth=2,
        )
        result = _should_harvest(signals)
        kinds = {k for k, _ in result}
        assert "dissonance" in kinds
        assert "surprise" in kinds
        assert "deep_processing" in kinds


# ── Build candidate tests ─────────────────────────────────


class TestBuildCandidate:
    def test_basic_fields(self):
        signals = HarvestSignals(
            user_text="ユーザー入力",
            ai_response="AI応答",
            thread_id="thread_1",
            turn_id="turn_1",
            skeleton_focus="user_goal",
        )
        candidate = _build_candidate("surprise", "H3:surprise_high", signals, 1000.0)

        assert candidate.candidate_kind_rough == "surprise"
        assert candidate.source_type == "turn_harvester"
        assert candidate.thread_id == "thread_1"
        assert candidate.turn_id == "turn_1"
        assert candidate.focus == "user_goal"
        assert candidate.trace_id == "H3:surprise_high"
        assert candidate.status == "pending"
        assert "ユーザー入力" in candidate.source_ref
        assert "AI応答" in candidate.source_ref

    def test_source_ref_truncation(self):
        signals = HarvestSignals(user_text="x" * 1000, ai_response="y" * 1000)
        candidate = _build_candidate("test", "test", signals, 1000.0)
        assert len(candidate.source_ref) <= 500


# ── Integration tests (harvest_candidates) ────────────────


class TestHarvestCandidates:
    def test_inserts_to_db(self, tmp_path):
        """Candidates are actually inserted into the DB."""
        db_path = tmp_path / "test.sqlite3"
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE raw_promotion_candidates (
                candidate_id TEXT PRIMARY KEY,
                candidate_kind_rough TEXT,
                source_type TEXT,
                source_ref TEXT,
                topic_key TEXT,
                focus TEXT,
                response_intent TEXT,
                question_intent TEXT,
                unresolved_ref TEXT,
                owner_agent TEXT,
                memory_domain TEXT,
                status TEXT,
                thread_id TEXT,
                turn_id TEXT,
                message_id TEXT,
                stream_id TEXT,
                trace_id TEXT,
                created_at REAL,
                updated_at REAL
            )
        """)
        conn.commit()
        conn.close()

        signals = HarvestSignals(
            user_text="テスト入力",
            ai_response="テスト応答",
            surprise_score=0.8,
            dissonance_on=True,
            thread_id="thread_test",
            turn_id="turn_test",
        )

        with patch("backend.services.memory.candidate_harvester.managed_conn") as mock_conn:
            test_conn = sqlite3.connect(str(db_path))
            mock_conn.return_value.__enter__ = lambda _: test_conn
            mock_conn.return_value.__exit__ = lambda *_: test_conn.commit()

            count, kinds_list = harvest_candidates(signals)

        assert count >= 2  # H2 (dissonance) + H3 (surprise)

        verify_conn = sqlite3.connect(str(db_path))
        rows = verify_conn.execute("SELECT * FROM raw_promotion_candidates").fetchall()
        verify_conn.close()

        assert len(rows) >= 2
        kinds = {r[1] for r in rows}  # candidate_kind_rough is column 1
        assert "dissonance" in kinds
        assert "surprise" in kinds

    def test_no_candidates_returns_zero(self):
        signals = HarvestSignals()
        count, kinds_list = harvest_candidates(signals)
        assert count == 0
        assert kinds_list == []

    def test_failure_returns_zero(self):
        """DB failure should not raise, just return 0."""
        signals = HarvestSignals(surprise_score=0.9)

        with patch(
            "backend.services.memory.candidate_harvester.managed_conn",
            side_effect=Exception("DB error"),
        ):
            count, kinds_list = harvest_candidates(signals)

        assert count == 0
        assert kinds_list == []


# ── commit_helpers integration ────────────────────────────


class TestCommitHelperIntegration:
    def test_harvest_helper_collects_signals(self):
        """_harvest_governance_candidates correctly maps state to HarvestSignals."""
        from backend.core.agent_graph.nodes.commit_helpers import (
            _harvest_governance_candidates,
        )

        captured_signals = []

        def mock_should_harvest(signals):
            captured_signals.append(signals)
            return []  # no candidates, just capture

        state = {
            "user_text": "違う、それは間違いだよ",
            "final_text": "応答",
            "selected_depth": 2,
            "dissonance_on": True,
            "surprise_score": 0.7,
            "conversation_skeleton": {
                "focus": "user_goal",
                "response_intent": "organize",
                "question_intent": None,
            },
            "merge_mode": "direct",
            "message_id": "msg_1",
            "stream_id": "stream_1",
        }

        with (
            patch(
                "backend.services.memory.candidate_harvester._should_harvest",
                side_effect=mock_should_harvest,
            ),
            patch(
                "backend.services.memory.somatic_feedback.detect_correction_level",
                return_value="strong",
            ),
        ):
            _harvest_governance_candidates(state, "thread_1", "turn_1")

        assert len(captured_signals) == 1
        s = captured_signals[0]
        assert s.user_text == "違う、それは間違いだよ"
        assert s.selected_depth == 2
        assert s.dissonance_on is True
        assert s.surprise_score == 0.7
        assert s.correction_level == "strong"
        assert s.skeleton_focus == "user_goal"
        assert s.thread_id == "thread_1"
        assert s.turn_id == "turn_1"
