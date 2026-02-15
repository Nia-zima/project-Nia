"""
Minimal Memory Gate (Phase3 v1).
Provides a deterministic fallback decision and validates rationale codes.
"""

from __future__ import annotations

import os
from typing import Dict

from backend.services.gate_codes import validate_code
from backend.core.constants.nia_spine_v10 import NIA_SPINE_ANCHOR_V10


def run_gate(user_text: str, candidate_raw_text: str, candidate_tags: str) -> Dict[str, object]:
    """
    Return a gate decision for memory_add.
    This is a minimal deterministic fallback until DSPy integration is enabled.
    """
    force = os.getenv("MEMORY_GATE_FORCE", "").lower().strip()
    if force in {"true", "1", "yes"}:
        code, _ = validate_code("origin_preference")
        return {
            "should_propose": True,
            "rationale": "forced allow",
            "rationale_code": code,
        }
    if force in {"false", "0", "no"}:
        code, _ = validate_code("low_signal")
        return {
            "should_propose": False,
            "rationale": "forced block",
            "rationale_code": code,
        }

    # Default heuristic: propose only if candidate has content.
    _ = NIA_SPINE_ANCHOR_V10  # anchor reserved for v1.1 prompt usage
    should = bool((candidate_raw_text or "").strip())
    code = "origin_preference" if should else "low_signal"
    code, _ = validate_code(code)
    rationale = "has candidate content" if should else "no candidate content"
    return {
        "should_propose": should,
        "rationale": rationale,
        "rationale_code": code,
    }
