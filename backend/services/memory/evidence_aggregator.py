"""Evidence Aggregator — accumulate evidence for promotion candidates.

Runs after candidate_harvester in s5_commit. For each active candidate,
checks whether the current turn provides supporting evidence.

No LLM calls. Pure rule-based matching from available signals.

Design doc: docs/memory_promotion_redesign.md §3.3

Evidence matching rules (E1-E6):
  E1: Same skeleton focus as candidate → skeleton reinforcement
  E2: Same candidate_kind_rough triggered again → repetition reinforcement
  E3: Retrieval hit on candidate's source_ref → retrieval reinforcement
  E4: Correction absent → correction-free reinforcement (incremental trust)
  E5: Different source_type than existing evidence → source diversity
  E6: Different date than existing evidence → date spread
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

from backend.core.db import managed_conn
from backend.services.memory.governance_repository import (
    count_evidence_by_candidate,
    insert_evidence,
    list_active_candidates,
    update_candidate_status,
)
from backend.services.memory.models import MemoryEvidence, RawPromotionCandidate

logger = logging.getLogger("nia")

JST = timezone(timedelta(hours=9))

# ── Evidence matching thresholds ────────────────────────


# Status transitions
_ACCUMULATING_THRESHOLD = 1  # evidence >= 1 → accumulating
_READY_THRESHOLD = 3  # evidence >= 3 → ready_for_normalization (仮閾値, M0.5 で再調整)


# ── Signals ─────────────────────────────────────────────


@dataclass
class EvidenceSignals:
    """Signals available at s5_commit time for evidence matching."""

    # Current turn signals (same as HarvestSignals subset)
    selected_depth: int = 0
    surprise_score: float = 0.0
    correction_level: str = "none"  # none / weak / strong

    # SkeletonCore labels (optional)
    skeleton_focus: Optional[str] = None
    skeleton_response_intent: Optional[str] = None

    # Candidate kinds triggered this turn (from candidate_harvester)
    triggered_kinds: list[str] | None = None

    # Retrieval similarity (for retrieval reinforcement)
    retrieval_top_similarity: float = 0.0

    # Provenance
    thread_id: str = ""
    turn_id: str = ""
    message_id: Optional[str] = None
    stream_id: Optional[str] = None


# ── Matching rules ──────────────────────────────────────


def _match_candidate(
    candidate: RawPromotionCandidate,
    signals: EvidenceSignals,
) -> tuple[str, float] | None:
    """Check if current turn provides evidence for a candidate.

    Returns (source_type, reliability) or None if no match.
    Priority: first matching rule wins.
    """
    # E1: Skeleton focus match (same focus as candidate)
    if (
        signals.skeleton_focus
        and candidate.focus
        and signals.skeleton_focus == candidate.focus
    ):
        return "skeleton", 0.3  # skeleton evidence starts low

    # E2: Same kind triggered again (repetition reinforcement)
    if signals.triggered_kinds and candidate.candidate_kind_rough in signals.triggered_kinds:
        return "repetition", 0.5

    # E3: Retrieval reinforcement (disabled until candidate-specific matching exists)
    # Current retrieval_top_similarity is session-global, not candidate-specific.
    # Enabling this would attach evidence to ALL active candidates on any high-sim turn.
    # TODO: Re-enable when topic_key or anchor_id matching is available.

    # E4: Correction-free turn on a correction/contradiction candidate
    if (
        candidate.candidate_kind_rough in ("contradiction", "dissonance")
        and signals.correction_level == "none"
    ):
        # Only count if the candidate is already accumulating
        if candidate.status == "accumulating":
            return "correction_free", 0.3

    return None


# ── Public API ──────────────────────────────────────────


def aggregate_evidence(signals: EvidenceSignals) -> int:
    """Match current turn against active candidates and accumulate evidence.

    Returns the number of evidence records inserted. Never raises.
    """
    try:
        candidates = list_active_candidates(limit=200)
        if not candidates:
            return 0

        now = time.time()
        today = datetime.now(JST).strftime("%Y-%m-%d")
        inserted = 0

        with managed_conn() as conn:
            for candidate in candidates:
                match = _match_candidate(candidate, signals)
                if match is None:
                    continue

                source_type, reliability = match

                evidence = MemoryEvidence(
                    evidence_id=uuid.uuid4().hex,
                    candidate_id=candidate.candidate_id,
                    claim_id=None,
                    source_type=source_type,
                    source_ref=f"turn:{signals.turn_id}",
                    evidence_date=today,
                    reliability=reliability,
                    thread_id=signals.thread_id or None,
                    turn_id=signals.turn_id or None,
                    message_id=signals.message_id,
                    stream_id=signals.stream_id,
                    trace_id=f"E:{source_type}",
                    created_at=now,
                )
                insert_evidence(conn, evidence)
                inserted += 1

                # Status transitions
                ev_count = count_evidence_by_candidate(conn, candidate.candidate_id)
                if candidate.status == "pending" and ev_count >= _ACCUMULATING_THRESHOLD:
                    update_candidate_status(conn, candidate.candidate_id, "accumulating", now)
                    logger.debug(
                        "[EVIDENCE] %s → accumulating (ev=%d)",
                        candidate.candidate_id[:8], ev_count,
                    )
                elif candidate.status == "accumulating" and ev_count >= _READY_THRESHOLD:
                    update_candidate_status(conn, candidate.candidate_id, "ready_for_normalization", now)
                    logger.info(
                        "[EVIDENCE] %s → ready_for_normalization (ev=%d kind=%s)",
                        candidate.candidate_id[:8], ev_count, candidate.candidate_kind_rough,
                    )

        if inserted:
            logger.info(
                "[EVIDENCE] %d evidence from turn=%s (%d active candidates)",
                inserted, signals.turn_id, len(candidates),
            )
        return inserted

    except Exception:
        logger.debug("[EVIDENCE] aggregation failed", exc_info=True)
        return 0
