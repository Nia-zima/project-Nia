"""NiaCore CfC Model — Closed-form Continuous-depth Neural Network.

System 1（速い直感）としてルールベースの depth 選択を補完する。
CfC は閉形式で < 1ms CPU 推論。GPU 不要。

Design doc: docs/niacore_lnn_design.md §2
"""
from __future__ import annotations

import json
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from backend.core.config import settings
from backend.core.logger import logger

try:
    import torch
    import torch.nn as nn
    from ncps.torch import CfC
    from ncps.wirings import AutoNCP

    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False

# ═══════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════

STATE_VECTOR_DIM = 34
CFC_UNITS = 64
NUM_DEPTHS = 4  # D0, D1, D2, WAIT
DEPTH_LABELS = ["D0", "D1", "D2", "WAIT"]

_CHECKPOINT_DIR = "data/niacore/checkpoints"
_MAX_CHECKPOINTS = 3

# struct format: 34 little-endian floats = 136 bytes
_STRUCT_FMT = f"<{STATE_VECTOR_DIM}f"
_STRUCT_SIZE = struct.calcsize(_STRUCT_FMT)

assert _STRUCT_SIZE == STATE_VECTOR_DIM * 4  # 136 bytes


# ═══════════════════════════════════════════════════════════════
# State Vector
# ═══════════════════════════════════════════════════════════════

@dataclass
class StateVector:
    """34次元の状態ベクトル。全て LLM 非依存の環境変数。

    Layout:
      [0]     user_input_length       len(text)/500 clamped [0,1]
      [1]     session_turn_count      messages/100 clamped [0,1]
      [2]     session_elapsed_sec     elapsed/7200 clamped [0,1]
      [3-7]   confidence metrics      5 metrics, already [0,1]
      [8]     retrieval_hit_rate      avg retrieval score [0,1]
      [9]     surprise_score          from state [0,1]
      [10]    surprise_v              integer (raw)
      [11]    somatic_value           top somatic intensity [0,1]
      [12-31] last_5_depths_onehot    5 turns × 4 depths (0 or 1)
      [32]    time_of_day             hour/24.0 [0,1]
      [33]    time_since_last_session  hours/168 clamped [0,1]
    """

    values: list[float] = field(default_factory=lambda: [0.0] * STATE_VECTOR_DIM)

    def __post_init__(self) -> None:
        if len(self.values) != STATE_VECTOR_DIM:
            raise ValueError(f"StateVector requires {STATE_VECTOR_DIM} values, got {len(self.values)}")

    def to_blob(self) -> bytes:
        """Serialize to compact binary (136 bytes)."""
        return struct.pack(_STRUCT_FMT, *self.values)

    @classmethod
    def from_blob(cls, data: bytes) -> StateVector:
        """Deserialize from binary blob."""
        if len(data) != _STRUCT_SIZE:
            raise ValueError(f"Expected {_STRUCT_SIZE} bytes, got {len(data)}")
        values = list(struct.unpack(_STRUCT_FMT, data))
        return cls(values=values)


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(v)))


