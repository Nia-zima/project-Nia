"""Turn Fingerprint — lightweight snapshot of Nia's internal state per turn.

Design doc: docs/temporal_somatic_contrast_design.md §3

Records raw values only. Derived values (long_silence, session_phase, etc.)
are computed at comparison time, never stored.
"""
from __future__ import annotations

import struct
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from backend.core.logger import logger

# ═══════════════════════════════════════════════════════════════
# Schema version & struct layout
# ═══════════════════════════════════════════════════════════════

SCHEMA_VERSION = 1

# V1 layout (17 fields):
#   [0]  confidence_context_coverage   float
#   [1]  confidence_self_consistency   float
#   [2]  confidence_logit_based        float
#   [3]  confidence_question_clarity   float
#   [4]  confidence_steering_risk      float
#   [5]  selected_depth                float (int stored as float)
#   [6]  surprise_score                float
#   [7]  somatic_top_intensity         float
#   [8]  retrieval_top_similarity      float
#   [9]  dissonance_on                 float (0.0 or 1.0)
#   [10] time_of_day_hour              float (0-23)
#   [11] gap_seconds                   float
#   [12] turn_index                    float (int stored as float)
#   [13] utc_timestamp                 float (double precision)
#   [14] skeleton_focus_hash           float (hash of label)
#   [15] skeleton_response_intent_hash float
#   [16] skeleton_question_intent_hash float

_V1_NUM_FLOATS = 14
_V1_NUM_DOUBLES = 1  # utc_timestamp needs double precision
_V1_NUM_LABEL_HASHES = 3

# Pack format: 14 floats + 1 double + 3 floats = 17 numeric values
# Use all floats for simplicity (utc_timestamp loses sub-second precision,
# but that's acceptable for fingerprint comparison).
FINGERPRINT_DIM = 17
_STRUCT_FMT = f"<{FINGERPRINT_DIM}f"
_STRUCT_SIZE = struct.calcsize(_STRUCT_FMT)

# Stable label-to-float mapping.
# All known SkeletonCore labels have explicit values.
# Unknown labels use sha256 for cross-process stability (hash() is seeded).
_KNOWN_LABELS: dict[str | None, float] = {
    None: 0.0,
    "": 0.0,
    # Focus
    "user_goal": 0.11,
    "missing_context": 0.22,
    "contradiction": 0.33,
    "priority_decision": 0.44,
    "emotional_state": 0.55,
    # ResponseIntent
    "receive": 0.12,
    "organize": 0.24,
    "ask": 0.36,
    "hold": 0.48,
    # QuestionIntent
    "clarify_goal": 0.13,
    "clarify_priority": 0.26,
    "clarify_emotion": 0.39,
    "fill_missing_fact": 0.52,
    "resolve_contradiction": 0.65,
    # Meeting extension (ME.1)
    "returning_theme": 0.66,
    "lingering_state": 0.77,
    "offer_fragile_self_observation": 0.88,
    "hold_open_space": 0.78,
}
_LABEL_CACHE: dict[str, float] = {}


def _label_to_float(label: str | None) -> float:
    """Convert a skeleton label string to a stable float in [0, 1].

    Known labels use an explicit map. Unknown labels use sha256
    for cross-process / cross-restart stability.
    """
    if label is None or label == "":
        return 0.0
    known = _KNOWN_LABELS.get(label)
    if known is not None:
        return known
    cached = _LABEL_CACHE.get(label)
    if cached is not None:
        return cached
    import hashlib
    h = int(hashlib.sha256(label.encode()).hexdigest()[:8], 16)
    val = (h % 10000) / 10000.0
    _LABEL_CACHE[label] = val
    return val


# ═══════════════════════════════════════════════════════════════
# Fingerprint dataclass
# ═══════════════════════════════════════════════════════════════

