"""Nia Drawing Language — Intent Parser (Layer 2).

Design: docs/nia_drawing_language.md §3c

構造化された描画意図 (DrawingIntent) を Nia Drawing Language DSL に
**決定論的に** 変換する。LLM の気分に依存しない。
モデルを変えても壊れない。
"""
from __future__ import annotations

from backend.core.drawing.intent_schema import (
    DrawingIntent,
    IntentArrangement,
    IntentColorFeel,
    IntentCountMode,
    IntentDominance,
    IntentElement,
    IntentOpacityFeel,
    IntentRole,
)


# ── color_feel → palette mapping ─────────────────────────────────────
# v0: 固定マッピング。将来は drawing knot として Nia 固有に進化する。

_COLOR_FEEL_MAP: dict[str, str] = {
    "warm": "warm_2",
    "warm_fading": "warm_1",
    "cool": "cool_2",
    "quiet": "cool_1",
    "neutral": "neutral_2",
    "dark": "neutral_3",
}

# ── dominance → default modifiers ────────────────────────────────────

_DOMINANCE_DEFAULTS: dict[str, dict[str, str]] = {
    "primary": {"opacity": "solid"},
    "secondary": {"opacity": "soft"},
    "background": {"opacity": "faint"},
    "trace": {"opacity": "faint"},
}

# ── role → dominance fallback ────────────────────────────────────────

_ROLE_TO_DOMINANCE: dict[str, str] = {
    "anchor": "primary",
    "background": "background",
    "frame": "background",
    "support": "secondary",
    "accent": "secondary",
    "detail": "trace",
}

# ── arrangement → DSL relation ───────────────────────────────────────

_ARRANGEMENT_TO_RELATION: dict[str, str] = {
    "near": "near",
    "far": "far",
    "touching": "touching",
    "inside": "inside",
    "above": "above",
    "below": "below",
    "left_of": "left_of",
    "right_of": "right_of",
    "surrounding": "surround",
    # scattered_around → composition (handled separately)
}


def intent_to_dsl(intent: DrawingIntent) -> str:
    """DrawingIntent → Nia Drawing Language DSL 文字列。

    完全に決定論的。同じ入力に対して常に同じ出力を返す。
    """
    declarations: list[str] = []
    placements: list[str] = []
    modifiers: list[str] = []
    compositions: list[str] = []

    for elem in intent.elements:
        # ── scatter/repeat 要素 ──
        if elem.count is not None and elem.relation_to and elem.arrangement == IntentArrangement.SCATTERED_AROUND:
            comp = _build_composition(elem)
            compositions.append(comp)
            continue

        # ── 通常要素 ──
        decl = _build_declaration(elem)
        declarations.append(decl)

        place = _build_placement(elem)
        if place:
            placements.append(place)

        mods = _build_modifiers(elem)
        modifiers.extend(mods)

    # DSL を組み立て（セクション間に空行）
    sections = []
    if declarations:
        sections.append("\n".join(declarations))
    if placements:
        sections.append("\n".join(placements))
    if modifiers:
        sections.append("\n".join(modifiers))
    if compositions:
        sections.append("\n".join(compositions))

    return "\n\n".join(sections)


# ── Private builders ─────────────────────────────────────────────────


def _build_declaration(elem: IntentElement) -> str:
    """要素宣言を生成。"""
    type_name = elem.type.value
    args: list[str] = []

    if elem.size:
        args.append(f"size={elem.size.value}")

    if args:
        return f"{elem.name}: {type_name}({', '.join(args)})"
    return f"{elem.name}: {type_name}"


def _build_placement(elem: IntentElement) -> str | None:
    """配置文を生成。"""
    if elem.position:
        # 最初の要素: 空間参照への配置
        target = elem.position.value
        line = f"{elem.name} at {target}"
        if elem.reason:
            line += f" because {_sanitize_reason(elem.reason)}"
        return line

    if elem.relation_to and elem.arrangement:
        # 2つ目以降: 既存要素との関係
        if elem.arrangement == IntentArrangement.SCATTERED_AROUND:
            return None  # composition で処理

        relation = _ARRANGEMENT_TO_RELATION.get(elem.arrangement.value)
        if not relation:
            return None

        line = f"{elem.name} {relation} {elem.relation_to}"

        if elem.distance:
            line += f" {elem.distance.value}"

        if elem.reason:
            line += f" because {_sanitize_reason(elem.reason)}"
        return line

    return None


def _build_modifiers(elem: IntentElement) -> list[str]:
    """修飾文を生成。dominance からのデフォルトと明示指定をマージ。"""
    mods: list[str] = []

    # dominance を解決
    dominance = _resolve_dominance(elem)
    defaults = _DOMINANCE_DEFAULTS.get(dominance, {})

    # color
    if elem.color_feel:
        palette = _COLOR_FEEL_MAP.get(elem.color_feel.value, "neutral_2")
        mods.append(f"{elem.name} color {palette}")

    # opacity: 明示指定 > dominance デフォルト
    if elem.opacity_feel:
        mods.append(f"{elem.name} opacity {elem.opacity_feel.value}")
    elif "opacity" in defaults:
        mods.append(f"{elem.name} opacity {defaults['opacity']}")

    return mods


def _build_composition(elem: IntentElement) -> str:
    """scatter/repeat 文を生成。"""
    count = elem.count or 3
    count_mode = elem.count_mode or IntentCountMode.APPROXIMATE

    # approximate なら density で表現、exact なら count で表現
    if count_mode == IntentCountMode.APPROXIMATE:
        density = _count_to_density(count)
        line = (
            f"scatter {elem.type.value} around {elem.relation_to} "
            f"count={count} density={density}"
        )
    else:
        line = (
            f"scatter {elem.type.value} around {elem.relation_to} "
            f"count={count}"
        )

    if elem.reason:
        line += f" because {_sanitize_reason(elem.reason)}"
    return line


def _resolve_dominance(elem: IntentElement) -> str:
    """dominance を解決。明示 > role からの推定 > default。"""
    if elem.dominance:
        return elem.dominance.value
    if elem.role:
        return _ROLE_TO_DOMINANCE.get(elem.role.value, "secondary")
    return "secondary"


def _count_to_density(count: int) -> str:
    """count から density を推定。"""
    if count <= 3:
        return "sparse"
    if count <= 8:
        return "loose"
    if count <= 15:
        return "normal"
    if count <= 30:
        return "dense"
    return "packed"


def _sanitize_reason(reason: str) -> str:
    """reason を because タグ語彙に変換。

    Intent の reason は自由文だが、DSL の because は tag 形式。
    スペースをアンダースコアに、英数字以外を除去。
    """
    import re
    tag = reason.strip().lower()
    tag = tag.replace(" ", "_")
    tag = re.sub(r"[^a-zA-Z0-9_-]", "", tag)
    return tag[:50] if tag else "intent"
