"""Conversation Adaptation: failure-to-policy / success-to-preference.

Design doc: docs/failure_success_policy_design.md
"""

from .schema import (
    ConversationAdaptationEvidence,
    ConversationAdaptationProposal,
)
from .writer import (
    generate_id,
    record_contradiction,
    record_evidence,
    record_proposal,
    record_proposal_status_update,
    record_support,
)

__all__ = [
    "ConversationAdaptationEvidence",
    "ConversationAdaptationProposal",
    "generate_id",
    "record_contradiction",
    "record_evidence",
    "record_proposal",
    "record_proposal_status_update",
    "record_support",
]
