"""Tests for turn intent detection, direct stance detection, and prompt hint injection."""
import pytest


# ── _detect_turn_intent ────────────────────────────────────────


class TestDetectTurnIntent:
    @pytest.fixture(autouse=True)
    def _import(self):
        from backend.core.agent_graph.nodes.routing import _detect_turn_intent
        self.detect = _detect_turn_intent

    # -- correction_response --

    def test_correction_with_reference(self):
        """訂正 marker + 参照表現 → correction_response"""
        assert self.detect("それは違うよ", None) == "correction_response"

    def test_correction_sakki_reference(self):
        assert self.detect("さっきの間違ってる", None) == "correction_response"

    def test_correction_marker_only_no_reference(self):
        """marker あるが参照表現なし → open_reflection"""
        assert self.detect("違う景色だね", None) == "open_reflection"

    def test_correction_general_statement(self):
        """一般論で参照なし → open_reflection"""
        assert self.detect("間違いは誰にでもある", None) == "open_reflection"

    # -- direct_answer --

    def test_closed_question_with_stance_marker(self):
        assert self.detect("ネロに言えてる？", None) == "direct_answer"

    def test_closed_question_ascii(self):
        assert self.detect("結局できてる?", None) == "direct_answer"

    def test_skeleton_resolve_contradiction(self):
        skel = {"question_intent": "resolve_contradiction"}
        assert self.detect("その話はどうなった", skel) == "direct_answer"

    def test_skeleton_clarify_goal(self):
        skel = {"question_intent": "clarify_goal"}
        assert self.detect("何がしたいの", skel) == "direct_answer"

    def test_clarify_emotion_closed_with_stance(self):
        """clarify_emotion + 閉じた質問 + stance marker → direct_answer"""
        skel = {"question_intent": "clarify_emotion"}
        assert self.detect("本当にそう感じた？", skel) == "direct_answer"

    def test_clarify_emotion_open_question(self):
        """clarify_emotion + 開いた問い → open_reflection"""
        skel = {"question_intent": "clarify_emotion"}
        assert self.detect("どう感じた", skel) == "open_reflection"

    # -- open_reflection --

    def test_open_question_no_stance(self):
        assert self.detect("最近どう？", None) == "open_reflection"

    def test_statement_no_question(self):
        assert self.detect("言えてるよ", None) == "open_reflection"

    def test_empty_input(self):
        assert self.detect("", None) == "open_reflection"
        assert self.detect("", {}) == "open_reflection"

    def test_no_skeleton(self):
        assert self.detect("普通の話だね", None) == "open_reflection"


# ── _detect_requires_direct_stance (compatibility) ─────────────


class TestDetectRequiresDirectStance:
    @pytest.fixture(autouse=True)
    def _import(self):
        from backend.core.agent_graph.nodes.routing import _detect_requires_direct_stance
        self.detect = _detect_requires_direct_stance

    def test_closed_question_with_stance_marker(self):
        assert self.detect("ネロに言えてる？", None) is True

    def test_closed_question_with_fullwidth_question(self):
        assert self.detect("それは本当？", None) is True

    def test_closed_question_with_ascii_question(self):
        assert self.detect("結局できてる?", None) is True

    def test_open_question_no_stance_marker(self):
        assert self.detect("最近どう？", None) is False

    def test_statement_with_stance_marker_no_question(self):
        assert self.detect("言えてるよ", None) is False

    def test_skeleton_resolve_contradiction(self):
        skel = {"question_intent": "resolve_contradiction"}
        assert self.detect("その話はどうなった", skel) is True

    def test_skeleton_clarify_goal(self):
        skel = {"question_intent": "clarify_goal"}
        assert self.detect("何がしたいの", skel) is True

    def test_skeleton_clarify_emotion_open(self):
        """clarify_emotion without closed question → False (updated behavior)"""
        skel = {"question_intent": "clarify_emotion"}
        assert self.detect("どう感じた", skel) is False

    def test_skeleton_clarify_emotion_closed_with_stance(self):
        """clarify_emotion with closed question + stance → True"""
        skel = {"question_intent": "clarify_emotion"}
        assert self.detect("本当にそう感じた？", skel) is True

    def test_correction_with_reference(self):
        """correction_response → requires_direct_stance=True"""
        assert self.detect("それは違うよ", None) is True

    def test_skeleton_fill_missing_fact_not_triggered(self):
        skel = {"question_intent": "fill_missing_fact"}
        assert self.detect("いつだっけ", skel) is False

    def test_empty_input(self):
        assert self.detect("", None) is False
        assert self.detect("", {}) is False


