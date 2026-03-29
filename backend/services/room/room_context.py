"""
Room Context — rule-based text generator for LLM prompt injection.

Phase P.5: Generate '=== 部屋の様子 ===' section.
No LLM calls. Same pattern as somatic_translator.

Principle: 仕組みは隠す。体験は渡す。
Bond value MUST NEVER appear in the output.
"""
from __future__ import annotations

from backend.core.logger import logger
from backend.services.room.room_state import load_room_state
from backend.services.room.runtime_facts import mood_to_visible, _VISIBLE_LABELS


def build_room_context() -> str:
    """Build room description text for Nia's LLM context.

    Returns formatted section string, or empty string if nothing to show.
    """
    try:
        room = load_room_state()
    except Exception:
        logger.debug("[RoomContext] failed to load room state", exc_info=True)
        return ""

    parts: list[str] = []

    # 1. Time of day
    tod_text = _TIME_DESCRIPTIONS.get(room.time_of_day, "")
    if tod_text:
        parts.append(tod_text)

    # 2. Pip mood (text only — no bond value)
    # Uses shared visible-state mapper (mood → PipVisible → label).
    pip = room.pip_state or {}
    pip_vis = mood_to_visible(pip.get("mood", "idle"))
    pip_text = _VISIBLE_LABELS.get(pip_vis, "")
    if pip_text:
        parts.append(f"Pipは{pip_text}")

    # 3. Objects summary
    objects = room.objects or []
    if objects:
        names = [o.get("name", o.get("template", "")) for o in objects[:8]]
        names = [n for n in names if n]
        if names:
            parts.append(f"部屋には{'、'.join(names)}がある")
    else:
        parts.append("部屋にはまだ何も置いていない")

    # 4. Wall art
    art = room.wall_art or []
    if art:
        if len(art) == 1:
            parts.append("壁に絵が1枚飾ってある")
        else:
            parts.append(f"壁に絵が{len(art)}枚飾ってある")

    # 5. Pip's favorite spot (if established)
    fav = pip.get("favorite_spot", "")
    if fav and fav not in ("", "center"):
        pos_name = _POSITION_NAMES.get(fav, fav)
        parts.append(f"Pipは{pos_name}がお気に入りみたい")

    if not parts:
        return ""

    return "=== 部屋の様子 ===\n" + "\n".join(f"- {p}" for p in parts)


# ── Lookup tables ────────────────────────────────────────────

_TIME_DESCRIPTIONS = {
    "morning": "朝の柔らかい光が窓から差し込んでいる",
    "day": "昼の明るい光が部屋を照らしている",
    "evening": "夕方のオレンジ色の光が部屋に入ってきている",
    "night": "夜。部屋は薄暗い",
    "late_night": "深夜。部屋はほとんど暗い",
}


# _PIP_MOOD_TEXT は runtime_facts.py の shared mapper に統合済み。
# mood_to_visible() + _VISIBLE_LABELS を使用する。

_POSITION_NAMES = {
    "corner": "隅っこ",
    "corner_ne": "右奥の隅",
    "corner_nw": "左奥の隅",
    "corner_se": "右手前の隅",
    "corner_sw": "左手前の隅",
    "near_window": "窓際",
    "near_door": "ドアの近く",
    "near_wall_n": "奥の壁際",
    "near_wall_s": "手前の壁際",
    "near_wall_e": "右の壁際",
    "near_wall_w": "左の壁際",
}
