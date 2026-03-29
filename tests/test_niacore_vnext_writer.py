"""Tests for NiaCore vNext shadow writer."""
import json
import pytest

from backend.core.db import managed_conn
from backend.core.niacore.vnext.writer import record_vnext_shadow


class TestRecordVNextShadow:
    def test_basic_write(self):
        row_id = record_vnext_shadow(
            turn_id="test_turn_001",
            session_id="test_session",
        )
        assert row_id is not None
        assert isinstance(row_id, str)

    def test_with_labels(self):
        row_id = record_vnext_shadow(
            turn_id="test_turn_002",
            session_id="test_session",
            attention_target="pip",
            recommended_action="hold_support",
            pseudo_teacher_rule_trace=json.dumps(["A1", "C3"]),
        )
        assert row_id is not None

        with managed_conn() as conn:
            row = conn.execute(
                "SELECT * FROM niacore_vnext_shadow WHERE id = ?", (row_id,)
            ).fetchone()
            assert row is not None
            assert row["attention_target"] == "pip"
            assert row["recommended_action"] == "hold_support"
            assert json.loads(row["pseudo_teacher_rule_trace"]) == ["A1", "C3"]

    def test_null_labels(self):
        row_id = record_vnext_shadow(
            turn_id="test_turn_003",
            attention_target=None,
            recommended_action=None,
        )
        assert row_id is not None

        with managed_conn() as conn:
            row = conn.execute(
                "SELECT * FROM niacore_vnext_shadow WHERE id = ?", (row_id,)
            ).fetchone()
            assert row["attention_target"] is None
            assert row["recommended_action"] is None

    def test_state_vector_blob_stored(self):
        fake_blob = b"\x00" * 200
        row_id = record_vnext_shadow(
            turn_id="test_turn_004",
            state_vector_v2=fake_blob,
        )
        assert row_id is not None

        with managed_conn() as conn:
            row = conn.execute(
                "SELECT state_vector_v2 FROM niacore_vnext_shadow WHERE id = ?",
                (row_id,),
            ).fetchone()
            assert row["state_vector_v2"] == fake_blob

    def test_model_info_stored(self):
        row_id = record_vnext_shadow(
            turn_id="test_turn_005",
            model_profile="depth2_reflective",
            model_provider="anthropic",
            model_name="claude-sonnet-4-6",
        )
        assert row_id is not None

        with managed_conn() as conn:
            row = conn.execute(
                "SELECT model_profile, model_provider, model_name "
                "FROM niacore_vnext_shadow WHERE id = ?",
                (row_id,),
            ).fetchone()
            assert row["model_profile"] == "depth2_reflective"
            assert row["model_provider"] == "anthropic"
            assert row["model_name"] == "claude-sonnet-4-6"

    def test_state_vector_version_default(self):
        row_id = record_vnext_shadow(turn_id="test_turn_006")
        with managed_conn() as conn:
            row = conn.execute(
                "SELECT state_vector_version FROM niacore_vnext_shadow WHERE id = ?",
                (row_id,),
            ).fetchone()
            assert row["state_vector_version"] == 2

    def test_turn_id_indexed(self):
        """Verify turn_id index exists for efficient lookups."""
        with managed_conn() as conn:
            indexes = conn.execute(
                "PRAGMA index_list('niacore_vnext_shadow')"
            ).fetchall()
            idx_names = [row["name"] for row in indexes]
            assert "idx_nvs_turn" in idx_names

    def test_depth2_mode_stored(self):
        row_id = record_vnext_shadow(
            turn_id="test_turn_007",
            depth2_mode="risk",
        )
        with managed_conn() as conn:
            row = conn.execute(
                "SELECT depth2_mode FROM niacore_vnext_shadow WHERE id = ?",
                (row_id,),
            ).fetchone()
            assert row["depth2_mode"] == "risk"
