"""Tests for Nia Drawing Language (Phase 1)."""
from __future__ import annotations

import pytest

from backend.core.drawing.parser import parse_drawing
from backend.core.drawing.scene_graph import build_scene_graph, CanvasConfig
from backend.core.drawing.renderer import render_svg
from backend.core.drawing.schema import (
    ElementType,
    Relation,
    SizeLevel,
)


# ── Parser Tests ──────────────────────────────────────────────────────


class TestParser:
    def test_declaration_simple(self):
        ast = parse_drawing("a: circle")
        assert len(ast.declarations) == 1
        assert ast.declarations[0].name == "a"
        assert ast.declarations[0].element_type == ElementType.CIRCLE

    def test_declaration_with_args(self):
        ast = parse_drawing("core: circle(size=small)")
        assert ast.declarations[0].size == SizeLevel.SMALL

    def test_placement(self):
        ast = parse_drawing("a at center")
        assert len(ast.placements) == 1
        assert ast.placements[0].subject == "a"
        assert ast.placements[0].relation == Relation.AT
        assert ast.placements[0].target == "center"

    def test_placement_with_distance(self):
        ast = parse_drawing("b above a far")
        assert ast.placements[0].distance == "far"

    def test_placement_with_because(self):
        ast = parse_drawing("a at center because anchor")
        assert ast.placements[0].because is not None
        assert "anchor" in ast.placements[0].because.tags

    def test_placement_with_multi_because(self):
        ast = parse_drawing("a at center because anchor + balance")
        tags = ast.placements[0].because.tags
        assert "anchor" in tags
        assert "balance" in tags

    def test_modifier(self):
        ast = parse_drawing("a color warm_3")
        assert len(ast.modifiers) == 1
        assert ast.modifiers[0].attribute == "color"
        assert ast.modifiers[0].value == "warm_3"

    def test_modifier_with_because(self):
        ast = parse_drawing("a opacity faint because distance")
        assert ast.modifiers[0].because is not None
        assert "distance" in ast.modifiers[0].because.tags

    def test_composition_repeat(self):
        ast = parse_drawing("repeat dot around a count=4 density=sparse")
        assert len(ast.compositions) == 1
        assert ast.compositions[0].op.value == "repeat"
        assert ast.compositions[0].element_type == ElementType.DOT
        assert ast.compositions[0].count == 4

    def test_composition_scatter(self):
        ast = parse_drawing("scatter line in b density=dense")
        assert ast.compositions[0].op.value == "scatter"
        assert ast.compositions[0].element_type == ElementType.LINE

    def test_comment_ignored(self):
        ast = parse_drawing("# this is a comment\na: circle")
        assert len(ast.declarations) == 1

    def test_inline_free_text(self):
        ast = parse_drawing("a color warm_3 because presence -- this felt right")
        assert ast.modifiers[0].because.free_text == "this felt right"

    def test_full_program(self):
        code = """
# declaration
sky: area(size=vast)
core: circle(size=small)
fragment: dot

# placement
sky at field because background
core at center because anchor
fragment above core near because orbiting

# modifier
sky color cool_1
sky opacity faint
core color warm_3
core opacity solid because presence

# composition
scatter dot around core count=6 density=sparse drift=slight because ambient
"""
        ast = parse_drawing(code)
        assert len(ast.declarations) == 3
        assert len(ast.placements) == 3
        assert len(ast.modifiers) == 4
        assert len(ast.compositions) == 1

    def test_seed_in_composition(self):
        ast = parse_drawing("scatter dot around a count=4 seed=42")
        assert ast.compositions[0].seed == 42

    def test_composition_in_preposition(self):
        ast = parse_drawing("scatter line in b density=dense")
        assert ast.compositions[0].relation.value == "inside"
        assert ast.compositions[0].target == "b"


# ── Scene Graph Tests ─────────────────────────────────────────────────


