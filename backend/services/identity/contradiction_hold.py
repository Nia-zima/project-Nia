"""Contradiction Hold — rewrite delay mechanism for knot contradictions.

Design (§13 of metabolic_hardening_design.md):
    - Detect when a knot's trigger fires but effect goes in unexpected direction
    - Create a hold (soft for L1, hard for L2+) to delay rewrite
    - Review after min_review_sleeps: absorbed / rejected / split
    - contradiction_score = kind_weight × effect_distance × support_ratio

Not a box to stop contradictions — a system to separate
short-term noise from long-term structural change.
"""
from __future__ import annotations

import json
import math
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

from backend.core.logger import logger
from backend.services.identity.knot_store import (
    get_knot,
    list_active_knots,
    list_pending_holds,
    save_hold,
    save_knot,
)
from backend.services.identity.schema import (
    ContradictionHold,
    ContradictionKind,
    HoldStatus,
    KnotType,
    MetabolicKnot,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return uuid.uuid4().hex[:12]


# ── Contradiction Score ───────────────────────────────────────────────


_KIND_WEIGHTS: dict[ContradictionKind, float] = {
    ContradictionKind.REVERSAL: 1.0,
    ContradictionKind.WEAKENING: 0.6,
    ContradictionKind.BRANCHING: 0.4,
}


def compute_contradiction_score(
    kind: ContradictionKind,
    effect_distance: float,
    support_ratio: float,
) -> float:
    """contradiction_score = kind_weight × effect_distance × support_ratio.

    All inputs and output in [0.0, 1.0].
    """
    w = _KIND_WEIGHTS[kind]
    return round(min(w * effect_distance * support_ratio, 1.0), 4)


def _euclidean_distance_normalized(a: dict[str, float], b: dict[str, float]) -> float:
    """Normalized euclidean distance between two effect dicts."""
    all_keys = set(a) | set(b)
    if not all_keys:
        return 0.0
    sq_sum = sum((a.get(k, 0.0) - b.get(k, 0.0)) ** 2 for k in all_keys)
    raw = math.sqrt(sq_sum / len(all_keys))
    return min(raw / 0.5, 1.0)  # normalize: 0.5 distance = 1.0 score


def _classify_contradiction(
    knot_effect: dict[str, float],
    observed_effect: dict[str, float],
) -> ContradictionKind:
    """Classify contradiction type based on effect comparison."""
    reversals = 0
    weakenings = 0
    branchings = 0

    for key in knot_effect:
        knot_val = knot_effect.get(key, 0.0)
        obs_val = observed_effect.get(key, 0.0)

        if abs(knot_val) < 0.01:
            continue

        if (knot_val > 0 and obs_val < -0.01) or (knot_val < 0 and obs_val > 0.01):
            reversals += 1
        elif abs(obs_val) < abs(knot_val) * 0.3:
            weakenings += 1

    # Check for new dominant effects not in original
    for key in observed_effect:
        if key not in knot_effect and abs(observed_effect[key]) > 0.1:
            branchings += 1

    if reversals > 0:
        return ContradictionKind.REVERSAL
    if branchings > 0:
        return ContradictionKind.BRANCHING
    return ContradictionKind.WEAKENING


# ── Contradiction Detection (Sleep Phase 4.6a) ───────────────────────


def detect_contradictions(conn: sqlite3.Connection, baseline_version: str) -> int:
    """Detect contradictions for all active L1+ knots.

    Scans recent activations (since last Sleep) for effect patterns
    that contradict the knot's established effect_signature.

    Returns number of new holds created.
    """
    now = _now_iso()
    knots = list_active_knots(conn)
    holds_created = 0

    for knot in knots:
        if knot.hardness_level < 1:
            continue  # L0 knots absorb contradictions directly

        # Get recent activations for this knot
        recent = conn.execute(
            """SELECT turn_id, effect_values, activated_at
               FROM knot_activations
               WHERE knot_id = ? AND baseline_version = ?
               ORDER BY activated_at DESC LIMIT 20""",
            (knot.knot_id, baseline_version),
        ).fetchall()

        if not recent:
            continue

        # Check each activation for contradiction
        contradicting_turns = []
        for row in recent:
            observed = json.loads(row["effect_values"])
            distance = _euclidean_distance_normalized(knot.effect_signature, observed)

            if distance > 0.3:  # significant divergence
                contradicting_turns.append(row["turn_id"])

        if not contradicting_turns:
            continue

        # Check if there's already a pending hold for this knot
        existing_holds = conn.execute(
            "SELECT 1 FROM knot_contradiction_holds WHERE knot_id = ? AND status = 'pending'",
            (knot.knot_id,),
        ).fetchone()

        if existing_holds:
            # Update existing hold with NEW evidence only (dedup against existing turn_ids)
            existing_row = conn.execute(
                "SELECT contradicting_turn_ids, evidence_count FROM knot_contradiction_holds WHERE knot_id = ? AND status = 'pending'",
                (knot.knot_id,),
            ).fetchone()
            existing_turn_ids = set(json.loads(existing_row["contradicting_turn_ids"])) if existing_row else set()
            new_turns = [t for t in contradicting_turns if t not in existing_turn_ids]
            if not new_turns:
                continue  # no new evidence
            merged_turns = list(existing_turn_ids | set(new_turns))
            conn.execute(
                """UPDATE knot_contradiction_holds
                   SET evidence_count = ?,
                       contradicting_turn_ids = ?,
                       updated_at = ?
                   WHERE knot_id = ? AND status = 'pending'""",
                (
                    len(merged_turns),
                    json.dumps(merged_turns),
                    now,
                    knot.knot_id,
                ),
            )
            logger.info(
                "[CONTRADICTION] Updated hold for %s: +%d new evidence (total=%d)",
                knot.knot_id, len(new_turns), len(merged_turns),
            )
            continue

        # Classify and score the contradiction
        # Use average of contradicting activations as observed effect
        all_observed: dict[str, list[float]] = {}
        for row in recent:
            if row["turn_id"] in contradicting_turns:
                ev = json.loads(row["effect_values"])
                for k, v in ev.items():
                    all_observed.setdefault(k, []).append(v)
        avg_observed = {k: sum(vs) / len(vs) for k, vs in all_observed.items()}

        kind = _classify_contradiction(knot.effect_signature, avg_observed)
        distance = _euclidean_distance_normalized(knot.effect_signature, avg_observed)
        support_ratio = len(contradicting_turns) / max(knot.activation_count, 1)
        score = compute_contradiction_score(kind, distance, support_ratio)

        # Determine hold type
        if knot.hardness_level == 1:
            hold_type = "soft"
            min_review = 1
        elif knot.hardness_level == 2:
            hold_type = "hard"
            min_review = 3
        else:  # L3
            hold_type = "review_lock"  # requires human review for absorbed/split
            min_review = 5

        hold = ContradictionHold(
            hold_id=f"hold_{_uid()}",
            knot_id=knot.knot_id,
            contradiction_kind=kind,
            contradiction_score=score,
            contradicting_turn_ids=contradicting_turns,
            evidence_count=len(contradicting_turns),
            hardness_level_at_hold=knot.hardness_level,
            trigger_signature_snapshot=dict(knot.trigger_signature),
            effect_signature_snapshot=dict(knot.effect_signature),
            baseline_version_at_hold=knot.current_baseline_version,
            protection_score_at_hold=knot.protection_score,
            hold_type=hold_type,
            min_review_sleeps=min_review,
            created_at=now,
            updated_at=now,
        )
        save_hold(conn, hold)
        holds_created += 1

        logger.info(
            "[CONTRADICTION] Hold created: knot=%s kind=%s score=%.3f evidence=%d type=%s",
            knot.knot_id, kind.value, score, len(contradicting_turns), hold_type,
        )

    return holds_created


# ── Contradiction Review (Sleep Phase 4.6b) ───────────────────────────


def review_holds(conn: sqlite3.Connection, baseline_version: str, *, sleep_started_at: str = "") -> dict:
    """Review pending holds that have reached min_review_sleeps.

    Args:
        sleep_started_at: holds created at or after this timestamp are skipped
                          (new holds should not be reviewed in the same Sleep they were created).
    Returns summary dict.
    """
    result = {"reviewed": 0, "absorbed": 0, "rejected": 0, "split": 0, "still_pending": 0}
    now = _now_iso()

    pending = list_pending_holds(conn)
    for hold in pending:
        # Skip holds created in the current Sleep (they need at least 1 Sleep to observe)
        if sleep_started_at and hold.created_at >= sleep_started_at:
            result["still_pending"] += 1
            continue

        hold.hold_duration_sleeps += 1

        if hold.hold_duration_sleeps < hold.min_review_sleeps:
            # Not ready for review yet — just increment duration
            conn.execute(
                "UPDATE knot_contradiction_holds SET hold_duration_sleeps = ?, updated_at = ? WHERE hold_id = ?",
                (hold.hold_duration_sleeps, now, hold.hold_id),
            )
            result["still_pending"] += 1
            continue

        result["reviewed"] += 1

        # Get the knot's current state
        knot = get_knot(conn, hold.knot_id)
        if not knot or knot.status.value != "active":
            # Knot was archived/merged — reject hold
            _resolve_hold(conn, hold, HoldStatus.REJECTED, "knot no longer active", now)
            result["rejected"] += 1
            continue

        # Re-evaluate contradiction with current data
        # Get activations since hold was created, filtered to current baseline
        # (§6b.1 invariant: do not mix effects from different baselines)
        post_hold_acts = conn.execute(
            """SELECT effect_values, interaction_regime
               FROM knot_activations
               WHERE knot_id = ? AND activated_at >= ? AND baseline_version = ?
               ORDER BY activated_at DESC""",
            (hold.knot_id, hold.created_at, baseline_version),
        ).fetchall()

        if not post_hold_acts:
            # No new activations — not enough evidence to decide
            if hold.hold_duration_sleeps >= hold.min_review_sleeps + 3:
                # Waited long enough with no activity — reject
                _resolve_hold(conn, hold, HoldStatus.REJECTED, "no activity since hold", now)
                result["rejected"] += 1
            else:
                conn.execute(
                    "UPDATE knot_contradiction_holds SET hold_duration_sleeps = ?, updated_at = ? WHERE hold_id = ?",
                    (hold.hold_duration_sleeps, now, hold.hold_id),
                )
                result["still_pending"] += 1
            continue

        # Compute average effect of post-hold activations
        all_effects: dict[str, list[float]] = {}
        regime_counts: dict[str, int] = {}
        for row in post_hold_acts:
            ev = json.loads(row["effect_values"])
            for k, v in ev.items():
                all_effects.setdefault(k, []).append(v)
            regime = row["interaction_regime"]
            regime_counts[regime] = regime_counts.get(regime, 0) + 1

        avg_post = {k: sum(vs) / len(vs) for k, vs in all_effects.items()}

        # Re-score
        distance = _euclidean_distance_normalized(
            hold.effect_signature_snapshot, avg_post
        )
        support_ratio = hold.evidence_count / max(knot.activation_count, 1)
        new_score = compute_contradiction_score(hold.contradiction_kind, distance, support_ratio)

        # Resolution decision
        if hold.evidence_count <= 2 and new_score < 0.3:
            _resolve_hold(conn, hold, HoldStatus.REJECTED, f"transient: score={new_score:.3f} evidence={hold.evidence_count}", now)
            result["rejected"] += 1

        elif hold.evidence_count >= 5 and new_score >= 0.5:
            if hold.hold_type == "review_lock":
                # L3 review_lock: mark as requires_review, don't auto-absorb
                conn.execute(
                    """UPDATE knot_contradiction_holds
                       SET requires_review = 1, contradiction_score = ?,
                           hold_duration_sleeps = ?, updated_at = ?
                       WHERE hold_id = ?""",
                    (new_score, hold.hold_duration_sleeps, now, hold.hold_id),
                )
                result["still_pending"] += 1
                logger.info("[CONTRADICTION] L3 review_lock: knot=%s score=%.3f awaiting human review", knot.knot_id, new_score)
            else:
                # Absorbed — update knot's effect signature
                knot.effect_signature = avg_post
                knot.updated_at = now
                save_knot(conn, knot)
                _resolve_hold(conn, hold, HoldStatus.ABSORBED, f"confirmed shift: score={new_score:.3f} evidence={hold.evidence_count}", now)
                result["absorbed"] += 1
                logger.info("[CONTRADICTION] Absorbed: knot=%s new_effect=%s", knot.knot_id, list(avg_post.keys()))

        elif len(regime_counts) > 1 and max(regime_counts.values()) / len(post_hold_acts) > 0.8:
            dominant_regime = max(regime_counts, key=regime_counts.get)
            if hold.hold_type == "review_lock":
                # L3 review_lock: mark split candidate for human review
                conn.execute(
                    """UPDATE knot_contradiction_holds
                       SET requires_review = 1, contradiction_score = ?,
                           resolution_reason = ?, hold_duration_sleeps = ?, updated_at = ?
                       WHERE hold_id = ?""",
                    (new_score, f"split candidate: {dominant_regime}", hold.hold_duration_sleeps, now, hold.hold_id),
                )
                result["still_pending"] += 1
                logger.info("[CONTRADICTION] L3 review_lock split: knot=%s regime=%s awaiting human review", knot.knot_id, dominant_regime)
            else:
                _resolve_hold(
                    conn, hold, HoldStatus.SPLIT,
                    f"regime-specific: {dominant_regime} has {regime_counts[dominant_regime]}/{len(post_hold_acts)} activations",
                    now,
                )
                result["split"] += 1
                logger.info("[CONTRADICTION] Split candidate: knot=%s regime=%s", knot.knot_id, dominant_regime)

        else:
            # Still pending — update score and continue
            conn.execute(
                """UPDATE knot_contradiction_holds
                   SET contradiction_score = ?, hold_duration_sleeps = ?, updated_at = ?
                   WHERE hold_id = ?""",
                (new_score, hold.hold_duration_sleeps, now, hold.hold_id),
            )
            result["still_pending"] += 1

    logger.info(
        "[CONTRADICTION] Review: reviewed=%d absorbed=%d rejected=%d split=%d pending=%d",
        result["reviewed"], result["absorbed"], result["rejected"],
        result["split"], result["still_pending"],
    )
    return result


def _resolve_hold(
    conn: sqlite3.Connection,
    hold: ContradictionHold,
    status: HoldStatus,
    reason: str,
    now: str,
) -> None:
    """Resolve a hold with the given status and reason."""
    conn.execute(
        """UPDATE knot_contradiction_holds
           SET status = ?, resolution_reason = ?, resolved_at = ?, updated_at = ?
           WHERE hold_id = ?""",
        (status.value, reason, now, now, hold.hold_id),
    )
    logger.info("[CONTRADICTION] Resolved: hold=%s status=%s reason=%s", hold.hold_id, status.value, reason)
