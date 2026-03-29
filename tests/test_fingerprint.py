"""Tests for Temporal Somatic Contrast — TS.0 Fingerprint recording.

Covers: Fingerprint dataclass, pack/unpack, build_fingerprint(),
        save_fingerprint(), commit_helpers integration.
"""
import struct
import time
from unittest.mock import MagicMock, patch

import pytest

from backend.core.temporal.fingerprint import (
    FINGERPRINT_DIM,
    SCHEMA_VERSION,
    Fingerprint,
    _label_to_float,
    build_fingerprint,
    save_fingerprint,
)


# ═══════════════════════════════════════════════════════════════
# Fingerprint dataclass
# ═══════════════════════════════════════════════════════════════

class TestFingerprint:
    """Fingerprint dataclass basic operations."""

    def test_defaults(self):
        fp = Fingerprint()
        assert fp.selected_depth == 0
        assert fp.surprise_score == 0.0
        assert fp.dissonance_on is False
        assert fp.skeleton_focus is None

    def test_to_blob_size(self):
        fp = Fingerprint()
        blob = fp.to_blob()
        assert len(blob) == FINGERPRINT_DIM * 4  # 17 floats × 4 bytes

    def test_roundtrip(self):
        fp = Fingerprint(
            confidence_context_coverage=0.8,
            confidence_self_consistency=0.7,
            confidence_logit_based=0.6,
            confidence_question_clarity=0.5,
            confidence_steering_risk=0.1,
            selected_depth=2,
            surprise_score=0.75,
            somatic_top_intensity=0.9,
            retrieval_top_similarity=0.85,
            dissonance_on=True,
            time_of_day_hour=23,
            gap_seconds=3600.0,
            turn_index=5,
            utc_timestamp=1709251200.0,
        )
        blob = fp.to_blob()
        restored = Fingerprint.from_blob(blob, version=1)

        assert restored.confidence_context_coverage == pytest.approx(0.8, abs=1e-5)
        assert restored.confidence_self_consistency == pytest.approx(0.7, abs=1e-5)
        assert restored.selected_depth == 2
        assert restored.surprise_score == pytest.approx(0.75, abs=1e-5)
        assert restored.dissonance_on is True
        assert restored.time_of_day_hour == 23
        assert restored.gap_seconds == pytest.approx(3600.0, abs=1e-1)
        assert restored.turn_index == 5

    def test_dissonance_false_roundtrip(self):
        fp = Fingerprint(dissonance_on=False)
        restored = Fingerprint.from_blob(fp.to_blob())
        assert restored.dissonance_on is False

    def test_skeleton_labels_lost_in_blob(self):
        """Skeleton labels are hashed in BLOB — originals cannot be recovered."""
        fp = Fingerprint(
            skeleton_focus="contradiction",
            skeleton_response_intent="ask",
            skeleton_question_intent="clarify_goal",
        )
        restored = Fingerprint.from_blob(fp.to_blob())
        # Labels are None after deserialization (hash only in BLOB)
        assert restored.skeleton_focus is None
        assert restored.skeleton_response_intent is None
        assert restored.skeleton_question_intent is None

    def test_invalid_version_raises(self):
        fp = Fingerprint()
        blob = fp.to_blob()
        with pytest.raises(ValueError, match="Unknown fingerprint schema version"):
            Fingerprint.from_blob(blob, version=99)

    def test_invalid_blob_size_raises(self):
        with pytest.raises(ValueError, match="expected"):
            Fingerprint.from_blob(b"\x00" * 10, version=1)


# ═══════════════════════════════════════════════════════════════
# Label hashing
# ═══════════════════════════════════════════════════════════════

class TestLabelHash:
    """_label_to_float produces stable, bounded values."""

    def test_none_returns_zero(self):
        assert _label_to_float(None) == 0.0

    def test_empty_returns_zero(self):
        assert _label_to_float("") == 0.0

    def test_stable(self):
        """Same label always produces same hash."""
        a = _label_to_float("contradiction")
        b = _label_to_float("contradiction")
        assert a == b

    def test_bounded(self):
        for label in ["user_goal", "emotional_state", "missing_context", "ask", "hold"]:
            val = _label_to_float(label)
            assert 0.0 <= val <= 1.0

    def test_different_labels_different_hash(self):
        a = _label_to_float("contradiction")
        b = _label_to_float("emotional_state")
        assert a != b

    def test_known_labels_are_stable_across_calls(self):
        """Known labels use explicit map, not hash(), so they are process-stable."""
        assert _label_to_float("contradiction") == 0.33
        assert _label_to_float("ask") == 0.36
        assert _label_to_float("clarify_goal") == 0.13

    def test_unknown_label_uses_sha256(self):
        """Unknown labels use sha256, which is deterministic."""
        val1 = _label_to_float("some_future_label_xyz")
        val2 = _label_to_float("some_future_label_xyz")
        assert val1 == val2
        assert 0.0 <= val1 <= 1.0


# ═══════════════════════════════════════════════════════════════
# build_fingerprint
# ═══════════════════════════════════════════════════════════════

