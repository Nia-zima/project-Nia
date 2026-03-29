"""Drawing Language — prompt reference generator.

Generates a minimal drawing language reference from schema.py constants.
This is the single source of truth for what the LLM sees vs what the parser accepts.

Injected into LLM context only when draw_intent is detected.
"""
from __future__ import annotations

from backend.core.drawing.schema import (
    COMPOSITION_KWARG_LEVELS,
    COMPOSITION_KWARGS,
    COMPOSITION_PREPOSITIONS,
    CompositionOp,
    ELEMENT_MODIFIER_ATTRIBUTES,
    ELEMENT_MODIFIER_LEVELS,
    ElementType,
    PaletteColor,
    Relation,
    SpatialRef,
)


_DRAW_INTENT_KEYWORDS: frozenset[str] = frozenset({
    "描", "絵", "draw", "sketch", "お絵かき", "落書き", "イラスト",
    "心の風景", "描いて", "描きたい", "描こう", "描ける",
})
"""Keywords that signal the user is asking Nia to draw."""


def detect_draw_intent(user_text: str) -> bool:
    """Check if user_text contains drawing-related intent.

    Pure function — no state dependency. Used by helpers.py to decide
    whether to inject the drawing reference into the LLM context.
    """
    if not user_text:
        return False
    return any(kw in user_text for kw in _DRAW_INTENT_KEYWORDS)


def build_drawing_reference() -> str:
    """Build a minimal drawing language reference for LLM context injection.

    All vocabulary is derived from schema.py constants — no hardcoded strings.
    """
    elements = ", ".join(e.value for e in ElementType)
    relations = ", ".join(r.value for r in Relation)
    spatial = ", ".join(s.value for s in SpatialRef)
    colors = ", ".join(c.value for c in PaletteColor)
    comp_ops = ", ".join(o.value for o in CompositionOp)
    prepositions = ", ".join(
        f"{k} (= {v.value})" for k, v in COMPOSITION_PREPOSITIONS.items()
    )

    # Element modifiers (applied per element)
    elem_mod_lines: list[str] = []
    for attr in sorted(ELEMENT_MODIFIER_ATTRIBUTES):
        if attr == "color":
            elem_mod_lines.append(f"  color: {colors}")
        elif attr in ELEMENT_MODIFIER_LEVELS:
            levels = " / ".join(lv.value for lv in ELEMENT_MODIFIER_LEVELS[attr])
            elem_mod_lines.append(f"  {attr}: {levels}")

    # Composition kwargs (used inside repeat/scatter)
    comp_kwarg_lines: list[str] = []
    for kw in sorted(COMPOSITION_KWARGS):
        if kw in COMPOSITION_KWARG_LEVELS:
            levels = " / ".join(lv.value for lv in COMPOSITION_KWARG_LEVELS[kw])
            comp_kwarg_lines.append(f"  {kw}: {levels}")
        elif kw == "count":
            comp_kwarg_lines.append("  count: 整数")
        elif kw == "seed":
            comp_kwarg_lines.append("  seed: 整数（再現用）")
        elif kw == "spacing":
            comp_kwarg_lines.append("  spacing: tight / normal / loose / wide")

    return f"""\
=== 描画の手 ===
あなたは ```draw ブロックで絵を描けます。

要素: {elements}
関係: {relations}
空間参照: {spatial}

要素の修飾（name attribute value）:
{chr(10).join(elem_mod_lines)}

構成: {comp_ops} (前置詞: {prepositions})
構成のオプション:
{chr(10).join(comp_kwarg_lines)}

文の種類:
  宣言: name: element(size=small, weight=bold)
  配置: name relation target [distance] [because tag -- 自由文]
  修飾: name attribute value [because tag]
  構成: repeat/scatter element relation target count=N density=level

例:
```draw
sky: area(size=vast)
core: circle(size=small)
sky at field because background
core at center because anchor
sky color cool_1
sky opacity faint
core color warm_3
scatter dot around core count=6 density=sparse because ambient
```

because は任意。選んだ理由を残したいときに使います。"""
