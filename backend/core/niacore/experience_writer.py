"""NiaCore Experience Replay Buffer — writer module.

Records (State, Action, Reward) tuples for offline batch learning.
Design doc: docs/niacore_lnn_design.md §3.3

All writes are fire-and-forget: failures are logged but never propagate.
"""
from __future__ import annotations

import time
import uuid

from backend.core.db import managed_conn
from backend.core.logger import logger


def record_turn_experience(
    *,
    turn_id: str,
    session_id: str | None = None,
    rule_based_depth: str,
    review_rejected: bool = False,
    review_checked: bool = True,
    user_correction: bool = False,
    state_vector: bytes | None = None,
    niacore_selected: str | None = None,
    niacore_logits: str | None = None,
    is_deviation: bool = False,
    surprise_v: int = 0,
) -> str | None:
    """Insert one row into niacore_experience.

    Returns the row id on success, None on failure.
    """
    try:
        row_id = uuid.uuid4().hex
        now = time.time()
        with managed_conn() as conn:
            conn.execute(
                """INSERT INTO niacore_experience
                   (id, turn_id, session_id, timestamp,
                    rule_based_depth,
                    review_rejected, review_checked,
                    user_correction,
                    state_vector, niacore_selected, niacore_logits,
                    is_deviation, surprise_v,
                    created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    row_id, turn_id, session_id, now,
                    rule_based_depth,
                    int(review_rejected), int(review_checked),
                    int(user_correction),
                    state_vector, niacore_selected, niacore_logits,
                    int(is_deviation), int(surprise_v),
                    now,
                ),
            )
        return row_id
    except Exception:
        logger.warning("[NiaCore] experience write failed", exc_info=True)
        return None


def close_correction_window(
    prev_turn_id: str,
    *,
    user_correction: bool,
) -> bool:
    """Close the correction observation window for the previous turn.

    Sets correction_window_closed=1 and updates user_correction.
    Returns True if a row was updated.
    """
    try:
        with managed_conn() as conn:
            cursor = conn.execute(
                """UPDATE niacore_experience
                   SET correction_window_closed = 1,
                       user_correction = ?
                   WHERE turn_id = ?
                     AND correction_window_closed = 0""",
                (int(user_correction), prev_turn_id),
            )
        return cursor.rowcount > 0
    except Exception:
        logger.warning("[NiaCore] close_correction_window failed", exc_info=True)
        return False
