"""Rule-based proposal generation from aggregated signals.

No LLM. Maps detected failure/success signals to structured
ConversationAdaptationProposal objects.

Design doc: docs/failure_success_policy_design.md §3, §4, §7
"""
from __future__ import annotations

from datetime import datetime, timezone

from backend.core.logger import logger

from .schema import (
    ConversationAdaptationProposal,
    EffectPayload,
    HistoryBias,
    TeacherAtom,
    TracePayload,
    build_proposal_key,
)
from .signal_detector import (
    FailureSignalSummary,
    SuccessSignalSummary,
    detect_failure_signals,
    detect_family_repetition,
    detect_success_signals,
)
from .writer import _now_iso, generate_id

# ── Thresholds ──────────────────────────────────────────────────────

# Failure: family repetition rate above which we generate a proposal
_FAMILY_REPEAT_RATE = 0.15  # 15% of turns in window

# Failure: correction strong count
_CORRECTION_STRONG_MIN = 2

# Failure: high hedge ratio threshold
_HIGH_HEDGE_RATE = 0.25  # 25% of turns have hedge_ratio > 0.5

# Success: minimum turns to generate a preference
_SUCCESS_MIN_TURNS = 10

# Minimum total turns in window to generate any proposal
_MIN_TURNS_FOR_PROPOSAL = 5

_CREATED_BY_FAILURE = "sleep_failure_to_policy_v0"
_CREATED_BY_SUCCESS = "sleep_success_to_preference_v0"