def build_state_vector(
    *,
    user_text: str = "",
    messages: list[dict[str, Any]] | None = None,
    confidence_metrics: dict[str, float] | None = None,
    surprise_score: float = 0.0,
    surprise_v: int = 0,
    somatic_senses: list[dict[str, Any]] | None = None,
    recent_depths: list[str] | None = None,
    session_start_time: float | None = None,
    time_since_last_session_hours: float = 0.0,
) -> StateVector:
    """AgentState のデータから StateVector を構築。

    全フィールドにデフォルト値があるため、部分的なデータでも構築可能。
    """
    vec = [0.0] * STATE_VECTOR_DIM
    now = time.time()

    # [0] user_input_length
    vec[0] = _clamp(len(user_text) / 500.0)

    # [1] session_turn_count
    msg_count = len(messages) if messages else 0
    vec[1] = _clamp(msg_count / 100.0)

    # [2] session_elapsed_sec
    if session_start_time and session_start_time > 0:
        elapsed = now - session_start_time
        vec[2] = _clamp(elapsed / 7200.0)

    # [3-7] confidence metrics
    cm = confidence_metrics or {}
    metric_keys = [
        "context_coverage",
        "self_consistency",
        "logit_based",
        "question_clarity",
        "steering_risk",
    ]
    for i, key in enumerate(metric_keys):
        vec[3 + i] = _clamp(float(cm.get(key, 0.0)))

    # [8] retrieval_hit_rate
    vec[8] = _clamp(float(cm.get("retrieval_hit_rate", 0.0)))

    # [9] surprise_score
    vec[9] = _clamp(float(surprise_score))

    # [10] surprise_v (raw integer, no clamp)
    vec[10] = float(int(surprise_v))

    # [11] somatic_value (top intensity)
    if somatic_senses:
        intensities = [float(s.get("intensity", 0.0)) for s in somatic_senses if isinstance(s, dict)]
        vec[11] = _clamp(max(intensities)) if intensities else 0.0

    # [12-31] last_5_depths_onehot (5 turns × 4 depth types)
    depth_map = {"D0": 0, "D1": 1, "D2": 2, "WAIT": 3, "0": 0, "1": 1, "2": 2}
    depths = (recent_depths or [])[-5:]
    for turn_idx, depth_str in enumerate(depths):
        depth_idx = depth_map.get(str(depth_str).upper(), 0)
        base = 12 + turn_idx * 4
        vec[base + depth_idx] = 1.0

    # [32] time_of_day
    import datetime
    hour = datetime.datetime.now().hour
    vec[32] = hour / 24.0

    # [33] time_since_last_session
    vec[33] = _clamp(float(time_since_last_session_hours) / 168.0)

    return StateVector(values=vec)


# ═══════════════════════════════════════════════════════════════
# NiaCore Output
# ═══════════════════════════════════════════════════════════════

@dataclass
class NiaCoreOutput:
    """CfC 推論結果。"""
    depth_preference: list[float]  # softmax probabilities [D0, D1, D2, WAIT]
    selected: str  # "D0" | "D1" | "D2" | "WAIT"
    logits_json: str  # JSON string of raw logits for logging
    inference_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "depth_preference": self.depth_preference,
            "selected": self.selected,
            "logits_json": self.logits_json,
            "inference_ms": self.inference_ms,
        }


# ═══════════════════════════════════════════════════════════════
# CfC Model
# ═══════════════════════════════════════════════════════════════

