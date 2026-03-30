"""Tests for Drawing Intent Schema and Intent Parser (Layer 1-2).

Tests are organized by:
1. Schema validation — Pydantic model accepts/rejects correctly
2. Intent Parser determinism — same input always produces same DSL
3. Color/dominance mapping — feel → palette, role → dominance
4. Composition handling — scatter/repeat from intent
5. End-to-end — intent YAML → DSL → parse → scene_graph → SVG
"""
import pytest
import yaml

from backend.core.drawing.intent_schema import (
    DrawingIntent,
    IntentArrangement,
    IntentColorFeel,
    IntentCountMode,
    IntentDominance,
    IntentElement,
    IntentElementType,
    IntentOpacityFeel,
    IntentPosition,
    IntentRole,
    IntentSize,
)
from backend.core.drawing.intent_parser import intent_to_dsl


# ── Fixtures ─────────────────────────────────────────────────────────


def _minimal_intent(**kwargs) -> DrawingIntent:
    """Create a minimal valid intent with overrides."""
    defaults = {
        "elements": [
            IntentElement(
                name="core",
                type=IntentElementType.CIRCLE,
                size=IntentSize.SMALL,
                position=IntentPosition.CENTER,
            )
        ]
    }
    defaults.update(kwargs)
    return DrawingIntent(**defaults)


def _full_intent() -> DrawingIntent:
    """The design doc's complete example."""
    return DrawingIntent(
        overall_mood="quiet_warmth",
        elements=[
            IntentElement(
                name="sky",
                type=IntentElementType.AREA,
                role=IntentRole.BACKGROUND,
                size=IntentSize.VAST,
                color_feel=IntentColorFeel.QUIET,
                opacity_feel=IntentOpacityFeel.FAINT,
                position=IntentPosition.FIELD,
                reason="background",
            ),
            IntentElement(
                name="core",
                type=IntentElementType.CIRCLE,
                role=IntentRole.ANCHOR,
                size=IntentSize.SMALL,
                color_feel=IntentColorFeel.WARM,
                opacity_feel=IntentOpacityFeel.SOLID,
                position=IntentPosition.CENTER,
                dominance=IntentDominance.PRIMARY,
                reason="presence",
            ),
            IntentElement(
                name="fragments",
                type=IntentElementType.DOT,
                count=6,
                count_mode=IntentCountMode.APPROXIMATE,
                relation_to="core",
                arrangement=IntentArrangement.SCATTERED_AROUND,
                color_feel=IntentColorFeel.WARM_FADING,
                opacity_feel=IntentOpacityFeel.SOFT,
                reason="orbiting",
            ),
            IntentElement(
                name="ground",
                type=IntentElementType.LINE,
                role=IntentRole.SUPPORT,
                size=IntentSize.MEDIUM,
                relation_to="core",
                arrangement=IntentArrangement.BELOW,
                color_feel=IntentColorFeel.NEUTRAL,
                opacity_feel=IntentOpacityFeel.FAINT,
                reason="boundary",
            ),
        ],
    )


# ── 1. Schema Validation ────────────────────────────────────────────


class TestSchemaValidation:
    def test_minimal_valid(self):
        intent = _minimal_intent()
        assert len(intent.elements) == 1
        assert intent.elements[0].name == "core"

    def test_full_valid(self):
        intent = _full_intent()
        assert len(intent.elements) == 4
        assert intent.overall_mood == "quiet_warmth"

    def test_empty_elements_rejected(self):
        with pytest.raises(Exception):
            DrawingIntent(elements=[])

    def test_duplicate_names_rejected(self):
        with pytest.raises(Exception):
            DrawingIntent(
                elements=[
                    IntentElement(name="a", type=IntentElementType.DOT, position=IntentPosition.CENTER),
                    IntentElement(name="a", type=IntentElementType.CIRCLE, relation_to="a"),
                ]
            )

    def test_first_element_needs_position(self):
        with pytest.raises(Exception):
            DrawingIntent(
                elements=[
                    IntentElement(name="a", type=IntentElementType.DOT, relation_to="b"),
                ]
            )

    def test_invalid_name_rejected(self):
        with pytest.raises(Exception):
            IntentElement(name="123bad", type=IntentElementType.DOT)

    def test_name_with_spaces_rejected(self):
        with pytest.raises(Exception):
            IntentElement(name="my element", type=IntentElementType.DOT)

    def test_count_bounds(self):
        with pytest.raises(Exception):
            IntentElement(name="a", type=IntentElementType.DOT, count=0)
        with pytest.raises(Exception):
            IntentElement(name="a", type=IntentElementType.DOT, count=101)

    def test_count_within_bounds(self):
        e = IntentElement(
            name="a", type=IntentElementType.DOT, count=50,
            arrangement=IntentArrangement.SCATTERED_AROUND,
        )
        assert e.count == 50

    def test_count_requires_scattered_around(self):
        with pytest.raises(Exception):
            IntentElement(
                name="a", type=IntentElementType.DOT, count=5,
                arrangement=IntentArrangement.INSIDE,
            )

    def test_count_without_arrangement_rejected(self):
        with pytest.raises(Exception):
            IntentElement(
                name="a", type=IntentElementType.DOT, count=5,
            )


