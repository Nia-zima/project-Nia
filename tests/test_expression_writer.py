"""Tests for Expression Layer E0: fire-and-forget DB writer."""
import pytest

from backend.core.db import managed_conn
from backend.core.expression.writer import record_expression_observation


class TestRecordExpressionObservation:
    def test_basic_write(self):
        row_id = record_expression_observation(
            turn_id="test_exo_001",
            thread_id="test_thread",
        )
        assert row_id is not None
        assert isinstance(row_id, str)

    def test_full_write(self):
        row_id = record_expression_observation(
            turn_id="test_exo_002",
            thread_id="test_thread",
            message_id="msg_001",
            stream_id="stream_001",
            selected_depth=1,
            depth2_mode="reflective",
            model_profile="depth2_reflective",
            model_provider="local",
            model_name="qwen3-14b",
            test_mode=False,
            skeleton_focus="returning_theme",
            response_intent="explore",
            question_intent="challenge_assumption",
            somatic_category="warmth",
            somatic_intensity=0.7,
            retrieval_hit=True,
            runtime_facts_available=True,
            char_length=42,
            sentence_count=3,
            hedge_count=2,
            hedge_ratio=0.667,
            assertion_count=1,
            assertion_ratio=0.333,
            question_count=1,
            self_ref_count=1,
            sensory_word_count=2,
            spatial_word_count=0,
            depth_word_count=1,
            pause_markers=1,
            negation_count=0,
            topic_shift=False,
            event_kind="spoken",
            hold_kind=None,
            review_used=True,
            user_correction=False,
        )
        assert row_id is not None

        with managed_conn() as conn:
            row = conn.execute(
                "SELECT * FROM expression_observations WHERE id = ?",
                (row_id,),
            ).fetchone()
            assert row is not None
            assert row["char_length"] == 42
            assert row["hedge_count"] == 2
            assert row["skeleton_focus"] == "returning_theme"
            assert row["model_provider"] == "local"
            assert row["review_used"] == 1

    def test_event_kind_stored(self):
        row_id = record_expression_observation(
            turn_id="test_exo_003",
            thread_id="test_thread",
            event_kind="wait_depth",
        )
        with managed_conn() as conn:
            row = conn.execute(
                "SELECT event_kind FROM expression_observations WHERE id = ?",
                (row_id,),
            ).fetchone()
            assert row["event_kind"] == "wait_depth"

    def test_non_speech_event_zero_features(self):
        row_id = record_expression_observation(
            turn_id="test_exo_004",
            thread_id="test_thread",
            event_kind="wait_hold",
            char_length=0,
            sentence_count=0,
        )
        with managed_conn() as conn:
            row = conn.execute(
                "SELECT char_length, sentence_count, event_kind "
                "FROM expression_observations WHERE id = ?",
                (row_id,),
            ).fetchone()
            assert row["char_length"] == 0
            assert row["sentence_count"] == 0
            assert row["event_kind"] == "wait_hold"

    def test_strata_stored(self):
        row_id = record_expression_observation(
            turn_id="test_exo_005",
            thread_id="test_thread",
            model_profile="depth2_risk",
            model_provider="anthropic",
            model_name="claude-sonnet-4-6",
            test_mode=True,
        )
        with managed_conn() as conn:
            row = conn.execute(
                "SELECT model_profile, model_provider, model_name, test_mode "
                "FROM expression_observations WHERE id = ?",
                (row_id,),
            ).fetchone()
            assert row["model_profile"] == "depth2_risk"
            assert row["model_provider"] == "anthropic"
            assert row["test_mode"] == 1

    def test_upstream_state_stored(self):
        row_id = record_expression_observation(
            turn_id="test_exo_006",
            thread_id="test_thread",
            skeleton_focus="lingering_state",
            response_intent="hold",
            somatic_category="tension",
            somatic_intensity=0.8,
        )
        with managed_conn() as conn:
            row = conn.execute(
                "SELECT skeleton_focus, response_intent, somatic_category, somatic_intensity "
                "FROM expression_observations WHERE id = ?",
                (row_id,),
            ).fetchone()
            assert row["skeleton_focus"] == "lingering_state"
            assert row["response_intent"] == "hold"
            assert row["somatic_category"] == "tension"
            assert abs(row["somatic_intensity"] - 0.8) < 1e-6

    def test_indexes_exist(self):
        with managed_conn() as conn:
            indexes = conn.execute(
                "PRAGMA index_list('expression_observations')"
            ).fetchall()
            idx_names = [row["name"] for row in indexes]
            assert "idx_exo_turn" in idx_names
            assert "idx_exo_thread" in idx_names
            assert "idx_exo_event" in idx_names

    def test_fire_and_forget(self):
        """Writer should not raise even on unexpected input."""
        # This should not raise — errors are caught internally
        result = record_expression_observation(
            turn_id="test_exo_007",
            thread_id="test_thread",
        )
        assert result is not None
