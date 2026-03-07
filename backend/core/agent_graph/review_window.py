from __future__ import annotations

import uuid
from typing import Iterable, Optional

from backend.core.agent_graph.state import AgentState
from backend.core.logger import logger

_REVIEW_PREFIX = "review:"

# Phase2 constants
D_LOW = 0.30
D_MAX = 0.95
K_HOLD = 0.03
K_REJECT = 0.07
MAX_PENDING = 10
MAX_SUPPRESSED = 5
MAX_REJECTED = 10
MAX_REASON_CODES = 10

# Fixed reason codes (Phase2 checklist)
_ALLOWED_REASON_CODES = {
    "system_wait_passthrough",
    "system_review_window",
    "system_hold_cancelled",
    "system_review_token_mismatch",
    "system_hold_cancelled_new_input",
    "safety_blocked",
    "risk_dissonance_on",
    "risk_high_dissonance",
    "risk_long_text",
    "risk_long_reply",
    "risk_memory_candidate",
    "risk_public_context",
    "keyword_memory",
    "keyword_policy",
    "keyword_identity",
    "keyword_decision",
    "keyword_public",
    "action_say_held",
    "action_rejected",
    # PII protection
    "pii_in_output",
    # Phase E: Guardrail v2
    "guardrail_no_provenance",
    "guardrail_contradiction",
    "guardrail_thin_retrieval",
}

def _merge_reason_codes(existing: Optional[list], additions: Iterable[str]) -> list[str]:
    seen = set()
    out: list[str] = []
    for code in existing or []:
        if not code or code in seen:
            continue
        if code not in _ALLOWED_REASON_CODES:
            continue
        seen.add(code)
        out.append(code)
    for code in additions:
        if not code or code in seen:
            continue
        if code not in _ALLOWED_REASON_CODES:
            continue
        seen.add(code)
        out.append(code)
    return out[-MAX_REASON_CODES:]


def _cap_items(items: Optional[list], limit: int) -> list:
    base = list(items or [])
    if len(base) <= limit:
        return base
    return base[-limit:]


def get_review_pending_actions(state: AgentState | dict) -> list:
    if "review_pending_actions" in state:
        return _cap_items(state.get("review_pending_actions") or [], MAX_PENDING)
    return _cap_items(state.get("pending_actions") or [], MAX_PENDING)


def get_review_token(state: AgentState) -> Optional[str]:
    direct = state.get("review_token")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    merge_mode = state.get("merge_mode")
    if not merge_mode:
        return None
    if not merge_mode.startswith(_REVIEW_PREFIX):
        return None
    token = merge_mode[len(_REVIEW_PREFIX):].strip()
    return token or None


def set_review_token(
    state: AgentState,
    *,
    token: Optional[str] = None,
    review_pending_actions: Optional[list] = None,
    pending_actions: Optional[list] = None,
    hold_kind: str = "speech_preview",
    reason_codes: Optional[list] = None,
    dissonance: Optional[float] = None,
) -> dict:
    token = token or uuid.uuid4().hex
    pending_source = review_pending_actions if review_pending_actions is not None else pending_actions
    pending = _cap_items(pending_source, MAX_PENDING)
    merged_reasons = _merge_reason_codes(reason_codes, ["system_review_window", "action_say_held"])
    base_dissonance = float(dissonance if dissonance is not None else (state.get("dissonance") or 0.0))
    after_hold = min(base_dissonance + K_HOLD, D_MAX)
    preview_text = ""
    for item in pending:
        if isinstance(item, dict) and item.get("kind") == "say":
            preview_text = str(item.get("text") or "").strip()
            break
    suppressed = _cap_items(
        list(state.get("suppressed_actions") or [])
        + [{"kind": "say", "text": preview_text, "token": token, "reasons": merged_reasons}],
        MAX_SUPPRESSED,
    )
    update = {
        "final_text": "WAIT",
        "hold_required": True,
        "hold_kind": hold_kind,
        "review_token": token,
        "review_pending_actions": pending,
        "merge_mode": f"{_REVIEW_PREFIX}{token}",
        "reason_codes": merged_reasons,
        "suppressed_actions": suppressed,
        "dissonance": after_hold,
    }
    if preview_text:
        update["draft"] = preview_text
    return update


