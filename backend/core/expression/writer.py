"""Expression Layer E0: fire-and-forget DB writer.

Records utterance metadata observations into expression_observations table.
Failures are logged but never propagate.

Design doc: docs/nia_expression_layer_design.md §4.5
"""
from __future__ import annotations

import time
import uuid

from backend.core.db import managed_conn
from backend.core.logger import logger


def record_expression_observation(
    *,
    turn_id: str,
    thread_id: str,
    message_id: str | None = None,
    stream_id: str | None = None,
    # strata
    selected_depth: int = 0,
    depth2_mode: str | None = None,
    model_profile: str | None = None,
    model_provider: str | None = None,
    model_name: str | None = None,
    test_mode: bool = False,
    # upstream state
    skeleton_focus: str | None = None,
    response_intent: str | None = None,
    question_intent: str | None = None,
    somatic_category: str | None = None,
    somatic_intensity: float | None = None,
    retrieval_hit: bool = False,
    runtime_facts_available: bool = False,
    # expression features
    char_length: int = 0,
    sentence_count: int = 0,
    hedge_count: int = 0,
    hedge_ratio: float = 0.0,
    assertion_count: int = 0,
    assertion_ratio: float = 0.0,
    question_count: int = 0,
    self_ref_count: int = 0,
    sensory_word_count: int = 0,
    spatial_word_count: int = 0,
    depth_word_count: int = 0,
    pause_markers: int = 0,
    negation_count: int = 0,
    topic_shift: bool = False,
    # result tags
    event_kind: str = "spoken",
    hold_kind: str | None = None,
    wait_origin: str | None = None,
    resumed_after_wait: bool = False,
    silence_gap_bucket: str = "none",
    review_used: bool = False,
    user_correction: bool = False,
    early_soft_close: bool = False,
    reassurance_loop: bool = False,
) -> str | None:
    """Insert one row into expression_observations.

    Returns the row id on success, None on failure.
    """
    try:
        row_id = uuid.uuid4().hex
        now = time.time()
        with managed_conn() as conn:
            conn.execute(
                """INSERT INTO expression_observations
                   (id, turn_id, thread_id, message_id, stream_id, timestamp,
                    selected_depth, depth2_mode,
                    model_profile, model_provider, model_name, test_mode,
                    skeleton_focus, response_intent, question_intent,
                    somatic_category, somatic_intensity,
                    retrieval_hit, runtime_facts_available,
                    char_length, sentence_count,
                    hedge_count, hedge_ratio,
                    assertion_count, assertion_ratio,
                    question_count, self_ref_count,
                    sensory_word_count, spatial_word_count, depth_word_count,
                    pause_markers, negation_count, topic_shift,
                    event_kind, hold_kind,
                    wait_origin, resumed_after_wait, silence_gap_bucket,
                    review_used, user_correction,
                    early_soft_close, reassurance_loop,
                    created_at)
                   VALUES (?, ?, ?, ?, ?, ?,
                           ?, ?,
                           ?, ?, ?, ?,
                           ?, ?, ?,
                           ?, ?,
                           ?, ?,
                           ?, ?,
                           ?, ?,
                           ?, ?,
                           ?, ?,
                           ?, ?, ?,
                           ?, ?, ?,
                           ?, ?,
                           ?, ?, ?,
                           ?, ?,
                           ?, ?,
                           ?)""",
                (
                    row_id, turn_id, thread_id, message_id, stream_id, now,
                    selected_depth, depth2_mode,
                    model_profile, model_provider, model_name, int(test_mode),
                    skeleton_focus, response_intent, question_intent,
                    somatic_category, somatic_intensity,
                    int(retrieval_hit), int(runtime_facts_available),
                    char_length, sentence_count,
                    hedge_count, hedge_ratio,
                    assertion_count, assertion_ratio,
                    question_count, self_ref_count,
                    sensory_word_count, spatial_word_count, depth_word_count,
                    pause_markers, negation_count, int(topic_shift),
                    event_kind, hold_kind,
                    wait_origin, int(resumed_after_wait), silence_gap_bucket,
                    int(review_used), int(user_correction),
                    int(early_soft_close), int(reassurance_loop),
                    now,
                ),
            )
        logger.debug(
            "[Expression E0] recorded: turn=%s event=%s chars=%d hedges=%d",
            turn_id, event_kind, char_length, hedge_count,
        )
        return row_id
    except Exception:
        logger.warning("[Expression E0] write failed", exc_info=True)
        return None
