"""Nia Drawing Language — AST and data models.

Design: docs/nia_drawing_language.md
4 vocabulary types: elements, relations, modifiers, spatial references.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── Elements ──────────────────────────────────────────────────────────


class ElementType(str, Enum):
    DOT = "dot"
    LINE = "line"
    CIRCLE = "circle"
    RECT = "rect"
    AREA = "area"


# ── Relations ─────────────────────────────────────────────────────────


class Relation(str, Enum):
    AT = "at"
    NEAR = "near"
    FAR = "far"
    OVERLAP = "overlap"
    INSIDE = "inside"
    TOUCHING = "touching"
    BETWEEN = "between"
    LEFT_OF = "left_of"
    RIGHT_OF = "right_of"
    ABOVE = "above"
    BELOW = "below"
    ALIGN = "align"
    AROUND = "around"
    SURROUND = "surround"


class CompositionOp(str, Enum):
    REPEAT = "repeat"
    SCATTER = "scatter"


# ── Spatial References ────────────────────────────────────────────────


class SpatialRef(str, Enum):
    CENTER = "center"
    UPPER = "upper"
    LOWER = "lower"
    LEFT_EDGE = "left_edge"
    RIGHT_EDGE = "right_edge"
    UPPER_LEFT = "upper_left"
    UPPER_RIGHT = "upper_right"
    LOWER_LEFT = "lower_left"
    LOWER_RIGHT = "lower_right"
    CORNER = "corner"
    MARGIN = "margin"
    FIELD = "field"


# ── Modifiers ─────────────────────────────────────────────────────────


class OpacityLevel(str, Enum):
    FAINT = "faint"
    SOFT = "soft"
    SOLID = "solid"


class SizeLevel(str, Enum):
    TINY = "tiny"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    VAST = "vast"


class WeightLevel(str, Enum):
    THIN = "thin"
    NORMAL = "normal"
    BOLD = "bold"
    HEAVY = "heavy"


class SoftnessLevel(str, Enum):
    SHARP = "sharp"
    NORMAL = "normal"
    SOFT = "soft"
    BLUR = "blur"


class DensityLevel(str, Enum):
    SPARSE = "sparse"
    LOOSE = "loose"
    NORMAL = "normal"
    DENSE = "dense"
    PACKED = "packed"


class DriftLevel(str, Enum):
    NONE = "none"
    SLIGHT = "slight"
    MODERATE = "moderate"
    STRONG = "strong"


# ── Color Palette (12 colors) ────────────────────────────────────────


class PaletteColor(str, Enum):
    WARM_1 = "warm_1"
    WARM_2 = "warm_2"
    WARM_3 = "warm_3"
    WARM_4 = "warm_4"
    COOL_1 = "cool_1"
    COOL_2 = "cool_2"
    COOL_3 = "cool_3"
    COOL_4 = "cool_4"
    NEUTRAL_1 = "neutral_1"
    NEUTRAL_2 = "neutral_2"
    NEUTRAL_3 = "neutral_3"
    NEUTRAL_4 = "neutral_4"


# Color → RGB mapping (initial palette, Nia doesn't see these values)
PALETTE_RGB: dict[PaletteColor, str] = {
    PaletteColor.WARM_1: "#F5D6C0",
    PaletteColor.WARM_2: "#E8A87C",
    PaletteColor.WARM_3: "#D4776B",
    PaletteColor.WARM_4: "#8B4049",
    PaletteColor.COOL_1: "#C8DDE6",
    PaletteColor.COOL_2: "#7EB0C9",
    PaletteColor.COOL_3: "#4A7FA5",
    PaletteColor.COOL_4: "#2C4A6E",
    PaletteColor.NEUTRAL_1: "#F0EDE8",
    PaletteColor.NEUTRAL_2: "#B8B2A8",
    PaletteColor.NEUTRAL_3: "#6E6860",
    PaletteColor.NEUTRAL_4: "#3A3632",
}


# ── Vocabulary Constants (single source of truth for parser + prompt) ─


# ── Element modifiers: applied to individual elements via scene_graph ──

ELEMENT_MODIFIER_ATTRIBUTES: frozenset[str] = frozenset({
    "color", "opacity", "size", "weight", "softness",
})
"""Modifier attributes that affect individual elements (scene_graph resolves these)."""

ELEMENT_MODIFIER_LEVELS: dict[str, type[Enum]] = {
    "opacity": OpacityLevel,
    "size": SizeLevel,
    "weight": WeightLevel,
    "softness": SoftnessLevel,
}
"""Element modifier attribute → level enum mapping (color uses PaletteColor, not levels)."""

# ── Composition kwargs: used only inside repeat/scatter statements ────

COMPOSITION_KWARGS: frozenset[str] = frozenset({
    "density", "drift", "count", "spacing", "seed",
})
"""Keyword arguments accepted inside composition statements."""

COMPOSITION_KWARG_LEVELS: dict[str, type[Enum]] = {
    "density": DensityLevel,
    "drift": DriftLevel,
}
"""Composition kwarg → level enum mapping."""

# ── Union: all modifier-like attributes the parser accepts ────────────

MODIFIER_ATTRIBUTES: frozenset[str] = ELEMENT_MODIFIER_ATTRIBUTES | frozenset({
    "density", "drift", "ratio",
})
"""Modifier-like vocabulary superset used by the parser for line routing.

