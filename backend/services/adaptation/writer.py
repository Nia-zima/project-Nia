"""Conversation Adaptation: fire-and-forget DB writer.

Phase A: records proposals and evidence into DB.
No runtime connection — observation only.

Design doc: docs/failure_success_policy_design.md §5, §10 Phase A
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone

from backend.core.config import settings
from backend.core.db import managed_conn
from backend.core.logger import logger

from .schema import (
    ConversationAdaptationEvidence,
    ConversationAdaptationProposal,
    ProposalStatus,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso8601(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _support_delta(current_support_count: int) -> int:
    return current_support_count if current_support_count > 0 else 1


def save_proposal(proposal: ConversationAdaptationProposal) -> str | None:
    """Insert or merge one proposal row. Returns the canonical proposal_id."""
    try:
        with managed_conn() as conn:
            existing = conn.execute(
                """SELECT proposal_id, first_seen_at, last_seen_at, expires_at
                   FROM conversation_adaptation_proposals
                   WHERE proposal_key = ?""",
                (proposal.proposal_key,),
            ).fetchone()

            if existing:
                first_seen_at = existing["first_seen_at"] or proposal.first_seen_at
                if _parse_iso8601(proposal.first_seen_at) < _parse_iso8601(first_seen_at):
                    first_seen_at = proposal.first_seen_at

                old_last_seen = existing["last_seen_at"] or proposal.last_seen_at
                last_seen_at = old_last_seen
                window_advanced = False
                if _parse_iso8601(proposal.last_seen_at) > _parse_iso8601(old_last_seen):
                    last_seen_at = proposal.last_seen_at
                    window_advanced = True

                expires_at = existing["expires_at"]
                if proposal.expires_at is not None:
                    if expires_at is None or _parse_iso8601(proposal.expires_at) > _parse_iso8601(expires_at):
                        expires_at = proposal.expires_at

                # Only increment support when the observation window has
                # actually advanced.  Re-running the same Sleep Cycle on
                # the same 24h window must NOT inflate support_count.
                support_delta = 1 if window_advanced else 0

                conn.execute(
                    """UPDATE conversation_adaptation_proposals
                       SET trace_json = ?,
                           validation_json = COALESCE(?, validation_json),
                           lineage_json = COALESCE(?, lineage_json),
                           confidence = COALESCE(?, confidence),
                           support_count = support_count + ?,
                           contradiction_count = contradiction_count + ?,
                           first_seen_at = ?,
                           last_seen_at = ?,
                           expires_at = ?,
                           updated_at = ?
                       WHERE proposal_key = ?""",
                    (
                        proposal.trace_json.model_dump_json(),
                        json.dumps(proposal.validation_json, ensure_ascii=False) if proposal.validation_json else None,
                        json.dumps(proposal.lineage_json, ensure_ascii=False) if proposal.lineage_json else None,
                        proposal.confidence,
                        support_delta,
                        proposal.contradiction_count,
                        first_seen_at,
                        last_seen_at,
                        expires_at,
                        proposal.updated_at,
                        proposal.proposal_key,
                    ),
                )
                canonical_id = str(existing["proposal_id"])
            else:
                conn.execute(
                    """INSERT INTO conversation_adaptation_proposals
                       (proposal_id, proposal_key, proposal_kind, status, scope, priority,
                        thread_mode, conversation_role, trigger_type, target_layer,
                        condition_json, trace_json, effect_json,
                        validation_json, lineage_json,
                        confidence, support_count, contradiction_count,
                        first_seen_at, last_seen_at, expires_at,
                        created_at, updated_at,
                        supersedes_proposal_id, created_by)
                       VALUES (?, ?, ?, ?, ?, ?,
                               ?, ?, ?, ?,
                               ?, ?, ?,
                               ?, ?,
                               ?, ?, ?,
                               ?, ?, ?,
                               ?, ?,
                               ?, ?)""",
                    (
                        proposal.proposal_id,
                        proposal.proposal_key,
                        proposal.proposal_kind,
                        proposal.status,
                        proposal.scope,
                        proposal.priority,
                        proposal.thread_mode,
                        proposal.conversation_role,
                        proposal.trigger_type,
                        proposal.target_layer,
                        json.dumps(proposal.condition_json, ensure_ascii=False),
                        proposal.trace_json.model_dump_json(),
                        proposal.effect_json.model_dump_json(),
                        json.dumps(proposal.validation_json, ensure_ascii=False) if proposal.validation_json else None,
                        json.dumps(proposal.lineage_json, ensure_ascii=False) if proposal.lineage_json else None,
                        proposal.confidence,
                        proposal.support_count,
                        proposal.contradiction_count,
                        proposal.first_seen_at,
                        proposal.last_seen_at,
                        proposal.expires_at,
                        proposal.created_at,
                        proposal.updated_at,
                        proposal.supersedes_proposal_id,
                        proposal.created_by,
                    ),
                )
                canonical_id = proposal.proposal_id
        logger.debug(
            "[Adaptation] proposal saved: id=%s key=%s kind=%s trigger=%s",
            canonical_id,
            proposal.proposal_key,
            proposal.proposal_kind,
            proposal.trigger_type,
            )
        return canonical_id
    except Exception:
        logger.warning("[Adaptation] proposal write failed", exc_info=True)
        return None


def save_evidence(evidence: ConversationAdaptationEvidence) -> str | None:
    """Insert one evidence row. Returns evidence_id on success, None on failure."""
    try:
        with managed_conn() as conn:
            conn.execute(
                """INSERT INTO conversation_adaptation_evidence
                   (evidence_id, proposal_id, thread_id, turn_id, message_id,
                    evidence_kind, evidence_source, evidence_weight,
                    payload_json, observed_at)
                   VALUES (?, ?, ?, ?, ?,
                           ?, ?, ?,
                           ?, ?)""",
                (
                    evidence.evidence_id,
                    evidence.proposal_id,
                    evidence.thread_id,
                    evidence.turn_id,
                    evidence.message_id,
                    evidence.evidence_kind,
                    evidence.evidence_source,
                    evidence.evidence_weight,
                    json.dumps(evidence.payload_json, ensure_ascii=False),
                    evidence.observed_at,
                ),
            )
        logger.debug(
            "[Adaptation] evidence saved: id=%s proposal=%s kind=%s",
            evidence.evidence_id,
            evidence.proposal_id,
            evidence.evidence_kind,
        )
        return evidence.evidence_id
    except sqlite3.IntegrityError:
        logger.warning(
            "[Adaptation] evidence FK violation: proposal=%s", evidence.proposal_id,
        )
        return None
    except Exception:
        logger.warning("[Adaptation] evidence write failed", exc_info=True)
        return None


def update_proposal_status(
    proposal_id: str,
    new_status: ProposalStatus,
    *,
    validation_json: dict | None = None,
) -> bool:
    """Update a proposal's status and optionally its validation result."""
    try:
        now = _now_iso()
        with managed_conn() as conn:
            if validation_json is not None:
                result = conn.execute(
                    """UPDATE conversation_adaptation_proposals
                       SET status = ?, validation_json = ?, updated_at = ?
                       WHERE proposal_id = ?""",
                    (new_status, json.dumps(validation_json, ensure_ascii=False), now, proposal_id),
                )
            else:
                result = conn.execute(
                    """UPDATE conversation_adaptation_proposals
                       SET status = ?, updated_at = ?
                       WHERE proposal_id = ?""",
                    (new_status, now, proposal_id),
                )
        if result.rowcount == 0:
            logger.warning("[Adaptation] proposal not found for status update: %s", proposal_id)
            return False
        logger.debug("[Adaptation] proposal %s -> %s", proposal_id, new_status)
        return True
    except Exception:
        logger.warning("[Adaptation] status update failed: %s", proposal_id, exc_info=True)
        return False


