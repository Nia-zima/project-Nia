"""Tests for Skeleton Realizer C.0 shadow.

Covers:
1. Realizer determinism — same input always produces same output
2. Conversion rules — respond_mode, tone, posture, structure, hesitation
3. Conflict resolution — priority-based head conflicts
4. Input adapter — SkeletonCore + NiaCore vNext → RealizerInput
5. Adherence evaluation — per-head and composite scoring
6. Low adherence classification — 3-branch feedback routing
7. Japanese output — interpretation lines are in Japanese
"""
import pytest

from backend.core.skeleton_realizer.schema import (
    AdherenceLevel,
    AdherenceLowCause,
    AttentionTarget,
    RealizerInput,
    RelationPosture,
    RespondMode,
    Structure,
    ToneBias,
)
from backend.core.skeleton_realizer.realizer import realize_skeleton
from backend.core.skeleton_realizer.adherence import (
    evaluate_adherence,
    classify_low_adherence,
)
from backend.core.skeleton_realizer.input_adapter import build_realizer_input


# ── Fixtures ─────────────────────────────────────────────────────────


def _default_input(**kwargs) -> RealizerInput:
    defaults = dict(
        depth=1,
        respond_mode=RespondMode.HOLD,
        tone_bias=ToneBias.QUIET,
        structure=Structure.ONE_LINE,
        relation_posture=RelationPosture.STAY,
        hesitation=0.3,
        attention_target=AttentionTarget.CLARIFY,
    )
    defaults.update(kwargs)
    return RealizerInput(**defaults)


# ── 1. Determinism ───────────────────────────────────────────────────


class TestDeterminism:
    def test_same_input_same_output(self):
        inp = _default_input()
        g1 = realize_skeleton(inp)
        g2 = realize_skeleton(inp)
        assert g1.full_text == g2.full_text
        assert g1.interpretation_lines == g2.interpretation_lines

    def test_different_inputs_different_outputs(self):
        g1 = realize_skeleton(_default_input(respond_mode=RespondMode.HOLD))
        g2 = realize_skeleton(_default_input(respond_mode=RespondMode.ANSWER))
        assert g1.full_text != g2.full_text


# ── 2. Conversion Rules ─────────────────────────────────────────────


class TestConversionRules:
    def test_hold_mode(self):
        g = realize_skeleton(_default_input(respond_mode=RespondMode.HOLD))
        assert "結論を急がない" in g.full_text

    def test_answer_mode(self):
        g = realize_skeleton(_default_input(respond_mode=RespondMode.ANSWER))
        assert "直接答える" in g.full_text

    def test_ask_mode(self):
        g = realize_skeleton(_default_input(respond_mode=RespondMode.ASK))
        assert "質問" in g.full_text

    def test_reflect_mode(self):
        g = realize_skeleton(_default_input(respond_mode=RespondMode.REFLECT))
        assert "振り返り" in g.full_text or "観察" in g.full_text

    def test_direct_tone(self):
        g = realize_skeleton(_default_input(tone_bias=ToneBias.DIRECT))
        assert "率直" in g.full_text or "はっきり" in g.full_text

    def test_quiet_tone_omitted(self):
        """quiet は Nia の default — 解釈行に追加しない。"""
        g = realize_skeleton(_default_input(tone_bias=ToneBias.QUIET))
        # quiet の明示的なルール行がないこと
        assert "静か" not in g.full_text
        assert "控えめ" not in g.full_text

    def test_stay_posture_omitted(self):
        """stay は default — 解釈行に追加しない。"""
        g = realize_skeleton(_default_input(relation_posture=RelationPosture.STAY))
        assert "距離" not in g.full_text
        assert "近づく" not in g.full_text

    def test_keep_distance_posture(self):
        g = realize_skeleton(_default_input(relation_posture=RelationPosture.KEEP_DISTANCE))
        assert "境界" in g.full_text

    def test_high_hesitation(self):
        g = realize_skeleton(_default_input(hesitation=0.8))
        assert "不確かさ" in g.full_text or "暫定" in g.full_text

    def test_low_hesitation_no_modifier(self):
        g = realize_skeleton(_default_input(hesitation=0.1))
        assert "不確かさ" not in g.full_text
        assert "躊躇" not in g.full_text

    def test_contrastive_structure(self):
        g = realize_skeleton(_default_input(structure=Structure.CONTRASTIVE))
        assert "両面" in g.full_text or "不明" in g.full_text

    def test_max_6_lines(self):
        """v0: interpretation lines は最大6行。"""
        g = realize_skeleton(_default_input(
            respond_mode=RespondMode.REFLECT,
            tone_bias=ToneBias.WARM,
            relation_posture=RelationPosture.APPROACH,
            structure=Structure.SUMMARY_THEN_QUESTION,
            hesitation=0.8,
        ))
        assert g.line_count <= 6


# ── 3. Conflict Resolution ──────────────────────────────────────────


