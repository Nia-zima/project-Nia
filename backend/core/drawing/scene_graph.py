"""Nia Drawing Language — Scene Graph.

Resolves relational declarations into positioned elements.
The scene graph is the intermediate representation between DSL and renderer.
It records resolved positions + the original because annotations for tracing.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Optional

from backend.core.drawing.schema import (
    CompositionStmt,
    DensityLevel,
    DrawingAST,
    DriftLevel,
    ElementDecl,
    ElementType,
    ModifierStmt,
    OpacityLevel,
    PaletteColor,
    PlacementStmt,
    Relation,
    SizeLevel,
    SpatialRef,
)


# ── Canvas Configuration ──────────────────────────────────────────────


@dataclass
class CanvasConfig:
    """Canvas size and grid resolution."""
    width: float = 400.0
    height: float = 400.0
    grid_size: int = 10  # conceptual grid (Nia doesn't see this)


# ── Resolved Scene Node ───────────────────────────────────────────────


@dataclass
class SceneNode:
    """A resolved element with absolute position and visual properties."""
    name: str
    element_type: ElementType
    x: float = 0.0
    y: float = 0.0
    width: float = 20.0
    height: float = 20.0
    color: str = "#B8B2A8"  # neutral_2 default
    opacity: float = 1.0
    stroke_width: float = 1.5
    softness: float = 0.0  # blur radius
    layer: int = 0
    because_tags: list[str] = field(default_factory=list)
    because_text: str = ""
    is_generated: bool = False  # True for repeat/scatter generated nodes
    seed: Optional[int] = None


@dataclass
class SceneGraph:
    """Complete scene: positioned nodes + metadata."""
    nodes: list[SceneNode] = field(default_factory=list)
    canvas: CanvasConfig = field(default_factory=CanvasConfig)
    resolved_layout: dict[str, tuple[float, float]] = field(default_factory=dict)


# ── Size Mapping ──────────────────────────────────────────────────────


_SIZE_MAP: dict[SizeLevel, float] = {
    SizeLevel.TINY: 8.0,
    SizeLevel.SMALL: 16.0,
    SizeLevel.MEDIUM: 30.0,
    SizeLevel.LARGE: 60.0,
    SizeLevel.VAST: 120.0,
}

_OPACITY_MAP = {"faint": 0.15, "soft": 0.45, "solid": 1.0}
_WEIGHT_MAP = {"thin": 0.5, "normal": 1.5, "bold": 3.0, "heavy": 5.0}
_SOFTNESS_MAP = {"sharp": 0.0, "normal": 1.0, "soft": 3.0, "blur": 8.0}

_PALETTE_RGB: dict[str, str] = {
    "warm_1": "#F5D6C0", "warm_2": "#E8A87C", "warm_3": "#D4776B", "warm_4": "#8B4049",
    "cool_1": "#C8DDE6", "cool_2": "#7EB0C9", "cool_3": "#4A7FA5", "cool_4": "#2C4A6E",
    "neutral_1": "#F0EDE8", "neutral_2": "#B8B2A8", "neutral_3": "#6E6860", "neutral_4": "#3A3632",
}


# ── Spatial Reference Resolution ──────────────────────────────────────


def _resolve_spatial_ref(ref: str, canvas: CanvasConfig) -> tuple[float, float]:
    """Resolve a spatial reference to (x, y)."""
    cx, cy = canvas.width / 2, canvas.height / 2
    refs = {
        "center": (cx, cy),
        "upper": (cx, canvas.height * 0.2),
        "lower": (cx, canvas.height * 0.8),
        "left_edge": (canvas.width * 0.1, cy),
        "right_edge": (canvas.width * 0.9, cy),
        "upper_left": (canvas.width * 0.15, canvas.height * 0.15),
        "upper_right": (canvas.width * 0.85, canvas.height * 0.15),
        "lower_left": (canvas.width * 0.15, canvas.height * 0.85),
        "lower_right": (canvas.width * 0.85, canvas.height * 0.85),
        "corner": (canvas.width * 0.1, canvas.height * 0.1),
        "margin": (canvas.width * 0.05, canvas.height * 0.05),
        "field": (cx, cy),  # field = whole canvas, centered
    }
    return refs.get(ref, (cx, cy))


# ── Relation Resolution ──────────────────────────────────────────────


_DISTANCE_MAP = {"touching": 15.0, "near": 40.0, "moderate": 80.0, "far": 140.0}


def _resolve_relation(
    relation: Relation,
    target_pos: tuple[float, float],
    distance: Optional[str],
    canvas: CanvasConfig,
) -> tuple[float, float]:
    """Resolve a relation to an offset from target position."""
    tx, ty = target_pos
    dist = _DISTANCE_MAP.get(distance or "near", 40.0)

    offsets: dict[Relation, tuple[float, float]] = {
        Relation.AT: (0, 0),
        Relation.NEAR: (dist * 0.3, dist * 0.3),
        Relation.FAR: (dist, dist),
        Relation.ABOVE: (0, -dist),
        Relation.BELOW: (0, dist),
        Relation.LEFT_OF: (-dist, 0),
        Relation.RIGHT_OF: (dist, 0),
        Relation.OVERLAP: (dist * 0.1, dist * 0.1),
        Relation.INSIDE: (0, 0),
        Relation.TOUCHING: (dist * 0.5, 0),
        Relation.BETWEEN: (0, 0),  # needs special handling
        Relation.ALIGN: (0, 0),
        Relation.AROUND: (dist * 0.6, 0),
        Relation.SURROUND: (dist * 0.5, 0),
    }
    dx, dy = offsets.get(relation, (0, 0))
    x = max(10, min(canvas.width - 10, tx + dx))
    y = max(10, min(canvas.height - 10, ty + dy))
    return (x, y)


# ── Build Scene Graph ─────────────────────────────────────────────────


def build_scene_graph(ast: DrawingAST, canvas: Optional[CanvasConfig] = None) -> SceneGraph:
    """Build a scene graph from a DrawingAST.

    Resolves all relations to absolute positions.
    """
    if canvas is None:
        canvas = CanvasConfig()

    scene = SceneGraph(canvas=canvas)
    positions: dict[str, tuple[float, float]] = {}
    elements: dict[str, ElementDecl] = {}

    # Phase 1: Register elements
    for decl in ast.declarations:
        elements[decl.name] = decl

    # Phase 2: Validate and resolve placements
    _spatial_ref_values = {r.value for r in SpatialRef}
    for stmt in ast.placements:
        # Strict validation: subject must be declared
        if stmt.subject not in elements:
            raise ValueError(f"Undeclared element '{stmt.subject}' in placement")

        target_pos: tuple[float, float]
        if stmt.target in positions:
            target_pos = positions[stmt.target]
        elif stmt.target in _spatial_ref_values:
            target_pos = _resolve_spatial_ref(stmt.target, canvas)
        else:
            raise ValueError(f"Unknown target '{stmt.target}' in placement of '{stmt.subject}'. Must be a declared element or spatial reference ({', '.join(sorted(_spatial_ref_values))})")

        pos = _resolve_relation(stmt.relation, target_pos, stmt.distance, canvas)
        positions[stmt.subject] = pos

    # Phase 3: Build nodes with modifiers
    modifiers: dict[str, dict[str, str]] = {}
    modifier_because: dict[str, list[str]] = {}
    for mod in ast.modifiers:
        modifiers.setdefault(mod.subject, {})[mod.attribute] = mod.value
        if mod.because:
            modifier_because.setdefault(mod.subject, []).extend(mod.because.tags)

    for name, decl in elements.items():
        pos = positions.get(name, (canvas.width / 2, canvas.height / 2))
        mods = modifiers.get(name, {})
        size = _SIZE_MAP.get(SizeLevel(mods.get("size", decl.size.value)), 30.0)

        # Collect because tags + free_text from placement and modifiers
        tags = []
        free_texts = []
        for stmt in ast.placements:
            if stmt.subject == name and stmt.because:
                tags.extend(stmt.because.tags)
                if stmt.because.free_text:
                    free_texts.append(stmt.because.free_text)
        tags.extend(modifier_because.get(name, []))
        for mod in ast.modifiers:
            if mod.subject == name and mod.because and mod.because.free_text:
                free_texts.append(mod.because.free_text)

        # Determine layer from because tags (background=0, default=1, emphasis=2)
        layer = 1
        if "background" in tags:
            layer = 0
        elif "emphasis" in tags or "presence" in tags:
            layer = 2

        node = SceneNode(
            name=name,
            element_type=decl.element_type,
            x=pos[0],
            y=pos[1],
            width=size if decl.element_type != ElementType.LINE else size * 3,
            height=size if decl.element_type != ElementType.LINE else _WEIGHT_MAP.get(decl.weight.value, 1.5),
            color=_PALETTE_RGB.get(mods.get("color", "neutral_2"), "#B8B2A8"),
            opacity=_OPACITY_MAP.get(mods.get("opacity", "solid"), 1.0),
            stroke_width=_WEIGHT_MAP.get(mods.get("weight", decl.weight.value), 1.5),
            softness=_SOFTNESS_MAP.get(mods.get("softness", "normal"), 1.0),
            layer=layer,
            because_tags=tags,
            because_text=" | ".join(free_texts) if free_texts else "",
        )
        scene.nodes.append(node)

    # Phase 4: Resolve compositions (repeat/scatter)
    for comp in ast.compositions:
        target_pos = positions.get(comp.target or "", (canvas.width / 2, canvas.height / 2))
        rng = random.Random(comp.seed) if comp.seed is not None else random.Random()

        # Get target element size for INSIDE relation
        target_elem = elements.get(comp.target or "")
        target_size = _SIZE_MAP.get(target_elem.size if target_elem else SizeLevel.MEDIUM, 30.0)

        base_dist = _DISTANCE_MAP.get(comp.spacing, 40.0)
        density_mult = {"sparse": 1.8, "loose": 1.4, "normal": 1.0, "dense": 0.6, "packed": 0.3}
        drift_range = {"none": 0, "slight": 5, "moderate": 15, "strong": 30}

        from backend.core.drawing.schema import Relation as _Rel

        for i in range(comp.count):
            angle = (2 * math.pi * i) / comp.count
            drift_r = drift_range.get(comp.drift.value, 0)

            if comp.relation == _Rel.INSIDE:
                # scatter IN: distribute inside the target element's bounds
                max_r = target_size * 0.4 * density_mult.get(comp.density.value, 1.0)
                r = rng.uniform(0, max_r)
                a = rng.uniform(0, 2 * math.pi)
                dx = r * math.cos(a) + rng.uniform(-drift_r, drift_r)
                dy = r * math.sin(a) + rng.uniform(-drift_r, drift_r)
            elif comp.relation == _Rel.AROUND or comp.relation is None:
                # repeat/scatter AROUND: distribute in a ring around target
                dist = base_dist * density_mult.get(comp.density.value, 1.0)
                dx = dist * math.cos(angle) + rng.uniform(-drift_r, drift_r)
                dy = dist * math.sin(angle) + rng.uniform(-drift_r, drift_r)
            else:
                # Other relations: offset in the relation direction
                dist = base_dist * density_mult.get(comp.density.value, 1.0)
                dx = dist * math.cos(angle) + rng.uniform(-drift_r, drift_r)
                dy = dist * math.sin(angle) + rng.uniform(-drift_r, drift_r)

            x = max(10, min(canvas.width - 10, target_pos[0] + dx))
            y = max(10, min(canvas.height - 10, target_pos[1] + dy))

            size = _SIZE_MAP.get(SizeLevel.TINY, 8.0)
            tags = comp.because.tags if comp.because else []

            node = SceneNode(
                name=f"_gen_{comp.op.value}_{i}",
                element_type=comp.element_type,
                x=x, y=y,
                width=size, height=size,
                color=_PALETTE_RGB.get("neutral_2", "#B8B2A8"),
                opacity=0.45,
                is_generated=True,
                seed=comp.seed,
                because_tags=tags,
            )
            scene.nodes.append(node)

    # Store resolved layout
    scene.resolved_layout = {name: pos for name, pos in positions.items()}

    return scene
