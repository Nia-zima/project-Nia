"""NiaCore vNext Shadow Writer — DB recording for Phase N0.

Fire-and-forget: failures are logged but never propagate.
Design doc: docs/niacore_vnext_design.md §11 (Phase N0)
"""
from __future__ import annotations

import time
import uuid

from backend.core.db import managed_conn
from backend.core.logger import logger


def record_vnext_shadow(
    *,
    turn_id: str,
    session_id: str | None = None,
    state_vector_v2: bytes | None = None,
    state_vector_version: int = 2,
    attention_target: str | None = None,
    recommended_action: str | None = None,
    pseudo_teacher_rule_trace: str = "[]",
    depth2_mode: str | None = None,
    stagnation_flags: str | None = None,
    model_profile: str | None = None,
    model_provider: str | None = None,
    model_name: str | None = None,
    feature_availability: str | None = None,
) -> str | None:
    """Insert one row into niacore_vnext_shadow.

    Returns the row id on success, None on failure.
    """
    try:
        row_id = uuid.uuid4().hex
        now = time.time()
        with managed_conn() as conn:
            conn.execute(
                """INSERT INTO niacore_vnext_shadow
                   (id, turn_id, session_id, timestamp,
                    state_vector_v2, state_vector_version,
                    attention_target, recommended_action,
                    pseudo_teacher_rule_trace,
                    depth2_mode, stagnation_flags,
                    model_profile, model_provider, model_name,
                    feature_availability, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    row_id, turn_id, session_id, now,
                    state_vector_v2, state_vector_version,
                    attention_target, recommended_action,
                    pseudo_teacher_rule_trace,
                    depth2_mode, stagnation_flags,
                    model_profile, model_provider, model_name,
                    feature_availability, now,
                ),
            )
        logger.debug(
            "[NiaCore vNext] shadow recorded: turn=%s attn=%s action=%s rules=%s",
            turn_id, attention_target, recommended_action, pseudo_teacher_rule_trace,
        )
        return row_id
    except Exception:
        logger.warning("[NiaCore vNext] shadow write failed", exc_info=True)
        return None
