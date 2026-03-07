"""
Pip State Machine — rule-based mood/animation transitions.

Design doc: docs/pip_and_room_design.md §2.3
Phase P.1: 6 base states, no LLM calls.
"""
from __future__ import annotations

import random

from backend.services.pip.pip_state import PipState, NiaContext


# ── State constants ───────────────────────────────────────────

IDLE = "idle"
CURIOUS = "curious"
PLAYFUL = "playful"
SLEEPY = "sleepy"
SLEEPING = "sleeping"
ALERT = "alert"

# Unlocked at Bond >= 0.7 (Phase P.4)
COMFORT = "comfort"
EMPATHY = "empathy"

BASE_STATES = {IDLE, CURIOUS, PLAYFUL, SLEEPY, SLEEPING, ALERT}
HIGH_BOND_STATES = {COMFORT, EMPATHY}
ALL_STATES = BASE_STATES | HIGH_BOND_STATES

# Energy thresholds
ENERGY_SLEEPY = 0.2
ENERGY_SLEEP = 0.1
ENERGY_WAKE = 0.8

# Energy rates (per update, ~1 min interval)
ENERGY_RECOVERY_RATE = 0.01    # sleeping -> energy gain
ENERGY_DRAIN_RATE = 0.002      # awake -> energy drain
ENERGY_NIGHT_DRAIN_BONUS = 0.001  # extra drain at night


class PipStateMachine:
    """Determine Pip's next state based on current state, energy, bond, and Nia context.

    Called once per minute by room_update_loop (Phase P.2).
    In P.1, can be called manually for testing.
    """

    def update(
        self,
        pip: PipState,
        nia_context: NiaContext | None = None,
        *,
        is_night: bool = False,
    ) -> PipState:
        """Compute next state and return the updated PipState.

        Args:
            pip: Current Pip state (mutated in place and returned).
            nia_context: Context about Nia's recent behavior. None = no interaction.
            is_night: Whether it's currently nighttime (affects energy drain).
        """
        if nia_context is None:
            nia_context = NiaContext()

        # --- Energy management ---
        if pip.mood == SLEEPING:
            pip.energy = min(1.0, pip.energy + ENERGY_RECOVERY_RATE)
        else:
            drain = ENERGY_DRAIN_RATE
            if is_night:
                drain += ENERGY_NIGHT_DRAIN_BONUS
            pip.energy = max(0.0, pip.energy - drain)

        # --- State transitions (priority order) ---
        new_mood, new_anim, new_pos = self._decide(pip, nia_context)

        pip.mood = new_mood
        pip.animation = new_anim
        if new_pos:
            pip.position = new_pos

        return pip

    def _decide(
        self,
        pip: PipState,
        ctx: NiaContext,
    ) -> tuple[str, str, str]:
        """Return (mood, animation, position) based on priority rules.

        Position is empty string if unchanged.
        """
        # 1. Sleep lifecycle
        if pip.mood == SLEEPING:
            if pip.energy >= ENERGY_WAKE or ctx.called_pip:
                return ALERT, "wake_up", ""
            return SLEEPING, "sleeping", ""

        if pip.mood == SLEEPY and pip.energy < ENERGY_SLEEP:
            sleep_pos = pip.favorite_spot or "corner"
            return SLEEPING, "sleeping", sleep_pos

        if pip.energy < ENERGY_SLEEPY and pip.mood not in (SLEEPING, SLEEPY):
            return SLEEPY, "yawn", ""

        # 2. Bond >= 0.7 high-trust states (P.4 preview — already in state machine)
        if pip.bond >= 0.7:
            if ctx.emotional_state == "low":
                return EMPATHY, "lean_against", "next_to_nia"
            if ctx.is_talking:
                return COMFORT, "snuggle", "next_to_nia"

        # 3. Nia interaction responses
        if ctx.called_pip and pip.bond >= 0.1:
            return CURIOUS, "head_tilt", "near_nia"

        if ctx.is_talking and pip.bond >= 0.1:
            return CURIOUS, "head_tilt", "near_nia"

        # 4. Alert -> transition back
        if pip.mood == ALERT:
            if pip.energy > 0.5:
                return CURIOUS, "head_tilt", ""
            return IDLE, "idle", ""

        # 5. Playful (enough energy + moderate bond)
        if pip.energy > 0.5 and pip.bond >= 0.4:
            anim = random.choice(["tail_wag", "spin", "look_around"])
            return PLAYFUL, anim, ""

        # 6. Default idle
        return IDLE, "idle", ""


# Singleton for convenience
pip_state_machine = PipStateMachine()
