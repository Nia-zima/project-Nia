"""Pseudo-teacher rules for NiaCore vNext Phase N0.

ルールベース擬似教師。attention_target と recommended_action を推定する。
SkeletonCore の R/I/Q ルール群と同じパターン — 何を観測するかを先に決める。

擬似教師は Nia の「正解」ではなく、設計者の推測。
Phase N0〜N2 では擬似教師自体の妥当性も検証対象。

Design doc: docs/niacore_vnext_design.md §10.4
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ═══════════════════════════════════════════════════════════════
# Result
# ═══════════════════════════════════════════════════════════════

@dataclass
class PseudoTeacherResult:
    """擬似教師の出力。null 系ラベルは正当な出力（L.11）。"""
    attention_target: str | None = None    # "pip" | "environment" | "memory_trace" | None
    recommended_action: str | None = None  # "soft_close" | "retrieve_alt_memory" | "hold_support" | None
    fired_rules: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
# Warmth keywords for A1
# ═══════════════════════════════════════════════════════════════

_WARMTH_KEYWORDS = frozenset({
    "温かい", "あたたかい", "やわらかい", "柔らかい",
    "気配", "ぬくもり", "そばに", "近くに",
    "warm", "warmth", "soft", "gentle",
})


def _has_warmth_somatic(somatic_senses: list[dict[str, Any]] | None) -> bool:
    """Check if any somatic sense text contains warmth-related keywords."""
    if not somatic_senses:
        return False
    for sense in somatic_senses:
        if not isinstance(sense, dict):
            continue
        text = str(sense.get("text", ""))
        for kw in _WARMTH_KEYWORDS:
            if kw in text:
                return True
    return False


# ═══════════════════════════════════════════════════════════════
# Confidence trend
# ═══════════════════════════════════════════════════════════════

def _confidence_declining(confidence_history: list[float] | None) -> bool:
    """直近 3 エントリが単調減少かどうか。"""
    if not confidence_history or len(confidence_history) < 3:
        return False
    tail = confidence_history[-3:]
    return tail[0] > tail[1] > tail[2]


# ═══════════════════════════════════════════════════════════════
# Main evaluation
# ═══════════════════════════════════════════════════════════════

def evaluate_pseudo_teacher(
    *,
    pip_position_near: bool = False,
    somatic_senses: list[dict[str, Any]] | None = None,
    room_change: str = "none",
    skeleton_focus: str | None = None,
    skeleton_response_intent: str | None = None,
    retrieval_top_similarity: float = 0.0,
    confidence: float = 0.5,
    confidence_history: list[float] | None = None,
) -> PseudoTeacherResult:
    """Evaluate pseudo-teacher rules A1-A3 and C1-C3.

    A-rules: first match wins for attention_target.
    C-rules: first match wins for recommended_action.
    Both can fire simultaneously (independent axes).

    Returns PseudoTeacherResult with null-safe defaults.
    """
    result = PseudoTeacherResult()

    # ── Attention rules (A1-A3, first match wins) ──────────────

    # A1: Pip nearby + warmth somatic → attention=pip
    if pip_position_near and _has_warmth_somatic(somatic_senses):
        result.attention_target = "pip"
        result.fired_rules.append("A1")

    # A2: Room change → attention=environment
    elif room_change != "none" and room_change:
        result.attention_target = "environment"
        result.fired_rules.append("A2")

    # A3: Returning theme + retrieval hit → attention=memory_trace
    elif skeleton_focus == "returning_theme" and retrieval_top_similarity >= 0.5:
        result.attention_target = "memory_trace"
        result.fired_rules.append("A3")

    # ── Action rules (C1-C3, first match wins) ─────────────────

    # C1: Reassurance loop (lingering + confidence declining) → soft_close
    if skeleton_focus == "lingering_state" and _confidence_declining(confidence_history):
        result.recommended_action = "soft_close"
        result.fired_rules.append("C1")

    # C2: Lingering + no retrieval progress → retrieve_alt_memory
    elif skeleton_focus == "lingering_state" and retrieval_top_similarity < 0.3:
        result.recommended_action = "retrieve_alt_memory"
        result.fired_rules.append("C2")

    # C3: Fragile self-observation → hold_support
    elif skeleton_response_intent == "offer_fragile_self_observation":
        result.recommended_action = "hold_support"
        result.fired_rules.append("C3")

    return result