class TestBuildFingerprint:
    """build_fingerprint() correctly maps inputs to Fingerprint fields."""

    def test_minimal_call(self):
        """Can be called with no arguments."""
        fp = build_fingerprint()
        assert isinstance(fp, Fingerprint)
        assert fp.selected_depth == 0
        assert fp.utc_timestamp > 0

    def test_confidence_mapping(self):
        fp = build_fingerprint(
            confidence_metrics={
                "context_coverage": 0.9,
                "self_consistency": 0.8,
                "logit_based": 0.7,
                "question_clarity": 0.6,
                "steering_risk": 0.1,
            }
        )
        assert fp.confidence_context_coverage == 0.9
        assert fp.confidence_self_consistency == 0.8
        assert fp.confidence_logit_based == 0.7

    def test_somatic_top_intensity(self):
        fp = build_fingerprint(
            somatic_senses=[
                {"text": "sense1", "intensity": 0.3},
                {"text": "sense2", "intensity": 0.8},
                {"text": "sense3", "intensity": 0.5},
            ]
        )
        assert fp.somatic_top_intensity == 0.8

    def test_somatic_empty(self):
        fp = build_fingerprint(somatic_senses=[])
        assert fp.somatic_top_intensity == 0.0

    def test_skeleton_labels(self):
        fp = build_fingerprint(
            skeleton_focus="emotional_state",
            skeleton_response_intent="receive",
            skeleton_question_intent="clarify_emotion",
        )
        assert fp.skeleton_focus == "emotional_state"
        assert fp.skeleton_response_intent == "receive"
        assert fp.skeleton_question_intent == "clarify_emotion"

    def test_time_of_day_set(self):
        fp = build_fingerprint()
        assert 0 <= fp.time_of_day_hour <= 23

    def test_gap_and_turn_index(self):
        fp = build_fingerprint(gap_seconds=120.5, turn_index=7)
        assert fp.gap_seconds == 120.5
        assert fp.turn_index == 7


# ═══════════════════════════════════════════════════════════════
# save_fingerprint (DB write)
# ═══════════════════════════════════════════════════════════════

class TestSaveFingerprint:
    """save_fingerprint() DB interaction."""

    def test_save_returns_id(self, tmp_path):
        """save_fingerprint writes to DB and returns row id."""
        import sqlite3
        from contextlib import contextmanager

        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE turn_fingerprints (
                id TEXT PRIMARY KEY,
                turn_id TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                message_id TEXT,
                stream_id TEXT,
                schema_version INTEGER NOT NULL DEFAULT 1,
                timestamp REAL NOT NULL,
                fingerprint BLOB NOT NULL,
                created_at REAL NOT NULL
            )
        """)
        conn.commit()

        @contextmanager
        def mock_conn():
            yield conn

        with patch("backend.core.db.managed_conn", mock_conn):
            fp = Fingerprint(selected_depth=1, surprise_score=0.5)
            row_id = save_fingerprint(
                turn_id="turn_001",
                thread_id="thread_001",
                fingerprint=fp,
                message_id="msg_001",
                stream_id="stream_001",
            )

        assert row_id is not None

        row = conn.execute("SELECT * FROM turn_fingerprints WHERE id = ?", (row_id,)).fetchone()
        assert row is not None
        assert row[1] == "turn_001"  # turn_id
        assert row[2] == "thread_001"  # thread_id
        assert row[3] == "msg_001"  # message_id
        assert row[4] == "stream_001"  # stream_id
        assert row[5] == 1  # schema_version

        # Verify blob roundtrip
        restored = Fingerprint.from_blob(row[7], version=row[5])
        assert restored.selected_depth == 1
        assert restored.surprise_score == pytest.approx(0.5, abs=1e-5)

        conn.close()

    def test_save_returns_none_on_error(self):
        """save_fingerprint returns None on DB error, never raises."""
        with patch(
            "backend.core.db.managed_conn",
            side_effect=Exception("DB error"),
        ):
            fp = Fingerprint()
            result = save_fingerprint(
                turn_id="turn_001",
                thread_id="thread_001",
                fingerprint=fp,
            )
            assert result is None


# ═══════════════════════════════════════════════════════════════
# commit_helpers integration
# ═══════════════════════════════════════════════════════════════

class TestCommitHelpersIntegration:
    """_record_fingerprint() correctly maps state to fingerprint."""

    def test_record_fingerprint_calls_save(self):
        from backend.core.agent_graph.nodes.commit_helpers import _record_fingerprint

        state = {
            "confidence_metrics": {
                "context_coverage": 0.8,
                "self_consistency": 0.7,
                "logit_based": 0.6,
                "question_clarity": 0.5,
                "steering_risk": 0.1,
            },
            "selected_depth": 1,
            "surprise_score": 0.65,
            "somatic_senses": [{"text": "test", "intensity": 0.4}],
            "dissonance_on": True,
            "conversation_skeleton": {
                "focus": "emotional_state",
                "response_intent": "receive",
                "question_intent": "clarify_emotion",
            },
            "messages": [],
            "message_id": "msg_test",
            "stream_id": "stream_test",
            "retrieval_top_similarity": 0.75,
        }

        with patch(
            "backend.core.temporal.fingerprint.save_fingerprint"
        ) as mock_save, patch(
            "backend.core.db.managed_conn"
        ):
            mock_save.return_value = "fake_id"
            _record_fingerprint(state, "thread_test", "turn_test")

            mock_save.assert_called_once()
            call_kwargs = mock_save.call_args[1]
            assert call_kwargs["turn_id"] == "turn_test"
            assert call_kwargs["thread_id"] == "thread_test"
            assert call_kwargs["message_id"] == "msg_test"

            fp = call_kwargs["fingerprint"]
            assert fp.confidence_context_coverage == 0.8
            assert fp.selected_depth == 1
            assert fp.surprise_score == 0.65
            assert fp.dissonance_on is True
            assert fp.skeleton_focus == "emotional_state"
