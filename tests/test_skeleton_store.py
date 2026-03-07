"""SkeletonCore store tests."""

import uuid

from backend.core.conversation_skeleton.schema import (
    ConversationSkeleton,
    Focus,
    QuestionIntent,
    ResponseIntent,
)
from backend.core.conversation_skeleton.store import (
    get_recent_skeletons,
    save_skeleton,
)
from backend.core.db import managed_conn


class TestSaveSkeleton:
    def test_basic_save(self):
        turn_id = uuid.uuid4().hex
        session_id = f"sess_{uuid.uuid4().hex[:8]}"
        skel = ConversationSkeleton(
            focus=Focus.USER_GOAL,
            response_intent=ResponseIntent.RECEIVE,
            rule_trace=["R8_default_user_goal", "I9_default_receive"],
        )
        row_id = save_skeleton(turn_id=turn_id, session_id=session_id, skeleton=skel)
        assert row_id is not None

        with managed_conn() as conn:
            row = conn.execute(
                "SELECT focus, response_intent, question_intent, source, confidence, rule_trace "
                "FROM conversation_skeletons WHERE id = ?",
                (row_id,),
            ).fetchone()
        assert row is not None
        assert row[0] == "user_goal"
        assert row[1] == "receive"
        assert row[2] is None
        assert row[3] == "nia_internal"
        assert row[4] == 0.5
        assert row[5] == "R8_default_user_goal,I9_default_receive"

    def test_save_with_question_intent(self):
        turn_id = uuid.uuid4().hex
        session_id = f"sess_{uuid.uuid4().hex[:8]}"
        skel = ConversationSkeleton(
            focus=Focus.CONTRADICTION,
            response_intent=ResponseIntent.ASK,
            question_intent=QuestionIntent.RESOLVE_CONTRADICTION,
            confidence=0.3,
        )
        row_id = save_skeleton(turn_id=turn_id, session_id=session_id, skeleton=skel)
        assert row_id is not None

        with managed_conn() as conn:
            row = conn.execute(
                "SELECT question_intent, confidence FROM conversation_skeletons WHERE id = ?",
                (row_id,),
            ).fetchone()
        assert row[0] == "resolve_contradiction"
        assert row[1] == 0.3


class TestGetRecentSkeletons:
    def _save_n(self, session_id: str, n: int) -> list[str]:
        """Save n skeletons with distinct focus values. Returns turn_ids."""
        focuses = list(Focus)
        turn_ids = []
        for i in range(n):
            tid = uuid.uuid4().hex
            turn_ids.append(tid)
            save_skeleton(
                turn_id=tid,
                session_id=session_id,
                skeleton=ConversationSkeleton(
                    focus=focuses[i % len(focuses)],
                    response_intent=ResponseIntent.RECEIVE,
                    rule_trace=[f"R{i}"],
                ),
            )
        return turn_ids

    def test_round_trip(self):
        sid = f"sess_{uuid.uuid4().hex[:8]}"
        self._save_n(sid, 2)
        result = get_recent_skeletons(sid, limit=3)
        assert len(result) == 2
        assert isinstance(result[0], ConversationSkeleton)

    def test_oldest_first_order(self):
        sid = f"sess_{uuid.uuid4().hex[:8]}"
        self._save_n(sid, 3)
        result = get_recent_skeletons(sid, limit=3)
        # First saved should be first in result (oldest first)
        assert len(result) == 3

    def test_limit_respected(self):
        sid = f"sess_{uuid.uuid4().hex[:8]}"
        self._save_n(sid, 5)
        result = get_recent_skeletons(sid, limit=2)
        assert len(result) == 2

    def test_empty_session(self):
        result = get_recent_skeletons(f"nonexistent_{uuid.uuid4().hex[:8]}")
        assert result == []

    def test_rule_trace_round_trip(self):
        sid = f"sess_{uuid.uuid4().hex[:8]}"
        skel = ConversationSkeleton(
            focus=Focus.EMOTIONAL_STATE,
            response_intent=ResponseIntent.RECEIVE,
            rule_trace=["R2_emotion_surprise", "I3_emotion_receive"],
        )
        save_skeleton(turn_id=uuid.uuid4().hex, session_id=sid, skeleton=skel)
        result = get_recent_skeletons(sid, limit=1)
        assert result[0].rule_trace == ["R2_emotion_surprise", "I3_emotion_receive"]

    def test_empty_rule_trace(self):
        sid = f"sess_{uuid.uuid4().hex[:8]}"
        skel = ConversationSkeleton(
            focus=Focus.USER_GOAL,
            response_intent=ResponseIntent.RECEIVE,
            rule_trace=[],
        )
        save_skeleton(turn_id=uuid.uuid4().hex, session_id=sid, skeleton=skel)
        result = get_recent_skeletons(sid, limit=1)
        assert result[0].rule_trace == []