def clear_review_token(*, next_merge_mode: Optional[str] = None) -> dict:
    return {
        "merge_mode": next_merge_mode,
        "review_token": None,
        "hold_required": False,
        "hold_kind": None,
        "review_pending_actions": [],
    }


def apply_review_decision(
    state: AgentState,
    *,
    token: str,
    decision: str,
) -> dict:
    expected = get_review_token(state)
    if not expected or expected != token:
        return {}

    pending_actions = get_review_pending_actions(state)
    candidate_text = ""
    for item in pending_actions:
        if isinstance(item, dict) and item.get("kind") == "say":
            candidate_text = str(item.get("text") or "").strip()
            break

    if decision == "approve":
        if not candidate_text:
            candidate_text = "WAIT"
        merged_reasons = _merge_reason_codes(state.get("reason_codes"), [])
        return {
            "final_text": candidate_text,
            **clear_review_token(next_merge_mode="B"),
            "reason_codes": merged_reasons,
        }
    if decision == "reject":
        before = state.get("dissonance")
        base = float(before or 0.0)
        after = min(base + K_REJECT, D_MAX)
        rejected_actions = _cap_items(
            list(state.get("rejected_actions") or [])
            + [
                {
                    "kind": "say",
                    "text": candidate_text,
                    "token": token,
                    "reasons": list(state.get("reason_codes") or []),
                }
            ],
            MAX_REJECTED,
        )
        merged_reasons = _merge_reason_codes(state.get("reason_codes"), ["action_rejected"])
        return {
            "final_text": "WAIT",
            **clear_review_token(next_merge_mode="wait"),
            "reason_codes": merged_reasons,
            "dissonance": after,
            "rejected_actions": rejected_actions,
        }
    return {}


def cancel_review_on_new_input(
    state: AgentState,
    *,
    user_text: Optional[str],
) -> dict:
    token = get_review_token(state)
    if not token:
        return {}
    if not user_text:
        return {}

    logger.info("[EVENT] hold_cancelled token=%s", token)
    pending_actions = get_review_pending_actions(state)
    shadowed = [
        {
            "kind": item.get("kind"),
            "text": item.get("text"),
            "token": token,
            "reasons": list(state.get("reason_codes") or []),
            "cancel_reason": "new_user_input",
        }
        for item in pending_actions
        if isinstance(item, dict)
    ]
    rejected_actions = _cap_items(list(state.get("rejected_actions") or []) + shadowed, MAX_REJECTED)
    merged_reasons = _merge_reason_codes(
        state.get("reason_codes"),
        ["system_hold_cancelled", "system_hold_cancelled_new_input"],
    )
    return {
        "final_text": "WAIT",
        **clear_review_token(next_merge_mode="wait"),
        "reason_codes": merged_reasons,
        "rejected_actions": rejected_actions,
    }


def build_hold_request_event(update: dict) -> Optional[dict]:
    token = update.get("review_token")
    if not token:
        token = get_review_token({"merge_mode": update.get("merge_mode")})
    if not token:
        return None
    pending_actions = get_review_pending_actions(update)
    preview_text = ""
    for item in pending_actions:
        if isinstance(item, dict) and item.get("kind") == "say":
            preview_text = str(item.get("text") or "").strip()
            break
    if not preview_text:
        preview_text = str(update.get("draft") or "").strip()
    payload = {
        "review_token": token,
        "hold_kind": update.get("hold_kind") or "speech_preview",
        "preview_text": preview_text,
        "reason_codes": _merge_reason_codes([], update.get("reason_codes") or []),
        "pending_actions": pending_actions,
    }
    return {"type": "event", "name": "hold_request", "payload": payload}


def build_hold_cancelled_event(review_token: Optional[str]) -> Optional[dict]:
    if not review_token:
        return None
    payload = {"review_token": review_token, "reason": "new_user_input"}
    return {"type": "event", "name": "hold_cancelled", "payload": payload}