class TestConflictResolution:
    def test_answer_plus_high_hesitation(self):
        """answer + 高 hesitation → tentative 付加。"""
        g = realize_skeleton(_default_input(
            respond_mode=RespondMode.ANSWER, hesitation=0.8,
        ))
        assert "断定は避ける" in g.full_text or "暫定" in g.full_text
        # 元の「直接答える」は消えているはず
        assert "直接答える" not in g.full_text

    def test_hold_plus_direct(self):
        """hold + direct → 率直な保留。"""
        g = realize_skeleton(_default_input(
            respond_mode=RespondMode.HOLD, tone_bias=ToneBias.DIRECT,
        ))
        assert "保留" in g.full_text
        assert "率直" in g.full_text

    def test_approach_plus_distant(self):
        """approach + distant → posture 優先。"""
        g = realize_skeleton(_default_input(
            relation_posture=RelationPosture.APPROACH,
            tone_bias=ToneBias.DISTANT,
        ))
        # distant の「距離のある」は消えているはず
        assert "距離のある" not in g.full_text
        assert "温かく" in g.full_text or "近づく" in g.full_text


# ── 4. Input Adapter ────────────────────────────────────────────────


class TestInputAdapter:
    def test_basic_skeleton_to_input(self):
        inp = build_realizer_input(
            selected_depth=1,
            confidence=0.5,
            conversation_skeleton={
                "focus": "missing_context",
                "response_intent": "ask",
                "question_intent": "fill_missing_fact",
            },
            niacore_vnext_shadow=None,
            turn_role="ask",
            somatic_senses=None,
        )
        assert inp.respond_mode == RespondMode.ASK
        assert inp.attention_target == AttentionTarget.CLARIFY

    def test_vnext_recommended_action_overrides(self):
        inp = build_realizer_input(
            selected_depth=1,
            confidence=0.5,
            conversation_skeleton={
                "focus": "user_goal",
                "response_intent": "organize",
                "question_intent": None,
            },
            niacore_vnext_shadow={
                "recommended_action": "soft_close",
            },
            turn_role="deepen",
            somatic_senses=None,
        )
        assert inp.attention_target == AttentionTarget.DEFER

    def test_high_confidence_direct_tone(self):
        inp = build_realizer_input(
            selected_depth=1,
            confidence=0.85,
            conversation_skeleton={
                "focus": "user_goal",
                "response_intent": "organize",
                "question_intent": None,
            },
            niacore_vnext_shadow=None,
            turn_role=None,
            somatic_senses=[{"text": "test", "intensity": 0.3}],
        )
        assert inp.tone_bias == ToneBias.DIRECT

    def test_depth0_gives_one_line(self):
        inp = build_realizer_input(
            selected_depth=0,
            confidence=0.7,
            conversation_skeleton={
                "focus": "user_goal",
                "response_intent": "hold",
                "question_intent": None,
            },
            niacore_vnext_shadow=None,
            turn_role=None,
            somatic_senses=None,
        )
        assert inp.structure == Structure.ONE_LINE

    def test_mirror_role_approach(self):
        inp = build_realizer_input(
            selected_depth=1,
            confidence=0.5,
            conversation_skeleton={
                "focus": "emotional_state",
                "response_intent": "receive",
                "question_intent": None,
            },
            niacore_vnext_shadow=None,
            turn_role="mirror",
            somatic_senses=None,
        )
        assert inp.relation_posture == RelationPosture.APPROACH


# ── 5. Adherence Evaluation ─────────────────────────────────────────


