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
    ELEMENT_MODIFIER_LEVELS,
    ElementDecl,
    ElementType,
    MODIFIER_ATTRIBUTES,
    ModifierStmt,
    OpacityLevel,
    PaletteColor,
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


def _normalize_dsl(code: str) -> str:
    """Pre-process DSL: split single-line DSL into proper lines.

    LLMs sometimes output the entire DSL on one line without newlines.
    Strategy: use findall to extract declaration statements (name: type(...))
    and composition statements (repeat/scatter ...), then return each as a line.
    Placement and modifier statements glued after declarations are kept on the
    same line as the declaration — the parser will error on them, which is correct
    (they should be separate lines).
    """
    if "\n" in code.strip():
        return code  # Already multi-line, don't touch

    _ELEMENT_KW = "|".join(e.value for e in ElementType)

    # Step 1: Insert \n before "name: element_type" patterns.
    # Use a regex that requires the name to be preceded by ) or a known
    # because-tag word boundary (not a partial word).
    result = re.sub(
        rf"(?<=[)\s])(?=[A-Za-z_][A-Za-z0-9_-]*:\s*(?:{_ELEMENT_KW}))",
        "\n",
        code.strip(),
    )

    # Step 2: Insert \n before composition keywords.
    result = re.sub(
        r"(?<=[)\s])(?=(?:repeat|scatter)\s)",
        "\n",
        result,
    )

    if "\n" in result:
        return result

    return code  # Single statement or couldn't split


def parse_drawing(code: str) -> DrawingAST:
    """Parse Nia drawing code into AST."""
    code = _normalize_dsl(code)
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
            line = _canonicalize_line(line)
            _parse_line(ast, line, free_text)
        except Exception as e:
            raise ValueError(f"Line {line_num}: {e}\n  {raw_line}") from e

    return ast


# ── Bounded Canonicalizer ─────────────────────────────────────────────
# Only fixes well-defined patterns. Everything else is left for the strict parser.

_TWO_WORD_SPATIAL = {
    "upper right": "upper_right",
    "upper left": "upper_left",
    "lower right": "lower_right",
    "lower left": "lower_left",
    "upper-right": "upper_right",
    "upper-left": "upper_left",
    "lower-right": "lower_right",
    "lower-left": "lower_left",
}

_LINE_FROM_TO_RE = re.compile(r"\bline\s+from\b", re.IGNORECASE)


# Strictly bounded: only "name: dot" with composition kwargs.
# Not generalized to circle/area/line — those need more observation first.
_DECL_DOT_COMPOSITION_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_-]*:\s*"
    r"(dot)\s+"
    r"((?:count|density|drift|spacing)=.*)"
    r"$"
)


def _canonicalize_line(line: str) -> str:
    """Apply bounded repairs to a single DSL line.

    Repairs:
    - 2-word spatial refs: "upper right" -> "upper_right"
    - Declaration-as-scatter: "name: dot count=50 around X" -> "scatter dot count=50 around X"
      Only when composition kwargs (count=, density=, drift=, spacing=) follow the element type.
    Errors:
    - "line from/to" syntax (unsupported)
    """
    # Reject unsupported "line from/to" syntax with a clear error
    if _LINE_FROM_TO_RE.search(line):
        raise ValueError(
            "'line from ... to ...' is not supported. "
            "Use 'name: line(weight=thin)' + placement instead."
        )

    # Repair 2-word spatial references
    for two_word, canonical in _TWO_WORD_SPATIAL.items():
        if two_word in line:
            line = line.replace(two_word, canonical)

    # Repair declaration-as-scatter: "name: dot count=50 around X because Y"
    # Condition: declaration form + composition kwargs immediately after element type.
    # Strictly bounded: only triggers when count=/density=/drift=/spacing= follows.
    m = _DECL_DOT_COMPOSITION_RE.match(line)
    if m:
        elem_type = m.group(1)
        rest = m.group(2)
        line = f"scatter {elem_type} {rest}"

    return line


