"""Re-exports for backward compatibility.

All imports of the form `from backend.core.agent_graph.nodes import X`
continue to work without changes.
"""

# ── Public node functions (used by graph.py, review_router.py) ──
from .routing import depth_selector
from .safety import safety_interrupt
from .dissonance import dissonance_check
from .depth_nodes import (
    depth0_reflex,
    depth1_organize_and_ask,
    depth2_value_align_and_preview,
)
from .merge import merge_output
from .actions import action_processing, s5_commit

# ── Helpers imported by tests ──
from .routing import (
    Depth2Mode,
    _should_use_risk_depth2,
    _select_depth2_mode,
    _reflective_score,
    _get_cumulative_turn_count,
    _is_simple_ack,
)
# Backward compat alias
_should_use_depth2 = _should_use_risk_depth2
from .safety import (
    _detect_pii,
    _detect_prompt_injection,
)
from .external_pipeline import (
    _detect_user_search_request,
    _apply_external_data_pipeline,
    _build_external_candidate_requests,
    _extract_search_query,
)

# ── Attributes monkeypatched by tests ──
# Tests use monkeypatch.setattr("backend.core.agent_graph.nodes.X", ...)
# so these must be importable from the package namespace.
from backend.core.config import settings  # noqa: F401  (tests patch nodes.settings.*)

__all__ = [
    # Graph nodes
    "safety_interrupt",
    "dissonance_check",
    "depth_selector",
    "depth0_reflex",
    "depth1_organize_and_ask",
    "depth2_value_align_and_preview",
    "merge_output",
    "action_processing",
    "s5_commit",
    # Test helpers
    "Depth2Mode",
    "_should_use_depth2",
    "_should_use_risk_depth2",
    "_select_depth2_mode",
    "_reflective_score",
    "_get_cumulative_turn_count",
    "_is_simple_ack",
    "_detect_pii",
    "_detect_prompt_injection",
    "_detect_user_search_request",
    "_apply_external_data_pipeline",
    "_build_external_candidate_requests",
    "_extract_search_query",
]
