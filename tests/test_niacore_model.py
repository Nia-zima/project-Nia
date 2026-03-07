"""Tests for backend.core.niacore.model — CfC model + StateVector."""
from __future__ import annotations

import struct
import time

import pytest

from backend.core.niacore.model import (
    STATE_VECTOR_DIM,
    DEPTH_LABELS,
    StateVector,
    build_state_vector,
    _STRUCT_SIZE,
)

# ── StateVector ──────────────────────────────────────────────

class TestStateVector:
    def test_default_dim(self):
        sv = StateVector()
        assert len(sv.values) == STATE_VECTOR_DIM == 34

    def test_wrong_dim_raises(self):
        with pytest.raises(ValueError, match="34"):
            StateVector(values=[0.0] * 10)

    def test_blob_roundtrip(self):
        sv = StateVector(values=[float(i) for i in range(STATE_VECTOR_DIM)])
        blob = sv.to_blob()
        assert len(blob) == _STRUCT_SIZE == 136
        restored = StateVector.from_blob(blob)
        for a, b in zip(sv.values, restored.values):
            assert abs(a - b) < 1e-5

    def test_blob_wrong_size_raises(self):
        with pytest.raises(ValueError, match="136"):
            StateVector.from_blob(b"\x00" * 10)


# ── build_state_vector ───────────────────────────────────────

class TestBuildStateVector:
    def test_empty_defaults(self):
        sv = build_state_vector()
        assert len(sv.values) == STATE_VECTOR_DIM
        assert all(isinstance(v, float) for v in sv.values)

    def test_user_text_normalized(self):
        sv = build_state_vector(user_text="a" * 1000)
        assert sv.values[0] == 1.0  # clamped at 1.0

    def test_confidence_metrics(self):
        metrics = {
            "context_coverage": 0.8,
            "self_consistency": 0.6,
            "logit_based": 0.5,
            "question_clarity": 0.9,
            "steering_risk": 0.3,
        }
        sv = build_state_vector(confidence_metrics=metrics)
        assert abs(sv.values[3] - 0.8) < 1e-5
        assert abs(sv.values[7] - 0.3) < 1e-5

    def test_depth_onehot(self):
        sv = build_state_vector(recent_depths=["D0", "D1", "D2", "WAIT", "D0"])
        # First turn D0 → index 12+0=12 should be 1.0
        assert sv.values[12] == 1.0
        # Second turn D1 → index 16+1=17 should be 1.0
        assert sv.values[17] == 1.0
        # Fourth turn WAIT → index 24+3=27 should be 1.0
        assert sv.values[27] == 1.0

    def test_somatic_top_intensity(self):
        senses = [
            {"text": "test", "intensity": 0.3},
            {"text": "test2", "intensity": 0.7},
        ]
        sv = build_state_vector(somatic_senses=senses)
        assert abs(sv.values[11] - 0.7) < 1e-5

    def test_time_of_day_range(self):
        sv = build_state_vector()
        assert 0.0 <= sv.values[32] <= 1.0


# ── CfC Model (requires torch + ncps) ──────────────────────

torch = pytest.importorskip("torch")
ncps = pytest.importorskip("ncps")

from backend.core.niacore.model import (  # noqa: E402
    NiaCoreModel,
    NiaCoreOutput,
    clamp_weights,
)


class TestNiaCoreModel:
    def test_forward_shape(self):
        model = NiaCoreModel()
        x = torch.randn(2, 1, STATE_VECTOR_DIM)
        logits = model(x)
        assert logits.shape == (2, 4)

    def test_infer_returns_output(self):
        model = NiaCoreModel()
        sv = StateVector()
        out = model.infer(sv)
        assert isinstance(out, NiaCoreOutput)
        assert len(out.depth_preference) == 4
        assert abs(sum(out.depth_preference) - 1.0) < 1e-4
        assert out.selected in DEPTH_LABELS
        assert out.inference_ms >= 0

    def test_infer_speed(self):
        """CPU inference should be fast (< 50ms generous bound)."""
        model = NiaCoreModel()
        sv = StateVector()
        t0 = time.perf_counter()
        for _ in range(10):
            model.infer(sv)
        elapsed = (time.perf_counter() - t0) * 1000
        assert elapsed < 500  # 10 inferences < 500ms

    def test_clamp_weights(self):
        model = NiaCoreModel()
        default_sd = {k: v.clone() for k, v in model.state_dict().items()}
        # Artificially shift weights
        with torch.no_grad():
            for param in model.parameters():
                param.add_(1.0)
        clamped = clamp_weights(model, default_sd, max_drift=0.3)
        assert clamped > 0
        # Verify all diffs are within bound
        for name, param in model.named_parameters():
            if name in default_sd:
                diff = (param.data - default_sd[name]).abs().max().item()
                assert diff <= 0.3 + 1e-6

    def test_checkpoint_roundtrip(self, tmp_path):
        model = NiaCoreModel()
        path = model.save_checkpoint(tmp_path / "test.pt")
        assert path.exists()
        loaded = NiaCoreModel.load_checkpoint(path)
        # Verify same output
        sv = StateVector()
        out1 = model.infer(sv)
        out2 = loaded.infer(sv)
        for a, b in zip(out1.depth_preference, out2.depth_preference):
            assert abs(a - b) < 1e-5
