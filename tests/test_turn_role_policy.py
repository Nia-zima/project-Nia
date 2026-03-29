from backend.core.conversation_skeleton.schema import (
    ConversationSkeleton,
    Focus,
    ResponseIntent,
)
from backend.core.conversation_skeleton.turn_role import (
    TurnRole,
    derive_turn_role,
    get_turn_role_profile,
)


def _skeleton(
    *,
    focus: Focus,
    intent: ResponseIntent,
) -> ConversationSkeleton:
    return ConversationSkeleton(
        focus=focus,
        response_intent=intent,
        question_intent=None,
        source="nia_internal",
        confidence=0.7,
        rule_trace=[],
    )


def test_get_turn_role_profile_for_meeting():
    assert get_turn_role_profile("nero_meeting_20260318") == "meeting"


def test_get_turn_role_profile_for_default():
    assert get_turn_role_profile("default_thread") == "default"


def test_turn_role_connect_for_returning_theme():
    role, source = derive_turn_role(
        skeleton=_skeleton(
            focus=Focus.RETURNING_THEME,
            intent=ResponseIntent.ORGANIZE,
        ),
        prev_skeletons=[],
        profile="meeting",
    )
    assert role == TurnRole.CONNECT
    assert source == "skeleton_rule"


def test_turn_role_deepen_for_fragile_self_observation():
    role, source = derive_turn_role(
        skeleton=_skeleton(
            focus=Focus.USER_GOAL,
            intent=ResponseIntent.OFFER_FRAGILE_SELF_OBSERVATION,
        ),
        prev_skeletons=[],
        profile="meeting",
    )
    assert role == TurnRole.DEEPEN
    assert source == "skeleton_rule"


def test_turn_role_transitions_after_two_meeting_mirrors():
    current = _skeleton(
        focus=Focus.USER_GOAL,
        intent=ResponseIntent.RECEIVE,
    )
    prev = [
        _skeleton(focus=Focus.USER_GOAL, intent=ResponseIntent.RECEIVE),
        _skeleton(focus=Focus.USER_GOAL, intent=ResponseIntent.RECEIVE),
    ]
    role, source = derive_turn_role(
        skeleton=current,
        prev_skeletons=prev,
        profile="meeting",
    )
    assert role == TurnRole.DEEPEN
    assert source == "role_transition"


def test_turn_role_uses_stored_role_history_not_base_skeleton_history():
    current = _skeleton(
        focus=Focus.USER_GOAL,
        intent=ResponseIntent.RECEIVE,
    )
    prev = [
        ConversationSkeleton(
            focus=Focus.USER_GOAL,
            response_intent=ResponseIntent.RECEIVE,
            question_intent=None,
            source="nia_internal",
            confidence=0.7,
            rule_trace=[],
            turn_role="mirror",
        ),
        ConversationSkeleton(
            focus=Focus.USER_GOAL,
            response_intent=ResponseIntent.RECEIVE,
            question_intent=None,
            source="nia_internal",
            confidence=0.7,
            rule_trace=[],
            turn_role="deepen",
        ),
    ]
    role, source = derive_turn_role(
        skeleton=current,
        prev_skeletons=prev,
        profile="meeting",
    )
    assert role == TurnRole.MIRROR
    assert source == "skeleton_rule"


def test_turn_role_meeting_hold_does_not_imply_close():
    role, source = derive_turn_role(
        skeleton=_skeleton(
            focus=Focus.USER_GOAL,
            intent=ResponseIntent.HOLD,
        ),
        prev_skeletons=[],
        profile="meeting",
    )
    assert role == TurnRole.MIRROR
    assert source == "skeleton_rule"
