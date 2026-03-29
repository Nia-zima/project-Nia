"""
Somatic Feedback — record whether somatic senses were correct.

Design doc: docs/somatic_self_awareness_design.md
Phase S.1b: feedback recording + correction/dissonance detection.

No LLM calls. All rule-based.
"""
from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field

from backend.core.logger import logger


@dataclass
class SomaticOutcome:
    """A single feedback record for a somatic sense."""

    id: str = ""
    thread_id: str = ""
    turn_id: str = ""
    query: str = ""
    sense_text: str = ""
    intensity: float = 0.0
    outcome: str = "unknown"  # "confirmed" / "contradicted" / "ignored"
    correction_source: str = ""  # "user_correction" / "self_dissonance" / ""
    created_at: float = 0.0


# ── Correction detection ─────────────────────────────────────


_CORRECTION_PATTERNS = [
    re.compile(r"違う[よねぞ。！]?"),
    re.compile(r"それは別"),
    re.compile(r"そうじゃな[いくて]"),
    re.compile(r"覚えてな[いく]"),
    re.compile(r"そんなこと[はを]?言ってな[いく]"),
    re.compile(r"間違[いえっ]"),
    re.compile(r"記憶違い"),
    re.compile(r"勘違い"),
    re.compile(r"ちがう"),
    re.compile(r"ちゃうちゃう"),
    re.compile(r"[Nn]o[,.]?\s*[Tt]hat'?s?\s*(not|wrong)", re.IGNORECASE),
]


def detect_correction(user_response: str) -> bool:
    """Detect if user is correcting Nia's memory-based statement.

    Rule-based regex check against known correction phrases.
    Returns True if any correction pattern matches.
    """
    if not user_response:
        return False
    for pattern in _CORRECTION_PATTERNS:
        if pattern.search(user_response):
            return True
    return False


# ── NiaCore correction strength classification ──────────────────

_STRONG_CORRECTION_PATTERNS = [
    re.compile(r"違う[よねぞ。！]?"),
    re.compile(r"そうじゃな[いくて]"),
    re.compile(r"覚えてな[いく]"),
    re.compile(r"そんなこと[はを]?言ってな[いく]"),
    re.compile(r"間違[いえっ]"),
    re.compile(r"記憶違い"),
    re.compile(r"ちがう"),
    re.compile(r"ちゃうちゃう"),
    re.compile(r"[Nn]o[,.]?\s*[Tt]hat'?s?\s*(not|wrong)", re.IGNORECASE),
]

_WEAK_CORRECTION_PATTERNS = [
    re.compile(r"それは別"),
    re.compile(r"勘違い"),
]


def detect_correction_level(user_response: str) -> str:
    """Classify correction strength: 'strong', 'weak', or 'none'.

    strong: Unambiguous negation/correction — used as NiaCore reward signal.
    weak: Soft redirection — logged but not used for reward.
    none: No correction detected.

    Design doc: docs/niacore_lnn_design.md §3.2
    """
    if not user_response:
        return "none"
    for pattern in _STRONG_CORRECTION_PATTERNS:
        if pattern.search(user_response):
            return "strong"
    for pattern in _WEAK_CORRECTION_PATTERNS:
        if pattern.search(user_response):
            return "weak"
    return "none"


# ── Self-dissonance detection ─────────────────────────────────


def detect_self_dissonance(
    sense_text: str,
    nia_response: str,
    retrieved_contents: list[str] | None = None,
) -> bool:
    """Detect mismatch between somatic sense and Nia's actual response.

    Heuristic: if the sense said "clearly remember" but Nia's response
    contains hedging/uncertainty language, that's a dissonance.
    """
    if not sense_text or not nia_response:
        return False

    # High confidence sense + uncertain response
    high_conf_markers = ["はっきり覚えている", "自信がある"]
    uncertain_markers = [
        "わからない", "分からない", "記憶にない", "覚えてない",
        "思い出せない", "はっきりしない", "曖昧", "定かではない",
    ]

    sense_is_confident = any(m in sense_text for m in high_conf_markers)
    response_is_uncertain = any(m in nia_response for m in uncertain_markers)

    if sense_is_confident and response_is_uncertain:
        return True

    # Low confidence sense + assertive response
    low_conf_markers = ["記憶にない", "自信がない", "曖昧"]
    assertive_markers = ["はっきり", "確かに", "間違いなく"]

    sense_is_unsure = any(m in sense_text for m in low_conf_markers)
    response_is_assertive = any(m in nia_response for m in assertive_markers)

    if sense_is_unsure and response_is_assertive:
        return True

    return False


