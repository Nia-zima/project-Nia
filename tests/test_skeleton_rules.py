"""SkeletonCore rules tests.

Focus (R1-R8), ResponseIntent (I1-I9), QuestionIntent (Q1-Q5),
extract_syntax_features, evaluate_skeleton.
"""

from backend.core.conversation_skeleton.rules import (
    SkeletonInput,
    determine_focus,
    determine_question_intent,
    determine_response_intent,
    evaluate_skeleton,
    extract_syntax_features,
)
from backend.core.conversation_skeleton.schema import (
    ConversationSkeleton,
    Focus,
    QuestionIntent,
    ResponseIntent,
)


# ---------------------------------------------------------------------------
# extract_syntax_features
# ---------------------------------------------------------------------------


class TestExtractSyntaxFeatures:
    def test_question_marks_jp_and_en(self):
        f = extract_syntax_features("これは？本当に？ really?")
        assert f["question_mark_count"] == 3

    def test_contrast_words(self):
        f = extract_syntax_features("でもそれは違うと思う")
        assert f["has_contrast_words"] is True

    def test_no_contrast(self):
        f = extract_syntax_features("今日はいい天気だ")
        assert f["has_contrast_words"] is False

    def test_negation(self):
        f = extract_syntax_features("それはできない")
        assert f["has_negation"] is True

    def test_emotion_words(self):
        f = extract_syntax_features("嬉しい！")
        assert f["has_emotion_words"] is True

    def test_info_insufficiency(self):
        f = extract_syntax_features("よくわからないんだけど")
        assert f["has_info_insufficiency"] is True

    def test_empty_text(self):
        f = extract_syntax_features("")
        assert f["question_mark_count"] == 0
        assert f["has_contrast_words"] is False

    def test_none_text(self):
        f = extract_syntax_features(None)  # type: ignore[arg-type]
        assert f["question_mark_count"] == 0


# ---------------------------------------------------------------------------
# Focus rules (R1-R8)
# ---------------------------------------------------------------------------


