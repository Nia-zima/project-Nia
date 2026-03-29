"""Protection Score calculation and Hardness level transitions.

Design:
    - 4 signals: reproducibility, damage_sensitivity, redundancy, temporal_stability
    - Type-specific weight profiles:
        response_knot: cross-regime reproducibility is key
        relational_knot: within-regime contrast matters more
        self_boundary_knot: episode consistency (recovery) is key
    - Protection Score P = weighted combination of signals
    - Hardness transitions: L0→L1→L2→L3, with softening in reverse
    - Minimum gate conditions prevent single-axis hardening
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from backend.services.identity.schema import KnotType, MetabolicKnot


# ── Signal Computation ────────────────────────────────────────────────


@dataclass
class KnotSignals:
    """Computed signals for a single knot."""
    reproducibility: float
    damage_sensitivity: float
    redundancy: float
    temporal_stability: float


def compute_signals(knot: MetabolicKnot, *, sibling_count: int = 0) -> KnotSignals:
    """Compute 4 signals from knot activation statistics.

    Args:
        knot: The knot to evaluate
        sibling_count: Number of sibling knots (for redundancy)
    """
    return KnotSignals(
        reproducibility=_compute_reproducibility(knot),
        damage_sensitivity=_compute_damage_sensitivity(knot),
        redundancy=_compute_redundancy(knot, sibling_count),
        temporal_stability=_compute_temporal_stability(knot),
    )


def _compute_reproducibility(knot: MetabolicKnot) -> float:
    """How consistently this knot activates across different contexts.

    Type-specific:
        response: distinct_regime_count is heavily weighted
        relational: distinct_thread_count within the regime matters
        self_boundary: distinct_day_count (episode recurrence) matters most
    """
    day = min(knot.distinct_day_count / 7.0, 1.0)   # saturate at 7 days
    thread = min(knot.distinct_thread_count / 5.0, 1.0)  # saturate at 5 threads
    regime = min(knot.distinct_regime_count / 2.0, 1.0)   # saturate at 2 regimes
    activation_floor = min(knot.activation_count / 20.0, 1.0)  # need at least 20

    if knot.knot_type == KnotType.RESPONSE:
        # Cross-regime is king for response knots
        return activation_floor * (0.20 * day + 0.20 * thread + 0.60 * regime)
    elif knot.knot_type == KnotType.RELATIONAL:
        # Relational knots are regime-specific by nature.
        # R = within-regime recurrence (threads × days) + regime contrast bonus.
        # Having only 1 regime is expected, not penalized.
        within_regime = 0.40 * day + 0.60 * thread
        # Bonus: relational knots are regime-specific by design.
        # Having exactly 1 regime is expected and should still get the bonus.
        # v0 proxy: distinct_regime_count >= 1 (raw count, not normalized).
        # Real contrast calculation requires cross-regime effect comparison (v1).
        contrast_bonus = 0.15 if knot.distinct_regime_count >= 1 else 0.0
        return activation_floor * min(within_regime + contrast_bonus, 1.0)
    else:  # SELF_BOUNDARY
        # Episode recurrence across days is what matters
        return activation_floor * (0.60 * day + 0.25 * thread + 0.15 * regime)


def _compute_damage_sensitivity(knot: MetabolicKnot) -> float:
    """How much removing this knot would destabilize the system.

    v0 approximation: based on activation density + effect magnitude + coupling.
    True damage propagation (v1+) requires perturbation replay.
    """
    # Effect magnitude: sum of absolute effect values
    effect_mag = sum(abs(v) for v in knot.effect_signature.values())
    effect_score = min(effect_mag / 1.0, 1.0)  # saturate at total delta of 1.0

    # Coupling out-degree
    coupling_score = min(len(knot.coupled_knots) / 3.0, 1.0)

    # Activation density (activations per day_span)
    if knot.day_span > 0:
        density = knot.activation_count / knot.day_span
        density_score = min(density / 10.0, 1.0)
    else:
        density_score = 0.0

    # For self_boundary: resilience is itself a damage signal
    # High resilience = this boundary matters
    if knot.knot_type == KnotType.SELF_BOUNDARY:
        resilience = knot.effect_signature.get("resilience", 0.0)
        return 0.30 * effect_score + 0.20 * coupling_score + 0.20 * density_score + 0.30 * resilience
    else:
        return 0.40 * effect_score + 0.30 * coupling_score + 0.30 * density_score


def _compute_redundancy(knot: MetabolicKnot, sibling_count: int) -> float:
    """How replaceable this knot is by siblings.

    High redundancy = less important to protect (inverted in protection score).
    """
    if sibling_count == 0:
        return 0.0  # No siblings → irreplaceable
    # More siblings → more redundant, but cap at 0.8
    return min(sibling_count / 5.0, 0.8)


def _compute_temporal_stability(knot: MetabolicKnot) -> float:
    """How stable this knot has been over time.

    Based on day_span and consistency of activation.
    """
    if knot.day_span == 0:
        return 0.0

    # Longer span = more stable
    span_score = min(knot.day_span / 14.0, 1.0)  # saturate at 2 weeks

    # Consistency: activations should be spread, not clustered
    if knot.activation_count > 0 and knot.distinct_day_count > 0:
        spread = knot.distinct_day_count / max(knot.day_span, 1)
        spread_score = min(spread, 1.0)
    else:
        spread_score = 0.0

    return 0.60 * span_score + 0.40 * spread_score


# ── Protection Score ──────────────────────────────────────────────────


# Type-specific weight profiles
_WEIGHTS: dict[KnotType, dict[str, float]] = {
    KnotType.RESPONSE: {
        "wR": 0.25,   # cross-regime reproducibility is most important
        "wD": 0.25,
        "wN": 0.15,
        "wT": 0.20,
        "wRD": 0.10,
        "wDT": 0.05,
    },
    KnotType.RELATIONAL: {
        "wR": 0.15,   # within-regime, so reproducibility is less central
        "wD": 0.30,   # damage matters more — this defines a relationship
        "wN": 0.10,
        "wT": 0.25,   # stability over time is important for relationships
        "wRD": 0.10,
        "wDT": 0.10,
    },
    KnotType.SELF_BOUNDARY: {
        "wR": 0.15,   # episode recurrence
        "wD": 0.35,   # damage is the core concept of boundary
        "wN": 0.10,
        "wT": 0.20,
        "wRD": 0.10,
        "wDT": 0.10,
    },
}


def compute_protection_score(signals: KnotSignals, knot_type: KnotType) -> float:
    """Compute protection score with type-specific weights.

    P = wR·R + wD·D + wN·(1-N) + wT·T + wRD·(R×D) + wDT·(D×T)
    """
    w = _WEIGHTS[knot_type]
    R, D, N, T = signals.reproducibility, signals.damage_sensitivity, signals.redundancy, signals.temporal_stability

    score = (
        w["wR"] * R
        + w["wD"] * D
        + w["wN"] * (1.0 - N)
        + w["wT"] * T
        + w["wRD"] * (R * D)
        + w["wDT"] * (D * T)
    )
    return round(min(max(score, 0.0), 1.0), 4)


# ── Minimum Gate Conditions ───────────────────────────────────────────


_L2_MINIMUM_GATE: dict[str, float] = {
    "R": 0.45,
    "D": 0.50,
    "T": 0.40,
}


def passes_minimum_gate(signals: KnotSignals, target_level: int) -> bool:
    """Check if signals pass minimum conditions for a target hardness level.

    L0→L1: no gate (any score can stabilize)
    L1→L2: all three minimums must be met
    L2→L3: all three minimums must be met (same thresholds, but also needs long time)
    """
    if target_level < 2:
        return True
    return (
        signals.reproducibility >= _L2_MINIMUM_GATE["R"]
        and signals.damage_sensitivity >= _L2_MINIMUM_GATE["D"]
        and signals.temporal_stability >= _L2_MINIMUM_GATE["T"]
    )


# ── Hardness Transitions ─────────────────────────────────────────────


@dataclass
class TransitionResult:
    """Result of a hardness transition check."""
    old_level: int
    new_level: int
    changed: bool
    reason: str


def evaluate_transition(knot: MetabolicKnot, signals: KnotSignals) -> TransitionResult:
    """Evaluate whether a knot should change hardness level.

    Promotion thresholds:
        L0 → L1: P >= 0.45
        L1 → L2: P >= 0.65, minimum gate, multiple Sleeps
        L2 → L3: P >= 0.82, minimum gate, long-term stability

    Demotion thresholds:
        L1 → L0: P < 0.35
        L2 → L1: P < 0.55
        L3 → L2: P < 0.70

    self_boundary_knot with low episode_confidence cannot go above L1.
    """
    level = knot.hardness_level
    P = compute_protection_score(signals, knot.knot_type)

    # self_boundary confidence gate: low episode_confidence blocks L2+ promotion
    _boundary_capped = False
    if knot.knot_type == KnotType.SELF_BOUNDARY:
        ep_conf = knot.episode_confidence_avg
        if ep_conf is not None and ep_conf < 0.5:
            _boundary_capped = True  # cannot promote to L2+

    # Promotion checks
    if level == 0 and P >= 0.45:
        return TransitionResult(0, 1, True, f"L0→L1: P={P:.3f} >= 0.45")

    if level == 1 and P >= 0.65 and passes_minimum_gate(signals, 2) and not _boundary_capped:
        if knot.day_span >= 7:  # at least a week
            return TransitionResult(1, 2, True, f"L1→L2: P={P:.3f} >= 0.65, gate passed, span={knot.day_span}d")

    if level == 2 and P >= 0.82 and passes_minimum_gate(signals, 3) and not _boundary_capped:
        if knot.day_span >= 30:  # at least a month
            return TransitionResult(2, 3, True, f"L2→L3: P={P:.3f} >= 0.82, gate passed, span={knot.day_span}d")

    # Demotion checks
    if level == 1 and P < 0.35:
        return TransitionResult(1, 0, True, f"L1→L0: P={P:.3f} < 0.35")

    if level == 2 and P < 0.55:
        return TransitionResult(2, 1, True, f"L2→L1: P={P:.3f} < 0.55")

    if level == 3 and P < 0.70:
        return TransitionResult(3, 2, True, f"L3→L2: P={P:.3f} < 0.70")

    # No change
    return TransitionResult(level, level, False, f"no change: P={P:.3f}")


# ── Apply Transition ──────────────────────────────────────────────────


def apply_signals_and_transition(
    knot: MetabolicKnot, *, sibling_count: int = 0
) -> tuple[KnotSignals, TransitionResult]:
    """Compute signals, protection score, and hardness transition for a knot.

    Updates knot fields in-place (caller must save).
    Returns (signals, transition) for logging.
    """
    signals = compute_signals(knot, sibling_count=sibling_count)
    P = compute_protection_score(signals, knot.knot_type)
    transition = evaluate_transition(knot, signals)

    # Update knot fields
    knot.reproducibility = round(signals.reproducibility, 4)
    knot.damage_sensitivity = round(signals.damage_sensitivity, 4)
    knot.redundancy = round(signals.redundancy, 4)
    knot.temporal_stability = round(signals.temporal_stability, 4)
    knot.protection_score = P
    if transition.changed:
        knot.hardness_level = transition.new_level

    return signals, transition