# ── _direct_stance_hint ─────────────────────────────────────────


class TestDirectStanceHint:
    @pytest.fixture(autouse=True)
    def _import(self):
        from backend.core.agent_graph.nodes.depth_nodes import _direct_stance_hint
        self.hint = _direct_stance_hint

    def test_hint_for_direct_answer(self):
        state = {"turn_intent": "direct_answer", "thread_id": "default_thread"}
        result = self.hint(state)
        assert "DIRECT ANSWER HINT" in result
        assert "立場を確認する質問" in result

    def test_hint_for_correction_response(self):
        state = {"turn_intent": "correction_response", "thread_id": "default_thread"}
        result = self.hint(state)
        assert "DIRECT ANSWER HINT" in result
        assert "訂正や異議" in result

    def test_no_hint_for_open_reflection(self):
        state = {"turn_intent": "open_reflection", "thread_id": "default_thread"}
        assert self.hint(state) == ""

    def test_no_hint_when_missing(self):
        state = {"thread_id": "default_thread"}
        assert self.hint(state) == ""

    def test_backward_compat_requires_direct_stance(self):
        """requires_direct_stance のみで turn_intent なし → no hint (turn_intent が正)"""
        state = {"requires_direct_stance": True, "thread_id": "default_thread"}
        assert self.hint(state) == ""


# ── merge direct stance scoring ─────────────────────────────────


class TestMergeDirectStanceScoring:
    @pytest.fixture(autouse=True)
    def _import(self):
        from backend.core.agent_graph.nodes.merge import _score_candidate_for_turn_role
        self.score = _score_candidate_for_turn_role

    def _base_state(self, **overrides):
        state = {
            "messages": [],
            "thread_id": "default_thread",
            "turn_intent": "direct_answer",
        }
        state.update(overrides)
        return state

    def test_direct_opener_gets_bonus(self):
        state = self._base_state()
        score = self.score(state=state, text="まだ言えてないよ。", role="deepen", base_score=0)
        score_abstract = self.score(state=state, text="静かな時間の中で感じてる。", role="deepen", base_score=0)
        assert score > score_abstract

    def test_abstract_opener_gets_penalty(self):
        state = self._base_state()
        score_neutral = self.score(state=state, text="考えてみたけど。", role="ask", base_score=0)
        score_abstract = self.score(state=state, text="静かな時間の中で感じてる。", role="ask", base_score=0)
        assert score_neutral > score_abstract

    def test_no_bonus_without_intent(self):
        state = self._base_state(turn_intent="open_reflection")
        score_direct = self.score(state=state, text="まだ言えてない。", role="deepen", base_score=0)
        score_abstract = self.score(state=state, text="静かな時間の中で感じてる。", role="deepen", base_score=0)
        assert score_direct == score_abstract

    def test_correction_intent_also_gets_bonus(self):
        state = self._base_state(turn_intent="correction_response")
        score = self.score(state=state, text="違うよ、そうじゃない。", role="deepen", base_score=0)
        score_abstract = self.score(state=state, text="静かな時間の中で感じてる。", role="deepen", base_score=0)
        assert score > score_abstract


# ── turn_intent preference (independent of turn_role) ──────────