class TestDetermineFocus:
    def test_r1_correction_strong(self):
        inp = SkeletonInput(correction_strong=True)
        focus, trace = determine_focus(inp)
        assert focus == Focus.CONTRADICTION
        assert "R1_contradiction_correction" in trace

    def test_r1_review_rejected(self):
        inp = SkeletonInput(review_rejected=True)
        focus, _ = determine_focus(inp)
        assert focus == Focus.CONTRADICTION

    def test_r2_emotion_surprise(self):
        inp = SkeletonInput(has_emotion_words=True, surprise_score=0.5)
        focus, trace = determine_focus(inp)
        assert focus == Focus.EMOTIONAL_STATE
        assert "R2_emotion_surprise" in trace

    def test_r3_missing_context_explicit(self):
        inp = SkeletonInput(context_coverage=0.3, has_info_insufficiency=True)
        focus, trace = determine_focus(inp)
        assert focus == Focus.MISSING_CONTEXT
        assert "R3_missing_context_explicit" in trace

    def test_r4_contrast_negation(self):
        inp = SkeletonInput(has_contrast_words=True, has_negation=True)
        focus, trace = determine_focus(inp)
        assert focus == Focus.CONTRADICTION
        assert "R4_contrast_negation" in trace

    def test_r5_low_coverage(self):
        inp = SkeletonInput(context_coverage=0.3)
        focus, trace = determine_focus(inp)
        assert focus == Focus.MISSING_CONTEXT
        assert "R5_low_coverage" in trace

    def test_r6_multi_question_steering(self):
        inp = SkeletonInput(question_mark_count=3, steering_risk=0.5)
        focus, trace = determine_focus(inp)
        assert focus == Focus.PRIORITY_DECISION
        assert "R6_multi_q_steering" in trace

    def test_r7_emotion_words_only(self):
        inp = SkeletonInput(has_emotion_words=True, surprise_score=0.1)
        focus, trace = determine_focus(inp)
        assert focus == Focus.EMOTIONAL_STATE
        assert "R7_emotion_words" in trace

    def test_r8_default(self):
        inp = SkeletonInput()
        focus, trace = determine_focus(inp)
        assert focus == Focus.USER_GOAL
        assert "R8_default_user_goal" in trace

    def test_priority_r1_over_r2(self):
        """R1 (correction) beats R2 (emotion+surprise)."""
        inp = SkeletonInput(
            correction_strong=True,
            has_emotion_words=True,
            surprise_score=0.5,
        )
        focus, _ = determine_focus(inp)
        assert focus == Focus.CONTRADICTION

    def test_priority_r1_beats_all(self):
        """R1 should beat every other rule simultaneously."""
        inp = SkeletonInput(
            correction_strong=True,
            has_emotion_words=True,
            surprise_score=0.5,
            context_coverage=0.2,
            has_info_insufficiency=True,
            has_contrast_words=True,
            has_negation=True,
            question_mark_count=3,
            steering_risk=0.5,
        )
        focus, trace = determine_focus(inp)
        assert focus == Focus.CONTRADICTION
        assert "R1_contradiction_correction" in trace

    def test_priority_r2_over_r3(self):
        """R2 (emotion+surprise) beats R3 (missing context)."""
        inp = SkeletonInput(
            has_emotion_words=True,
            surprise_score=0.5,
            context_coverage=0.3,
            has_info_insufficiency=True,
        )
        focus, trace = determine_focus(inp)
        assert focus == Focus.EMOTIONAL_STATE
        assert "R2_emotion_surprise" in trace

    def test_priority_r4_over_r5(self):
        """R4 (contrast+negation) beats R5 (low coverage alone)."""
        inp = SkeletonInput(
            context_coverage=0.3,
            has_contrast_words=True,
            has_negation=True,
        )
        focus, trace = determine_focus(inp)
        assert focus == Focus.CONTRADICTION
        assert "R4_contrast_negation" in trace

    def test_priority_r5_over_r6(self):
        """R5 (low coverage) beats R6 (multi-q + steering)."""
        inp = SkeletonInput(
            context_coverage=0.3,
            question_mark_count=3,
            steering_risk=0.5,
        )
        focus, trace = determine_focus(inp)
        assert focus == Focus.MISSING_CONTEXT
        assert "R5_low_coverage" in trace

    def test_priority_r6_over_r7(self):
        """R6 (priority decision) beats R7 (emotion words only)."""
        inp = SkeletonInput(
            question_mark_count=3,
            steering_risk=0.5,
            has_emotion_words=True,
            surprise_score=0.1,  # Low surprise so R2 doesn't fire
        )
        focus, trace = determine_focus(inp)
        assert focus == Focus.PRIORITY_DECISION
        assert "R6_multi_q_steering" in trace


# ---------------------------------------------------------------------------
# ResponseIntent rules (I1-I9)
# ---------------------------------------------------------------------------


