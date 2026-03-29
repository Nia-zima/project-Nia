"""
Pip State — data models for Pip the mechanical dog.

Design doc: docs/pip_and_room_design.md
Phase P.1: Pure data structures, no LLM calls.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class PipState:
    """Core state of Pip. Single Bond variable drives all behavior."""

    bond: float = 0.0               # -1.0 ~ 1.0 (initial: neutral)
    mood: str = "idle"              # Current mood (state machine output)
    energy: float = 1.0             # 0.0 ~ 1.0 (decreases when awake...)
    position: str = "center"        # Position in room
    animation: str = "idle"         # Current animation
    favorite_spot: str = ""         # Favorite spot (forms when Bond >= 0.4)
    last_interaction: float = 0.0   # Epoch: last time Nia interacted with Pip
    scrap_count: int = 0            # Phase A: number of scraps for visual fill
    current_scrap_id: str = ""      # Phase A: currently held scrap ID


@dataclass
class NiaContext:
    """Context about Nia's recent behavior relevant to Pip."""

    called_pip: bool = False        # Nia called Pip's name
    mentioned_pip: bool = False     # Nia mentioned/referred to Pip
    drew_pip: bool = False          # Nia drew Pip
    placed_near_pip: bool = False   # Nia placed an object near Pip
    is_talking: bool = False        # Nia is currently in a conversation
    emotional_state: str = "neutral"  # Nia's inferred emotional state


# ── Bond Rules ────────────────────────────────────────────────


BOND_RULES: dict[str, float] = {
    # Nia's actions -> Bond delta
    "nia_calls_name":      +0.02,
    "nia_talks_to_pip":    +0.03,
    "nia_draws_pip":       +0.05,
    "nia_places_near_pip": +0.01,

    # Time decay
    "decay_per_hour":      -0.005,
    "decay_cap":            0.0,     # Bond does not naturally decay below 0.0

    # Special events
    "nia_ignores_long":    -0.01,    # 12h+ of no interaction (added to decay)
    "nia_room_change":     -0.008,   # Nia rearranged the room (Pip is confused)
}


BOND_MIN = -1.0
BOND_MAX = 1.0


def clamp_bond(value: float) -> float:
    """Clamp bond to valid range [-1.0, 1.0]."""
    return max(BOND_MIN, min(BOND_MAX, value))


def apply_bond_delta(pip: PipState, delta: float) -> float:
    """Apply a bond change and return the new clamped value."""
    pip.bond = clamp_bond(pip.bond + delta)
    return pip.bond


def apply_interaction_bond(pip: PipState, ctx: NiaContext) -> float:
    """Apply bond changes based on Nia's interaction context.

    Returns total bond delta applied.
    """
    total_delta = 0.0

    if ctx.drew_pip:
        total_delta += BOND_RULES["nia_draws_pip"]
    if ctx.called_pip:
        total_delta += BOND_RULES["nia_calls_name"]
    elif ctx.mentioned_pip:
        # mentioned but not called by name → same as talked_to but weaker
        total_delta += BOND_RULES["nia_calls_name"] * 0.5
    if ctx.placed_near_pip:
        total_delta += BOND_RULES["nia_places_near_pip"]

    if total_delta > 0:
        apply_bond_delta(pip, total_delta)
        pip.last_interaction = time.time()

    return total_delta


def dict_to_pip(d: dict) -> PipState:
    """Convert a dict (from JSON storage) to PipState."""
    return PipState(
        bond=d.get("bond", 0.0),
        mood=d.get("mood", "idle"),
        energy=d.get("energy", 1.0),
        position=d.get("position", "center"),
        animation=d.get("animation", "idle"),
        favorite_spot=d.get("favorite_spot", ""),
        last_interaction=d.get("last_interaction", 0.0),
        scrap_count=d.get("scrap_count", 0),
        current_scrap_id=d.get("current_scrap_id", ""),
    )


def pip_to_dict(pip: PipState) -> dict:
    """Convert PipState to a JSON-serializable dict."""
    return {
        "bond": round(pip.bond, 4),
        "mood": pip.mood,
        "energy": round(pip.energy, 4),
        "position": pip.position,
        "animation": pip.animation,
        "favorite_spot": pip.favorite_spot,
        "last_interaction": pip.last_interaction,
        "scrap_count": pip.scrap_count,
        "current_scrap_id": pip.current_scrap_id,
    }


def apply_time_decay(pip: PipState, hours_since_interaction: float) -> float:
    """Apply natural Bond decay based on time since last interaction.

    Bond does not decay below decay_cap (0.0) through natural decay.
    Returns the delta applied.
    """
    if hours_since_interaction <= 0 or pip.bond <= BOND_RULES["decay_cap"]:
        return 0.0

    decay = BOND_RULES["decay_per_hour"] * hours_since_interaction

    # Extra penalty for long ignore (12h+)
    if hours_since_interaction >= 12:
        decay += BOND_RULES["nia_ignores_long"]

    # Don't decay below the cap
    new_bond = max(BOND_RULES["decay_cap"], pip.bond + decay)
    delta = new_bond - pip.bond
    pip.bond = new_bond
    return delta
