"""Knot Extractors — Sleep Cycle Phase 4.5.

Extracts the 4 adopted knots from existing trace data:
  - RK-1: low_confidence_compression_knot (response)
  - RK-2: organize_priority_knot (response)
  - LK-macro: meeting_inward_softening_knot (relational)
  - SK-2: correction_resilience_knot (self_boundary)

Design:
  - Each extractor reads raw traces from observation tables
  - Computes effect as baseline delta
  - Upserts to metabolic_knots + records knot_activations
  - Fire-and-forget pattern: errors are logged, never raised
  - No runtime impact: this runs in Sleep Cycle only
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

from backend.core.logger import logger
from backend.services.identity.knot_store import (
    get_knot,
    get_latest_baseline_version,
    save_activation,
    save_baseline_snapshot,
    save_knot,
)
from backend.services.identity.schema import (
    KnotActivation,
    KnotBaseline,
    KnotStatus,
    KnotType,
    MetabolicKnot,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return uuid.uuid4().hex[:12]


# ── Baseline Computation ──────────────────────────────────────────────


def compute_and_save_baselines(conn: sqlite3.Connection) -> str:
    """Compute regime-specific baselines from all observation data.

    Returns the new baseline_version string.
    """
    version = f"bv_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    now = _now_iso()
    baselines: list[KnotBaseline] = []

    # Effect keys we track (from expression_observations + niacore_experience + skeletons)
    for regime in ("default", "meeting"):
        thread_filter = (
            "NOT LIKE 'nero_meeting%'" if regime == "default" else "LIKE 'nero_meeting%'"
        )

        # --- Expression-based effects ---
        row = conn.execute(f"""
            SELECT
                COUNT(*) as n,
                AVG(e.hedge_ratio) as hedge_ratio,
                AVG(e.assertion_ratio) as assertion_ratio,
                AVG(e.pause_markers) as pause_markers,
                AVG(e.self_ref_count) as self_ref,
                AVG(e.char_length) as char_length,
                AVG(e.question_count) as question_count,
                AVG(e.sentence_count) as sentence_count
            FROM expression_observations e
            JOIN conversation_skeletons s ON e.turn_id = s.turn_id
            WHERE s.session_id {thread_filter}
        """).fetchone()

        n = row["n"] if row and row["n"] else 0
        if n > 0:
            for key in ("hedge_ratio", "assertion_ratio", "pause_markers",
                        "self_ref", "char_length", "question_count", "sentence_count"):
                val = row[key] if row[key] is not None else 0.0
                baselines.append(KnotBaseline(
                    baseline_version=version, regime=regime,
                    effect_key=key, value=float(val),
                    sample_count=n, created_at=now,
                ))

        # --- Skeleton-based effects ---
        skeleton_rows = conn.execute(f"""
            SELECT response_intent, COUNT(*) as cnt
            FROM conversation_skeletons
            WHERE session_id {thread_filter}
            GROUP BY response_intent
        """).fetchall()
        total = sum(r["cnt"] for r in skeleton_rows)
        if total > 0:
            intent_rates: dict[str, float] = {}
            for r in skeleton_rows:
                intent_rates[r["response_intent"]] = r["cnt"] / total
            for intent_key in ("organize", "ask", "offer_fragile_self_observation", "receive"):
                baselines.append(KnotBaseline(
                    baseline_version=version, regime=regime,
                    effect_key=f"{intent_key}_rate", value=intent_rates.get(intent_key, 0.0),
                    sample_count=total, created_at=now,
                ))

        # --- Depth-based effects ---
        depth_rows = conn.execute(f"""
            SELECT rule_based_depth, COUNT(*) as cnt
            FROM niacore_experience n
            JOIN conversation_skeletons s ON n.turn_id = s.turn_id
            WHERE s.session_id {thread_filter}
            GROUP BY rule_based_depth
        """).fetchall()
        depth_total = sum(r["cnt"] for r in depth_rows)
        if depth_total > 0:
            for r in depth_rows:
                baselines.append(KnotBaseline(
                    baseline_version=version, regime=regime,
                    effect_key=f"depth_{r['rule_based_depth']}_rate",
                    value=r["cnt"] / depth_total,
                    sample_count=depth_total, created_at=now,
                ))

    if baselines:
        save_baseline_snapshot(conn, baselines)
        logger.info("[KNOT_BASELINE] Saved %d entries, version=%s", len(baselines), version)
    else:
        logger.warning("[KNOT_BASELINE] No data to compute baselines")

    return version


# ── Response Knot Extractor ───────────────────────────────────────────


_RK1_ID = "rk1_low_confidence_compression"
_RK2_ID = "rk2_organize_priority"


def extract_response_knots(conn: sqlite3.Connection, baseline_version: str) -> int:
    """Extract RK-1 (uncertainty_softening) and RK-2 (organize_priority).

    Returns number of knots upserted.
    """
    count = 0
    try:
        count += _extract_rk1(conn, baseline_version)
    except Exception:
        logger.exception("[KNOT_EXTRACT] RK-1 failed")
    try:
        count += _extract_rk2(conn, baseline_version)
    except Exception:
        logger.exception("[KNOT_EXTRACT] RK-2 failed")
    return count


def _extract_rk1(conn: sqlite3.Connection, bv: str) -> int:
    """RK-1: low_confidence_compression_knot.
    trigger: low confidence proxy (depth0 selection)
    effect: assertion↑, pause↓, hedge↓ vs baseline — short, direct, compressed
    Note: Step 0 predicted hedge↑ but real data shows the opposite.
    """
    now = _now_iso()

    # Compute per-regime effect deltas
    for regime in ("default", "meeting"):
        thread_filter = (
            "NOT LIKE 'nero_meeting%'" if regime == "default" else "LIKE 'nero_meeting%'"
        )

        # Get baseline values
        baseline_row = conn.execute(
            "SELECT effect_key, value FROM knot_baselines WHERE baseline_version = ? AND regime = ?",
            (bv, regime),
        ).fetchall()
        baseline = {r["effect_key"]: r["value"] for r in baseline_row}
        if not baseline:
            continue

        # High uncertainty proxy: depth0 turns (lowest confidence selection)
        row = conn.execute(f"""
            SELECT COUNT(*) as n,
                   AVG(e.hedge_ratio) as hedge,
                   AVG(e.assertion_ratio) as assert_r,
                   AVG(e.pause_markers) as pause
            FROM expression_observations e
            JOIN conversation_skeletons s ON e.turn_id = s.turn_id
            WHERE s.session_id {thread_filter}
              AND e.selected_depth = 0
        """).fetchone()

        if not row or row["n"] < 3:
            continue

        effect = {
            "hedge_ratio": (row["hedge"] or 0) - baseline.get("hedge_ratio", 0),
            "assertion_ratio": (row["assert_r"] or 0) - baseline.get("assertion_ratio", 0),
            "pause_markers": (row["pause"] or 0) - baseline.get("pause_markers", 0),
        }

        # Record activation for each matching turn
        turn_ids = conn.execute(f"""
            SELECT e.turn_id FROM expression_observations e
            JOIN conversation_skeletons s ON e.turn_id = s.turn_id
            WHERE s.session_id {thread_filter} AND e.selected_depth = 0
        """).fetchall()

        for t in turn_ids:
            _save_activation_if_new(conn, KnotActivation(
                activation_id=f"act_{_uid()}",
                knot_id=_RK1_ID,
                turn_id=t["turn_id"],
                thread_id=regime,
                interaction_regime=regime,
                baseline_version=bv,
                trigger_values={"confidence": "low"},
                effect_values=effect,
                activated_at=now,
            ))

    # Compute distinct counts from activations
    stats = _compute_knot_stats(conn, _RK1_ID, bv)

    existing = get_knot(conn, _RK1_ID)
    if existing:
        existing.activation_count = stats["activation_count"]
        existing.distinct_day_count = stats["distinct_day_count"]
        existing.distinct_thread_count = stats["distinct_thread_count"]
        existing.distinct_regime_count = stats["distinct_regime_count"]
        existing.day_span = stats["day_span"]
        existing.effect_signature = stats.get("avg_effect", existing.effect_signature)
        existing.current_baseline_version = bv
        existing.last_activated_at = now
        existing.updated_at = now
        save_knot(conn, existing)
    else:
        knot = MetabolicKnot(
            knot_id=_RK1_ID,
            knot_type=KnotType.RESPONSE,
            trigger_signature={"confidence": "low"},
            effect_signature=stats.get("avg_effect", {}),
            activation_count=stats["activation_count"],
            distinct_day_count=stats["distinct_day_count"],
            distinct_thread_count=stats["distinct_thread_count"],
            distinct_regime_count=stats["distinct_regime_count"],
            day_span=stats["day_span"],
            current_baseline_version=bv,
            first_seen_at=now,
            last_activated_at=now,
            created_at=now,
            updated_at=now,
        )
        save_knot(conn, knot)

    logger.info("[KNOT_EXTRACT] RK-1 upserted: activations=%d", stats["activation_count"])
    return 1


def _extract_rk2(conn: sqlite3.Connection, bv: str) -> int:
    """RK-2: organize_priority_knot.
    trigger: focus=user_goal or contradiction
    effect: organize_rate↑ vs baseline
    """
    now = _now_iso()

    for regime in ("default", "meeting"):
        thread_filter = (
            "NOT LIKE 'nero_meeting%'" if regime == "default" else "LIKE 'nero_meeting%'"
        )

        baseline_row = conn.execute(
            "SELECT effect_key, value FROM knot_baselines WHERE baseline_version = ? AND regime = ?",
            (bv, regime),
        ).fetchall()
        baseline = {r["effect_key"]: r["value"] for r in baseline_row}
        if not baseline:
            continue

        # When focus is user_goal or contradiction, what's the intent distribution?
        rows = conn.execute(f"""
            SELECT response_intent, COUNT(*) as cnt
            FROM conversation_skeletons
            WHERE session_id {thread_filter}
              AND focus IN ('user_goal', 'contradiction')
            GROUP BY response_intent
        """).fetchall()
        total = sum(r["cnt"] for r in rows)
        if total < 5:
            continue

        intent_rates = {r["response_intent"]: r["cnt"] / total for r in rows}
        effect = {
            "organize_rate": intent_rates.get("organize", 0) - baseline.get("organize_rate", 0),
            "ask_rate": intent_rates.get("ask", 0) - baseline.get("ask_rate", 0),
        }

        # Record activations
        turn_ids = conn.execute(f"""
            SELECT turn_id FROM conversation_skeletons
            WHERE session_id {thread_filter}
              AND focus IN ('user_goal', 'contradiction')
        """).fetchall()

        for t in turn_ids:
            _save_activation_if_new(conn, KnotActivation(
                activation_id=f"act_{_uid()}",
                knot_id=_RK2_ID,
                turn_id=t["turn_id"],
                thread_id=regime,
                interaction_regime=regime,
                baseline_version=bv,
                trigger_values={"focus": "user_goal|contradiction"},
                effect_values=effect,
                activated_at=now,
            ))

    stats = _compute_knot_stats(conn, _RK2_ID, bv)

    existing = get_knot(conn, _RK2_ID)
    if existing:
        existing.activation_count = stats["activation_count"]
        existing.distinct_day_count = stats["distinct_day_count"]
        existing.distinct_thread_count = stats["distinct_thread_count"]
        existing.distinct_regime_count = stats["distinct_regime_count"]
        existing.day_span = stats["day_span"]
        existing.effect_signature = stats.get("avg_effect", existing.effect_signature)
        existing.current_baseline_version = bv
        existing.last_activated_at = now
        existing.updated_at = now
        save_knot(conn, existing)
    else:
        knot = MetabolicKnot(
            knot_id=_RK2_ID,
            knot_type=KnotType.RESPONSE,
            trigger_signature={"focus": ["user_goal", "contradiction"]},
            effect_signature=stats.get("avg_effect", {}),
            activation_count=stats["activation_count"],
            distinct_day_count=stats["distinct_day_count"],
            distinct_thread_count=stats["distinct_thread_count"],
            distinct_regime_count=stats["distinct_regime_count"],
            day_span=stats["day_span"],
            current_baseline_version=bv,
            first_seen_at=now,
            last_activated_at=now,
            created_at=now,
            updated_at=now,
        )
        save_knot(conn, knot)

    logger.info("[KNOT_EXTRACT] RK-2 upserted: activations=%d", stats["activation_count"])
    return 1


# ── Relational Knot Extractor ─────────────────────────────────────────


_LK_MACRO_ID = "lk_meeting_inward_softening"


def extract_relational_knots(conn: sqlite3.Connection, baseline_version: str) -> int:
    """Extract LK-macro: meeting_inward_softening_knot.

    Compares meeting vs default on multiple effect dimensions.
    """
    now = _now_iso()

    # Get default baseline as reference
    default_bl = conn.execute(
        "SELECT effect_key, value FROM knot_baselines WHERE baseline_version = ? AND regime = 'default'",
        (baseline_version,),
    ).fetchall()
    default_baseline = {r["effect_key"]: r["value"] for r in default_bl}

    meeting_bl = conn.execute(
        "SELECT effect_key, value FROM knot_baselines WHERE baseline_version = ? AND regime = 'meeting'",
        (baseline_version,),
    ).fetchall()
    meeting_baseline = {r["effect_key"]: r["value"] for r in meeting_bl}

    if not default_baseline or not meeting_baseline:
        logger.warning("[KNOT_EXTRACT] LK-macro: missing baseline for default or meeting")
        return 0

    # Effect = meeting_value - default_value (how meeting shifts relative to default)
    effect: dict[str, float] = {}
    for key in ("hedge_ratio", "assertion_ratio", "self_ref",
                "organize_rate", "offer_fragile_self_observation_rate", "ask_rate"):
        m_val = meeting_baseline.get(key, 0.0)
        d_val = default_baseline.get(key, 0.0)
        delta = m_val - d_val
        if abs(delta) > 0.001:
            effect[key] = round(delta, 4)

    if not effect:
        logger.info("[KNOT_EXTRACT] LK-macro: no significant regime difference")
        return 0

    # Record activations for all meeting turns
    meeting_turns = conn.execute("""
        SELECT turn_id FROM conversation_skeletons
        WHERE session_id LIKE 'nero_meeting%'
    """).fetchall()

    for t in meeting_turns:
        save_activation(conn, KnotActivation(
            activation_id=f"act_{_uid()}",
            knot_id=_LK_MACRO_ID,
            turn_id=t["turn_id"],
            thread_id="meeting",
            interaction_regime="meeting",
            baseline_version=baseline_version,
            trigger_values={"interaction_regime": "meeting"},
            effect_values=effect,
            activated_at=now,
        ))

    stats = _compute_knot_stats(conn, _LK_MACRO_ID, baseline_version)

    existing = get_knot(conn, _LK_MACRO_ID)
    if existing:
        existing.activation_count = stats["activation_count"]
        existing.distinct_day_count = stats["distinct_day_count"]
        existing.distinct_thread_count = stats["distinct_thread_count"]
        existing.distinct_regime_count = stats["distinct_regime_count"]
        existing.day_span = stats["day_span"]
        existing.effect_signature = effect
        existing.current_baseline_version = baseline_version
        existing.last_activated_at = now
        existing.updated_at = now
        save_knot(conn, existing)
    else:
        knot = MetabolicKnot(
            knot_id=_LK_MACRO_ID,
            knot_type=KnotType.RELATIONAL,
            trigger_signature={"interaction_regime": "meeting"},
            effect_signature=effect,
            activation_count=stats["activation_count"],
            distinct_day_count=stats["distinct_day_count"],
            distinct_thread_count=stats["distinct_thread_count"],
            distinct_regime_count=stats["distinct_regime_count"],
            day_span=stats["day_span"],
            current_baseline_version=baseline_version,
            first_seen_at=now,
            last_activated_at=now,
            created_at=now,
            updated_at=now,
        )
        save_knot(conn, knot)

    logger.info("[KNOT_EXTRACT] LK-macro upserted: activations=%d effects=%s",
                stats["activation_count"], list(effect.keys()))
    return 1


# ── Self-Boundary Knot Extractor ──────────────────────────────────────


_SK2_ID = "sk2_correction_resilience"


def extract_self_boundary_knots(conn: sqlite3.Connection, baseline_version: str) -> int:
    """Extract SK-2: correction_resilience_knot.

    Measures whether depth distribution stays stable after user_correction.
    """
    now = _now_iso()

    # Baseline depth distribution (all turns)
    all_depths = conn.execute("""
        SELECT rule_based_depth, COUNT(*) as cnt
        FROM niacore_experience
        GROUP BY rule_based_depth
    """).fetchall()
    all_total = sum(r["cnt"] for r in all_depths)
    if all_total < 10:
        return 0

    baseline_dist = {r["rule_based_depth"]: r["cnt"] / all_total for r in all_depths}

    # Post-correction depth distribution
    corr_depths = conn.execute("""
        SELECT rule_based_depth, COUNT(*) as cnt
        FROM niacore_experience
        WHERE user_correction = 1
        GROUP BY rule_based_depth
    """).fetchall()
    corr_total = sum(r["cnt"] for r in corr_depths)
    if corr_total < 5:
        logger.info("[KNOT_EXTRACT] SK-2: too few correction turns (%d)", corr_total)
        return 0

    corr_dist = {r["rule_based_depth"]: r["cnt"] / corr_total for r in corr_depths}

    # Effect = how much the distribution shifts after correction
    effect: dict[str, float] = {}
    for depth_key in baseline_dist:
        delta = corr_dist.get(depth_key, 0.0) - baseline_dist[depth_key]
        effect[f"depth_{depth_key}_delta"] = round(delta, 4)

    # Overall stability metric: sum of absolute deltas (lower = more resilient)
    total_drift = sum(abs(v) for v in effect.values())
    effect["total_drift"] = round(total_drift, 4)
    effect["resilience"] = round(1.0 - min(total_drift, 1.0), 4)

    # Record activations for correction turns
    corr_turns = conn.execute("""
        SELECT turn_id FROM niacore_experience WHERE user_correction = 1
    """).fetchall()

    for t in corr_turns:
        save_activation(conn, KnotActivation(
            activation_id=f"act_{_uid()}",
            knot_id=_SK2_ID,
            turn_id=t["turn_id"],
            thread_id="all",
            interaction_regime="all",
            baseline_version=baseline_version,
            trigger_values={"user_correction": True},
            effect_values=effect,
            activated_at=now,
        ))

    stats = _compute_knot_stats(conn, _SK2_ID, baseline_version)

    existing = get_knot(conn, _SK2_ID)
    if existing:
        existing.activation_count = stats["activation_count"]
        existing.distinct_day_count = stats["distinct_day_count"]
        existing.distinct_thread_count = stats["distinct_thread_count"]
        existing.distinct_regime_count = stats["distinct_regime_count"]
        existing.day_span = stats["day_span"]
        existing.effect_signature = effect
        existing.current_baseline_version = baseline_version
        existing.last_activated_at = now
        existing.updated_at = now
        save_knot(conn, existing)
    else:
        knot = MetabolicKnot(
            knot_id=_SK2_ID,
            knot_type=KnotType.SELF_BOUNDARY,
            trigger_signature={"user_correction": True},
            effect_signature=effect,
            activation_count=stats["activation_count"],
            distinct_day_count=stats["distinct_day_count"],
            distinct_thread_count=stats["distinct_thread_count"],
            distinct_regime_count=stats["distinct_regime_count"],
            day_span=stats["day_span"],
            current_baseline_version=baseline_version,
            first_seen_at=now,
            last_activated_at=now,
            created_at=now,
            updated_at=now,
        )
        save_knot(conn, knot)

    logger.info("[KNOT_EXTRACT] SK-2 upserted: activations=%d resilience=%.3f",
                stats["activation_count"], effect.get("resilience", 0))
    return 1


# ── Shared Helpers ────────────────────────────────────────────────────


def _activation_exists(conn: sqlite3.Connection, knot_id: str, turn_id: str) -> bool:
    """Check if an activation already exists for this knot + turn pair."""
    row = conn.execute(
        "SELECT 1 FROM knot_activations WHERE knot_id = ? AND turn_id = ? LIMIT 1",
        (knot_id, turn_id),
    ).fetchone()
    return row is not None


def _save_activation_if_new(conn: sqlite3.Connection, act: KnotActivation) -> bool:
    """Save activation only if this knot+turn pair doesn't already exist.

    Returns True if saved, False if skipped (duplicate).
    """
    if _activation_exists(conn, act.knot_id, act.turn_id):
        return False
    save_activation(conn, act)
    return True


def _compute_knot_stats(conn: sqlite3.Connection, knot_id: str, baseline_version: str = "") -> dict:
    """Compute activation statistics for a knot from knot_activations.

    Args:
        baseline_version: if provided, average effects only from activations
                          matching this baseline_version (6b.1 invariant).
    """
    row = conn.execute("""
        SELECT
            COUNT(DISTINCT turn_id) as activation_count,
            COUNT(DISTINCT DATE(activated_at)) as distinct_day_count,
            COUNT(DISTINCT thread_id) as distinct_thread_count,
            COUNT(DISTINCT interaction_regime) as distinct_regime_count,
            CAST(julianday(MAX(activated_at)) - julianday(MIN(activated_at)) AS INTEGER) as day_span
        FROM knot_activations
        WHERE knot_id = ?
    """, (knot_id,)).fetchone()

    stats = {
        "activation_count": row["activation_count"] if row else 0,
        "distinct_day_count": row["distinct_day_count"] if row else 0,
        "distinct_thread_count": row["distinct_thread_count"] if row else 0,
        "distinct_regime_count": row["distinct_regime_count"] if row else 0,
        "day_span": max(row["day_span"] or 0, 0) if row else 0,
    }

    # Compute average effect — only from activations matching the current baseline
    # (6b.1 invariant: do not average effects across different baselines)
    bv_filter = "AND baseline_version = ?" if baseline_version else ""
    bv_params = (knot_id, baseline_version) if baseline_version else (knot_id,)
    effect_rows = conn.execute(
        f"SELECT effect_values FROM knot_activations WHERE knot_id = ? {bv_filter}",
        bv_params,
    ).fetchall()
    if effect_rows:
        all_effects: dict[str, list[float]] = {}
        for r in effect_rows:
            ev = json.loads(r["effect_values"])
            for k, v in ev.items():
                all_effects.setdefault(k, []).append(v)
        stats["avg_effect"] = {k: round(sum(vs) / len(vs), 4) for k, vs in all_effects.items()}

    return stats


# ── Orchestrator ──────────────────────────────────────────────────────


def run_knot_distillation(conn: sqlite3.Connection) -> dict:
    """Run all knot extractors. Called from Sleep Cycle Phase 4.5.

    Returns summary dict for logging.
    """
    result = {"baseline_version": "", "knots_upserted": 0, "errors": []}

    try:
        bv = compute_and_save_baselines(conn)
        result["baseline_version"] = bv
    except Exception as e:
        logger.exception("[KNOT_DISTILL] Baseline computation failed")
        result["errors"].append(f"baseline: {e}")
        return result

    for name, func in [
        ("response", extract_response_knots),
        ("relational", extract_relational_knots),
        ("self_boundary", extract_self_boundary_knots),
    ]:
        try:
            n = func(conn, bv)
            result["knots_upserted"] += n
        except Exception as e:
            logger.exception("[KNOT_DISTILL] %s extractor failed", name)
            result["errors"].append(f"{name}: {e}")

    logger.info(
        "[KNOT_DISTILL] Complete: baseline=%s knots=%d errors=%d",
        result["baseline_version"], result["knots_upserted"], len(result["errors"]),
    )
    return result