class TestDetermineResponseIntent:
    def test_i1_depth_wait(self):
        inp = SkeletonInput(depth_action="wait")
        intent, trace = determine_response_intent(Focus.USER_GOAL, inp)
        assert intent == ResponseIntent.HOLD
        assert "I1_depth_wait" in trace

    def test_i2_contradiction_low_coverage_ask(self):
        inp = SkeletonInput(context_coverage=0.3)
        intent, trace = determine_response_intent(Focus.CONTRADICTION, inp)
        assert intent == ResponseIntent.ASK
        assert "I2_low_coverage_ask" in trace

    def test_i2_contradiction_high_coverage_organize(self):
        inp = SkeletonInput(context_coverage=0.7)
        intent, trace = determine_response_intent(Focus.CONTRADICTION, inp)
        assert intent == ResponseIntent.ORGANIZE
        assert "I2_organize_contradiction" in trace

    def test_i3_emotion_receive(self):
        inp = SkeletonInput()
        intent, trace = determine_response_intent(Focus.EMOTIONAL_STATE, inp)
        assert intent == ResponseIntent.RECEIVE
        assert "I3_emotion_receive" in trace

    def test_i4_priority_organize(self):
        inp = SkeletonInput()
        intent, trace = determine_response_intent(Focus.PRIORITY_DECISION, inp)
        assert intent == ResponseIntent.ORGANIZE
        assert "I4_priority_organize" in trace

    def test_i5_anti_repetition_receive_to_organize(self):
        prev = [
            ConversationSkeleton(focus=Focus.USER_GOAL, response_intent=ResponseIntent.RECEIVE),
            ConversationSkeleton(focus=Focus.USER_GOAL, response_intent=ResponseIntent.RECEIVE),
        ]
        inp = SkeletonInput(prev_skeletons=prev)
        intent, trace = determine_response_intent(Focus.USER_GOAL, inp)
        assert intent == ResponseIntent.ORGANIZE
        assert "I5_anti_repetition" in trace

    def test_i5_anti_repetition_organize_to_ask(self):
        prev = [
            ConversationSkeleton(focus=Focus.USER_GOAL, response_intent=ResponseIntent.ORGANIZE),
            ConversationSkeleton(focus=Focus.USER_GOAL, response_intent=ResponseIntent.ORGANIZE),
        ]
        inp = SkeletonInput(prev_skeletons=prev)
        intent, trace = determine_response_intent(Focus.USER_GOAL, inp)
        assert intent == ResponseIntent.ASK
        assert "I5_anti_repetition" in trace

    def test_i5_not_triggered_with_one_prev(self):
        """I5 requires len >= 2. Should not fire with 1 prev skeleton."""
        prev = [ConversationSkeleton(focus=Focus.USER_GOAL, response_intent=ResponseIntent.RECEIVE)]
        inp = SkeletonInput(prev_skeletons=prev)
        intent, trace = determine_response_intent(Focus.USER_GOAL, inp)
        assert "I5_anti_repetition" not in trace

    def test_i5_not_triggered_with_different_intents(self):
        """I5 only fires if last 2 intents are identical."""
        prev = [
            ConversationSkeleton(focus=Focus.USER_GOAL, response_intent=ResponseIntent.RECEIVE),
            ConversationSkeleton(focus=Focus.USER_GOAL, response_intent=ResponseIntent.ORGANIZE),
        ]
        inp = SkeletonInput(prev_skeletons=prev)
        intent, trace = determine_response_intent(Focus.USER_GOAL, inp)
        assert "I5_anti_repetition" not in trace

    def test_i5_with_three_same_intents(self):
        """I5 uses only last 2 skeletons."""
        prev = [
            ConversationSkeleton(focus=Focus.USER_GOAL, response_intent=ResponseIntent.RECEIVE),
            ConversationSkeleton(focus=Focus.USER_GOAL, response_intent=ResponseIntent.RECEIVE),
            ConversationSkeleton(focus=Focus.USER_GOAL, response_intent=ResponseIntent.RECEIVE),
        ]
        inp = SkeletonInput(prev_skeletons=prev)
        intent, trace = determine_response_intent(Focus.USER_GOAL, inp)
        assert intent == ResponseIntent.ORGANIZE
        assert "I5_anti_repetition" in trace

    def test_i5_ask_no_defined_shift(self):
        """I5 detects ASK repetition but has no shift rule — falls through."""
        prev = [
            ConversationSkeleton(focus=Focus.USER_GOAL, response_intent=ResponseIntent.ASK),
            ConversationSkeleton(focus=Focus.USER_GOAL, response_intent=ResponseIntent.ASK),
        ]
        inp = SkeletonInput(prev_skeletons=prev)
        intent, trace = determine_response_intent(Focus.USER_GOAL, inp)
        # I5 fires (trace recorded) but no shift for ASK, falls through to I9
        assert "I5_anti_repetition" in trace
        assert intent == ResponseIntent.RECEIVE

    def test_i6_depth0_high_coverage(self):
        inp = SkeletonInput(selected_depth=0, context_coverage=0.8)
        intent, trace = determine_response_intent(Focus.USER_GOAL, inp)
        assert intent == ResponseIntent.RECEIVE
        assert "I6_depth0_receive" in trace

    def test_i7_depth_ask(self):
        inp = SkeletonInput(depth_action="ask")
        intent, trace = determine_response_intent(Focus.USER_GOAL, inp)
        assert intent == ResponseIntent.ASK
        assert "I7_depth_ask" in trace

    def test_i8_depth1_organize(self):
        inp = SkeletonInput(selected_depth=1)
        intent, trace = determine_response_intent(Focus.USER_GOAL, inp)
        assert intent == ResponseIntent.ORGANIZE
        assert "I8_depth1_organize" in trace

    def test_i9_default_receive(self):
        inp = SkeletonInput(selected_depth=0, context_coverage=0.5)
        intent, trace = determine_response_intent(Focus.USER_GOAL, inp)
        assert intent == ResponseIntent.RECEIVE
        assert "I9_default_receive" in trace