class TestSceneGraph:
    def test_simple_placement(self):
        code = """
a: circle(size=small)
a at center
"""
        ast = parse_drawing(code)
        scene = build_scene_graph(ast)
        assert len(scene.nodes) == 1
        # Center of 400x400 canvas
        assert abs(scene.nodes[0].x - 200) < 1
        assert abs(scene.nodes[0].y - 200) < 1

    def test_relational_placement(self):
        code = """
a: circle(size=small)
b: dot
a at center
b above a far
"""
        ast = parse_drawing(code)
        scene = build_scene_graph(ast)
        assert len(scene.nodes) == 2
        a_node = next(n for n in scene.nodes if n.name == "a")
        b_node = next(n for n in scene.nodes if n.name == "b")
        # b should be above a (lower y value)
        assert b_node.y < a_node.y

    def test_color_modifier(self):
        code = """
a: circle
a at center
a color warm_3
"""
        ast = parse_drawing(code)
        scene = build_scene_graph(ast)
        assert scene.nodes[0].color == "#D4776B"

    def test_opacity_modifier(self):
        code = """
a: circle
a at center
a opacity faint
"""
        ast = parse_drawing(code)
        scene = build_scene_graph(ast)
        assert scene.nodes[0].opacity == pytest.approx(0.15)

    def test_composition_generates_nodes(self):
        code = """
a: circle
a at center
repeat dot around a count=6
"""
        ast = parse_drawing(code)
        scene = build_scene_graph(ast)
        generated = [n for n in scene.nodes if n.is_generated]
        assert len(generated) == 6

    def test_seed_reproducibility(self):
        code = """
a: circle
a at center
scatter dot around a count=4 seed=42 drift=moderate
"""
        ast = parse_drawing(code)
        scene1 = build_scene_graph(ast)
        scene2 = build_scene_graph(ast)
        gen1 = [(n.x, n.y) for n in scene1.nodes if n.is_generated]
        gen2 = [(n.x, n.y) for n in scene2.nodes if n.is_generated]
        assert gen1 == gen2

    def test_because_tags_preserved(self):
        code = """
a: circle
a at center because anchor + balance
"""
        ast = parse_drawing(code)
        scene = build_scene_graph(ast)
        assert "anchor" in scene.nodes[0].because_tags
        assert "balance" in scene.nodes[0].because_tags

    def test_resolved_layout_stored(self):
        code = """
a: circle
a at center
"""
        ast = parse_drawing(code)
        scene = build_scene_graph(ast)
        assert "a" in scene.resolved_layout

    def test_undeclared_element_raises(self):
        code = """
a: circle
b at center
"""
        ast = parse_drawing(code)
        with pytest.raises(ValueError, match="Undeclared element 'b'"):
            build_scene_graph(ast)

    def test_unknown_target_raises(self):
        code = """
a: circle
a at nonexistent_place
"""
        ast = parse_drawing(code)
        with pytest.raises(ValueError, match="Unknown target 'nonexistent_place'"):
            build_scene_graph(ast)

    def test_background_layer_ordering(self):
        code = """
sky: area(size=vast)
core: circle(size=small)
sky at field because background
core at center because anchor
"""
        ast = parse_drawing(code)
        scene = build_scene_graph(ast)
        sky = next(n for n in scene.nodes if n.name == "sky")
        core = next(n for n in scene.nodes if n.name == "core")
        assert sky.layer == 0  # background
        assert core.layer == 1  # default

    def test_because_free_text_preserved(self):
        code = "a: circle\na at center because anchor"
        ast = parse_drawing(code)
        # Add free text via inline comment
        code2 = "a: circle\na color warm_3 because presence -- this felt warm"
        ast2 = parse_drawing(code2)
        scene = build_scene_graph(ast2)
        a_node = next(n for n in scene.nodes if n.name == "a")
        assert "this felt warm" in a_node.because_text

    def test_scatter_in_target(self):
        code = """
b: area(size=large)
b at center
scatter dot in b count=4 seed=42
"""
        ast = parse_drawing(code)
        scene = build_scene_graph(ast)
        generated = [n for n in scene.nodes if n.is_generated]
        assert len(generated) == 4
        # All generated dots should be within b's area (roughly near center)
        for n in generated:
            assert 50 < n.x < 350  # within canvas with margin
            assert 50 < n.y < 350


# ── Renderer Tests ────────────────────────────────────────────────────


class TestRenderer:
    def test_renders_svg(self):
        code = """
a: circle(size=small)
a at center
a color warm_3
"""
        ast = parse_drawing(code)
        scene = build_scene_graph(ast)
        svg = render_svg(scene)
        assert svg.startswith("<svg")
        assert "</svg>" in svg
        assert "warm" not in svg  # color names replaced with RGB
        assert "#D4776B" in svg

    def test_data_attributes(self):
        code = """
a: circle
a at center because anchor
"""
        ast = parse_drawing(code)
        scene = build_scene_graph(ast)
        svg = render_svg(scene)
        assert 'data-name="a"' in svg
        assert 'data-because="anchor"' in svg

    def test_full_drawing(self):
        code = """
sky: area(size=vast)
core: circle(size=small)
fragment_1: dot
ground: line(weight=thin)

sky at field because background
core at center because anchor
fragment_1 above core near because orbiting
ground below core far because boundary

sky color cool_1
sky opacity faint
core color warm_3
core opacity solid because presence
fragment_1 color warm_1
fragment_1 opacity soft
ground color neutral_1
ground opacity faint

scatter dot around core count=6 density=sparse drift=slight seed=42 because ambient
"""
        ast = parse_drawing(code)
        scene = build_scene_graph(ast)
        svg = render_svg(scene)

        # Basic structure checks
        assert "<svg" in svg
        assert "</svg>" in svg
        assert 'data-name="core"' in svg
        assert 'data-name="sky"' in svg
        # core has both anchor (from placement) and presence (from modifier)
        assert 'data-because="anchor' in svg
        assert 'data-because="background"' in svg

        # Generated nodes from scatter
        generated = [n for n in scene.nodes if n.is_generated]
        assert len(generated) == 6

    def test_area_element_renders_as_ellipse(self):
        code = """
a: area(size=large)
a at center
"""
        ast = parse_drawing(code)
        scene = build_scene_graph(ast)
        svg = render_svg(scene)
        assert "<ellipse" in svg

    def test_line_element(self):
        code = """
a: line(weight=bold)
a at center
"""
        ast = parse_drawing(code)
        scene = build_scene_graph(ast)
        svg = render_svg(scene)
        assert "<line" in svg
