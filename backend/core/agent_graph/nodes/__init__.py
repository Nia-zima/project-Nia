"""Re-exports for backward compatibility.

All imports of the form `from backend.core.agent_graph.nodes import X`
continue to work without changes.
"""

# ── Public node functions (used by graph.py, review_router.py) ──
from .routing import safety_interrupt, dissonance_check, depth_selector
from .depth_nodes import (
    depth0_reflex,
    depth1_organize_and_ask,
    depth2_value_align_and_preview,
)
from .merge import merge_output
from .actions import action_processing, s5_commit

# ── Helpers imported by tests ──
from .routing import (
    _should_use_depth2,
    _get_cumulative_turn_count,
    _is_simple_ack,
    _detect_pii,
    _detect_prompt_injection,
)
from .external_pipeline import (
    _detect_user_search_request,
    _apply_external_data_pipeline,
    _build_external_candidate_requests,
    _extract_search_query,
)
from .helpers import extract_section, get_llm, get_depth_llm, get_plan_llm

# ── Attributes monkeypatched by tests ──
# Tests use monkeypatch.setattr("backend.core.agent_graph.nodes.X", ...)
# so these must be importable from the package namespace.
from backend.core.config import settings  # noqa: F401  (tests patch nodes.settings.*)
from .routing import build_memory_context  # noqa: F401  (test_context_integration)
from .merge import log_turn_observation  # noqa: F401  (test_external_data)

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
    # Helpers
    "extract_section",
    "get_llm",
    "get_depth_llm",
    "get_plan_llm",
    "_should_use_depth2",
    "_get_cumulative_turn_count",
    "_is_simple_ack",
    "_detect_user_search_request",
    "_apply_external_data_pipeline",
    "_build_external_candidate_requests",
    "_extract_search_query",
]
