"""SkeletonCore integration tests.

builder + config flags + actions recording.
"""

from unittest.mock import patch

from backend.core.conversation_skeleton.builder import build_conversation_skeleton
from backend.core.conversation_skeleton.schema import (
    Focus,
    ResponseIntent,
)


class TestBuildConversationSkeleton:
    def test_minimal_state(self):
        """Minimal state still produces a valid skeleton."""
        skel = build_conversation_skeleton(
            state={},
            thread_id="test_thread",
            user_text="こんにちは",
        )
        assert skel is not None
        assert skel.focus == Focus.USER_GOAL
        assert skel.response_intent == ResponseIntent.RECEIVE

    def test_emotion_input(self):
        skel = build_conversation_skeleton(
            state={"surprise_score": 0.5},
            thread_id="test_thread",
            user_text="嬉しいな！",
        )
        assert skel is not None
        assert skel.focus == Focus.EMOTIONAL_STATE

    def test_contradiction_with_correction(self):
        """correction_strong triggers CONTRADICTION focus."""
        with patch(
            "backend.services.memory.somatic_feedback.detect_correction_level",
            return_value="strong",
        ):
            skel = build_conversation_skeleton(
                state={},
                thread_id="test_thread",
                user_text="違う、そうじゃない",
            )
        assert skel is not None
        assert skel.focus == Focus.CONTRADICTION

    def test_returns_none_on_exception(self):
        """Never raises — returns None on failure."""
        with patch(
            "backend.core.conversation_skeleton.builder.evaluate_skeleton",
            side_effect=RuntimeError("boom"),
        ):
            skel = build_conversation_skeleton(
                state={},
                thread_id="test_thread",
                user_text="テスト",
            )
        assert skel is None

    def test_with_confidence_metrics(self):
        state = {
            "confidence_metrics": {
                "context_coverage": 0.2,
                "self_consistency": 0.8,
                "logit_based": 0.5,
                "question_clarity": 0.6,
                "steering_risk": 0.1,
            },
            "selected_depth": 1,
            "depth_action": "depth1",
        }
        skel = build_conversation_skeleton(
            state=state,
            thread_id="test_thread",
            user_text="わからないんだけど",
        )
        assert skel is not None
        # Low context_coverage + info_insufficiency → MISSING_CONTEXT
        assert skel.focus == Focus.MISSING_CONTEXT

    def test_depth_action_wait_produces_hold(self):
        state = {"depth_action": "wait"}
        skel = build_conversation_skeleton(
            state=state,
            thread_id="test_thread",
            user_text="うーん",
        )
        assert skel is not None
        assert skel.response_intent == ResponseIntent.HOLD