# ---------------------------------------------------------------------------
# QuestionIntent rules (Q1-Q5)
# ---------------------------------------------------------------------------


class TestDetermineQuestionIntent:
    def test_not_ask_returns_none(self):
        inp = SkeletonInput()
        qi, trace = determine_question_intent(Focus.USER_GOAL, ResponseIntent.RECEIVE, inp)
        assert qi is None
        assert trace == []

    def test_q1_resolve_contradiction(self):
        inp = SkeletonInput()
        qi, trace = determine_question_intent(Focus.CONTRADICTION, ResponseIntent.ASK, inp)
        assert qi == QuestionIntent.RESOLVE_CONTRADICTION
        assert "Q1_resolve_contradiction" in trace

    def test_q2_fill_missing_fact(self):
        inp = SkeletonInput()
        qi, _ = determine_question_intent(Focus.MISSING_CONTEXT, ResponseIntent.ASK, inp)
        assert qi == QuestionIntent.FILL_MISSING_FACT

    def test_q3_clarify_emotion(self):
        inp = SkeletonInput()
        qi, _ = determine_question_intent(Focus.EMOTIONAL_STATE, ResponseIntent.ASK, inp)
        assert qi == QuestionIntent.CLARIFY_EMOTION

    def test_q4_clarify_priority(self):
        inp = SkeletonInput()
        qi, _ = determine_question_intent(Focus.PRIORITY_DECISION, ResponseIntent.ASK, inp)
        assert qi == QuestionIntent.CLARIFY_PRIORITY

    def test_q5_default_clarify_goal(self):
        inp = SkeletonInput()
        qi, trace = determine_question_intent(Focus.USER_GOAL, ResponseIntent.ASK, inp)
        assert qi == QuestionIntent.CLARIFY_GOAL
        assert "Q5_clarify_goal" in trace


# ---------------------------------------------------------------------------
# evaluate_skeleton
# ---------------------------------------------------------------------------


class TestEvaluateSkeleton:
    def test_basic_default(self):
        skel = evaluate_skeleton(SkeletonInput())
        assert skel.focus == Focus.USER_GOAL
        assert skel.response_intent == ResponseIntent.RECEIVE
        assert skel.question_intent is None
        assert skel.source == "nia_internal"
        assert len(skel.rule_trace) >= 2

    def test_contradiction_ask_chain(self):
        inp = SkeletonInput(correction_strong=True, context_coverage=0.3)
        skel = evaluate_skeleton(inp)
        assert skel.focus == Focus.CONTRADICTION
        assert skel.response_intent == ResponseIntent.ASK
        assert skel.question_intent == QuestionIntent.RESOLVE_CONTRADICTION

    def test_emotion_receive_chain(self):
        inp = SkeletonInput(has_emotion_words=True, surprise_score=0.5)
        skel = evaluate_skeleton(inp)
        assert skel.focus == Focus.EMOTIONAL_STATE
        assert skel.response_intent == ResponseIntent.RECEIVE
        assert skel.question_intent is None

    def test_hold_on_wait(self):
        inp = SkeletonInput(depth_action="wait")
        skel = evaluate_skeleton(inp)
        assert skel.response_intent == ResponseIntent.HOLD
        assert skel.question_intent is None


