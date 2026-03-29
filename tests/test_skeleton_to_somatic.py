"""SkeletonCore skeleton_to_somatic tests."""

from backend.core.conversation_skeleton.schema import (
    ConversationSkeleton,
    Focus,
    QuestionIntent,
    ResponseIntent,
)
from backend.core.conversation_skeleton.skeleton_to_somatic import (
    SkeletonSense,
    _COMPOSED_TEMPLATES,
    _FOCUS_TEMPLATES,
    _INTENT_TEMPLATES,
    _QUESTION_TEMPLATES,
    format_skeleton_somatic,
    skeleton_to_somatic,
)


class TestSkeletonToSomatic:
    def test_composed_template_fires(self):
        """(EMOTIONAL_STATE, RECEIVE) → composed template."""
        skel = ConversationSkeleton(
            focus=Focus.EMOTIONAL_STATE,
            response_intent=ResponseIntent.RECEIVE,
        )
        senses = skeleton_to_somatic(skel)
        assert len(senses) == 1
        assert senses[0].category == "気配+姿勢"
        assert "受け止めたい" in senses[0].text

    def test_individual_templates_when_no_composed(self):
        """(USER_GOAL, RECEIVE) → no composed, 2 individual templates."""
        skel = ConversationSkeleton(
            focus=Focus.USER_GOAL,
            response_intent=ResponseIntent.RECEIVE,
        )
        senses = skeleton_to_somatic(skel)
        assert len(senses) == 2
        categories = {s.category for s in senses}
        assert "気配" in categories
        assert "姿勢" in categories

    def test_question_intent_adds_third_sense(self):
        skel = ConversationSkeleton(
            focus=Focus.CONTRADICTION,
            response_intent=ResponseIntent.ASK,
            question_intent=QuestionIntent.RESOLVE_CONTRADICTION,
        )
        senses = skeleton_to_somatic(skel)
        # composed (CONTRADICTION, ASK) + question intent
        assert len(senses) == 2
        assert senses[-1].category == "引っかかり"
        assert "不協和音" in senses[-1].text

    def test_no_question_intent_for_non_ask(self):
        skel = ConversationSkeleton(
            focus=Focus.USER_GOAL,
            response_intent=ResponseIntent.ORGANIZE,
        )
        senses = skeleton_to_somatic(skel)
        # composed (USER_GOAL, ORGANIZE) has a template
        assert all(s.category != "引っかかり" for s in senses)

    def test_hold_template(self):
        skel = ConversationSkeleton(
            focus=Focus.USER_GOAL,
            response_intent=ResponseIntent.HOLD,
        )
        senses = skeleton_to_somatic(skel)
        intent_senses = [s for s in senses if s.category == "姿勢"]
        assert len(intent_senses) == 1
        assert "急がないほうがいい" in intent_senses[0].text

    def test_all_focus_have_templates(self):
        for f in Focus:
            assert f in _FOCUS_TEMPLATES, f"Missing template for Focus.{f.name}"

    def test_all_intent_have_templates(self):
        for ri in ResponseIntent:
            assert ri in _INTENT_TEMPLATES, f"Missing template for ResponseIntent.{ri.name}"

    def test_all_question_have_templates(self):
        for qi in QuestionIntent:
            assert qi in _QUESTION_TEMPLATES, f"Missing template for QuestionIntent.{qi.name}"

    def test_intensity_range(self):
        for templates in [_FOCUS_TEMPLATES, _INTENT_TEMPLATES, _QUESTION_TEMPLATES]:
            for key, (text, intensity) in templates.items():
                assert 0.0 <= intensity <= 1.0, f"{key}: intensity {intensity} out of range"

    def test_composed_intensity_range(self):
        for key, (text, intensity) in _COMPOSED_TEMPLATES.items():
            assert 0.0 <= intensity <= 1.0, f"{key}: intensity {intensity} out of range"

    def test_composed_missing_context_ask(self):
        skel = ConversationSkeleton(
            focus=Focus.MISSING_CONTEXT,
            response_intent=ResponseIntent.ASK,
        )
        senses = skeleton_to_somatic(skel)
        assert len(senses) == 1
        assert senses[0].category == "気配+姿勢"
        assert "全体が見えていない" in senses[0].text

    def test_composed_user_goal_organize(self):
        skel = ConversationSkeleton(
            focus=Focus.USER_GOAL,
            response_intent=ResponseIntent.ORGANIZE,
        )
        senses = skeleton_to_somatic(skel)
        assert len(senses) == 1
        assert "相手の意図は見えている" in senses[0].text

    def test_composed_priority_hold(self):
        skel = ConversationSkeleton(
            focus=Focus.PRIORITY_DECISION,
            response_intent=ResponseIntent.HOLD,
        )
        senses = skeleton_to_somatic(skel)
        assert len(senses) == 1
        assert "焦らないでおこう" in senses[0].text


class TestFormatSkeletonSomatic:
    def test_empty_senses(self):
        assert format_skeleton_somatic([]) == ""

    def test_basic_format(self):
        senses = [
            SkeletonSense(text="テスト1", intensity=0.5, category="気配"),
            SkeletonSense(text="テスト2", intensity=0.6, category="姿勢"),
        ]
        result = format_skeleton_somatic(senses)
        assert result.startswith("=== 会話の気配 ===\n")
        assert "指示ではない" in result
        assert "- テスト1" in result
        assert "- テスト2" in result

    def test_section_header_distinct_from_somatic(self):
        """'=== 会話の気配 ===' is distinct from somatic's '=== 今の感覚 ==='."""
        senses = [SkeletonSense(text="t", intensity=0.5, category="気配")]
        result = format_skeleton_somatic(senses)
        assert "会話の気配" in result
        assert "今の感覚" not in result

    def test_single_sense(self):
        senses = [SkeletonSense(text="テスト", intensity=0.5, category="気配")]
        result = format_skeleton_somatic(senses)
        assert result.startswith("=== 会話の気配 ===")
        assert "- テスト" in result

    def test_empty_text_skipped(self):
        """Senses with empty text are filtered out."""
        senses = [
            SkeletonSense(text="有効", intensity=0.5, category="気配"),
            SkeletonSense(text="", intensity=0.5, category="姿勢"),
        ]
        result = format_skeleton_somatic(senses)
        assert "有効" in result
        lines = [l for l in result.split("\n") if l.startswith("- ")]
        assert len(lines) == 1

    def test_all_empty_text_returns_empty(self):
        """If all senses have empty text, return empty string."""
        senses = [
            SkeletonSense(text="", intensity=0.5, category="気配"),
            SkeletonSense(text="", intensity=0.5, category="姿勢"),
        ]
        result = format_skeleton_somatic(senses)
        assert result == ""
