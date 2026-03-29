"""Read active adaptation proposals for runtime use.

Phase C: provides merged HistoryBias to _recent_history() scorer.
Only reads proposals with target_layer='history_selection' and
active status ('proposed', 'shadow_pass', 'graduated').

Design doc: docs/failure_success_policy_design.md §6, §8
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from backend.core.config import settings
from backend.core.db import managed_conn
from backend.core.logger import logger


@dataclass(frozen=True)
class MergedHistoryBias:
    """Flattened history_bias from all active proposals.

    Merge rules:
    - downrank/uprank families: union of all proposals
    - cap_same_family: minimum across proposals (strictest wins)
    - prefer/avoid trace_match: union of all proposals
    """

    downrank_families: frozenset[str] = field(default_factory=frozenset)
    uprank_families: frozenset[str] = field(default_factory=frozenset)
    cap_same_family: int | None = None
    prefer_trace_match: frozenset[str] = field(default_factory=frozenset)
    avoid_trace_match: frozenset[str] = field(default_factory=frozenset)

    @property
    def is_empty(self) -> bool:
        return (
            not self.downrank_families
            and not self.uprank_families
            and self.cap_same_family is None
            and not self.prefer_trace_match
            and not self.avoid_trace_match
        )


_EMPTY_BIAS = MergedHistoryBias()

# Active statuses that should influence runtime behavior
_ACTIVE_STATUSES = ("proposed", "shadow_pass", "graduated")


def get_merged_history_bias(
    thread_mode: str | None = None,
) -> MergedHistoryBias:
    """Fetch and merge history_bias from all active history_selection proposals.

    Returns MergedHistoryBias (frozen, safe to cache per-turn).
    Gate-aware: returns empty bias when ADAPTATION_RECORD_ENABLED is off.
    """
    if not getattr(settings, "ADAPTATION_RECORD_ENABLED", False):
        return _EMPTY_BIAS

    try:
        return _fetch_and_merge(thread_mode)
    except Exception:
        logger.warning("[AdaptationReader] failed to read proposals", exc_info=True)
        return _EMPTY_BIAS


def _fetch_and_merge(thread_mode: str | None) -> MergedHistoryBias:
    """Core fetch + merge logic."""
    with managed_conn() as conn:
        if thread_mode:
            rows = conn.execute(
                """SELECT effect_json FROM conversation_adaptation_proposals
                   WHERE target_layer = 'history_selection'
                     AND status IN (?, ?, ?)
                     AND (thread_mode IS NULL OR thread_mode = ?)
                     AND (expires_at IS NULL OR strftime('%s', expires_at) > strftime('%s', 'now'))
                   ORDER BY priority DESC, updated_at DESC""",
                (*_ACTIVE_STATUSES, thread_mode),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT effect_json FROM conversation_adaptation_proposals
                   WHERE target_layer = 'history_selection'
                     AND status IN (?, ?, ?)
                     AND (expires_at IS NULL OR strftime('%s', expires_at) > strftime('%s', 'now'))
                   ORDER BY priority DESC, updated_at DESC""",
                _ACTIVE_STATUSES,
            ).fetchall()

    if not rows:
        return _EMPTY_BIAS

    downrank: set[str] = set()
    uprank: set[str] = set()
    caps: list[int] = []
    prefer: set[str] = set()
    avoid: set[str] = set()

    for row in rows:
        try:
            effect = json.loads(row[0] or "{}")
            hb = effect.get("history_bias", {})
        except (json.JSONDecodeError, TypeError):
            continue

        downrank.update(hb.get("downrank_families", []))
        uprank.update(hb.get("uprank_families", []))
        if hb.get("cap_same_family") is not None:
            caps.append(hb["cap_same_family"])
        prefer.update(hb.get("prefer_trace_match", []))
        avoid.update(hb.get("avoid_trace_match", []))

    return MergedHistoryBias(
        downrank_families=frozenset(downrank),
        uprank_families=frozenset(uprank),
        cap_same_family=min(caps) if caps else None,
        prefer_trace_match=frozenset(prefer),
        avoid_trace_match=frozenset(avoid),
    )
