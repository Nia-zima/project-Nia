"""Expression Layer E0: event kind determination.

Classifies each turn into one of the expression observation event kinds.
Design doc: docs/nia_expression_layer_design.md §4.6
"""
from __future__ import annotations


def determine_event_kind(
    *,
    final_text: str | None,
    hold_required: bool = False,
    depth_action: str | None = None,
    hold_kind: str | None = None,
) -> str:
    """Determine the expression event kind for a turn.

    Returns one of: "spoken", "wait_depth", "wait_hold", "soft_close", "empty_abort".
    """
    if not final_text or not final_text.strip():
        return "empty_abort"

    text = final_text.strip()

    if text == "WAIT":
        if depth_action == "wait":
            return "wait_depth"
        return "wait_hold"

    if hold_required:
        return "wait_hold"

    if hold_kind == "soft_close":
        return "soft_close"

    return "spoken"