@dataclass
class Fingerprint:
    """Raw internal-state snapshot for a single turn.

    All fields are raw values. No interpretation, no derived values.
    """

    # Confidence metrics
    confidence_context_coverage: float = 0.0
    confidence_self_consistency: float = 0.0
    confidence_logit_based: float = 0.0
    confidence_question_clarity: float = 0.0
    confidence_steering_risk: float = 0.0

    # Depth & surprise
    selected_depth: int = 0
    surprise_score: float = 0.0

    # Somatic & retrieval
    somatic_top_intensity: float = 0.0
    retrieval_top_similarity: float = 0.0

    # Dissonance
    dissonance_on: bool = False

    # Temporal (raw — not converted to categories)
    time_of_day_hour: int = 0
    gap_seconds: float = 0.0
    turn_index: int = 0
    utc_timestamp: float = 0.0

    # Skeleton labels (stored as strings, hashed for BLOB)
    skeleton_focus: str | None = None
    skeleton_response_intent: str | None = None
    skeleton_question_intent: str | None = None

    def to_blob(self) -> bytes:
        """Serialize to compact binary."""
        values = [
            self.confidence_context_coverage,
            self.confidence_self_consistency,
            self.confidence_logit_based,
            self.confidence_question_clarity,
            self.confidence_steering_risk,
            float(self.selected_depth),
            self.surprise_score,
            self.somatic_top_intensity,
            self.retrieval_top_similarity,
            1.0 if self.dissonance_on else 0.0,
            float(self.time_of_day_hour),
            self.gap_seconds,
            float(self.turn_index),
            self.utc_timestamp,
            _label_to_float(self.skeleton_focus),
            _label_to_float(self.skeleton_response_intent),
            _label_to_float(self.skeleton_question_intent),
        ]
        return struct.pack(_STRUCT_FMT, *values)

    @classmethod
    def from_blob(cls, data: bytes, version: int = SCHEMA_VERSION) -> Fingerprint:
        """Deserialize from binary blob.

        Handles version differences: unknown versions return defaults for
        fields that don't exist in older schemas.
        """
        if version == 1:
            if len(data) != _STRUCT_SIZE:
                raise ValueError(f"V1 fingerprint: expected {_STRUCT_SIZE} bytes, got {len(data)}")
            vals = struct.unpack(_STRUCT_FMT, data)
            return cls(
                confidence_context_coverage=vals[0],
                confidence_self_consistency=vals[1],
                confidence_logit_based=vals[2],
                confidence_question_clarity=vals[3],
                confidence_steering_risk=vals[4],
                selected_depth=int(vals[5]),
                surprise_score=vals[6],
                somatic_top_intensity=vals[7],
                retrieval_top_similarity=vals[8],
                dissonance_on=vals[9] > 0.5,
                time_of_day_hour=int(vals[10]),
                gap_seconds=vals[11],
                turn_index=int(vals[12]),
                utc_timestamp=vals[13],
                # Labels are lost in BLOB (hash only). Use None.
                skeleton_focus=None,
                skeleton_response_intent=None,
                skeleton_question_intent=None,
            )
        raise ValueError(f"Unknown fingerprint schema version: {version}")


# ═══════════════════════════════════════════════════════════════
# Builder
# ═══════════════════════════════════════════════════════════════

def build_fingerprint(
    *,
    confidence_metrics: dict[str, float] | None = None,
    selected_depth: int = 0,
    surprise_score: float = 0.0,
    somatic_senses: list[dict[str, Any]] | None = None,
    retrieval_top_similarity: float = 0.0,
    dissonance_on: bool = False,
    turn_index: int = 0,
    gap_seconds: float = 0.0,
    skeleton_focus: str | None = None,
    skeleton_response_intent: str | None = None,
    skeleton_question_intent: str | None = None,
) -> Fingerprint:
    """Build a Fingerprint from available turn state.

    All parameters have defaults — can be called with partial data.
    """
    cm = confidence_metrics or {}
    somatic_top = 0.0
    if somatic_senses:
        somatic_top = max(
            (s.get("intensity", 0.0) for s in somatic_senses),
            default=0.0,
        )

    now = time.time()
    from datetime import datetime
    hour = datetime.now().hour

    return Fingerprint(
        confidence_context_coverage=cm.get("context_coverage", 0.0),
        confidence_self_consistency=cm.get("self_consistency", 0.0),
        confidence_logit_based=cm.get("logit_based", 0.0),
        confidence_question_clarity=cm.get("question_clarity", 0.0),
        confidence_steering_risk=cm.get("steering_risk", 0.0),
        selected_depth=selected_depth,
        surprise_score=surprise_score,
        somatic_top_intensity=somatic_top,
        retrieval_top_similarity=retrieval_top_similarity,
        dissonance_on=dissonance_on,
        time_of_day_hour=hour,
        gap_seconds=gap_seconds,
        turn_index=turn_index,
        utc_timestamp=now,
        skeleton_focus=skeleton_focus,
        skeleton_response_intent=skeleton_response_intent,
        skeleton_question_intent=skeleton_question_intent,
    )


# ═══════════════════════════════════════════════════════════════
# DB writer
# ═══════════════════════════════════════════════════════════════

def save_fingerprint(
    *,
    turn_id: str,
    thread_id: str,
    fingerprint: Fingerprint,
    message_id: str | None = None,
    stream_id: str | None = None,
) -> str | None:
    """Save fingerprint to DB. Returns row id or None on failure.

    Never raises — logs and returns None on error.
    """
    try:
        from backend.core.db import managed_conn

        row_id = str(uuid.uuid4())
        now = time.time()
        blob = fingerprint.to_blob()

        with managed_conn() as conn:
            conn.execute(
                """INSERT INTO turn_fingerprints
                   (id, turn_id, thread_id, message_id, stream_id,
                    schema_version, timestamp, fingerprint, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    row_id,
                    turn_id,
                    thread_id,
                    message_id,
                    stream_id,
                    SCHEMA_VERSION,
                    fingerprint.utc_timestamp,
                    blob,
                    now,
                ),
            )
        logger.debug(
            "[FINGERPRINT] saved turn=%s thread=%s depth=%d surprise=%.2f",
            turn_id, thread_id, fingerprint.selected_depth, fingerprint.surprise_score,
        )
        return row_id
    except Exception:
        logger.debug("[FINGERPRINT] save failed", exc_info=True)
        return None