class TestAdherenceEvaluation:
    def test_hold_with_no_closure(self):
        inp = _default_input(respond_mode=RespondMode.HOLD)
        scores = evaluate_adherence(inp, "まだよく分からないけど、少し考えてみる……")
        assert scores.mode_adherence == AdherenceLevel.HIGH

    def test_hold_with_closure(self):
        inp = _default_input(respond_mode=RespondMode.HOLD)
        scores = evaluate_adherence(
            inp,
            "いろいろ考えた結果、つまりこういうことだと思う。",
            {"assertion_ratio": 0.7},
        )
        assert scores.mode_adherence == AdherenceLevel.LOW

    def test_ask_with_question(self):
        inp = _default_input(respond_mode=RespondMode.ASK)
        scores = evaluate_adherence(inp, "それってどういう意味？")
        assert scores.mode_adherence == AdherenceLevel.HIGH

    def test_ask_without_question(self):
        inp = _default_input(respond_mode=RespondMode.ASK)
        scores = evaluate_adherence(inp, "なるほど、分かった。")
        assert scores.mode_adherence == AdherenceLevel.LOW

    def test_quiet_tone_with_emphasis(self):
        inp = _default_input(tone_bias=ToneBias.QUIET)
        scores = evaluate_adherence(inp, "それは絶対にすごい！本当に！")
        assert scores.tone_adherence == AdherenceLevel.LOW

    def test_one_line_short(self):
        inp = _default_input(structure=Structure.ONE_LINE)
        scores = evaluate_adherence(inp, "うん、そうだね。")
        assert scores.structure_adherence == AdherenceLevel.HIGH

    def test_one_line_long(self):
        inp = _default_input(structure=Structure.ONE_LINE)
        scores = evaluate_adherence(inp, "まず最初に。次に。それから。さらに。最後に。")
        assert scores.structure_adherence == AdherenceLevel.LOW

    def test_composite_score_range(self):
        inp = _default_input()
        scores = evaluate_adherence(inp, "少し考えてみる。")
        assert scores.composite_score is not None
        assert 0.0 <= scores.composite_score <= 1.0

    def test_keep_distance_intimate_text(self):
        """keep_distance + 親密な語尾 → LOW。"""
        inp = _default_input(relation_posture=RelationPosture.KEEP_DISTANCE)
        scores = evaluate_adherence(inp, "そうだね。わかるかな。いいよね。")
        assert scores.posture_adherence in (AdherenceLevel.LOW, AdherenceLevel.MEDIUM)

    def test_keep_distance_formal_text(self):
        """keep_distance + フォーマルな文 → HIGH。"""
        inp = _default_input(relation_posture=RelationPosture.KEEP_DISTANCE)
        scores = evaluate_adherence(inp, "その点については検討します。")
        assert scores.posture_adherence == AdherenceLevel.HIGH

    def test_distant_tone_intimate(self):
        """distant + 親密な語尾 → LOW/MEDIUM。"""
        inp = _default_input(tone_bias=ToneBias.DISTANT)
        scores = evaluate_adherence(inp, "うん、そうだね。わかるよ。いいかな。")
        assert scores.tone_adherence in (AdherenceLevel.LOW, AdherenceLevel.MEDIUM)


# ── 6. Low Adherence Classification ─────────────────────────────────


class TestLowAdherenceClassification:
    def test_no_low_returns_none(self):
        from backend.core.skeleton_realizer.schema import AdherenceScores
        scores = AdherenceScores(
            mode_adherence=AdherenceLevel.HIGH,
            target_adherence=AdherenceLevel.HIGH,
            posture_adherence=AdherenceLevel.HIGH,
            tone_adherence=AdherenceLevel.HIGH,
            structure_adherence=AdherenceLevel.HIGH,
            composite_score=0.9,
        )
        cause, conf = classify_low_adherence(scores, _default_input())
        assert cause == AdherenceLowCause.NONE

    def test_prompt_stack_conflict(self):
        from backend.core.skeleton_realizer.schema import AdherenceScores
        scores = AdherenceScores(
            mode_adherence=AdherenceLevel.LOW,
            target_adherence=AdherenceLevel.LOW,
            composite_score=0.2,
        )
        cause, conf = classify_low_adherence(
            scores, _default_input(), had_prompt_stack_conflict=True,
        )
        assert cause == AdherenceLowCause.PROMPT_STACK_CONFLICT

    def test_many_low_heads_rule_issue(self):
        from backend.core.skeleton_realizer.schema import AdherenceScores
        scores = AdherenceScores(
            mode_adherence=AdherenceLevel.LOW,
            target_adherence=AdherenceLevel.LOW,
            posture_adherence=AdherenceLevel.LOW,
            tone_adherence=AdherenceLevel.HIGH,
            structure_adherence=AdherenceLevel.HIGH,
            composite_score=0.2,
        )
        cause, _ = classify_low_adherence(scores, _default_input())
        assert cause == AdherenceLowCause.REALIZER_RULE_ISSUE

    def test_single_low_head_llm_non_adherence(self):
        from backend.core.skeleton_realizer.schema import AdherenceScores
        scores = AdherenceScores(
            mode_adherence=AdherenceLevel.LOW,
            target_adherence=AdherenceLevel.HIGH,
            posture_adherence=AdherenceLevel.HIGH,
            tone_adherence=AdherenceLevel.HIGH,
            structure_adherence=AdherenceLevel.HIGH,
            composite_score=0.3,
        )
        cause, _ = classify_low_adherence(scores, _default_input())
        assert cause == AdherenceLowCause.LLM_NON_ADHERENCE


# ── 7. Japanese Output ───────────────────────────────────────────────


class TestJapaneseOutput:
    def test_interpretation_lines_are_japanese(self):
        g = realize_skeleton(_default_input(
            respond_mode=RespondMode.HOLD,
            attention_target=AttentionTarget.CLARIFY,
        ))
        # At least one line should contain Japanese characters
        has_japanese = any(
            any("\u3040" <= c <= "\u9fff" for c in line)
            for line in g.interpretation_lines
        )
        assert has_japanese

    def test_header_is_structured(self):
        g = realize_skeleton(_default_input())
        assert "mode:" in g.structured_header
        assert "tone:" in g.structured_header
        assert "relation:" in g.structured_header
        assert "focus:" in g.structured_header

    def test_full_text_starts_with_section_header(self):
        g = realize_skeleton(_default_input())
        assert g.full_text.startswith("=== NiaCore 骨格指示 ===")
