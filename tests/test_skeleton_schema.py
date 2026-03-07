"""SkeletonCore schema tests."""

from backend.core.conversation_skeleton.schema import (
    ConversationSkeleton,
    Focus,
    QuestionIntent,
    ResponseIntent,
)


class TestFocusEnum:
    def test_values(self):
        assert Focus.USER_GOAL == "user_goal"
        assert Focus.MISSING_CONTEXT == "missing_context"
        assert Focus.CONTRADICTION == "contradiction"
        assert Focus.PRIORITY_DECISION == "priority_decision"
        assert Focus.EMOTIONAL_STATE == "emotional_state"

    def test_member_count(self):
        assert len(Focus) == 5

    def test_string_conversion(self):
        assert str(Focus.USER_GOAL) == "Focus.USER_GOAL"
        assert Focus.USER_GOAL.value == "user_goal"


class TestResponseIntentEnum:
    def test_values(self):
        assert ResponseIntent.RECEIVE == "receive"
        assert ResponseIntent.ORGANIZE == "organize"
        assert ResponseIntent.ASK == "ask"
        assert ResponseIntent.HOLD == "hold"

    def test_member_count(self):
        assert len(ResponseIntent) == 4


class TestQuestionIntentEnum:
    def test_values(self):
        assert QuestionIntent.CLARIFY_GOAL == "clarify_goal"
        assert QuestionIntent.CLARIFY_PRIORITY == "clarify_priority"
        assert QuestionIntent.CLARIFY_EMOTION == "clarify_emotion"
        assert QuestionIntent.FILL_MISSING_FACT == "fill_missing_fact"
        assert QuestionIntent.RESOLVE_CONTRADICTION == "resolve_contradiction"

    def test_member_count(self):
        assert len(QuestionIntent) == 5


class TestConversationSkeleton:
    def test_defaults(self):
        skel = ConversationSkeleton(
            focus=Focus.USER_GOAL,
            response_intent=ResponseIntent.RECEIVE,
        )
        assert skel.question_intent is None
        assert skel.source == "nia_internal"
        assert skel.confidence == 0.5
        assert skel.rule_trace == []

    def test_with_question_intent(self):
        skel = ConversationSkeleton(
            focus=Focus.CONTRADICTION,
            response_intent=ResponseIntent.ASK,
            question_intent=QuestionIntent.RESOLVE_CONTRADICTION,
        )
        assert skel.question_intent == QuestionIntent.RESOLVE_CONTRADICTION

    def test_nero_source(self):
        skel = ConversationSkeleton(
            focus=Focus.USER_GOAL,
            response_intent=ResponseIntent.ORGANIZE,
            source="nero_external",
        )
        assert skel.source == "nero_external"

    def test_rule_trace_mutable(self):
        s1 = ConversationSkeleton(focus=Focus.USER_GOAL, response_intent=ResponseIntent.RECEIVE)
        s2 = ConversationSkeleton(focus=Focus.USER_GOAL, response_intent=ResponseIntent.RECEIVE)
        s1.rule_trace.append("test")
        assert s2.rule_trace == []  # field(default_factory) ensures independence
