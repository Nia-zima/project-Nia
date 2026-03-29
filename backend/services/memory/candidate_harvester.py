"""Candidate Harvester — rule-based extraction of promotion candidates.

Runs after s5_commit to extract memory candidates from conversation turns.
No LLM calls. Pure rule-based extraction from available signals.

Signals used:
  - surprise_score (from awareness core)
  - dissonance_on (from dissonance check)
  - correction detection (from somatic feedback)
  - selected_depth (deeper = more noteworthy)
  - conversation_skeleton labels (if available)

Design doc: docs/data_store_map.md, Live化ロードマップ Phase A
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from backend.core.db import managed_conn
from backend.services.memory.governance_repository import insert_candidate
from backend.services.memory.models import RawPromotionCandidate

logger = logging.getLogger("nia")

# ── Extraction Rules ──────────────────────────────────────


@dataclass
class HarvestSignals:
    """Signals available at s5_commit time."""
    user_text: str = ""
    ai_response: str = ""
    selected_depth: int = 0
    surprise_score: float = 0.0
    dissonance_on: bool = False
    correction_level: str = "none"  # none / weak / strong
    merge_mode: str = ""
    # SkeletonCore (optional)
    skeleton_focus: Optional[str] = None
    skeleton_response_intent: Optional[str] = None
    skeleton_question_intent: Optional[str] = None
    # Provenance
    thread_id: str = ""
    turn_id: str = ""
    message_id: Optional[str] = None
    stream_id: Optional[str] = None


def _should_harvest(signals: HarvestSignals) -> list[tuple[str, str]]:
    """Determine if this turn should produce candidates.

    Returns list of (candidate_kind_rough, reason) tuples.
    Empty list = no candidates.
    """
    candidates: list[tuple[str, str]] = []

    # H1: Strong correction → contradiction candidate
    if signals.correction_level == "strong":
        candidates.append(("contradiction", "H1:correction_strong"))

    # H2: Dissonance detected → dissonance candidate
    if signals.dissonance_on:
        candidates.append(("dissonance", "H2:dissonance_on"))

    # H3: High surprise → noteworthy event
    if signals.surprise_score >= 0.6:
        candidates.append(("surprise", "H3:surprise_high"))

    # H4: Depth 2 reached → deep processing event
    if signals.selected_depth >= 2:
        candidates.append(("deep_processing", "H4:depth2"))

    # H5: Skeleton detected contradiction focus
    if signals.skeleton_focus == "contradiction":
        # Don't duplicate if H1/H2 already fired
        if not any(k == "contradiction" for k, _ in candidates):
            candidates.append(("contradiction", "H5:skeleton_contradiction"))

    # H6: Skeleton detected emotional state with high surprise
    if signals.skeleton_focus == "emotional_state" and signals.surprise_score >= 0.3:
        candidates.append(("emotional_pattern", "H6:emotional_surprise"))

    return candidates


def _build_candidate(
    kind: str,
    reason: str,
    signals: HarvestSignals,
    now: float,
) -> RawPromotionCandidate:
    """Build a RawPromotionCandidate from signals."""
    # Build a source_ref summarizing the turn content
    user_snippet = signals.user_text[:200] if signals.user_text else ""
    ai_snippet = signals.ai_response[:200] if signals.ai_response else ""
    source_ref = f"user: {user_snippet} | ai: {ai_snippet}"

    return RawPromotionCandidate(
        candidate_id=uuid.uuid4().hex,
        candidate_kind_rough=kind,
        source_type="turn_harvester",
        source_ref=source_ref[:500],
        topic_key=None,
        focus=signals.skeleton_focus,
        response_intent=signals.skeleton_response_intent,
        question_intent=signals.skeleton_question_intent,
        owner_agent="nia",
        memory_domain="default",
        status="pending",
        thread_id=signals.thread_id or None,
        turn_id=signals.turn_id or None,
        message_id=signals.message_id,
        stream_id=signals.stream_id,
        trace_id=reason,
        created_at=now,
        updated_at=now,
    )


# ── Public API ────────────────────────────────────────────


def harvest_candidates(signals: HarvestSignals) -> tuple[int, list[str]]:
    """Extract and save promotion candidates from a conversation turn.

    Returns (number of candidates inserted, list of triggered kind strings).
    Never raises.
    """
    try:
        matches = _should_harvest(signals)
        if not matches:
            logger.debug(
                "[CANDIDATE_HARVESTER] checked turn=%s, 0 candidates "
                "(depth=%d surprise=%.2f dissonance=%s correction=%s)",
                signals.turn_id, signals.selected_depth,
                signals.surprise_score, signals.dissonance_on,
                signals.correction_level,
            )
            return 0, []

        now = time.time()
        inserted = 0
        triggered_kinds: list[str] = []

        with managed_conn() as conn:
            for kind, reason in matches:
                candidate = _build_candidate(kind, reason, signals, now)
                insert_candidate(conn, candidate)
                inserted += 1
                triggered_kinds.append(kind)
                logger.debug(
                    "[CANDIDATE_HARVESTER] inserted %s (%s) turn=%s",
                    kind, reason, signals.turn_id,
                )

        if inserted:
            logger.info(
                "[CANDIDATE_HARVESTER] %d candidates from turn=%s",
                inserted, signals.turn_id,
            )
        return inserted, triggered_kinds

    except Exception:
        logger.debug("[CANDIDATE_HARVESTER] harvest failed", exc_info=True)
        return 0, []
