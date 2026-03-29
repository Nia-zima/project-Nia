"""Tests for StateVectorV2 — v1 extension with spatial/relational/memory signals."""
import struct
import pytest

from backend.core.niacore.model import StateVector, STATE_VECTOR_DIM, build_state_vector
from backend.core.niacore.vnext.state_vector_v2 import (
    STATE_VECTOR_V2_DIM,
    STATE_VECTOR_VERSION,
    StateVectorV2,
    build_state_vector_v2,
    _STRUCT_SIZE_V2,
)


class TestStateVectorV2Basics:
    def test_v2_dimension_count(self):
        assert STATE_VECTOR_V2_DIM == 50

    def test_v2_version(self):
        sv2 = StateVectorV2()
        assert sv2.version == 2
        assert sv2.version == STATE_VECTOR_VERSION

    def test_v2_default_values(self):
        sv2 = StateVectorV2()
        assert len(sv2.values) == 50
        assert all(v == 0.0 for v in sv2.values)

    def test_v2_wrong_dimension_raises(self):
        with pytest.raises(ValueError, match="requires 50"):
            StateVectorV2(values=[0.0] * 34)

    def test_v2_struct_size(self):
        assert _STRUCT_SIZE_V2 == 200  # 50 * 4 bytes


class TestStateVectorV2Serialization:
    def test_to_blob_size(self):
        sv2 = StateVectorV2()
        blob = sv2.to_blob()
        assert len(blob) == 200

    def test_roundtrip(self):
        values = [float(i) / 50.0 for i in range(50)]
        sv2 = StateVectorV2(values=values)
        blob = sv2.to_blob()
        restored = StateVectorV2.from_blob(blob)
        for a, b in zip(sv2.values, restored.values):
            assert abs(a - b) < 1e-6

    def test_from_blob_wrong_size(self):
        with pytest.raises(ValueError, match="Expected 200"):
            StateVectorV2.from_blob(b"\x00" * 136)

    def test_v1_values_property(self):
        values = [float(i) for i in range(50)]
        sv2 = StateVectorV2(values=values)
        v1_vals = sv2.v1_values
        assert len(v1_vals) == 34
        assert v1_vals == values[:34]


class TestBuildStateVectorV2:
    def _make_v1(self) -> StateVector:
        return build_state_vector(user_text="テスト入力")

    def test_preserves_v1_values(self):
        v1 = self._make_v1()
        sv2 = build_state_vector_v2(v1=v1)
        for i in range(34):
            assert abs(sv2.values[i] - v1.values[i]) < 1e-6

    def test_defaults_to_zero_for_v2_positions(self):
        v1 = StateVector()
        sv2 = build_state_vector_v2(v1=v1)
        # v2-specific positions (except time_of_day_fine which copies v1[32])
        for i in [34, 35, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49]:
            assert sv2.values[i] == 0.0 or sv2.values[i] in (0.0, 0.2)  # pip_state default is "idle"=0.2

    def test_pip_proximity(self):
        v1 = StateVector()
        sv2 = build_state_vector_v2(v1=v1, pip_proximity=0.75)
        assert abs(sv2.values[34] - 0.75) < 1e-6

    def test_pip_proximity_clamped(self):
        v1 = StateVector()
        sv2 = build_state_vector_v2(v1=v1, pip_proximity=5.0)
        assert sv2.values[34] == 1.0

    def test_pip_state_encoding(self):
        v1 = StateVector()
        sv2 = build_state_vector_v2(v1=v1, pip_state="near_nia")
        assert abs(sv2.values[35] - 0.6) < 1e-6

    def test_room_zone_encoding(self):
        v1 = StateVector()
        sv2 = build_state_vector_v2(v1=v1, room_zone="window_side")
        assert abs(sv2.values[36] - 0.25) < 1e-6

    def test_skeleton_focus_encoding(self):
        v1 = StateVector()
        sv2 = build_state_vector_v2(v1=v1, skeleton_focus="returning_theme")
        assert abs(sv2.values[47] - 0.3) < 1e-6

    def test_skeleton_response_intent_encoding(self):
        v1 = StateVector()
        sv2 = build_state_vector_v2(v1=v1, skeleton_response_intent="explore")
        assert abs(sv2.values[48] - 0.1) < 1e-6

    def test_skeleton_question_intent_encoding(self):
        v1 = StateVector()
        sv2 = build_state_vector_v2(v1=v1, skeleton_question_intent="challenge_assumption")
        assert abs(sv2.values[49] - 0.5) < 1e-6

    def test_memory_signals(self):
        v1 = StateVector()
        sv2 = build_state_vector_v2(
            v1=v1,
            active_memory_pressure=0.8,
            unresolved_memory_pressure=0.3,
            contradiction_pressure=0.5,
            retrieval_reinforcement=0.7,
        )
        assert abs(sv2.values[43] - 0.8) < 1e-6
        assert abs(sv2.values[44] - 0.3) < 1e-6
        assert abs(sv2.values[45] - 0.5) < 1e-6
        assert abs(sv2.values[46] - 0.7) < 1e-6

    def test_partial_signals_safe(self):
        """Missing signals produce safe defaults — no crash."""
        v1 = StateVector()
        sv2 = build_state_vector_v2(v1=v1)
        assert len(sv2.values) == 50
        assert sv2.version == 2

    def test_time_of_day_fine_copies_v1(self):
        v1 = StateVector()
        v1.values[32] = 0.5  # noon
        sv2 = build_state_vector_v2(v1=v1)
        assert sv2.values[37] == v1.values[32]