The parser routes lines with these attributes to _parse_modifier(), but
density/drift are rejected as composition-only and ratio as declaration-only.
Only ELEMENT_MODIFIER_ATTRIBUTES actually produce ModifierStmt.
prompt_ref uses the narrower ELEMENT_MODIFIER_ATTRIBUTES for LLM context.
"""

MODIFIER_LEVELS: dict[str, type[Enum]] = {
    **ELEMENT_MODIFIER_LEVELS,
    "density": DensityLevel,
    "drift": DriftLevel,
}
"""Modifier attribute → level enum mapping. density/drift are included for
composition kwarg validation; they are rejected as element modifiers by the parser."""

COMPOSITION_PREPOSITIONS: dict[str, Relation] = {
    "in": Relation.INSIDE,
    "around": Relation.AROUND,
}
"""Preposition sugar accepted in composition statements."""


# ── AST Nodes ─────────────────────────────────────────────────────────


class BecauseAnnotation(BaseModel):
    """Reason annotation: tag(s) + optional free text."""
    tags: list[str] = Field(default_factory=list)
    free_text: str = ""


class ElementDecl(BaseModel):
    """Element declaration: `a: circle(size=small)`"""
    name: str
    element_type: ElementType
    size: SizeLevel = SizeLevel.MEDIUM
    weight: WeightLevel = WeightLevel.NORMAL
    ratio: str = "balanced"


class PlacementStmt(BaseModel):
    """Placement: `a at center because anchor`"""
    subject: str
    relation: Relation
    target: str  # element name or spatial ref
    distance: Optional[str] = None  # near/far qualifier
    because: Optional[BecauseAnnotation] = None


class ModifierStmt(BaseModel):
    """Modifier: `a color warm_3 because presence`"""
    subject: str
    attribute: str  # color, opacity, size, softness, density, drift
    value: str
    because: Optional[BecauseAnnotation] = None


class CompositionStmt(BaseModel):
    """Composition: `repeat dot around a count=4 density=sparse`"""
    op: CompositionOp
    element_type: ElementType
    relation: Optional[Relation] = None
    target: Optional[str] = None
    count: int = 4
    density: DensityLevel = DensityLevel.NORMAL
    drift: DriftLevel = DriftLevel.NONE
    spacing: str = "normal"
    because: Optional[BecauseAnnotation] = None
    seed: Optional[int] = None  # for reproducibility


class DrawingAST(BaseModel):
    """Complete drawing program."""
    declarations: list[ElementDecl] = Field(default_factory=list)
    placements: list[PlacementStmt] = Field(default_factory=list)
    modifiers: list[ModifierStmt] = Field(default_factory=list)
    compositions: list[CompositionStmt] = Field(default_factory=list)