# ---------------------------------------------------------------------------
# Meeting extension: syntax markers
# ---------------------------------------------------------------------------


class TestMeetingExtensionMarkers:
    def test_return_markers(self):
        f = extract_syntax_features("また同じ話に戻ってきた")
        assert f["has_return_markers"] is True

    def test_linger_markers(self):
        f = extract_syntax_features("まだ引っかかるものがある")
        assert f["has_linger_markers"] is True

    def test_hedge_markers(self):
        f = extract_syntax_features("なんとなく気がするんだけど")
        assert f["has_hedge_markers"] is True

    def test_self_ref(self):
        f = extract_syntax_features("なんか自分の中にある感じ")
        assert f["has_self_ref"] is True

    def test_open_hold_markers(self):
        f = extract_syntax_features("そのまま置いておけばいい")
        assert f["has_open_hold_markers"] is True

    def test_no_markers_on_neutral(self):
        f = extract_syntax_features("今日はいい天気だ")
        assert f["has_return_markers"] is False
        assert f["has_linger_markers"] is False
        assert f["has_hedge_markers"] is False
        assert f["has_self_ref"] is False
        assert f["has_open_hold_markers"] is False


# ---------------------------------------------------------------------------
# Meeting extension: Focus rules (RM1, RM2)
# ---------------------------------------------------------------------------


class TestMeetingFocusRules:
    def test_rm1_returning_theme(self):
        inp = SkeletonInput(
            is_meeting=True,
            has_return_markers=True,
            retrieval_top_similarity=0.5,
            turn_index=3,
        )
        focus, trace = determine_focus(inp)
        assert focus == Focus.RETURNING_THEME
        assert "RM1_returning_theme" in trace

    def test_rm1_not_meeting_falls_through(self):
        """RM1 は is_meeting=false では発火しない。"""
        inp = SkeletonInput(
            is_meeting=False,
            has_return_markers=True,
            retrieval_top_similarity=0.5,
            turn_index=3,
        )
        focus, trace = determine_focus(inp)
        assert focus != Focus.RETURNING_THEME
        assert "RM1_returning_theme" not in trace

    def test_rm1_low_similarity_falls_through(self):
        """retrieval_top_similarity < 0.45 では RM1 不発火。"""
        inp = SkeletonInput(
            is_meeting=True,
            has_return_markers=True,
            retrieval_top_similarity=0.3,
            turn_index=3,
        )
        focus, trace = determine_focus(inp)
        assert focus != Focus.RETURNING_THEME

    def test_rm1_first_turn_falls_through(self):
        """turn_index <= 1 では RM1 不発火。"""
        inp = SkeletonInput(
            is_meeting=True,
            has_return_markers=True,
            retrieval_top_similarity=0.5,
            turn_index=1,
        )
        focus, trace = determine_focus(inp)
        assert focus != Focus.RETURNING_THEME

    def test_rm2_lingering_state(self):
        inp = SkeletonInput(
            is_meeting=True,
            has_linger_markers=True,
            has_info_insufficiency=False,
        )
        focus, trace = determine_focus(inp)
        assert focus == Focus.LINGERING_STATE
        assert "RM2_lingering_state" in trace

    def test_rm2_with_info_insufficiency_falls_through(self):
        """has_info_insufficiency=true なら missing_context に任せる。"""
        inp = SkeletonInput(
            is_meeting=True,
            has_linger_markers=True,
            has_info_insufficiency=True,
            context_coverage=0.3,
        )
        focus, trace = determine_focus(inp)
        assert focus != Focus.LINGERING_STATE

    def test_r1_still_overrides_meeting(self):
        """R1 (contradiction) は meeting でも最優先。"""
        inp = SkeletonInput(
            is_meeting=True,
            correction_strong=True,
            has_return_markers=True,
            retrieval_top_similarity=0.5,
            turn_index=3,
        )
        focus, trace = determine_focus(inp)
        assert focus == Focus.CONTRADICTION


