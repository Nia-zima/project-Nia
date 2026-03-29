"""StateVectorV2 — v1 (34 dims) + spatial / relational / memory signals.

Phase N0: 記録のみ。CfC モデルはまだ消費しない。
v1 の 34 次元契約を壊さない。state_vector_version=2 で分離。

Design doc: docs/niacore_vnext_design.md §6
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any

from backend.core.niacore.model import STATE_VECTOR_DIM as V1_DIM, StateVector

# ═══════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════

V2_EXTRA_DIM = 16  # spatial(6) + relational(3) + memory(4) + skeleton(3)
STATE_VECTOR_V2_DIM = V1_DIM + V2_EXTRA_DIM  # 50

STATE_VECTOR_VERSION = 2

_STRUCT_FMT_V2 = f"<{STATE_VECTOR_V2_DIM}f"
_STRUCT_SIZE_V2 = struct.calcsize(_STRUCT_FMT_V2)

assert STATE_VECTOR_V2_DIM == 50
assert _STRUCT_SIZE_V2 == STATE_VECTOR_V2_DIM * 4  # 200 bytes

# v2-specific index offsets (relative to position 34)
# Spatial signals [34-39]
_IDX_PIP_PROXIMITY = 34
_IDX_PIP_STATE = 35
_IDX_ROOM_ZONE = 36
_IDX_TIME_OF_DAY_FINE = 37
_IDX_AMBIENT_STATE = 38
_IDX_RECENT_ACTION = 39

# Relational signals [40-42]
_IDX_USER_ENGAGEMENT = 40
_IDX_EMOTIONAL_SALIENCE = 41
_IDX_SOCIAL_PULL = 42

# Memory signals [43-46]
_IDX_ACTIVE_MEMORY_PRESSURE = 43
_IDX_UNRESOLVED_MEMORY_PRESSURE = 44
_IDX_CONTRADICTION_PRESSURE = 45
_IDX_RETRIEVAL_REINFORCEMENT = 46

# Skeleton signals [47-49]
_IDX_SKELETON_FOCUS = 47
_IDX_SKELETON_RESPONSE_INTENT = 48
_IDX_SKELETON_QUESTION_INTENT = 49


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(v)))


# ═══════════════════════════════════════════════════════════════
# Encoding helpers
# ═══════════════════════════════════════════════════════════════

# Pip state encoding (ordinal / count)
_PIP_STATE_MAP: dict[str, float] = {
    "sleeping": 0.0,
    "idle": 0.2,
    "active": 0.4,
    "near_nia": 0.6,
    "playing": 0.8,
    "empathy": 1.0,
}

# Room zone encoding
_ROOM_ZONE_MAP: dict[str, float] = {
    "center": 0.0,
    "window_side": 0.25,
    "door_side": 0.5,
    "corner": 0.75,
    "unknown": 0.0,
}

# Skeleton focus encoding (from SkeletonCore schema)
_SKELETON_FOCUS_MAP: dict[str, float] = {
    "new_topic": 0.0,
    "continuing_topic": 0.15,
    "returning_theme": 0.3,
    "user_question": 0.45,
    "emotional_shift": 0.6,
    "lingering_state": 0.75,
    "external_reference": 0.9,
    "silence_after_depth": 1.0,
}

# Skeleton response_intent encoding
_SKELETON_RESPONSE_INTENT_MAP: dict[str, float] = {
    "acknowledge": 0.0,
    "explore": 0.1,
    "deepen": 0.2,
    "question_back": 0.3,
    "offer_perspective": 0.4,
    "offer_fragile_self_observation": 0.5,
    "hold": 0.6,
    "redirect": 0.7,
    "express_uncertainty": 0.8,
}

# Skeleton question_intent encoding
_SKELETON_QUESTION_INTENT_MAP: dict[str, float] = {
    "clarify": 0.0,
    "explore_feeling": 0.25,
    "challenge_assumption": 0.5,
    "invite_elaboration": 0.75,
    "rhetorical": 1.0,
}

# Recent action encoding
_RECENT_ACTION_MAP: dict[str, float] = {
    "idle": 0.0,
    "sit": 0.2,
    "look_at": 0.4,
    "move_near": 0.6,
    "move_away": 0.8,
    "pause": 1.0,
}


# ═══════════════════════════════════════════════════════════════
# StateVectorV2
# ═══════════════════════════════════════════════════════════════

@dataclass
class StateVectorV2:
    """50次元の状態ベクトル。v1 (34 dims) + spatial / relational / memory (16 dims).

    Layout:
      [0-33]  v1 signals (copied verbatim from StateVector)
      [34]    pip_proximity          normalized distance [0,1]
      [35]    pip_state              ordinal encoding [0,1]
      [36]    room_zone              ordinal encoding [0,1]
      [37]    time_of_day_fine       hour/24 [0,1] (also in v1[32])
      [38]    ambient_state          lighting level [0,1]
      [39]    recent_action          ordinal encoding [0,1]
      [40]    user_engagement        message frequency proxy [0,1]
      [41]    emotional_salience     somatic top intensity [0,1]
      [42]    social_pull            skeleton intent proxy [0,1]
      [43]    active_memory_pressure working memory count / cap [0,1]
      [44]    unresolved_memory_pressure persistence [0,1]
      [45]    contradiction_pressure flag [0,1]
      [46]    retrieval_reinforcement top similarity [0,1]
      [47]    skeleton_focus         ordinal encoding [0,1]
      [48]    skeleton_response_intent ordinal encoding [0,1]
      [49]    skeleton_question_intent ordinal encoding [0,1]
    """

    version: int = STATE_VECTOR_VERSION
    values: list[float] = field(default_factory=lambda: [0.0] * STATE_VECTOR_V2_DIM)

    def __post_init__(self) -> None:
        if len(self.values) != STATE_VECTOR_V2_DIM:
            raise ValueError(
                f"StateVectorV2 requires {STATE_VECTOR_V2_DIM} values, got {len(self.values)}"
            )

    def to_blob(self) -> bytes:
        """Serialize to compact binary (200 bytes)."""
        return struct.pack(_STRUCT_FMT_V2, *self.values)

    @classmethod
    def from_blob(cls, data: bytes) -> StateVectorV2:
        """Deserialize from binary blob."""
        if len(data) != _STRUCT_SIZE_V2:
            raise ValueError(f"Expected {_STRUCT_SIZE_V2} bytes, got {len(data)}")
        values = list(struct.unpack(_STRUCT_FMT_V2, data))
        return cls(values=values)

    @property
    def v1_values(self) -> list[float]:
        """Return only the first 34 values (v1 compatible)."""
        return self.values[:V1_DIM]


def build_state_vector_v2(
    *,
    v1: StateVector,
    # Spatial signals
    pip_proximity: float = 0.0,
    pip_state: str = "idle",
    room_zone: str = "unknown",
    ambient_state: float = 0.0,
    recent_action: str = "idle",
    # Relational signals
    user_engagement: float = 0.0,
    emotional_salience: float = 0.0,
    social_pull: float = 0.0,
    # Memory signals
    active_memory_pressure: float = 0.0,
    unresolved_memory_pressure: float = 0.0,
    contradiction_pressure: float = 0.0,
    retrieval_reinforcement: float = 0.0,
    # Skeleton signals
    skeleton_focus: str | None = None,
    skeleton_response_intent: str | None = None,
    skeleton_question_intent: str | None = None,
) -> StateVectorV2:
    """Build StateVectorV2 from v1 + additional signals.

    All v2-specific signals have safe defaults (0.0).
    """
    vec = list(v1.values) + [0.0] * V2_EXTRA_DIM

    # Spatial [34-39]
    vec[_IDX_PIP_PROXIMITY] = _clamp(pip_proximity)
    vec[_IDX_PIP_STATE] = _PIP_STATE_MAP.get(pip_state, 0.2)
    vec[_IDX_ROOM_ZONE] = _ROOM_ZONE_MAP.get(room_zone, 0.0)
    vec[_IDX_TIME_OF_DAY_FINE] = vec[32]  # copy from v1 time_of_day
    vec[_IDX_AMBIENT_STATE] = _clamp(ambient_state)
    vec[_IDX_RECENT_ACTION] = _RECENT_ACTION_MAP.get(recent_action, 0.0)

    # Relational [40-42]
    vec[_IDX_USER_ENGAGEMENT] = _clamp(user_engagement)
    vec[_IDX_EMOTIONAL_SALIENCE] = _clamp(emotional_salience)
    vec[_IDX_SOCIAL_PULL] = _clamp(social_pull)

    # Memory [43-46]
    vec[_IDX_ACTIVE_MEMORY_PRESSURE] = _clamp(active_memory_pressure)
    vec[_IDX_UNRESOLVED_MEMORY_PRESSURE] = _clamp(unresolved_memory_pressure)
    vec[_IDX_CONTRADICTION_PRESSURE] = _clamp(contradiction_pressure)
    vec[_IDX_RETRIEVAL_REINFORCEMENT] = _clamp(retrieval_reinforcement)

    # Skeleton [47-49]
    if skeleton_focus:
        vec[_IDX_SKELETON_FOCUS] = _SKELETON_FOCUS_MAP.get(skeleton_focus, 0.0)
    if skeleton_response_intent:
        vec[_IDX_SKELETON_RESPONSE_INTENT] = _SKELETON_RESPONSE_INTENT_MAP.get(
            skeleton_response_intent, 0.0
        )
    if skeleton_question_intent:
        vec[_IDX_SKELETON_QUESTION_INTENT] = _SKELETON_QUESTION_INTENT_MAP.get(
            skeleton_question_intent, 0.0
        )

    return StateVectorV2(values=vec)