# ── 2. Intent Parser Determinism ─────────────────────────────────────


class TestParserDeterminism:
    def test_same_input_same_output(self):
        intent = _full_intent()
        dsl1 = intent_to_dsl(intent)
        dsl2 = intent_to_dsl(intent)
        assert dsl1 == dsl2

    def test_minimal_produces_declaration_and_placement(self):
        dsl = intent_to_dsl(_minimal_intent())
        assert "core: circle(size=small)" in dsl
        assert "core at center" in dsl

    def test_no_empty_lines_in_sections(self):
        dsl = intent_to_dsl(_full_intent())
        # Sections are separated by double newlines, but within sections no empty lines
        for section in dsl.split("\n\n"):
            lines = section.strip().split("\n")
            assert all(line.strip() for line in lines)


# ── 3. Color / Dominance Mapping ─────────────────────────────────────


class TestColorDominanceMapping:
    def test_warm_maps_to_palette(self):
        intent = _minimal_intent(
            elements=[
                IntentElement(
                    name="a", type=IntentElementType.CIRCLE,
                    position=IntentPosition.CENTER,
                    color_feel=IntentColorFeel.WARM,
                ),
            ]
        )
        dsl = intent_to_dsl(intent)
        assert "a color warm_2" in dsl

    def test_quiet_maps_to_cool(self):
        intent = _minimal_intent(
            elements=[
                IntentElement(
                    name="a", type=IntentElementType.AREA,
                    position=IntentPosition.FIELD,
                    color_feel=IntentColorFeel.QUIET,
                ),
            ]
        )
        dsl = intent_to_dsl(intent)
        assert "a color cool_1" in dsl

    def test_dominance_primary_gives_solid(self):
        intent = _minimal_intent(
            elements=[
                IntentElement(
                    name="a", type=IntentElementType.CIRCLE,
                    position=IntentPosition.CENTER,
                    dominance=IntentDominance.PRIMARY,
                ),
            ]
        )
        dsl = intent_to_dsl(intent)
        assert "a opacity solid" in dsl

    def test_explicit_opacity_overrides_dominance(self):
        intent = _minimal_intent(
            elements=[
                IntentElement(
                    name="a", type=IntentElementType.CIRCLE,
                    position=IntentPosition.CENTER,
                    dominance=IntentDominance.PRIMARY,
                    opacity_feel=IntentOpacityFeel.FAINT,
                ),
            ]
        )
        dsl = intent_to_dsl(intent)
        assert "a opacity faint" in dsl
        assert "a opacity solid" not in dsl

    def test_role_anchor_implies_primary(self):
        intent = _minimal_intent(
            elements=[
                IntentElement(
                    name="a", type=IntentElementType.CIRCLE,
                    position=IntentPosition.CENTER,
                    role=IntentRole.ANCHOR,
                    # no explicit dominance
                ),
            ]
        )
        dsl = intent_to_dsl(intent)
        assert "a opacity solid" in dsl

    def test_role_background_implies_faint(self):
        intent = _minimal_intent(
            elements=[
                IntentElement(
                    name="a", type=IntentElementType.AREA,
                    position=IntentPosition.FIELD,
                    role=IntentRole.BACKGROUND,
                ),
            ]
        )
        dsl = intent_to_dsl(intent)
        assert "a opacity faint" in dsl


# ── 4. Composition Handling ──────────────────────────────────────────