# ---------------------------------------------------------------------------
# Meeting extension: ResponseIntent rules (IM1, IM2)
# ---------------------------------------------------------------------------


class TestMeetingResponseIntentRules:
    def test_im1_offer_fragile_self_observation_hedge_and_self_ref(self):
        """hedge + self_ref (both markers) で IM1 発火。"""
        inp = SkeletonInput(
            is_meeting=True,
            has_hedge_markers=True,
            has_self_ref=True,
        )
        intent, trace = determine_response_intent(Focus.USER_GOAL, inp)
        assert intent == ResponseIntent.OFFER_FRAGILE_SELF_OBSERVATION
        assert "IM1_offer_fragile_self_observation" in trace

    def test_im1_hedge_only(self):
        """hedge のみでも IM1 発火（1-of-2）。"""
        inp = SkeletonInput(
            is_meeting=True,
            has_hedge_markers=True,
            has_self_ref=False,
        )
        intent, trace = determine_response_intent(Focus.USER_GOAL, inp)
        assert intent == ResponseIntent.OFFER_FRAGILE_SELF_OBSERVATION

    def test_im1_not_meeting_falls_through(self):
        inp = SkeletonInput(
            is_meeting=False,
            has_hedge_markers=True,
            has_self_ref=True,
        )
        intent, trace = determine_response_intent(Focus.USER_GOAL, inp)
        assert intent != ResponseIntent.OFFER_FRAGILE_SELF_OBSERVATION

    def test_im1_no_markers_falls_through(self):
        """hedge も self_ref もなければ IM1 不発火。"""
        inp = SkeletonInput(
            is_meeting=True,
            has_hedge_markers=False,
            has_self_ref=False,
        )
        intent, trace = determine_response_intent(Focus.USER_GOAL, inp)
        assert intent != ResponseIntent.OFFER_FRAGILE_SELF_OBSERVATION

    def test_im1_blocked_by_info_insufficiency(self):
        """has_info_insufficiency=True は guard で弾く。"""
        inp = SkeletonInput(
            is_meeting=True,
            has_hedge_markers=True,
            has_self_ref=True,
            has_info_insufficiency=True,
        )
        intent, trace = determine_response_intent(Focus.USER_GOAL, inp)
        assert intent != ResponseIntent.OFFER_FRAGILE_SELF_OBSERVATION

    def test_im1_blocked_by_contradiction_focus(self):
        """focus=CONTRADICTION は guard で弾く。"""
        inp = SkeletonInput(
            is_meeting=True,
            has_hedge_markers=True,
            has_self_ref=True,
        )
        intent, trace = determine_response_intent(Focus.CONTRADICTION, inp)
        assert "IM1_offer_fragile_self_observation" not in trace

    def test_im2_meeting_ask_path(self):
        """IM2: meeting + open_hold + returning_theme → ASK。
        IM2 は IM1 より先に評価されるので、open_hold_markers があれば ASK に行く。
        """
        inp = SkeletonInput(
            is_meeting=True,
            has_open_hold_markers=True,
        )
        intent, trace = determine_response_intent(Focus.RETURNING_THEME, inp)
        assert intent == ResponseIntent.ASK
        assert "IM2_meeting_ask" in trace

    def test_im2_requires_meeting_focus(self):
        """IM2 は returning_theme / lingering_state 以外では不発火。"""
        inp = SkeletonInput(
            is_meeting=True,
            has_open_hold_markers=True,
        )
        intent, trace = determine_response_intent(Focus.USER_GOAL, inp)
        assert "IM2_meeting_ask" not in trace