def _parse_line(ast: DrawingAST, line: str, free_text: str) -> None:
    """Parse a single line into the appropriate AST node."""
    tokens = line.split()

    # Declaration: `name: type(args)` — re-tokenize preserving parens content
    if len(tokens) >= 2 and tokens[0].endswith(":"):
        # Rejoin and re-split to handle spaces inside parentheses
        # e.g. "sky: area(color=cool_1, opacity=faint) at field because background"
        decl_match = re.match(r"(\S+)\s+(\w+\([^)]*\)|\w+)(.*)", line)
        if decl_match:
            name_token = decl_match.group(1)
            type_token = decl_match.group(2)
            rest = decl_match.group(3).strip()
            decl_tokens = [name_token, type_token]
            # Parse rest as placement/modifier if present
            _parse_declaration(ast, decl_tokens, free_text)
            # If there's trailing text (e.g. "at field because background"),
            # parse it as a separate placement statement
            if rest:
                rest_tokens = rest.split()
                name_bare = name_token.rstrip(":")
                if rest_tokens and rest_tokens[0] in _RELATIONS:
                    _parse_placement(ast, [name_bare] + rest_tokens, free_text)
                elif len(rest_tokens) >= 2 and rest_tokens[0] in _MODIFIER_ATTRS:
                    _parse_modifier(ast, [name_bare] + rest_tokens, free_text)
                else:
                    raise ValueError(
                        f"Unexpected trailing text after declaration: '{rest}'. "
                        f"Each statement (declaration, placement, modifier) must be on its own line."
                    )
            return
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


_PALETTE_VALUES = {c.value for c in PaletteColor}


def _validate_modifier_value(attr: str, value: str) -> None:
    """Validate a modifier value against known enums.

    Prevents silent fallback to defaults in scene_graph.
    """
    if attr == "color":
        if value not in _PALETTE_VALUES:
            raise ValueError(
                f"Unknown color '{value}'. Valid: {', '.join(sorted(_PALETTE_VALUES))}"
            )
    elif attr in ELEMENT_MODIFIER_LEVELS:
        valid = {lv.value for lv in ELEMENT_MODIFIER_LEVELS[attr]}
        if value not in valid:
            raise ValueError(
                f"Unknown {attr} level '{value}'. Valid: {', '.join(sorted(valid))}"
            )


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

    # Auto-promote modifier-like args (color, opacity, softness) to ModifierStmt.
    # LLMs often write area(color=cool_1, opacity=faint) instead of separate lines.
    # Validate values to prevent silent fallback in scene_graph.
    for attr in ELEMENT_MODIFIER_ATTRIBUTES:
        if attr in args and attr not in ("size", "weight"):
            value = args[attr]
            _validate_modifier_value(attr, value)
            ast.modifiers.append(ModifierStmt(
                subject=name,
                attribute=attr,
                value=value,
            ))


def _parse_placement(ast: DrawingAST, tokens: list[str], free_text: str) -> None:
    """Parse: `subject relation target [distance] [because tag+...]`"""
    subject = tokens[0]
    relation = Relation(tokens[1])
    target = tokens[2]

    # Look for optional distance qualifier and because
    _DISTANCE_WORDS = {"near", "far", "touching"}
    distance = None
    because = None
    i = 3
    while i < len(tokens):
        if tokens[i] == "because":
            because = _parse_because(tokens[i + 1:], free_text)
            break
        elif tokens[i] in _DISTANCE_WORDS:
            distance = tokens[i]
        else:
            raise ValueError(
                f"Unexpected token '{tokens[i]}' in placement statement. "
                f"Each statement must be on its own line."
            )
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

    # Validate value against known enums to prevent silent fallback in scene_graph
    if attribute in ELEMENT_MODIFIER_ATTRIBUTES:
        _validate_modifier_value(attribute, value)

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
