"""Sleep Cycle package — backward-compatible re-exports.

All public symbols are re-exported here so that existing imports like
``from backend.scripts.sleep_cycle import integrated_sleep_cycle`` continue
to work unchanged.
"""
from backend.scripts.sleep_cycle.helpers import (  # noqa: F401
    extract_section_content,
    replace_section_content,
    normalize_learnings_safe,
    compute_divergence,
    save_divergence_log,
    resolve_source,
    normalize_sleep_log,
    sanitize_for_sleep,
    filter_sleep_memories,
    _build_dream_text,
    estimate_importance,
    save_proposal_to_db,
    save_auto_applied_log,
    _build_memory_block_from_reflections,
    logger,
    PROJECT_ROOT,
    LOG_FILE,
    ARCHIVE_DIR,
    AUTONOMOUS_DIR,
    DIVERGENCE_LOG,
    _SLEEP_LLM_TIMEOUT,
    _no_think_suffix,
    AUTO_APPLIED_LOG,
    PENDING_PROPOSALS_DIR,
)
from backend.scripts.sleep_cycle.layers import (  # noqa: F401
    layer_a_impression_record,
    layer_b_guardian_proposal,
    layer_b_guardian_adaptive,
)
from backend.scripts.sleep_cycle.extraction import (  # noqa: F401
    _extract_semantics_from_episodic,
    _deduplicate_claims,
    _bigram_jaccard,
)
from backend.scripts.sleep_cycle.compression import _compress_old_episodic  # noqa: F401
from backend.scripts.sleep_cycle.orchestrator import integrated_sleep_cycle  # noqa: F401
