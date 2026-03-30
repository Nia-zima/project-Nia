"""Tests for drawing prompt reference generation and intent detection.

Covers:
- draw_intent detection from user_text
- prompt reference vocabulary matches intent_schema.py enums
- build_context_suffix injection when draw_intent is present
- no injection when draw_intent is absent or test_mode
- parser-level security and modifier restrictions (unchanged)
"""
from __future__ import annotations

import pytest


# ── Draw intent detection ──────────────────────────────────────────────


class TestDrawIntentDetection:
    """Test detect_draw_intent pure function."""

    def test_japanese_draw_keywords(self):
        from backend.core.drawing.prompt_ref import detect_draw_intent

        assert detect_draw_intent("絵を描きたい")
        assert detect_draw_intent("お絵かきしよう")
        assert detect_draw_intent("心の風景を描いて")
        assert detect_draw_intent("落書きする")
        assert detect_draw_intent("イラスト描こう")

    def test_english_draw_keywords(self):
        from backend.core.drawing.prompt_ref import detect_draw_intent

        assert detect_draw_intent("can you draw something?")
        assert detect_draw_intent("let's sketch")

    def test_no_intent(self):
        from backend.core.drawing.prompt_ref import detect_draw_intent

        assert not detect_draw_intent("今日の天気は？")
        assert not detect_draw_intent("考えてみて")
        assert not detect_draw_intent("")

    def test_empty_and_none(self):
        from backend.core.drawing.prompt_ref import detect_draw_intent

        assert not detect_draw_intent("")
        assert not detect_draw_intent(None)  # type: ignore[arg-type]


# ── Prompt reference vocabulary consistency ─────────────────────────────


class TestPromptReferenceVocabulary:
    """Verify that the prompt reference includes all intent_schema.py vocabulary."""

    def test_all_intent_element_types_in_reference(self):
        from backend.core.drawing.prompt_ref import build_drawing_reference
        from backend.core.drawing.intent_schema import IntentElementType

        ref = build_drawing_reference()
        for et in IntentElementType:
            assert et.value in ref, f"IntentElementType {et.value} missing from reference"

    def test_all_intent_roles_in_reference(self):
        from backend.core.drawing.prompt_ref import build_drawing_reference
        from backend.core.drawing.intent_schema import IntentRole

        ref = build_drawing_reference()
        for r in IntentRole:
            assert r.value in ref, f"IntentRole {r.value} missing from reference"

    def test_all_intent_sizes_in_reference(self):
        from backend.core.drawing.prompt_ref import build_drawing_reference
        from backend.core.drawing.intent_schema import IntentSize

        ref = build_drawing_reference()
        for s in IntentSize:
            assert s.value in ref, f"IntentSize {s.value} missing from reference"

    def test_all_intent_color_feels_in_reference(self):
        from backend.core.drawing.prompt_ref import build_drawing_reference
        from backend.core.drawing.intent_schema import IntentColorFeel

        ref = build_drawing_reference()
        for c in IntentColorFeel:
            assert c.value in ref, f"IntentColorFeel {c.value} missing from reference"

    def test_all_intent_positions_in_reference(self):
        from backend.core.drawing.prompt_ref import build_drawing_reference
        from backend.core.drawing.intent_schema import IntentPosition

        ref = build_drawing_reference()
        for p in IntentPosition:
            assert p.value in ref, f"IntentPosition {p.value} missing from reference"

    def test_all_intent_arrangements_in_reference(self):
        from backend.core.drawing.prompt_ref import build_drawing_reference
        from backend.core.drawing.intent_schema import IntentArrangement

        ref = build_drawing_reference()
        for a in IntentArrangement:
            assert a.value in ref, f"IntentArrangement {a.value} missing from reference"

    def test_all_intent_dominance_in_reference(self):
        from backend.core.drawing.prompt_ref import build_drawing_reference
        from backend.core.drawing.intent_schema import IntentDominance

        ref = build_drawing_reference()
        for d in IntentDominance:
            assert d.value in ref, f"IntentDominance {d.value} missing from reference"

    def test_reference_contains_draw_fence(self):
        """Reference shows ```draw fence so LLM knows the output format."""
        from backend.core.drawing.prompt_ref import build_drawing_reference

        ref = build_drawing_reference()
        assert "```draw" in ref

    def test_reference_contains_reason_field(self):
        from backend.core.drawing.prompt_ref import build_drawing_reference

        ref = build_drawing_reference()
        assert "reason" in ref

    def test_reference_contains_example(self):
        from backend.core.drawing.prompt_ref import build_drawing_reference

        ref = build_drawing_reference()
        assert "elements:" in ref

    def test_dead_fields_not_in_prompt(self):
        """overall_mood, relation_strength, count_mode are v0-unused — don't expose."""
        from backend.core.drawing.prompt_ref import build_drawing_reference

        ref = build_drawing_reference()
        assert "overall_mood" not in ref
        assert "relation_strength" not in ref
        assert "count_mode" not in ref


# ── Context suffix injection ────────────────────────────────────────────