if _TORCH_AVAILABLE:

    class NiaCoreModel(nn.Module):
        """CfC-based depth selector.

        Input:  (batch, 1, 34)  — single-step state vector
        Output: (batch, 4)      — logits for [D0, D1, D2, WAIT]
        """

        def __init__(self) -> None:
            super().__init__()
            wiring = AutoNCP(CFC_UNITS, NUM_DEPTHS)
            self.cfc = CfC(STATE_VECTOR_DIM, wiring, batch_first=True)
            self.depth_head = nn.Linear(NUM_DEPTHS, NUM_DEPTHS)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            """Forward pass.

            Args:
                x: (batch, 1, STATE_VECTOR_DIM)

            Returns:
                logits: (batch, NUM_DEPTHS)
            """
            output, _ = self.cfc(x)
            return self.depth_head(output[:, -1, :])

        @torch.no_grad()
        def infer(self, state_vec: StateVector) -> NiaCoreOutput:
            """Single-sample CPU inference. Target < 1ms."""
            self.eval()
            t0 = time.perf_counter()
            x = torch.tensor([state_vec.values], dtype=torch.float32).unsqueeze(1)
            logits = self.forward(x)  # (1, 4)
            probs = torch.softmax(logits, dim=-1).squeeze(0).tolist()
            elapsed_ms = (time.perf_counter() - t0) * 1000

            selected_idx = int(torch.argmax(logits, dim=-1).item())
            return NiaCoreOutput(
                depth_preference=probs,
                selected=DEPTH_LABELS[selected_idx],
                logits_json=json.dumps(logits.squeeze(0).tolist()),
                inference_ms=round(elapsed_ms, 3),
            )

        def save_checkpoint(self, path: Path | None = None) -> Path:
            """Save model weights."""
            if path is None:
                ckpt_dir = settings.PROJECT_ROOT / _CHECKPOINT_DIR
                ckpt_dir.mkdir(parents=True, exist_ok=True)
                ts = int(time.time())
                path = ckpt_dir / f"niacore_{ts}.pt"
            torch.save(self.state_dict(), path)
            logger.info("[NiaCore] checkpoint saved: %s", path)
            return path

        @classmethod
        def load_checkpoint(cls, path: Path) -> NiaCoreModel:
            """Load model from checkpoint."""
            model = cls()
            state_dict = torch.load(path, map_location="cpu", weights_only=True)
            model.load_state_dict(state_dict)
            model.eval()
            logger.info("[NiaCore] checkpoint loaded: %s", path)
            return model

    def clamp_weights(
        model: NiaCoreModel,
        default_state_dict: dict[str, torch.Tensor],
        max_drift: float = 0.3,
    ) -> int:
        """Limit parameter drift from initial weights.

        For each parameter, clamp the difference from default within [-max_drift, +max_drift].
        Returns number of clamped parameters.
        """
        clamped_count = 0
        with torch.no_grad():
            for name, param in model.named_parameters():
                if name in default_state_dict:
                    default = default_state_dict[name]
                    diff = param.data - default
                    clamped_diff = torch.clamp(diff, -max_drift, max_drift)
                    if not torch.equal(diff, clamped_diff):
                        param.data = default + clamped_diff
                        clamped_count += 1
        return clamped_count

    def prune_checkpoints(max_keep: int = _MAX_CHECKPOINTS) -> int:
        """Keep only the most recent checkpoints. Returns number pruned."""
        ckpt_dir = settings.PROJECT_ROOT / _CHECKPOINT_DIR
        if not ckpt_dir.exists():
            return 0
        files = sorted(ckpt_dir.glob("niacore_*.pt"), key=lambda p: p.stat().st_mtime)
        to_remove = files[:-max_keep] if len(files) > max_keep else []
        for f in to_remove:
            f.unlink()
            logger.info("[NiaCore] pruned old checkpoint: %s", f.name)
        return len(to_remove)

    def get_latest_checkpoint() -> Optional[Path]:
        """Return path to the most recent checkpoint, or None."""
        ckpt_dir = settings.PROJECT_ROOT / _CHECKPOINT_DIR
        if not ckpt_dir.exists():
            return None
        files = sorted(ckpt_dir.glob("niacore_*.pt"), key=lambda p: p.stat().st_mtime)
        return files[-1] if files else None

    def load_or_create_model() -> NiaCoreModel:
        """Load latest checkpoint or create a fresh model."""
        ckpt = get_latest_checkpoint()
        if ckpt:
            try:
                return NiaCoreModel.load_checkpoint(ckpt)
            except Exception:
                logger.warning("[NiaCore] failed to load checkpoint, creating fresh model", exc_info=True)
        model = NiaCoreModel()
        model.eval()
        return model

else:
    # Stub when torch/ncps not installed
    class NiaCoreModel:  # type: ignore[no-redef]
        """Stub — torch not available."""

        def infer(self, state_vec: StateVector) -> NiaCoreOutput:
            return NiaCoreOutput(
                depth_preference=[0.25, 0.25, 0.25, 0.25],
                selected="D0",
                logits_json="[]",
                inference_ms=0.0,
            )

    def clamp_weights(*args: Any, **kwargs: Any) -> int:
        return 0

    def prune_checkpoints(**kwargs: Any) -> int:
        return 0

    def get_latest_checkpoint() -> Optional[Path]:
        return None

    def load_or_create_model() -> NiaCoreModel:  # type: ignore[misc]
        return NiaCoreModel()
