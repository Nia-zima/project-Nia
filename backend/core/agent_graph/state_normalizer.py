from __future__ import annotations

from typing import Any, Mapping


def _as_list(value: Any) -> list:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return []


def _get_review_token(values: Mapping[str, Any]) -> str | None:
    direct = values.get("review_token")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    merge_mode = values.get("merge_mode")
    if isinstance(merge_mode, str) and merge_mode.startswith("review:"):
        token = merge_mode[len("review:"):].strip()
        return token or None
    return None


def _is_review_rejected_item(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    kind = str(item.get("kind") or "").lower()
    if kind == "say":
        return True
    if item.get("review_token") or item.get("token") or item.get("cancel_reason"):
        return True
    reasons = item.get("reasons") or item.get("reason_codes") or []
    if isinstance(reasons, (list, tuple, set)):
        normalized = {str(reason) for reason in reasons if reason}
        if "action_rejected" in normalized:
            return True
        if any(code.startswith("system_hold_cancelled") for code in normalized):
            return True
    return False


def normalize_checkpoint_state(values: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = dict(values or {})
    normalized = dict(raw)

    review_token = _get_review_token(raw)
    review_pending_explicit = "review_pending_actions" in raw
    review_pending_actions = _as_list(raw.get("review_pending_actions"))
    pending_actions = _as_list(raw.get("pending_actions"))
    if not review_pending_explicit and review_token:
        review_pending_actions = pending_actions
        pending_actions = []
    normalized["review_pending_actions"] = review_pending_actions
    normalized["pending_actions"] = pending_actions

    review_rejected_explicit = "review_rejected_actions" in raw
    if review_rejected_explicit:
        review_rejected_actions = _as_list(raw.get("review_rejected_actions"))
        rejected_actions = _as_list(raw.get("rejected_actions"))
    else:
        review_rejected_actions = []
        rejected_actions = []
        for item in _as_list(raw.get("rejected_actions")):
            if _is_review_rejected_item(item):
                review_rejected_actions.append(item)
            else:
                rejected_actions.append(item)
    normalized["review_rejected_actions"] = review_rejected_actions
    normalized["rejected_actions"] = rejected_actions

    return normalized
