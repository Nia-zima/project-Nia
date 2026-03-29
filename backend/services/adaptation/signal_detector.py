"""Shared failure / success signal detection.

This module is the single source of truth for detecting conversation
quality signals. Both the Sleep Cycle (Phase B proposal generation)
and runtime triggers (open_reflection shaping) call the same functions.

Design doc: docs/failure_success_policy_design.md §3, §4
Design decision #16: trigger/evidence の判定ロジックを二重化しない
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from backend.core.agent_graph.nodes.helpers import (
    _SEMANTIC_FAMILIES,
    _SEMANTIC_FAMILY_THRESHOLD,
)
from backend.core.db import managed_conn
from backend.core.logger import logger


# ── Data classes ────────────────────────────────────────────────────

@dataclass
class FailureSignalSummary:
    """Aggregated failure signals for a time window."""

    # semantic family repetition (denominator: family_total_responses)
    family_repeat_counts: dict[str, int] = field(default_factory=dict)
    family_total_responses: int = 0
    dominant_family: str | None = None

    # correction (denominator: expression_turns)
    correction_strong_count: int = 0
    correction_weak_count: int = 0

    # contract / directness (denominator: expression_turns)
    hold_count: int = 0
    wait_count: int = 0

    # expression patterns (denominator: expression_turns)
    avg_hedge_ratio: float = 0.0
    high_hedge_turn_count: int = 0  # hedge_ratio > 0.5
    user_correction_count: int = 0
    expression_turns: int = 0

    # skeleton patterns (denominator: skeleton_turns)
    hold_intent_count: int = 0
    contradiction_focus_count: int = 0
    skeleton_turns: int = 0

    # Watermark: latest source row timestamp across all sources.
    # Used by writer to decide whether support_count should increment.
    latest_source_ts: float = 0.0

    @property
    def total_turns(self) -> int:
        """Best available turn count across sources."""
        return max(self.expression_turns, self.skeleton_turns, self.family_total_responses)


@dataclass
class SuccessSignalSummary:
    """Aggregated success signals for a time window."""

    # agency
    self_initiated_topic_count: int = 0

    # relational (denominator: skeleton_turns)
    fragile_observation_count: int = 0
    returning_theme_count: int = 0
    skeleton_turns: int = 0

    # expressive diversity (denominator: expression_turns)
    distinct_opener_families: int = 0
    opener_family_distribution: dict[str, int] = field(default_factory=dict)
    low_hedge_turn_count: int = 0  # hedge_ratio < 0.2 with assertion_ratio >= 0.3
    expression_turns: int = 0

    # continuity
    retrieval_hit_count: int = 0

    # Watermark: latest source row timestamp across all sources.
    latest_source_ts: float = 0.0

    @property
    def total_turns(self) -> int:
        """Best available turn count across sources."""
        return max(self.expression_turns, self.skeleton_turns)


# ── Failure detection ───────────────────────────────────────────────

def detect_failure_signals(
    thread_id: str = "default_thread",
    window_seconds: int = 86400,
) -> FailureSignalSummary:
    """Aggregate failure signals from observation tables over a time window.

    This is the shared detection function used by both Sleep Cycle and
    runtime triggers.
    """
    summary = FailureSignalSummary()
    try:
        with managed_conn() as conn:
            _fill_expression_failures(conn, thread_id, window_seconds, summary)
            _fill_skeleton_failures(conn, thread_id, window_seconds, summary)
            _fill_correction_failures(conn, thread_id, window_seconds, summary)
    except Exception:
        logger.warning("[SignalDetector] failure detection failed", exc_info=True)
    return summary


def _fill_expression_failures(
    conn: sqlite3.Connection,
    thread_id: str,
    window_seconds: int,
    summary: FailureSignalSummary,
) -> None:
    """Fill failure summary from expression_observations."""
    rows = conn.execute(
        """SELECT hedge_ratio, event_kind, user_correction, created_at
           FROM expression_observations
           WHERE thread_id = ?
             AND created_at >= (strftime('%s', 'now') - ?)
             AND event_kind IN ('spoken', 'hold', 'wait')
           ORDER BY created_at DESC""",
        (thread_id, window_seconds),
    ).fetchall()

    if not rows:
        return

    summary.expression_turns = len(rows)
    # rows are ORDER BY created_at DESC, so first row has the latest ts
    if rows:
        latest = float(rows[0][3] or 0)
        if latest > summary.latest_source_ts:
            summary.latest_source_ts = latest
    total_hedge = 0.0
    for row in rows:
        hedge = row[0] or 0.0
        event_kind = row[1] or "spoken"
        user_corr = row[2] or 0

        total_hedge += hedge
        if hedge > 0.5:
            summary.high_hedge_turn_count += 1
        if event_kind == "hold":
            summary.hold_count += 1
        elif event_kind == "wait":
            summary.wait_count += 1
        if user_corr:
            summary.user_correction_count += 1

    summary.avg_hedge_ratio = total_hedge / summary.expression_turns if summary.expression_turns else 0.0


def _fill_skeleton_failures(
    conn: sqlite3.Connection,
    thread_id: str,
    window_seconds: int,
    summary: FailureSignalSummary,
) -> None:
    """Fill failure summary from conversation_skeletons."""
    rows = conn.execute(
        """SELECT focus, response_intent, created_at
           FROM conversation_skeletons
           WHERE session_id = ?
             AND created_at >= (strftime('%s', 'now') - ?)
           ORDER BY created_at DESC""",
        (thread_id, window_seconds),
    ).fetchall()

    summary.skeleton_turns = len(rows)
    if rows:
        latest = float(rows[0][2] or 0)
        if latest > summary.latest_source_ts:
            summary.latest_source_ts = latest
    for row in rows:
        focus = row[0] or ""
        intent = row[1] or ""
        if focus == "contradiction":
            summary.contradiction_focus_count += 1
        if intent == "hold":
            summary.hold_intent_count += 1


def _fill_correction_failures(
    conn: sqlite3.Connection,
    thread_id: str,
    window_seconds: int,
    summary: FailureSignalSummary,
) -> None:
    """Fill correction counts from niacore_experience.

    Note: niacore_experience has user_correction (BOOLEAN) and session_id (not thread_id).
    We treat user_correction=1 as 'strong' correction (no weak/strong split in this table).
    For strong/weak distinction, somatic_feedback.detect_correction_level() is the source,
    but that data is not persisted per-turn in niacore_experience.
    """
    rows = conn.execute(
        """SELECT user_correction, created_at
           FROM niacore_experience
           WHERE session_id = ?
             AND created_at >= (strftime('%s', 'now') - ?)
             AND user_correction = 1
           ORDER BY created_at DESC""",
        (thread_id, window_seconds),
    ).fetchall()

    if rows:
        latest = float(rows[0][1] or 0)
        if latest > summary.latest_source_ts:
            summary.latest_source_ts = latest
    for _row in rows:
        # user_correction=1 is treated as strong (conservative)
        summary.correction_strong_count += 1


# ── Semantic family aggregation (shared) ────────────────────────────

def detect_family_repetition(
    thread_id: str = "default_thread",
    window_seconds: int = 86400,
) -> tuple[dict[str, int], int, float]:
    """Count semantic family occurrences in recent AI responses.

    Uses the same _SEMANTIC_FAMILIES from helpers.py to avoid
    divergence between runtime and Sleep-side detection.

    Source: memory_events table (event_type='conversation_turn'),
    payload_json["ai_response"].

    Returns: ({family_name: count}, total_responses, latest_ts)
    """
    counts: dict[str, int] = {}
    total_responses = 0
    latest_ts = 0.0
    try:
        with managed_conn() as conn:
            rows = conn.execute(
                """SELECT payload_json, created_at
                   FROM memory_events
                   WHERE thread_id = ?
                     AND event_type = 'conversation_turn'
                     AND created_at >= (strftime('%s', 'now') - ?)
                   ORDER BY created_at DESC
                   LIMIT 50""",
                (thread_id, window_seconds),
            ).fetchall()

        total_responses = len(rows)
        if rows:
            latest_ts = float(rows[0][1] or 0)
        import json as _json
        for row in rows:
            try:
                payload = _json.loads(row[0] or "{}")
                text = payload.get("ai_response", "")
            except (ValueError, TypeError):
                text = ""
            for family_name, markers in _SEMANTIC_FAMILIES.items():
                if any(m in text for m in markers):
                    counts[family_name] = counts.get(family_name, 0) + 1
    except Exception:
        logger.warning("[SignalDetector] family repetition detection failed", exc_info=True)
    return counts, total_responses, latest_ts


# ── Success detection ───────────────────────────────────────────────

def detect_success_signals(
    thread_id: str = "default_thread",
    window_seconds: int = 86400,
) -> SuccessSignalSummary:
    """Aggregate success signals from observation tables over a time window.

    This is the shared detection function used by both Sleep Cycle and
    runtime triggers.
    """
    summary = SuccessSignalSummary()
    try:
        with managed_conn() as conn:
            _fill_expression_successes(conn, thread_id, window_seconds, summary)
            _fill_skeleton_successes(conn, thread_id, window_seconds, summary)
    except Exception:
        logger.warning("[SignalDetector] success detection failed", exc_info=True)
    return summary


def _fill_expression_successes(
    conn: sqlite3.Connection,
    thread_id: str,
    window_seconds: int,
    summary: SuccessSignalSummary,
) -> None:
    """Fill success summary from expression_observations."""
    rows = conn.execute(
        """SELECT hedge_ratio, assertion_ratio, retrieval_hit, created_at
           FROM expression_observations
           WHERE thread_id = ?
             AND created_at >= (strftime('%s', 'now') - ?)
             AND event_kind = 'spoken'
           ORDER BY created_at DESC""",
        (thread_id, window_seconds),
    ).fetchall()

    if not rows:
        return

    summary.expression_turns = len(rows)
    latest = float(rows[0][3] or 0)
    if latest > summary.latest_source_ts:
        summary.latest_source_ts = latest
    for row in rows:
        hedge = row[0] or 0.0
        assertion = row[1] or 0.0
        retrieval = row[2] or 0

        if hedge < 0.2 and assertion >= 0.3:
            summary.low_hedge_turn_count += 1
        if retrieval:
            summary.retrieval_hit_count += 1


def _fill_skeleton_successes(
    conn: sqlite3.Connection,
    thread_id: str,
    window_seconds: int,
    summary: SuccessSignalSummary,
) -> None:
    """Fill success summary from conversation_skeletons."""
    rows = conn.execute(
        """SELECT focus, response_intent, created_at
           FROM conversation_skeletons
           WHERE session_id = ?
             AND created_at >= (strftime('%s', 'now') - ?)
           ORDER BY created_at DESC""",
        (thread_id, window_seconds),
    ).fetchall()

    summary.skeleton_turns = len(rows)
    if rows:
        latest = float(rows[0][2] or 0)
        if latest > summary.latest_source_ts:
            summary.latest_source_ts = latest
    for row in rows:
        focus = row[0] or ""
        intent = row[1] or ""
        if focus == "returning_theme":
            summary.returning_theme_count += 1
        if intent == "offer_fragile_self_observation":
            summary.fragile_observation_count += 1