# ── Recording ─────────────────────────────────────────────────


def record_outcome(
    outcome: SomaticOutcome,
) -> None:
    """Persist a somatic feedback outcome to the somatic_log table."""
    try:
        from backend.core.db import managed_conn

        if not outcome.id:
            outcome.id = uuid.uuid4().hex
        if not outcome.created_at:
            outcome.created_at = time.time()

        with managed_conn() as conn:
            conn.execute(
                """
                INSERT INTO somatic_log
                    (id, thread_id, turn_id, query, sense_text, intensity,
                     outcome, correction_source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    outcome.id,
                    outcome.thread_id,
                    outcome.turn_id,
                    outcome.query,
                    outcome.sense_text,
                    outcome.intensity,
                    outcome.outcome,
                    outcome.correction_source,
                    outcome.created_at,
                ),
            )
    except Exception:
        logger.warning("[SomaticFeedback] record_outcome failed", exc_info=True)


def record_outcomes_batch(
    outcomes: list[SomaticOutcome],
) -> int:
    """Persist multiple somatic feedback outcomes in one transaction.

    Returns the number of successfully inserted rows.
    """
    if not outcomes:
        return 0
    try:
        from backend.core.db import managed_conn

        now = time.time()
        rows = []
        for o in outcomes:
            if not o.id:
                o.id = uuid.uuid4().hex
            if not o.created_at:
                o.created_at = now
            rows.append((
                o.id, o.thread_id, o.turn_id, o.query,
                o.sense_text, o.intensity, o.outcome,
                o.correction_source, o.created_at,
            ))

        with managed_conn() as conn:
            conn.executemany(
                """
                INSERT INTO somatic_log
                    (id, thread_id, turn_id, query, sense_text, intensity,
                     outcome, correction_source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        return len(rows)
    except Exception:
        logger.warning("[SomaticFeedback] record_outcomes_batch failed", exc_info=True)
        return 0


# ── Accuracy queries ──────────────────────────────────────────


def get_recent_accuracy(thread_id: str = "", n: int = 20) -> tuple[float, int]:
    """Return (accuracy, sample_count) from the last *n* somatic outcomes.

    accuracy = confirmed / (confirmed + contradicted).
    Outcomes with outcome='ignored' or 'unknown' are excluded.
    Returns (1.0, 0) when no relevant samples exist.
    """
    try:
        from backend.core.db import managed_conn

        with managed_conn() as conn:
            if thread_id:
                rows = conn.execute(
                    """
                    SELECT outcome FROM somatic_log
                    WHERE thread_id = ? AND outcome IN ('confirmed', 'contradicted')
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (thread_id, n),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT outcome FROM somatic_log
                    WHERE outcome IN ('confirmed', 'contradicted')
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (n,),
                ).fetchall()

        if not rows:
            return 1.0, 0

        confirmed = sum(1 for r in rows if r[0] == "confirmed")
        total = len(rows)
        return confirmed / total, total
    except Exception:
        logger.warning("[SomaticFeedback] get_recent_accuracy failed", exc_info=True)
        return 1.0, 0


def has_recent_contradiction(thread_id: str = "", lookback_turns: int = 3) -> bool:
    """Check if any of the last *lookback_turns* outcomes was a contradiction."""
    try:
        from backend.core.db import managed_conn

        with managed_conn() as conn:
            if thread_id:
                row = conn.execute(
                    """
                    SELECT COUNT(*) FROM (
                        SELECT outcome FROM somatic_log
                        WHERE thread_id = ? ORDER BY created_at DESC LIMIT ?
                    ) WHERE outcome = 'contradicted'
                    """,
                    (thread_id, lookback_turns),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT COUNT(*) FROM (
                        SELECT outcome FROM somatic_log
                        ORDER BY created_at DESC LIMIT ?
                    ) WHERE outcome = 'contradicted'
                    """,
                    (lookback_turns,),
                ).fetchone()
        return bool(row and row[0] > 0)
    except Exception:
        logger.warning("[SomaticFeedback] has_recent_contradiction failed", exc_info=True)
        return False
