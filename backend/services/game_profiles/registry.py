"""Game profile registry for managing multiple game integrations."""
from __future__ import annotations

import logging
from typing import Optional

from backend.services.game_profiles.base import GameProfile

logger = logging.getLogger(__name__)


class GameProfileRegistry:
    """Registry of available game profiles."""

    def __init__(self):
        self._profiles: dict[str, GameProfile] = {}
        self._active: Optional[str] = None

    def register(self, profile: GameProfile) -> None:
        """Register a game profile."""
        self._profiles[profile.game_id] = profile
        logger.info("[GAME_PROFILE] Registered: %s (%s)", profile.game_id, profile.game_name)

    def get(self, game_id: str) -> Optional[GameProfile]:
        """Get a profile by ID."""
        return self._profiles.get(game_id)

    def get_active(self) -> Optional[GameProfile]:
        """Get the currently active profile."""
        if self._active:
            return self._profiles.get(self._active)
        return None

    def set_active(self, game_id: str) -> bool:
        """Set the active game profile."""
        if game_id not in self._profiles:
            logger.warning("[GAME_PROFILE] Unknown profile: %s", game_id)
            return False
        self._active = game_id
        logger.info("[GAME_PROFILE] Active: %s", game_id)
        return True

    def clear_active(self) -> None:
        """Clear the active profile."""
        self._active = None

    def list_profiles(self) -> list[dict]:
        """List all registered profiles."""
        return [
            {
                "game_id": p.game_id,
                "game_name": p.game_name,
                "active": p.game_id == self._active,
            }
            for p in self._profiles.values()
        ]


# Global instance
game_profile_registry = GameProfileRegistry()