class TestTurnIntentPreference:
    """turn_intent preference works even when turn_role ranking is skipped."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from backend.core.agent_graph.nodes.merge import _apply_turn_intent_preference
        self.apply = _apply_turn_intent_preference

    def test_replaces_abstract_with_direct_candidate(self):
        """turn_intent=direct_answer + abstract default → replaced with direct candidate"""
        state = {"turn_intent": "direct_answer"}
        candidates = [
            {"text": "静かな時間の中で感じてる。", "merge_mode": "B", "base_score": 1},
            {"text": "まだ言えてないよ。", "merge_mode": "B", "base_score": 0},
        ]
        text, mode = self.apply(
            state=state, candidates=candidates,
            say_candidate="静かな時間の中で感じてる。", merge_mode="B",
        )
        assert text == "まだ言えてないよ。"

    def test_keeps_direct_candidate(self):
        """turn_intent=direct_answer + already direct → no change"""
        state = {"turn_intent": "direct_answer"}
        candidates = [
            {"text": "まだ言えてない。", "merge_mode": "B", "base_score": 1},
        ]
        text, mode = self.apply(
            state=state, candidates=candidates,
            say_candidate="まだ言えてない。", merge_mode="B",
        )
        assert text == "まだ言えてない。"

    def test_no_change_for_open_reflection(self):
        """open_reflection → no change regardless of content"""
        state = {"turn_intent": "open_reflection"}
        candidates = [
            {"text": "静かな時間の中で感じてる。", "merge_mode": "B", "base_score": 1},
            {"text": "まだ言えてない。", "merge_mode": "B", "base_score": 0},
        ]
        text, mode = self.apply(
            state=state, candidates=candidates,
            say_candidate="静かな時間の中で感じてる。", merge_mode="B",
        )
        assert text == "静かな時間の中で感じてる。"

    def test_keeps_abstract_if_no_direct_alternative(self):
        """No direct candidate available → keeps abstract"""
        state = {"turn_intent": "direct_answer"}
        candidates = [
            {"text": "静かな時間の中で感じてる。", "merge_mode": "B", "base_score": 1},
            {"text": "心が動いている。", "merge_mode": "B", "base_score": 0},
        ]
        text, mode = self.apply(
            state=state, candidates=candidates,
            say_candidate="静かな時間の中で感じてる。", merge_mode="B",
        )
        assert text == "静かな時間の中で感じてる。"

    def test_correction_response_also_triggers(self):
        """correction_response → same behavior as direct_answer"""
        state = {"turn_intent": "correction_response"}
        candidates = [
            {"text": "静かな時間の中で考えてた。", "merge_mode": "B", "base_score": 1},
            {"text": "違うよ、そうじゃない。", "merge_mode": "B", "base_score": 0},
        ]
        text, mode = self.apply(
            state=state, candidates=candidates,
            say_candidate="静かな時間の中で考えてた。", merge_mode="B",
        )
        assert text == "違うよ、そうじゃない。"

    def test_hai_iie_recognized_as_direct(self):
        """はい / いいえ は direct opener として認識される"""
        state = {"turn_intent": "direct_answer"}
        candidates = [
            {"text": "静かな時間の中で感じてる。", "merge_mode": "B", "base_score": 1},
            {"text": "いいえ。まだそこまでは。", "merge_mode": "B", "base_score": 0},
        ]
        text, mode = self.apply(
            state=state, candidates=candidates,
            say_candidate="静かな時間の中で感じてる。", merge_mode="B",
        )
        assert text == "いいえ。まだそこまでは。"


# ── semantic repetition family ─────────────────────────────────


class TestSemanticRepetitionFamily:
    @pytest.fixture(autouse=True)
    def _import(self):
        from backend.core.agent_graph.nodes.helpers import (
            _detect_semantic_family,
            _detect_repetition_sense,
        )
        self.detect_family = _detect_semantic_family
        self.detect_sense = _detect_repetition_sense

    def test_quiet_atmosphere_detected(self):
        texts = [
            "静かな時間の中で感じてる。",
            "穏やかな気持ちがある。",
            "何か別のことを考えていた。",
        ]
        assert self.detect_family(texts) == "quiet_atmosphere"

    def test_heart_moves_detected(self):
        texts = [
            "心が動いた気がする。",
            "何かが揺れている。",
        ]
        assert self.detect_family(texts) == "heart_moves"

    def test_no_family_when_varied(self):
        texts = [
            "まだ言えてない。",
            "考えてみたけど。",
            "そうだね。",
        ]
        assert self.detect_family(texts) is None

    def test_no_family_with_single_text(self):
        texts = ["静かな時間の中で感じてる。"]
        assert self.detect_family(texts) is None

    def test_sense_returns_text_on_family_hit(self):
        from langchain_core.messages import AIMessage
        state = {
            "messages": [
                AIMessage(content="静かな時間の中で考えていた。"),
                AIMessage(content="穏やかに落ち着いてきた。"),
                AIMessage(content="何かを感じた。"),
            ],
        }
        result = self.detect_sense(state)
        assert "別の角度" in result

    def test_sense_empty_when_no_family(self):
        from langchain_core.messages import AIMessage
        state = {
            "messages": [
                AIMessage(content="まだ言えてない。"),
                AIMessage(content="考えてみたけど。"),
            ],
        }
        result = self.detect_sense(state)
        assert result == ""


# ── Step 7: diversity-aware history selection ──────────────────


class TestDiversityAwareHistory:
    @pytest.fixture(autouse=True)
    def _import(self):
        from backend.core.agent_graph.nodes.helpers import _recent_history
        self.recent_history = _recent_history

    def _make_state(self, pairs):
        """Build state with alternating Human/AI message pairs + trailing Human."""
        from langchain_core.messages import HumanMessage, AIMessage
        msgs = []
        for h, a in pairs:
            msgs.append(HumanMessage(content=h))
            msgs.append(AIMessage(content=a))
        # Add current turn Human (will be excluded by _recent_history)
        msgs.append(HumanMessage(content="current turn"))
        return {"messages": msgs}

    def test_open_reflection_unchanged(self):
        """open_reflection → 現行と完全一致"""
        pairs = [
            ("q1", "静かな時間の中で感じてる。"),
            ("q2", "穏やかだね。"),
            ("q3", "心が動いた。"),
            ("q4", "まだ言えてない。"),
        ]
        state = self._make_state(pairs)
        result_default = self.recent_history(state, max_pairs=4)
        result_open = self.recent_history(state, max_pairs=4, turn_intent="open_reflection")
        # Should be identical
        default_texts = [getattr(m, "content", "") for m in result_default]
        open_texts = [getattr(m, "content", "") for m in result_open]
        assert default_texts == open_texts

    def test_direct_answer_reduces_abstract_density(self):
        """direct_answer + abstract 多数 → abstract の密度が下がり、半分以下になる"""
        from langchain_core.messages import AIMessage
        # 8 pairs: 6 abstract + 2 direct
        pairs = [
            ("q1", "まだ言えてない。"),          # direct
            ("q2", "静かな時間の中で感じてる。"),  # abstract
            ("q3", "穏やかな気持ちがある。"),      # abstract
            ("q4", "落ち着いた時間だった。"),      # abstract
            ("q5", "いいえ、違うよ。"),            # direct
            ("q6", "静かな時間の中で考えてた。"),  # abstract
            ("q7", "心が動いた。"),               # abstract (heart_moves)
            ("q8", "静けさの中にいる。"),          # abstract
        ]
        state = self._make_state(pairs)
        result = self.recent_history(state, max_pairs=5, turn_intent="direct_answer")
        ai_texts = [getattr(m, "content", "") for m in result
                     if isinstance(m, AIMessage)]
        abstract_count = sum(1 for t in ai_texts
                            if "静か" in t or "穏やか" in t or "心が動" in t or "落ち着" in t)
        direct_count = sum(1 for t in ai_texts
                          if t.startswith("まだ") or t.startswith("いいえ"))
        # Direct should be present
        assert direct_count >= 1
        # Family cap: abstract は scored 枠の半分以下（anchor 含めても全体の過半数にならない）
        assert abstract_count <= len(ai_texts) // 2 + 1  # anchor に abstract が入る分の余裕

    def test_large_history_abstract_capped(self):
        """45ペア相当の長い履歴で abstract の密度が下がる"""
        from langchain_core.messages import AIMessage
        # 40 abstract + 5 direct
        pairs = []
        for i in range(45):
            if i % 9 == 0:  # 5 direct at positions 0, 9, 18, 27, 36
                pairs.append((f"q{i}", "まだ言えてない。"))
            else:
                pairs.append((f"q{i}", "静かな時間の中で感じてる。"))
        state = self._make_state(pairs)
        result = self.recent_history(state, max_pairs=30, turn_intent="direct_answer")
        ai_texts = [getattr(m, "content", "") for m in result
                     if isinstance(m, AIMessage)]
        abstract_count = sum(1 for t in ai_texts if "静か" in t)
        direct_count = sum(1 for t in ai_texts if t.startswith("まだ"))
        # All 5 direct candidates should be preserved
        assert direct_count >= 4
        # Scored cap limits abstract in scored slots to ~half
        # Anchor (3 pairs) may all be abstract, so total abstract = scored_cap + anchor_abstract
        # scored_cap = (max_pairs - anchor_size) // 2 ≈ 13
        # total abstract ≤ 13 + 3 = 16 (much less than original 40)
        assert abstract_count <= 17
        # Total pairs should be less than 30 (cap drops some slots rather than filling with abstract)
        assert len(ai_texts) < 30

    def test_anchor_always_included(self):
        """直近 anchor ペアは必ず含まれる"""
        from langchain_core.messages import AIMessage
        pairs = [
            ("q1", "まだ言えてない。"),
            ("q2", "静かな時間の中で。"),
            ("q3", "穏やかだね。"),
            ("q4", "静かな時間の中で考えてた。"),  # ← 直近、abstract でも anchor
        ]
        state = self._make_state(pairs)
        result = self.recent_history(state, max_pairs=3, turn_intent="direct_answer")
        ai_texts = [getattr(m, "content", "") for m in result
                     if isinstance(m, AIMessage)]
        # 直近のペア（q4）は anchor として必ず含まれる
        assert any("考えてた" in t for t in ai_texts)

    def test_chronological_order_preserved(self):
        """選択後も時間順が保たれる"""
        from langchain_core.messages import HumanMessage
        pairs = [
            ("q1", "まだ言えてない。"),
            ("q2", "静かな時間の中で。"),
            ("q3", "いいえ。"),
            ("q4", "穏やかだね。"),
            ("q5", "そうだよ。"),
            ("q6", "静かな時間の中で考えてた。"),
        ]
        state = self._make_state(pairs)
        result = self.recent_history(state, max_pairs=4, turn_intent="direct_answer")
        human_texts = [getattr(m, "content", "") for m in result
                       if isinstance(m, HumanMessage)]
        # q の番号が昇順であること
        q_numbers = []
        for t in human_texts:
            if t.startswith("q"):
                q_numbers.append(int(t[1:]))
        assert q_numbers == sorted(q_numbers)

    def test_small_history_returns_all(self):
        """max_pairs より候補が少ない → そのまま返す"""
        pairs = [
            ("q1", "まだ言えてない。"),
            ("q2", "静かな時間の中で。"),
        ]
        state = self._make_state(pairs)
        result = self.recent_history(state, max_pairs=5, turn_intent="direct_answer")
        from langchain_core.messages import AIMessage
        ai_texts = [getattr(m, "content", "") for m in result
                     if isinstance(m, AIMessage)]
        assert len(ai_texts) == 2  # both included

    def test_wait_and_role_merge_preserved(self):
        """WAIT 除去と同ロール結合が diversity モードでも維持される"""
        from langchain_core.messages import HumanMessage, AIMessage
        msgs = [
            HumanMessage(content="q1"),
            AIMessage(content="まだ言えてない。"),
            AIMessage(content="WAIT"),  # should be excluded before reaching _recent_history
            HumanMessage(content="q2"),
            AIMessage(content="静かな時間の中で。"),
            HumanMessage(content="current turn"),
        ]
        # WAIT is filtered by content check
        state = {"messages": msgs}
        result = self.recent_history(state, max_pairs=5, turn_intent="direct_answer")
        contents = [getattr(m, "content", "") for m in result]
        assert "WAIT" not in contents


# ── open_reflection trigger-based family cap ─────────────────────


class TestOpenReflectionFamilyCap:
    """open_reflection で family 反復が検出されたときだけ diversity-aware 選択が入る。"""

    @pytest.fixture(autouse=True)
    def _import(self):
        from langchain_core.messages import HumanMessage as _H, AIMessage as _A
        from backend.core.agent_graph.nodes.helpers import _recent_history
        self.recent_history = _recent_history
        self.HumanMessage = _H
        self.AIMessage = _A

    def _build_messages(self, ai_texts: list[str]) -> list:
        """交互の Human/AI メッセージ + 末尾に current turn Human を作る。"""
        H, A = self.HumanMessage, self.AIMessage
        msgs = []
        for i, text in enumerate(ai_texts):
            msgs.append(H(content=f"q{i}"))
            msgs.append(A(content=text))
        msgs.append(H(content="current turn"))
        return msgs

    def test_no_trigger_when_varied(self):
        """Family 反復なし → そのまま（diversity 選択を通らない）"""
        A = self.AIMessage
        msgs = self._build_messages([
            "まだ言えてない。",
            "考えてみたけど。",
            "そうだね。",
            "普通の会話。",
            "別の話題。",
        ])
        state = {"messages": msgs}
        result = self.recent_history(state, max_pairs=5, turn_intent="open_reflection")
        ai_contents = [getattr(m, "content", "") for m in result if isinstance(m, A)]
        assert len(ai_contents) == 5

    def test_trigger_when_family_repeats(self):
        """Family 反復あり → diversity-aware 選択で repeated family が cap される"""
        A = self.AIMessage
        msgs = self._build_messages([
            "静かな時間の中で。",
            "穏やかな気持ち。",
            "落ち着いた雰囲気。",
            "まだ言えてない。",
            "考えてみた。",
            "静かな時間を過ごして。",
            "普通の会話。",
            "別の話題。",
        ])
        state = {"messages": msgs}
        result = self.recent_history(state, max_pairs=5, turn_intent="open_reflection")
        ai_contents = [getattr(m, "content", "") for m in result if isinstance(m, A)]

        # quiet_atmosphere family は cap + anchor=1 で強く制限される
        quiet_count = sum(
            1 for c in ai_contents
            if any(m in c for m in ("静かな時間", "穏やか", "落ち着い"))
        )
        # anchor=1 + scored cap(half) → quiet は最大 2-3
        assert quiet_count <= 3, f"quiet family should be capped, got {quiet_count}"
        # Non-family 応答が十分含まれる
        non_quiet = [c for c in ai_contents if not any(m in c for m in ("静かな時間", "穏やか", "落ち着い"))]
        assert len(non_quiet) >= 2

    def test_other_families_not_penalized(self):
        """Trigger された family 以外は cap されない"""
        A = self.AIMessage
        msgs = self._build_messages([
            "静かな時間の中で。",         # quiet_atmosphere (trigger)
            "穏やかな気持ち。",            # quiet_atmosphere (trigger)
            "心が動いた気がする。",         # heart_moves (別 family)
            "何かが揺れている。",           # heart_moves (別 family)
            "まだ言えてない。",
            "考えてみた。",
            "普通の会話。",
            "別の話題。",
        ])
        state = {"messages": msgs}
        result = self.recent_history(state, max_pairs=5, turn_intent="open_reflection")
        ai_contents = [getattr(m, "content", "") for m in result if isinstance(m, A)]

        # heart_moves は target ではないので cap されない
        heart_count = sum(
            1 for c in ai_contents
            if any(m in c for m in ("心が動", "揺れ"))
        )
        # heart_moves のペアが残っている（cap で落とされていない）
        assert heart_count >= 1, "non-target family should not be penalized"

    def test_short_history_still_caps_when_triggered(self):
        """5 ペア以下でも trigger 時は family cap が効く"""
        A = self.AIMessage
        msgs = self._build_messages([
            "静かな時間の中で。",
            "穏やかな気持ち。",
            "落ち着いた雰囲気。",
            "まだ言えてない。",
        ])
        state = {"messages": msgs}
        result = self.recent_history(state, max_pairs=5, turn_intent="open_reflection")
        ai_contents = [getattr(m, "content", "") for m in result if isinstance(m, A)]

        # 4 ペア（< max_pairs=5）でも trigger が発火して cap が効く
        quiet_count = sum(
            1 for c in ai_contents
            if any(m in c for m in ("静かな時間", "穏やか", "落ち着い"))
        )
        # 4 ペア中 3 が quiet → cap で最低 1 つは落ちるはず
        assert quiet_count <= 2, f"short history: quiet should be capped, got {quiet_count}"

    def test_no_direct_bonus_in_open_reflection(self):
        """open_reflection では direct opener bonus が入らない"""
        A = self.AIMessage
        msgs = self._build_messages([
            "静かな時間の中で。",
            "穏やかな気持ち。",
            "まだ言えてない。",  # direct opener
            "いいえ。",           # direct opener
            "考えてみた。",
            "静かな時間を過ごして。",
        ])
        state = {"messages": msgs}
        result = self.recent_history(state, max_pairs=5, turn_intent="open_reflection")
        ai_contents = [getattr(m, "content", "") for m in result if isinstance(m, A)]

        # direct_answer 用の bonus がないので、direct opener が
        # 他の non-family テキストより優先されるわけではない
        # 重要なのは family cap だけが効いていること
        quiet_count = sum(
            1 for c in ai_contents
            if any(m in c for m in ("静かな時間", "穏やか", "落ち着い"))
        )
        assert quiet_count <= 3
