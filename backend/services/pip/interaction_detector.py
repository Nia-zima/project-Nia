"""
Nia Interaction Detector — detect Pip-related cues in Nia's output.

Design doc: docs/pip_and_room_design.md §2.5
Phase P.1: regex/keyword based, no LLM calls.
"""
from __future__ import annotations

import re

from backend.services.pip.pip_state import NiaContext


# ── Pattern definitions ───────────────────────────────────────

_PIP_NAME_PATTERNS = [
    re.compile(r"[Pp]ip"),
    re.compile(r"ピップ"),
    re.compile(r"ぴっぷ"),
]

_PIP_REFERENCE_PATTERNS = [
    re.compile(r"この子"),
    re.compile(r"あの子"),
    re.compile(r"犬"),
    re.compile(r"ペット"),
    re.compile(r"しっぽ"),
    re.compile(r"歯車.{0,3}犬"),
    re.compile(r"メカ.{0,2}犬"),
    re.compile(r"機械犬"),
]

_DRAW_PIP_PATTERNS = [
    re.compile(r"[Pp]ip.{0,5}(描|書|draw)"),
    re.compile(r"(描|書).{0,5}[Pp]ip"),
    re.compile(r"ピップ.{0,5}(描|書)"),
    re.compile(r"(描|書).{0,5}ピップ"),
]


class NiaInteractionDetector:
    """Detect Nia's interactions with Pip from text output and action list."""

    def detect(
        self,
        nia_output: str = "",
        nia_actions: list[str] | None = None,
        *,
        is_talking: bool = False,
        emotional_state: str = "neutral",
    ) -> NiaContext:
        """Analyze Nia's output for Pip-related cues.

        Args:
            nia_output: Nia's text response.
            nia_actions: List of action strings from the action system.
            is_talking: Whether Nia is currently in active conversation.
            emotional_state: Inferred emotional state of Nia.

        Returns:
            NiaContext with detected interaction flags.
        """
        if nia_actions is None:
            nia_actions = []

        ctx = NiaContext()
        ctx.is_talking = is_talking
        ctx.emotional_state = emotional_state

        if not nia_output and not nia_actions:
            return ctx

        # Name called
        ctx.called_pip = any(
            p.search(nia_output) for p in _PIP_NAME_PATTERNS
        )

        # Mentioned (includes name call)
        ctx.mentioned_pip = ctx.called_pip or any(
            p.search(nia_output) for p in _PIP_REFERENCE_PATTERNS
        )

        # Drew Pip (from actions or text patterns)
        ctx.drew_pip = (
            "draw_pip" in nia_actions
            or any(p.search(nia_output) for p in _DRAW_PIP_PATTERNS)
        )

        # Placed near Pip (from actions)
        ctx.placed_near_pip = any(
            a.startswith("place_object") and "near_pip" in a
            for a in nia_actions
        )

        return ctx


# Singleton
interaction_detector = NiaInteractionDetector()