# ---------------------------------------------------------------------------
# Meeting extension: QuestionIntent rules (QM1)
# ---------------------------------------------------------------------------


class TestMeetingQuestionIntentRules:
    def test_qm1_hold_open_space(self):
        inp = SkeletonInput(
            is_meeting=True,
            has_open_hold_markers=True,
            has_info_insufficiency=False,
        )
        qi, trace = determine_question_intent(
            Focus.RETURNING_THEME, ResponseIntent.ASK, inp,
        )
        assert qi == QuestionIntent.HOLD_OPEN_SPACE
        assert "QM1_hold_open_space" in trace

    def test_qm1_not_meeting_falls_through(self):
        inp = SkeletonInput(
            is_meeting=False,
            has_open_hold_markers=True,
        )
        qi, trace = determine_question_intent(
            Focus.RETURNING_THEME, ResponseIntent.ASK, inp,
        )
        assert qi != QuestionIntent.HOLD_OPEN_SPACE

    def test_qm1_with_info_insufficiency_falls_through(self):
        """info_insufficiency があれば fill_missing_fact 側に任せる。"""
        inp = SkeletonInput(
            is_meeting=True,
            has_open_hold_markers=True,
            has_info_insufficiency=True,
        )
        qi, trace = determine_question_intent(
            Focus.MISSING_CONTEXT, ResponseIntent.ASK, inp,
        )
        assert qi == QuestionIntent.FILL_MISSING_FACT

    def test_qm1_only_fires_on_ask(self):
        """response_intent != ASK なら question_intent は None。"""
        inp = SkeletonInput(
            is_meeting=True,
            has_open_hold_markers=True,
        )
        qi, _ = determine_question_intent(
            Focus.RETURNING_THEME, ResponseIntent.RECEIVE, inp,
        )
        assert qi is None


# ---------------------------------------------------------------------------
# Meeting extension: full chain (evaluate_skeleton)
# ---------------------------------------------------------------------------


class TestMeetingEvaluateChain:
    def test_returning_theme_to_hold_open_space(self):
        """RM1 → IM2 → QM1 の完全チェーン。
        IM2 は IM1 より先に評価されるので open_hold_markers で ASK に行く。
        """
        inp = SkeletonInput(
            is_meeting=True,
            has_return_markers=True,
            retrieval_top_similarity=0.5,
            turn_index=3,
            has_open_hold_markers=True,
        )
        skel = evaluate_skeleton(inp)
        assert skel.focus == Focus.RETURNING_THEME
        assert skel.response_intent == ResponseIntent.ASK
        assert skel.question_intent == QuestionIntent.HOLD_OPEN_SPACE

    def test_lingering_state_with_hedge(self):
        """RM2 → IM1 チェーン。"""
        inp = SkeletonInput(
            is_meeting=True,
            has_linger_markers=True,
            has_hedge_markers=True,
            has_self_ref=True,
        )
        skel = evaluate_skeleton(inp)
        assert skel.focus == Focus.LINGERING_STATE
        assert skel.response_intent == ResponseIntent.OFFER_FRAGILE_SELF_OBSERVATION

    def test_non_meeting_ignores_extension(self):
        """is_meeting=false では全て既存ルールにフォールバック。"""
        inp = SkeletonInput(
            is_meeting=False,
            has_return_markers=True,
            retrieval_top_similarity=0.5,
            turn_index=3,
            has_open_hold_markers=True,
            has_hedge_markers=True,
            has_self_ref=True,
        )
        skel = evaluate_skeleton(inp)
        assert skel.focus == Focus.USER_GOAL  # R8 default