class TestComposition:
    def test_scattered_around_generates_scatter(self):
        intent = DrawingIntent(
            elements=[
                IntentElement(
                    name="core", type=IntentElementType.CIRCLE,
                    position=IntentPosition.CENTER,
                ),
                IntentElement(
                    name="bits", type=IntentElementType.DOT,
                    count=5, relation_to="core",
                    arrangement=IntentArrangement.SCATTERED_AROUND,
                ),
            ]
        )
        dsl = intent_to_dsl(intent)
        assert "scatter dot around core count=5" in dsl

    def test_approximate_includes_density(self):
        intent = DrawingIntent(
            elements=[
                IntentElement(
                    name="core", type=IntentElementType.CIRCLE,
                    position=IntentPosition.CENTER,
                ),
                IntentElement(
                    name="bits", type=IntentElementType.DOT,
                    count=10, count_mode=IntentCountMode.APPROXIMATE,
                    relation_to="core",
                    arrangement=IntentArrangement.SCATTERED_AROUND,
                ),
            ]
        )
        dsl = intent_to_dsl(intent)
        assert "density=normal" in dsl

    def test_exact_count_no_density(self):
        intent = DrawingIntent(
            elements=[
                IntentElement(
                    name="core", type=IntentElementType.CIRCLE,
                    position=IntentPosition.CENTER,
                ),
                IntentElement(
                    name="bits", type=IntentElementType.DOT,
                    count=3, count_mode=IntentCountMode.EXACT,
                    relation_to="core",
                    arrangement=IntentArrangement.SCATTERED_AROUND,
                ),
            ]
        )
        dsl = intent_to_dsl(intent)
        assert "count=3" in dsl
        assert "density=" not in dsl

    def test_composition_because(self):
        intent = DrawingIntent(
            elements=[
                IntentElement(
                    name="core", type=IntentElementType.CIRCLE,
                    position=IntentPosition.CENTER,
                ),
                IntentElement(
                    name="bits", type=IntentElementType.DOT,
                    count=6, relation_to="core",
                    arrangement=IntentArrangement.SCATTERED_AROUND,
                    reason="orbiting",
                ),
            ]
        )
        dsl = intent_to_dsl(intent)
        assert "because orbiting" in dsl


# ── 5. Reason Sanitization ───────────────────────────────────────────


class TestReasonSanitization:
    def test_spaces_to_underscores(self):
        intent = _minimal_intent(
            elements=[
                IntentElement(
                    name="a", type=IntentElementType.CIRCLE,
                    position=IntentPosition.CENTER,
                    reason="warm presence here",
                ),
            ]
        )
        dsl = intent_to_dsl(intent)
        assert "because warm_presence_here" in dsl

    def test_special_chars_stripped(self):
        intent = _minimal_intent(
            elements=[
                IntentElement(
                    name="a", type=IntentElementType.CIRCLE,
                    position=IntentPosition.CENTER,
                    reason="anchor!! (main)",
                ),
            ]
        )
        dsl = intent_to_dsl(intent)
        assert "because anchor_main" in dsl


# ── 6. End-to-End: Intent → DSL → Parse → SVG ───────────────────────


class TestEndToEnd:
    def test_full_intent_to_svg(self):
        """The design doc example should produce valid DSL → SVG."""
        from backend.core.drawing.parser import parse_drawing
        from backend.core.drawing.scene_graph import build_scene_graph
        from backend.core.drawing.renderer import render_svg

        intent = _full_intent()
        dsl = intent_to_dsl(intent)

        ast = parse_drawing(dsl)
        assert len(ast.declarations) >= 2  # sky, core, ground (fragments → scatter)

        scene = build_scene_graph(ast)
        assert len(scene.nodes) > 0

        svg = render_svg(scene)
        assert "<svg" in svg

    def test_minimal_intent_to_svg(self):
        from backend.core.drawing.parser import parse_drawing
        from backend.core.drawing.scene_graph import build_scene_graph
        from backend.core.drawing.renderer import render_svg

        dsl = intent_to_dsl(_minimal_intent())
        ast = parse_drawing(dsl)
        scene = build_scene_graph(ast)
        svg = render_svg(scene)
        assert "<svg" in svg

    def test_yaml_string_roundtrip(self):
        """Simulate LLM output: YAML string → parse → DrawingIntent → DSL."""
        yaml_str = """
overall_mood: quiet_warmth
elements:
  - name: sky
    type: area
    role: background
    size: vast
    color_feel: quiet
    opacity_feel: faint
    position: field
  - name: core
    type: circle
    size: small
    position: center
    color_feel: warm
    dominance: primary
"""
        raw = yaml.safe_load(yaml_str)
        intent = DrawingIntent.model_validate(raw)
        dsl = intent_to_dsl(intent)
        assert "sky: area(size=vast)" in dsl
        assert "core: circle(size=small)" in dsl
        assert "sky at field" in dsl
        assert "core at center" in dsl

    def test_nested_intent_key(self):
        """Support both {elements: ...} and {intent: {elements: ...}}."""
        yaml_str = """
intent:
  overall_mood: calm
  elements:
    - name: dot1
      type: dot
      position: center
"""
        raw = yaml.safe_load(yaml_str)
        if "intent" in raw and isinstance(raw["intent"], dict):
            raw = raw["intent"]
        intent = DrawingIntent.model_validate(raw)
        dsl = intent_to_dsl(intent)
        assert "dot1: dot" in dsl
