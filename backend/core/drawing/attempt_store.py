"""Drawing Attempt Store — persistence for failed drawing attempts.

Separate from trace_store (success-only) to prevent silent_fallback_masking.
Parse/render failures get an explicit record instead of being silently swallowed.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel

from backend.core.logger import logger


class DrawingAttempt(BaseModel):
    """Record of a drawing attempt that did not produce a valid trace."""

    drawing_id: str
    dsl_code: str
    status: str  # "parse_error" | "scene_error" | "render_error"
    error_message: str
    error_phase: str  # "parse" | "scene_graph" | "render"
    thread_id: Optional[str] = None
    created_at: str


# ── DDL ───────────────────────────────────────────────────────────────


def ensure_drawing_attempt_schema(conn: sqlite3.Connection) -> None:
    """Create drawing_attempts table if it doesn't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS drawing_attempts (
            drawing_id      TEXT NOT NULL,
            dsl_code        TEXT NOT NULL,
            status          TEXT NOT NULL,
            error_message   TEXT NOT NULL,
            error_phase     TEXT NOT NULL,
            thread_id       TEXT,
            created_at      TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_da_drawing_id
        ON drawing_attempts(drawing_id);
        CREATE INDEX IF NOT EXISTS idx_da_created
        ON drawing_attempts(created_at DESC);
    """)
    logger.info("[DRAWING_ATTEMPT] Schema ensured: 1 table")


# ── Save ──────────────────────────────────────────────────────────────


def save_attempt(conn: sqlite3.Connection, attempt: DrawingAttempt) -> None:
    """Save a failed drawing attempt."""
    conn.execute(
        """INSERT INTO drawing_attempts
           (drawing_id, dsl_code, status, error_message, error_phase, thread_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            attempt.drawing_id,
            attempt.dsl_code,
            attempt.status,
            attempt.error_message,
            attempt.error_phase,
            attempt.thread_id,
            attempt.created_at,
        ),
    )


# ── Get ───────────────────────────────────────────────────────────────


def list_attempts(
    conn: sqlite3.Connection, *, limit: int = 20
) -> list[DrawingAttempt]:
    """List recent failed drawing attempts."""
    rows = conn.execute(
        "SELECT * FROM drawing_attempts ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [DrawingAttempt(**dict(r)) for r in rows]