def _ts_to_iso(ts: float) -> str:
    """Convert UNIX timestamp to ISO 8601 UTC string."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


# ── Public API ──────────────────────────────────────────────────────

def _derive_thread_context(thread_id: str) -> tuple[str | None, str | None]:
    """Derive thread_mode and conversation_role from thread_id.

    Returns (thread_mode, conversation_role).
    """
    if thread_id.startswith("nero_meeting_"):
        return "meeting", "nero_meeting"
    if thread_id == "default_thread":
        return "default_thread", None
    return thread_id, None


def generate_proposals(
    thread_id: str = "default_thread",
    window_seconds: int = 86400,
) -> list[ConversationAdaptationProposal]:
    """Generate failure-to-policy and success-to-preference proposals.

    Called from Sleep Cycle. Returns proposals ready for save_proposal().
    """
    proposals: list[ConversationAdaptationProposal] = []

    failure = detect_failure_signals(thread_id, window_seconds)
    success = detect_success_signals(thread_id, window_seconds)
    family_counts, family_total, family_latest_ts = detect_family_repetition(thread_id, window_seconds)

    # Attach family info to failure summary
    failure.family_repeat_counts = family_counts
    failure.family_total_responses = family_total
    if family_counts:
        failure.dominant_family = max(family_counts, key=family_counts.get)
    # Merge family latest_ts into failure watermark
    if family_latest_ts > failure.latest_source_ts:
        failure.latest_source_ts = family_latest_ts

    # Source-data watermark: the latest observation timestamp across all
    # sources.  Used as last_seen_at so that the writer can distinguish
    # "new data arrived" from "same data re-processed".
    failure_watermark = _ts_to_iso(failure.latest_source_ts) if failure.latest_source_ts else _now_iso()
    success_watermark = _ts_to_iso(success.latest_source_ts) if success.latest_source_ts else _now_iso()

    thread_mode, conversation_role = _derive_thread_context(thread_id)

    # Generate failure proposals
    proposals.extend(_generate_family_repetition_proposals(failure, failure_watermark))
    proposals.extend(_generate_correction_proposals(failure, failure_watermark))
    proposals.extend(_generate_hedge_proposals(failure, failure_watermark))

    # Generate success proposals
    proposals.extend(_generate_diversity_preference(success, success_watermark))
    proposals.extend(_generate_relational_preference(success, success_watermark))

    # Stamp thread context onto all proposals and regenerate proposal_key
    for p in proposals:
        p.thread_mode = thread_mode
        p.conversation_role = conversation_role
        p.proposal_key = build_proposal_key(
            proposal_kind=p.proposal_kind,
            scope=p.scope,
            priority=p.priority,
            thread_mode=p.thread_mode,
            conversation_role=p.conversation_role,
            trigger_type=p.trigger_type,
            target_layer=p.target_layer,
            condition_json=p.condition_json,
            effect_json=p.effect_json.model_dump(mode="json"),
            created_by=p.created_by,
        )

    if proposals:
        logger.info(
            "[ProposalGenerator] generated %d proposals (failure=%d, success=%d)",
            len(proposals),
            sum(1 for p in proposals if p.proposal_kind == "failure_policy"),
            sum(1 for p in proposals if p.proposal_kind == "success_preference"),
        )

    return proposals


# ── Failure proposal generators ─────────────────────────────────────

def _generate_family_repetition_proposals(
    failure: FailureSignalSummary,
    watermark: str,
) -> list[ConversationAdaptationProposal]:
    """Generate proposals for semantic family repetition."""
    denominator = failure.family_total_responses
    if denominator < _MIN_TURNS_FOR_PROPOSAL:
        return []

    proposals = []
    for family, count in failure.family_repeat_counts.items():
        rate = count / denominator if denominator > 0 else 0
        if rate < _FAMILY_REPEAT_RATE:
            continue

        now = _now_iso()
        proposals.append(
            ConversationAdaptationProposal(
                proposal_id=generate_id(),
                proposal_kind="failure_policy",
                trigger_type="repetition",
                target_layer="history_selection",
                condition_json={
                    "semantic_state": {
                        "repeated_family": [family],
                        "family_repeat_rate": round(rate, 3),
                    },
                },
                trace_json=TracePayload(
                    axes={"agency": 0.1, "expressive_diversity": 0.1},
                    observed_patterns=["semantic_family_repeat", "same_opener_family"],
                    source_summary={
                        "expression": [f"family={family}", f"rate={rate:.2f}"],
                    },
                ),
                effect_json=EffectPayload(
                    history_bias=HistoryBias(
                        downrank_families=[family],
                        cap_same_family=1,
                        avoid_trace_match=["same_opener_family"],
                    ),
                    teacher_atoms=[
                        TeacherAtom(
                            head="intent",
                            channel="transition",
                            direction="away_from",
                            label="same_family_reentry",
                            weight=min(0.9, rate * 3),
                        ),
                        TeacherAtom(
                            head="expression",
                            channel="opener",
                            direction="diversify",
                            label="same_opener_family",
                            weight=min(0.8, rate * 2.5),
                        ),
                    ],
                ),
                first_seen_at=watermark,
                last_seen_at=watermark,
                created_at=now,
                updated_at=now,
                created_by=_CREATED_BY_FAILURE,
            )
        )
    return proposals


def _generate_correction_proposals(
    failure: FailureSignalSummary,
    watermark: str,
) -> list[ConversationAdaptationProposal]:
    """Generate proposals for repeated corrections."""
    if failure.expression_turns < _MIN_TURNS_FOR_PROPOSAL:
        return []
    if failure.correction_strong_count < _CORRECTION_STRONG_MIN:
        return []

    now = _now_iso()
    rate = failure.correction_strong_count / failure.expression_turns
    return [
        ConversationAdaptationProposal(
            proposal_id=generate_id(),
            proposal_kind="failure_policy",
            trigger_type="correction",
            target_layer="history_selection",
            condition_json={
                "correction_state": {
                    "strong_count": failure.correction_strong_count,
                    "weak_count": failure.correction_weak_count,
                    "rate": round(rate, 3),
                },
            },
            trace_json=TracePayload(
                axes={"relational": 0.3},
                observed_patterns=["correction_strong_repeated"],
                source_summary={
                    "somatic_feedback": [
                        f"strong={failure.correction_strong_count}",
                        f"weak={failure.correction_weak_count}",
                    ],
                },
            ),
            effect_json=EffectPayload(
                history_bias=HistoryBias(
                    avoid_trace_match=["correction_strong_repeated"],
                ),
                teacher_atoms=[
                    TeacherAtom(
                        head="intent",
                        channel="alignment",
                        direction="toward",
                        label="repair_alignment_directly",
                        weight=min(0.9, rate * 4),
                    ),
                    TeacherAtom(
                        head="attention",
                        channel="repair",
                        direction="toward",
                        label="user_repair_signal",
                        weight=0.7,
                    ),
                ],
            ),
            first_seen_at=watermark,
            last_seen_at=watermark,
            created_at=now,
            updated_at=now,
            created_by=_CREATED_BY_FAILURE,
        )
    ]


def _generate_hedge_proposals(
    failure: FailureSignalSummary,
    watermark: str,
) -> list[ConversationAdaptationProposal]:
    """Generate proposals for excessive hedging."""
    if failure.expression_turns < _MIN_TURNS_FOR_PROPOSAL:
        return []
    high_hedge_rate = failure.high_hedge_turn_count / failure.expression_turns if failure.expression_turns > 0 else 0
    if high_hedge_rate < _HIGH_HEDGE_RATE:
        return []

    now = _now_iso()
    return [
        ConversationAdaptationProposal(
            proposal_id=generate_id(),
            proposal_kind="failure_policy",
            trigger_type="directness",
            target_layer="history_selection",
            condition_json={
                "expression_state": {
                    "avg_hedge_ratio": round(failure.avg_hedge_ratio, 3),
                    "high_hedge_rate": round(high_hedge_rate, 3),
                },
            },
            trace_json=TracePayload(
                axes={"expressive_diversity": 0.2},
                observed_patterns=["hedge_dense"],
                source_summary={
                    "expression": [
                        f"avg_hedge={failure.avg_hedge_ratio:.2f}",
                        f"high_rate={high_hedge_rate:.2f}",
                    ],
                },
            ),
            effect_json=EffectPayload(
                history_bias=HistoryBias(
                    avoid_trace_match=["hedge_dense"],
                ),
                teacher_atoms=[
                    TeacherAtom(
                        head="expression",
                        channel="stance",
                        direction="away_from",
                        label="hedge_dense",
                        weight=min(0.8, high_hedge_rate * 2),
                    ),
                ],
            ),
            first_seen_at=watermark,
            last_seen_at=watermark,
            created_at=now,
            updated_at=now,
            created_by=_CREATED_BY_FAILURE,
        )
    ]


# ── Success proposal generators ─────────────────────────────────────

def _generate_diversity_preference(
    success: SuccessSignalSummary,
    watermark: str,
) -> list[ConversationAdaptationProposal]:
    """Generate preference for expressive diversity when observed."""
    if success.expression_turns < _SUCCESS_MIN_TURNS:
        return []
    if success.low_hedge_turn_count == 0:
        return []

    confident_rate = success.low_hedge_turn_count / success.expression_turns
    if confident_rate < 0.1:
        return []

    now = _now_iso()
    return [
        ConversationAdaptationProposal(
            proposal_id=generate_id(),
            proposal_kind="success_preference",
            trigger_type="positive_trace",
            target_layer="history_selection",
            condition_json={
                "expression_state": {
                    "confident_rate": round(confident_rate, 3),
                    "retrieval_hit_count": success.retrieval_hit_count,
                },
            },
            trace_json=TracePayload(
                axes={
                    "agency": 0.3,
                    "expressive_diversity": 0.6,
                },
                observed_patterns=["confident_expression", "diverse_opener"],
                source_summary={
                    "expression": [
                        f"confident_rate={confident_rate:.2f}",
                        f"retrieval_hits={success.retrieval_hit_count}",
                    ],
                },
            ),
            effect_json=EffectPayload(
                history_bias=HistoryBias(
                    prefer_trace_match=["confident_expression"],
                ),
                teacher_atoms=[
                    TeacherAtom(
                        head="expression",
                        channel="stance",
                        direction="toward",
                        label="fragile_open",
                        weight=min(0.8, confident_rate * 3),
                    ),
                ],
            ),
            first_seen_at=watermark,
            last_seen_at=watermark,
            created_at=now,
            updated_at=now,
            created_by=_CREATED_BY_SUCCESS,
        )
    ]


def _generate_relational_preference(
    success: SuccessSignalSummary,
    watermark: str,
) -> list[ConversationAdaptationProposal]:
    """Generate preference for relational engagement when observed."""
    # Use skeleton_turns as denominator since relational signals come from skeletons
    denominator = success.skeleton_turns
    if denominator < _SUCCESS_MIN_TURNS:
        return []

    relational_count = success.fragile_observation_count + success.returning_theme_count
    if relational_count == 0:
        return []

    relational_rate = relational_count / denominator
    now = _now_iso()
    return [
        ConversationAdaptationProposal(
            proposal_id=generate_id(),
            proposal_kind="success_preference",
            trigger_type="positive_trace",
            target_layer="history_selection",
            condition_json={
                "skeleton_state": {
                    "fragile_observation_count": success.fragile_observation_count,
                    "returning_theme_count": success.returning_theme_count,
                },
            },
            trace_json=TracePayload(
                axes={
                    "relational": 0.8,
                    "continuity": 0.5,
                },
                observed_patterns=["relational_engagement", "returning_theme_present"],
                source_summary={
                    "skeleton": [
                        f"fragile_obs={success.fragile_observation_count}",
                        f"returning_theme={success.returning_theme_count}",
                    ],
                },
            ),
            effect_json=EffectPayload(
                history_bias=HistoryBias(
                    prefer_trace_match=["relational_engagement"],
                ),
                teacher_atoms=[
                    TeacherAtom(
                        head="intent",
                        channel="initiative",
                        direction="toward",
                        label="reconnect_prior_theme",
                        weight=min(0.8, relational_rate * 4),
                    ),
                    TeacherAtom(
                        head="attention",
                        channel="theme_binding",
                        direction="toward",
                        label="shared_theme",
                        weight=0.6,
                    ),
                ],
            ),
            first_seen_at=watermark,
            last_seen_at=watermark,
            created_at=now,
            updated_at=now,
            created_by=_CREATED_BY_SUCCESS,
        )
    ]
