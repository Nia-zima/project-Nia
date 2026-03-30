"""Skeleton Realizer — DB persistence for shadow records.

C.0: fire-and-forget recording of skeleton guidance + adherence.
Table: skeleton_guidance_shadow (guidance + adherence in one record)
"""
from __future__ import annotations

import json
import sqlite3
from typing import Optional

from backend.core.logger import logger
from backend.core.skeleton_realizer.schema import (
    AdherenceRecord,
    RealizerInput,
    SkeletonGuidance,
)


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS skeleton_guidance_shadow (
            record_id       TEXT PRIMARY KEY,
            turn_id         TEXT NOT NULL,
            thread_id       TEXT NOT NULL,

            -- Realizer input (NiaCore heads)
            depth           INTEGER NOT NULL,
            respond_mode    TEXT NOT NULL,
            tone_bias       TEXT NOT NULL,
            structure       TEXT NOT NULL,
            relation_posture TEXT NOT NULL,
            hesitation      REAL NOT NULL,
            attention_target TEXT NOT NULL,

            -- Realizer output
            structured_header TEXT NOT NULL,
            interpretation_lines TEXT NOT NULL,  -- JSON array
            full_text       TEXT NOT NULL,
            line_count      INTEGER NOT NULL,

            -- Adherence
            mode_adherence      TEXT,
            target_adherence    TEXT,
            posture_adherence   TEXT,
            tone_adherence      TEXT,
            structure_adherence TEXT,
            composite_score     REAL,

            -- §13: 還流分類
            low_adherence_detected INTEGER NOT NULL DEFAULT 0,
            low_adherence_heads TEXT,  -- JSON array
            feedback_target     TEXT NOT NULL DEFAULT 'none',
            feedback_confidence TEXT NOT NULL DEFAULT 'unknown',
            conflict_detail     TEXT,

            created_at      TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_sgs_thread
        ON skeleton_guidance_shadow(thread_id);
        CREATE INDEX IF NOT EXISTS idx_sgs_created
        ON skeleton_guidance_shadow(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_sgs_low
        ON skeleton_guidance_shadow(low_adherence_detected)
        WHERE low_adherence_detected = 1;
    """)
    logger.info("[SKELETON_REALIZER] Schema ensured")


def save_shadow_record(
    conn: sqlite3.Connection,
    record: AdherenceRecord,
) -> None:
    """Save a shadow guidance + adherence record."""
    inp = record.realizer_input
    guidance = record.skeleton_guidance
    scores = record.adherence_scores

    conn.execute(
        """INSERT OR REPLACE INTO skeleton_guidance_shadow (
            record_id, turn_id, thread_id,
            depth, respond_mode, tone_bias, structure, relation_posture,
            hesitation, attention_target,
            structured_header, interpretation_lines, full_text, line_count,
            mode_adherence, target_adherence, posture_adherence,
            tone_adherence, structure_adherence, composite_score,
            low_adherence_detected, low_adherence_heads,
            feedback_target, feedback_confidence, conflict_detail,
            created_at
        ) VALUES (
            ?,?,?, ?,?,?,?,?, ?,?, ?,?,?,?, ?,?,?, ?,?,?, ?,?, ?,?,?, ?
        )""",
        (
            record.record_id, record.turn_id, record.thread_id,
            inp.depth, inp.respond_mode.value, inp.tone_bias.value,
            inp.structure.value, inp.relation_posture.value,
            inp.hesitation, inp.attention_target.value,
            guidance.structured_header,
            json.dumps(guidance.interpretation_lines, ensure_ascii=False),
            guidance.full_text,
            guidance.line_count,
            scores.mode_adherence.value if scores.mode_adherence else None,
            scores.target_adherence.value if scores.target_adherence else None,
            scores.posture_adherence.value if scores.posture_adherence else None,
            scores.tone_adherence.value if scores.tone_adherence else None,
            scores.structure_adherence.value if scores.structure_adherence else None,
            scores.composite_score,
            1 if record.low_adherence_detected else 0,
            json.dumps(record.low_adherence_heads),
            record.feedback_target.value,
            record.feedback_confidence.value,
            record.conflict_detail,
            record.created_at,
        ),
    )


def list_shadow_records(
    conn: sqlite3.Connection,
    *,
    thread_id: Optional[str] = None,
    low_only: bool = False,
    limit: int = 50,
) -> list[dict]:
    """List shadow records for review."""
    where_parts = []
    params: list = []

    if thread_id:
        where_parts.append("thread_id = ?")
        params.append(thread_id)
    if low_only:
        where_parts.append("low_adherence_detected = 1")

    where = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    params.append(limit)

    rows = conn.execute(
        f"SELECT * FROM skeleton_guidance_shadow {where} ORDER BY created_at DESC LIMIT ?",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def get_adherence_stats(
    conn: sqlite3.Connection,
    *,
    thread_id: Optional[str] = None,
    days: int = 14,
) -> dict:
    """Get aggregate adherence stats within a time window.

    Uses created_at cutoff for the C.1→C.2 卒業条件 (直近14日平均).
    """
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    where_parts = [f"created_at >= '{cutoff}'"]
    params: list = []

    if thread_id:
        where_parts.append("thread_id = ?")
        params.append(thread_id)

    where = f"WHERE {' AND '.join(where_parts)}"

    row = conn.execute(
        f"""SELECT
            COUNT(*) as total,
            AVG(composite_score) as avg_composite,
            SUM(CASE WHEN low_adherence_detected = 1 THEN 1 ELSE 0 END) as low_count,
            SUM(CASE WHEN feedback_target = 'realizer_rule_issue' THEN 1 ELSE 0 END) as rule_issues,
            SUM(CASE WHEN feedback_target = 'prompt_stack_conflict' THEN 1 ELSE 0 END) as stack_conflicts,
            SUM(CASE WHEN feedback_target = 'llm_non_adherence' THEN 1 ELSE 0 END) as llm_issues
        FROM skeleton_guidance_shadow {where}""",
        params,
    ).fetchone()

    return dict(row) if row else {}