def increment_support(proposal_id: str) -> bool:
    """Increment support_count for a proposal."""
    try:
        now = _now_iso()
        with managed_conn() as conn:
            result = conn.execute(
                """UPDATE conversation_adaptation_proposals
                   SET support_count = support_count + 1,
                       last_seen_at = ?, updated_at = ?
                   WHERE proposal_id = ?""",
                (now, now, proposal_id),
            )
        if result.rowcount == 0:
            logger.warning("[Adaptation] proposal not found for increment_support: %s", proposal_id)
            return False
        return True
    except Exception:
        logger.warning("[Adaptation] increment_support failed: %s", proposal_id, exc_info=True)
        return False


def increment_contradiction(proposal_id: str) -> bool:
    """Increment contradiction_count for a proposal."""
    try:
        now = _now_iso()
        with managed_conn() as conn:
            result = conn.execute(
                """UPDATE conversation_adaptation_proposals
                   SET contradiction_count = contradiction_count + 1,
                       last_seen_at = ?, updated_at = ?
                   WHERE proposal_id = ?""",
                (now, now, proposal_id),
            )
        if result.rowcount == 0:
            logger.warning("[Adaptation] proposal not found for increment_contradiction: %s", proposal_id)
            return False
        return True
    except Exception:
        logger.warning("[Adaptation] increment_contradiction failed: %s", proposal_id, exc_info=True)
        return False


def generate_id() -> str:
    """Generate a hex UUID for proposal/evidence IDs."""
    return uuid.uuid4().hex


def record_proposal(proposal: ConversationAdaptationProposal) -> str | None:
    """Gate-aware facade for proposal recording."""
    if not getattr(settings, "ADAPTATION_RECORD_ENABLED", False):
        logger.debug("[Adaptation] proposal skipped: ADAPTATION_RECORD_ENABLED=false")
        return None
    return save_proposal(proposal)


def record_evidence(evidence: ConversationAdaptationEvidence) -> str | None:
    """Gate-aware facade for evidence recording."""
    if not getattr(settings, "ADAPTATION_RECORD_ENABLED", False):
        logger.debug("[Adaptation] evidence skipped: ADAPTATION_RECORD_ENABLED=false")
        return None
    return save_evidence(evidence)


def record_proposal_status_update(
    proposal_id: str,
    new_status: ProposalStatus,
    *,
    validation_json: dict | None = None,
) -> bool:
    """Gate-aware facade for proposal status changes."""
    if not getattr(settings, "ADAPTATION_RECORD_ENABLED", False):
        logger.debug("[Adaptation] status update skipped: ADAPTATION_RECORD_ENABLED=false")
        return False
    return update_proposal_status(
        proposal_id,
        new_status,
        validation_json=validation_json,
    )


def record_support(proposal_id: str) -> bool:
    """Gate-aware facade for support increments."""
    if not getattr(settings, "ADAPTATION_RECORD_ENABLED", False):
        logger.debug("[Adaptation] support skipped: ADAPTATION_RECORD_ENABLED=false")
        return False
    return increment_support(proposal_id)


def record_contradiction(proposal_id: str) -> bool:
    """Gate-aware facade for contradiction increments."""
    if not getattr(settings, "ADAPTATION_RECORD_ENABLED", False):
        logger.debug("[Adaptation] contradiction skipped: ADAPTATION_RECORD_ENABLED=false")
        return False
    return increment_contradiction(proposal_id)
