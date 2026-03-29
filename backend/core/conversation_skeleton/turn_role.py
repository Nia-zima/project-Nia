"""Turn role derivation built on top of SkeletonCore.

This is intentionally lightweight and closed-vocabulary:
it provides a weak conversational "next move" hint without
templating or hard-gating the final utterance.
"""

from __future__ import annotations

from enum import Enum

from .schema import ConversationSkeleton, Focus, ResponseIntent


class TurnRole(str, Enum):
    MIRROR = "mirror"
    DEEPEN = "deepen"
    CONNECT = "connect"
    ASK = "ask"
    CLOSE = "close"


def get_turn_role_profile(thread_id: str) -> str:
    """Return the active role profile for the thread."""
    return "meeting" if str(thread_id or "").startswith("nero_meeting_") else "default"


def _base_turn_role(
    skeleton: ConversationSkeleton,
    *,
    profile: str,
) -> TurnRole:
    if skeleton.response_intent == ResponseIntent.ASK:
        return TurnRole.ASK
    if skeleton.focus == Focus.RETURNING_THEME:
        return TurnRole.CONNECT
    if skeleton.focus == Focus.LINGERING_STATE:
        return TurnRole.DEEPEN
    if skeleton.response_intent == ResponseIntent.OFFER_FRAGILE_SELF_OBSERVATION:
        return TurnRole.DEEPEN
    if skeleton.response_intent == ResponseIntent.ORGANIZE:
        return TurnRole.DEEPEN
    if skeleton.response_intent == ResponseIntent.RECEIVE:
        return TurnRole.MIRROR
    return TurnRole.MIRROR


def _stored_or_base_turn_role(
    skeleton: ConversationSkeleton,
    *,
    profile: str,
) -> TurnRole:
    raw = str(getattr(skeleton, "turn_role", "") or "").strip().lower()
    if raw:
        try:
            return TurnRole(raw)
        except ValueError:
            pass
    return _base_turn_role(skeleton, profile=profile)


def _transitioned_turn_role(
    base_role: TurnRole,
    *,
    prev_roles: list[TurnRole],
    profile: str,
) -> TurnRole:
    if len(prev_roles) < 2:
        return base_role
    if not (prev_roles[-1] == prev_roles[-2] == base_role):
        return base_role

    if profile == "meeting":
        transition_map = {
            TurnRole.MIRROR: TurnRole.DEEPEN,
            TurnRole.DEEPEN: TurnRole.CONNECT,
            TurnRole.CONNECT: TurnRole.ASK,
            TurnRole.ASK: TurnRole.DEEPEN,
            TurnRole.CLOSE: TurnRole.MIRROR,
        }
    else:
        transition_map = {
            TurnRole.MIRROR: TurnRole.DEEPEN,
            TurnRole.DEEPEN: TurnRole.ASK,
            TurnRole.CONNECT: TurnRole.ASK,
            TurnRole.ASK: TurnRole.MIRROR,
            TurnRole.CLOSE: TurnRole.MIRROR,
        }
    return transition_map.get(base_role, base_role)


def derive_turn_role(
    *,
    skeleton: ConversationSkeleton,
    prev_skeletons: list[ConversationSkeleton] | None = None,
    profile: str = "default",
) -> tuple[TurnRole, str]:
    """Derive the role and the reason/source label.

    Sources:
      - skeleton_rule: direct from current skeleton
      - role_transition: shifted to avoid same-role loops
    """
    prev = list(prev_skeletons or [])
    base_role = _base_turn_role(skeleton, profile=profile)
    prev_roles = [_stored_or_base_turn_role(s, profile=profile) for s in prev]
    final_role = _transitioned_turn_role(
        base_role,
        prev_roles=prev_roles,
        profile=profile,
    )
    source = "role_transition" if final_role != base_role else "skeleton_rule"
    return final_role, source