class TestContextSuffixInjection:
    """Test that build_context_suffix injects drawing ref on draw_intent."""

    def test_draw_intent_injects_reference(self):
        from backend.core.agent_graph.nodes.helpers import build_context_suffix

        state = {
            "user_text": "絵を描きたい",
            "memory_context": "",
        }
        suffix = build_context_suffix(state)
        assert "=== 描画の手 ===" in suffix

    def test_no_draw_intent_no_injection(self):
        from backend.core.agent_graph.nodes.helpers import build_context_suffix

        state = {
            "user_text": "今日はどうだった？",
            "memory_context": "",
        }
        suffix = build_context_suffix(state)
        assert "描画の手" not in suffix

    def test_test_mode_no_injection(self):
        from backend.core.agent_graph.nodes.helpers import build_context_suffix

        state = {
            "user_text": "絵を描きたい",
            "memory_context": "",
            "test_mode": True,
        }
        suffix = build_context_suffix(state)
        assert "描画の手" not in suffix

    def test_injection_includes_all_element_types(self):
        from backend.core.agent_graph.nodes.helpers import build_context_suffix
        from backend.core.drawing.intent_schema import IntentElementType

        state = {
            "user_text": "draw something",
            "memory_context": "",
        }
        suffix = build_context_suffix(state)
        for et in IntentElementType:
            assert et.value in suffix


# ── Parser rejects unsafe names ────────────────────────────────────────


class TestParserRejectsUnsafeNames:
    """Element names and because tags must be safe for SVG attributes."""

    def test_injection_in_element_name(self):
        from backend.core.drawing.parser import parse_drawing

        with pytest.raises(ValueError, match="Invalid element name"):
            parse_drawing('a"onload="alert(1): circle')

    def test_spaces_in_element_name(self):
        from backend.core.drawing.parser import parse_drawing

        with pytest.raises(ValueError):
            parse_drawing("a b: circle")

    def test_injection_in_because_tag(self):
        from backend.core.drawing.parser import parse_drawing

        with pytest.raises(ValueError, match="Invalid because tag"):
            parse_drawing('a: circle\na at center because "onclick=evil')

    def test_valid_names_pass(self):
        from backend.core.drawing.parser import parse_drawing

        ast = parse_drawing("my_element-1: circle\nmy_element-1 at center because anchor")
        assert len(ast.declarations) == 1
        assert ast.declarations[0].name == "my_element-1"


class TestRendererEscaping:
    """SVG renderer escapes data attributes."""

    def test_name_is_escaped_in_svg(self):
        from backend.core.drawing.parser import parse_drawing
        from backend.core.drawing.scene_graph import build_scene_graph
        from backend.core.drawing.renderer import render_svg

        ast = parse_drawing("test_node: circle\ntest_node at center")
        scene = build_scene_graph(ast)
        svg = render_svg(scene)
        assert 'data-name="test_node"' in svg

    def test_because_tags_escaped_in_svg(self):
        from backend.core.drawing.parser import parse_drawing
        from backend.core.drawing.scene_graph import build_scene_graph
        from backend.core.drawing.renderer import render_svg

        ast = parse_drawing("a: circle\na at center because anchor")
        scene = build_scene_graph(ast)
        svg = render_svg(scene)
        assert 'data-because="anchor"' in svg


# ── Parser rejects no-op element modifiers ─────────────────────────────


class TestParserRejectsNoOpModifiers:
    """Verify parser raises on density/drift/ratio as element modifiers."""

    def test_density_as_element_modifier_raises(self):
        from backend.core.drawing.parser import parse_drawing

        with pytest.raises(ValueError, match="composition-only"):
            parse_drawing("a: circle\na density dense")

    def test_drift_as_element_modifier_raises(self):
        from backend.core.drawing.parser import parse_drawing

        with pytest.raises(ValueError, match="composition-only"):
            parse_drawing("a: circle\na drift slight")

    def test_ratio_as_element_modifier_raises(self):
        from backend.core.drawing.parser import parse_drawing

        with pytest.raises(ValueError, match="declaration-only"):
            parse_drawing("a: circle\na ratio wide")

    def test_valid_element_modifiers_still_work(self):
        from backend.core.drawing.parser import parse_drawing

        ast = parse_drawing(
            "a: circle\na color warm_3\na opacity faint\na size small\n"
            "a weight bold\na softness blur"
        )
        assert len(ast.modifiers) == 5

    def test_density_in_composition_still_works(self):
        from backend.core.drawing.parser import parse_drawing

        ast = parse_drawing("a: circle\na at center\nscatter dot around a count=4 density=sparse")
        assert len(ast.compositions) == 1
        assert ast.compositions[0].density.value == "sparse"

    def test_drift_in_composition_still_works(self):
        from backend.core.drawing.parser import parse_drawing

        ast = parse_drawing("a: circle\na at center\nscatter dot around a count=4 drift=slight")
        assert len(ast.compositions) == 1
        assert ast.compositions[0].drift.value == "slight"
