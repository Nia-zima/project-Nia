"""Integration tests for NiaCore vNext pipeline."""
import base64
import json
from unittest.mock import patch

import pytest

from backend.core.db import managed_conn


class TestVNextCommitHelpers:
    def test_record_vnext_shadow_from_state(self):
        """Mock state with vnext data → verify DB write."""
        from backend.core.niacore.vnext.state_vector_v2 import StateVectorV2

        sv2 = StateVectorV2()
        blob_b64 = base64.b64encode(sv2.to_blob()).decode("ascii")

        state = {
            "niacore_vnext_shadow": {
                "_state_vector_v2_blob": blob_b64,
                "state_vector_version": 2,
                "attention_target": "pip",
                "recommended_action": "hold_support",
                "pseudo_teacher_rule_trace": ["A1", "C3"],
                "depth2_mode": None,
                "model_profile": "default",
                "model_provider": "local",
                "model_name": "qwen3-14b",
            }
        }

        from backend.core.agent_graph.nodes.commit_helpers import (
            _record_niacore_vnext_shadow,
        )

        _record_niacore_vnext_shadow(state, "test_thread", "test_turn_int_001")

        with managed_conn() as conn:
            row = conn.execute(
                "SELECT * FROM niacore_vnext_shadow WHERE turn_id = ?",
                ("test_turn_int_001",),
            ).fetchone()
            assert row is not None
            assert row["attention_target"] == "pip"
            assert row["recommended_action"] == "hold_support"
            assert row["model_provider"] == "local"
            rules = json.loads(row["pseudo_teacher_rule_trace"])
            assert "A1" in rules
            assert "C3" in rules

    def test_no_write_when_vnext_absent(self):
        """No vnext data in state → no DB write."""
        from backend.core.agent_graph.nodes.commit_helpers import (
            _record_niacore_vnext_shadow,
        )

        _record_niacore_vnext_shadow({}, "test_thread", "test_turn_int_002")

        with managed_conn() as conn:
            row = conn.execute(
                "SELECT * FROM niacore_vnext_shadow WHERE turn_id = ?",
                ("test_turn_int_002",),
            ).fetchone()
            assert row is None


class TestVNextFeatureGate:
    def test_vnext_requires_experience_enabled(self):
        """NIACORE_VNEXT_SHADOW_ENABLED=true forces NIACORE_EXPERIENCE_ENABLED=true."""
        import warnings
        from backend.core.config import _validate_feature_flags

        # Create a mock settings-like object with vnext on, experience off
        class FakeSettings:
            NIACORE_VNEXT_SHADOW_ENABLED = True
            NIACORE_EXPERIENCE_ENABLED = False
            # Other flags needed by _validate_feature_flags
            NIACORE_TRAINING_ENABLED = False
            NIACORE_SHADOW_ENABLED = False
            SOMATIC_ADAPTIVE_ENABLED = False
            SOMATIC_ENABLED = False
            SOMATIC_FEEDBACK_ENABLED = False
            SKELETON_SOMATIC_ENABLED = False
            SKELETON_RECORD_ENABLED = False
            GOVERNANCE_CANDIDATE_ENABLED = False
            GOVERNANCE_OBSERVE_ENABLED = False
            GOVERNANCE_EVIDENCE_ENABLED = False
            ATMOSPHERE_ENABLED = False
            RUNTIME_FACTS_ENABLED = False

        s = FakeSettings()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _validate_feature_flags(s)
            assert s.NIACORE_EXPERIENCE_ENABLED is True
            warning_msgs = [str(x.message) for x in w]
            assert any("NIACORE_VNEXT_SHADOW" in m for m in warning_msgs)

    def test_vnext_default_off(self):
        """Default: NIACORE_VNEXT_SHADOW_ENABLED=false."""
        from backend.core.config import Settings

        with patch.dict("os.environ", {}, clear=False):
            s = Settings()
            assert s.NIACORE_VNEXT_SHADOW_ENABLED is False


class TestVNextAndV1Coexist:
    def test_both_shadows_can_record(self):
        """v1 experience and vnext shadow can both write in the same session."""
        from backend.core.niacore.experience_writer import record_turn_experience
        from backend.core.niacore.vnext.writer import record_vnext_shadow

        turn_id = "test_turn_coexist_001"

        v1_id = record_turn_experience(
            turn_id=turn_id,
            rule_based_depth="D0",
        )
        vnext_id = record_vnext_shadow(
            turn_id=turn_id,
            attention_target="environment",
            pseudo_teacher_rule_trace=json.dumps(["A2"]),
        )

        assert v1_id is not None
        assert vnext_id is not None

        with managed_conn() as conn:
            v1_row = conn.execute(
                "SELECT * FROM niacore_experience WHERE turn_id = ?", (turn_id,)
            ).fetchone()
            vnext_row = conn.execute(
                "SELECT * FROM niacore_vnext_shadow WHERE turn_id = ?", (turn_id,)
            ).fetchone()
            assert v1_row is not None
            assert vnext_row is not None
            assert v1_row["rule_based_depth"] == "D0"
            assert vnext_row["attention_target"] == "environment"
