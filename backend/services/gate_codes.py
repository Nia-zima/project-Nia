"""
Gate rationale codes for Phase3 v1.
Keeps a single source of truth and provides validation with safe fallback.
"""

from __future__ import annotations

from typing import Iterable, Tuple

# SKIP-side
SKIP_CODES = [
    "too_trivial",
    "low_signal",
    "already_known",
    "out_of_context",
    "ephemeral",
    "private_sensitive",
    "needs_confirmation",
]

# PROPOSE-side
PROPOSE_CODES = [
    "origin_preference",
    "origin_goal",
    "system_contract",
    "high_value_insight",
    "origin_essence",
]

ALL_CODES = SKIP_CODES + PROPOSE_CODES
ALL_CODES_SET = set(ALL_CODES)


def validate_code(code: str | None) -> Tuple[str, bool]:
    """
    Validate a rationale code.
    Returns (normalized_code, was_fallback).
    """
    if not code or code not in ALL_CODES_SET:
        return "low_signal", True
    return code, False
