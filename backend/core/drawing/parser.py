"""Nia Drawing Language — DSL parser.

Parses Nia's drawing code into a DrawingAST.
Each line is one of: declaration, placement, modifier, composition, or comment.
"""
from __future__ import annotations

import re
from typing import Optional

from backend.core.drawing.schema import (
    BecauseAnnotation,
    COMPOSITION_PREPOSITIONS,
    CompositionOp,
    CompositionStmt,
    DensityLevel,
    DrawingAST,
    DriftLevel,
    ELEMENT_MODIFIER_ATTRIBUTES,
    ElementDecl,
    ElementType,
    MODIFIER_ATTRIBUTES,
    ModifierStmt,
    OpacityLevel,
    PlacementStmt,
    Relation,
    SizeLevel,
    SpatialRef,
    WeightLevel,
)


_ELEMENT_TYPES = {e.value for e in ElementType}
_RELATIONS = {r.value for r in Relation}
_SPATIAL_REFS = {r.value for r in SpatialRef}
_COMPOSITION_OPS = {o.value for o in CompositionOp}
_MODIFIER_ATTRS = MODIFIER_ATTRIBUTES
_COMPOSITION_PREPOSITIONS = COMPOSITION_PREPOSITIONS
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def parse_drawing(code: str) -> DrawingAST:
    """Parse Nia drawing code into AST."""
    ast = DrawingAST()
    for line_num, raw_line in enumerate(code.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        # Remove inline comment (-- style)
        free_text = ""
        if " -- " in line:
            line, free_text = line.rsplit(" -- ", 1)
            line = line.strip()
            free_text = free_text.strip()

        try:
            _parse_line(ast, line, free_text)
        except Exception as e:
            raise ValueError(f"Line {line_num}: {e}\n  {raw_line}") from e

    return ast


def _parse_line(ast: DrawingAST, line: str, free_text: str) -> None:
    """Parse a single line into the appropriate AST node."""
    tokens = line.split()

    # Declaration: `name: type(args)`
    if len(tokens) >= 2 and tokens[0].endswith(":"):
        _parse_declaration(ast, tokens, free_text)
        return

    # Composition: `repeat/scatter type ...`
    if tokens[0] in _COMPOSITION_OPS:
        _parse_composition(ast, tokens, free_text)
        return

    # Check if second token is a relation → placement
    if len(tokens) >= 3 and tokens[1] in _RELATIONS:
        _parse_placement(ast, tokens, free_text)
        return

    # Check if second token is a modifier attribute → modifier
    if len(tokens) >= 3 and tokens[1] in _MODIFIER_ATTRS:
        _parse_modifier(ast, tokens, free_text)
        return

    raise ValueError(f"Cannot parse: {line}")


def _validate_name(name: str) -> None:
    """Reject element names that could cause injection in SVG attributes."""
    if not _SAFE_NAME_RE.match(name):
        raise ValueError(
            f"Invalid element name '{name}': must match [A-Za-z0-9_-]+"
        )


def _parse_declaration(ast: DrawingAST, tokens: list[str], free_text: str) -> None:
    """Parse: `name: type(key=val, ...)` or `name: type`"""
    name = tokens[0].rstrip(":")
    _validate_name(name)
    type_str = tokens[1]

    # Extract type and args: circle(size=small) → type=circle, args={size: small}
    args: dict[str, str] = {}
    match = re.match(r"(\w+)\(([^)]*)\)", type_str)
    if match:
        type_name = match.group(1)
        for arg in match.group(2).split(","):
            arg = arg.strip()
            if "=" in arg:
                k, v = arg.split("=", 1)
                args[k.strip()] = v.strip()
    else:
        type_name = type_str

    if type_name not in _ELEMENT_TYPES:
        raise ValueError(f"Unknown element type: {type_name}")

    decl = ElementDecl(
        name=name,
        element_type=ElementType(type_name),
        size=SizeLevel(args.get("size", "medium")),
        weight=WeightLevel(args.get("weight", "normal")),
        ratio=args.get("ratio", "balanced"),
    )
    ast.declarations.append(decl)


def _parse_placement(ast: DrawingAST, tokens: list[str], free_text: str) -> None:
    """Parse: `subject relation target [distance] [because tag+...]`"""
    subject = tokens[0]
    relation = Relation(tokens[1])
    target = tokens[2]

    # Look for optional distance qualifier and because
    distance = None
    because = None
    i = 3
    while i < len(tokens):
        if tokens[i] == "because":
            because = _parse_because(tokens[i + 1:], free_text)
            break
        elif tokens[i] in ("near", "far", "touching"):
            distance = tokens[i]
        i += 1

    if because is None and free_text:
        because = BecauseAnnotation(free_text=free_text)

    ast.placements.append(PlacementStmt(
        subject=subject, relation=relation, target=target,
        distance=distance, because=because,
    ))


_COMPOSITION_ONLY_ATTRS = frozenset({"density", "drift"})
_DECLARATION_ONLY_ATTRS = frozenset({"ratio"})


def _parse_modifier(ast: DrawingAST, tokens: list[str], free_text: str) -> None:
    """Parse: `subject attr value [because tag+...]`"""
    subject = tokens[0]
    attribute = tokens[1]
    value = tokens[2]

    if attribute in _COMPOSITION_ONLY_ATTRS:
        raise ValueError(
            f"'{attribute}' is a composition-only keyword (use inside repeat/scatter). "
            f"Cannot be used as element modifier: '{subject} {attribute} {value}'"
        )
    if attribute in _DECLARATION_ONLY_ATTRS:
        raise ValueError(
            f"'{attribute}' is a declaration-only parameter (use in element declaration). "
            f"Cannot be used as element modifier: '{subject} {attribute} {value}'"
        )

    because = None
    if len(tokens) > 3 and tokens[3] == "because":
        because = _parse_because(tokens[4:], free_text)
    elif free_text:
        because = BecauseAnnotation(free_text=free_text)

    ast.modifiers.append(ModifierStmt(
        subject=subject, attribute=attribute, value=value, because=because,
    ))


def _parse_composition(ast: DrawingAST, tokens: list[str], free_text: str) -> None:
    """Parse: `repeat/scatter type [relation target] [key=val ...] [because tag+...]`"""
    op = CompositionOp(tokens[0])
    elem_type = ElementType(tokens[1])

    relation = None
    target = None
    kwargs: dict[str, str] = {}
    because = None
    seed = None

    i = 2
    while i < len(tokens):
        tok = tokens[i]
        if tok == "because":
            because = _parse_because(tokens[i + 1:], free_text)
            break
        elif tok in _COMPOSITION_PREPOSITIONS:
            # Handle 'in' and 'around' as prepositions
            relation = _COMPOSITION_PREPOSITIONS[tok]
            if i + 1 < len(tokens) and "=" not in tokens[i + 1] and tokens[i + 1] != "because":
                target = tokens[i + 1]
                i += 1
        elif tok in _RELATIONS:
            relation = Relation(tok)
            if i + 1 < len(tokens) and tokens[i + 1] not in _RELATIONS and "=" not in tokens[i + 1] and tokens[i + 1] != "because":
                target = tokens[i + 1]
                i += 1
        elif "=" in tok:
            k, v = tok.split("=", 1)
            kwargs[k] = v
        i += 1

    if because is None and free_text:
        because = BecauseAnnotation(free_text=free_text)

    if "seed" in kwargs:
        seed = int(kwargs.pop("seed"))

    ast.compositions.append(CompositionStmt(
        op=op,
        element_type=elem_type,
        relation=relation,
        target=target,
        count=int(kwargs.get("count", "4")),
        density=DensityLevel(kwargs.get("density", "normal")),
        drift=DriftLevel(kwargs.get("drift", "none")),
        spacing=kwargs.get("spacing", "normal"),
        because=because,
        seed=seed,
    ))


def _parse_because(tokens: list[str], free_text: str) -> BecauseAnnotation:
    """Parse because annotation: `tag1 + tag2` or just tags."""
    raw = " ".join(tokens)
    # Split on '+' for multi-tag
    parts = [p.strip() for p in raw.split("+")]
    tags = [p for p in parts if p and not p.startswith("--")]
    # Validate tags for safe SVG attribute use
    for tag in tags:
        if not _SAFE_NAME_RE.match(tag):
            raise ValueError(
                f"Invalid because tag '{tag}': must match [A-Za-z0-9_-]+"
            )
    return BecauseAnnotation(tags=tags, free_text=free_text)
