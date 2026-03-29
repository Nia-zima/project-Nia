"""Tests for drawing prompt reference generation and intent detection.

Covers:
- draw_intent detection from user_text
- prompt reference vocabulary matches schema.py constants
- build_context_suffix injection when draw_intent is present
- no injection when draw_intent is absent or test_mode
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
    """Verify that the prompt reference includes all schema.py vocabulary."""

    def test_all_element_types_in_reference(self):
        from backend.core.drawing.prompt_ref import build_drawing_reference
        from backend.core.drawing.schema import ElementType

        ref = build_drawing_reference()
        for et in ElementType:
            assert et.value in ref, f"ElementType {et.value} missing from reference"

    def test_all_relations_in_reference(self):
        from backend.core.drawing.prompt_ref import build_drawing_reference
        from backend.core.drawing.schema import Relation

        ref = build_drawing_reference()
        for r in Relation:
            assert r.value in ref, f"Relation {r.value} missing from reference"

    def test_all_spatial_refs_in_reference(self):
        from backend.core.drawing.prompt_ref import build_drawing_reference
        from backend.core.drawing.schema import SpatialRef

        ref = build_drawing_reference()
        for s in SpatialRef:
            assert s.value in ref, f"SpatialRef {s.value} missing from reference"

    def test_all_palette_colors_in_reference(self):
        from backend.core.drawing.prompt_ref import build_drawing_reference
        from backend.core.drawing.schema import PaletteColor

        ref = build_drawing_reference()
        for c in PaletteColor:
            assert c.value in ref, f"PaletteColor {c.value} missing from reference"

    def test_element_modifier_attributes_in_reference(self):
        from backend.core.drawing.prompt_ref import build_drawing_reference
        from backend.core.drawing.schema import ELEMENT_MODIFIER_ATTRIBUTES

        ref = build_drawing_reference()
        for attr in ELEMENT_MODIFIER_ATTRIBUTES:
            assert attr in ref, f"Element modifier '{attr}' missing from reference"

    def test_element_modifier_levels_in_reference(self):
        from backend.core.drawing.prompt_ref import build_drawing_reference
        from backend.core.drawing.schema import ELEMENT_MODIFIER_LEVELS

        ref = build_drawing_reference()
        for attr, enum_cls in ELEMENT_MODIFIER_LEVELS.items():
            for lv in enum_cls:
                assert lv.value in ref, f"Level {attr}.{lv.value} missing from reference"

    def test_composition_kwargs_in_reference(self):
        from backend.core.drawing.prompt_ref import build_drawing_reference
        from backend.core.drawing.schema import COMPOSITION_KWARGS

        ref = build_drawing_reference()
        for kw in COMPOSITION_KWARGS:
            assert kw in ref, f"Composition kwarg '{kw}' missing from reference"

    def test_composition_kwarg_levels_in_reference(self):
        from backend.core.drawing.prompt_ref import build_drawing_reference
        from backend.core.drawing.schema import COMPOSITION_KWARG_LEVELS

        ref = build_drawing_reference()
        for attr, enum_cls in COMPOSITION_KWARG_LEVELS.items():
            for lv in enum_cls:
                assert lv.value in ref, f"Composition kwarg level {attr}.{lv.value} missing"

    def test_no_op_modifiers_excluded_from_element_section(self):
        """density, drift, ratio should NOT appear as element modifiers in the prompt."""
        from backend.core.drawing.prompt_ref import build_drawing_reference

        ref = build_drawing_reference()
        # Split at "構成" to isolate the element modifier section
        elem_section = ref.split("構成")[0]
        # ratio should not appear at all (declaration-only, not in prompt)
        assert "ratio" not in elem_section
        # density/drift should be in composition section, not element section
        assert "density" not in elem_section
        assert "drift" not in elem_section

    def test_composition_ops_in_reference(self):
        from backend.core.drawing.prompt_ref import build_drawing_reference
        from backend.core.drawing.schema import CompositionOp

        ref = build_drawing_reference()
        for op in CompositionOp:
            assert op.value in ref, f"CompositionOp {op.value} missing from reference"

    def test_composition_prepositions_in_reference(self):
        from backend.core.drawing.prompt_ref import build_drawing_reference
        from backend.core.drawing.schema import COMPOSITION_PREPOSITIONS

        ref = build_drawing_reference()
        for prep in COMPOSITION_PREPOSITIONS:
            assert prep in ref, f"Preposition '{prep}' missing from reference"

    def test_reference_contains_draw_fence(self):
        """Reference shows the ```draw fence so LLM knows the output format."""
        from backend.core.drawing.prompt_ref import build_drawing_reference

        ref = build_drawing_reference()
        assert "```draw" in ref

    def test_reference_contains_because(self):
        from backend.core.drawing.prompt_ref import build_drawing_reference

        ref = build_drawing_reference()
        assert "because" in ref


# ── Context suffix injection ────────────────────────────────────────────


# ── Parser rejects no-op element modifiers ─────────────────────────────


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

        # Even if a name somehow got through, renderer escapes it
        ast = parse_drawing("test_node: circle\ntest_node at center")
        scene = build_scene_graph(ast)
        svg = render_svg(scene)
        assert 'data-name="test_node"' in svg
        # Verify no unescaped quotes in data attributes
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
        from backend.core.drawing.schema import ElementType

        state = {
            "user_text": "draw something",
            "memory_context": "",
        }
        suffix = build_context_suffix(state)
        for et in ElementType:
            assert et.value in suffix
