"""Abstract base class for game profiles."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class GameProfile(ABC):
    """Abstract base for game integrations."""

    @property
    @abstractmethod
    def game_id(self) -> str:
        """Unique game identifier (e.g. 'minecraft')."""
        ...

    @property
    @abstractmethod
    def game_name(self) -> str:
        """Human-readable game name."""
        ...

    @abstractmethod
    async def get_state(self) -> dict[str, Any]:
        """Get current game state snapshot."""
        ...

    @abstractmethod
    async def execute_action(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Execute a game action."""
        ...

    @abstractmethod
    async def is_connected(self) -> bool:
        """Check if the game bot is connected."""
        ...

    @abstractmethod
    def format_state_for_llm(self, state: dict[str, Any], depth: int) -> str:
        """Format game state for LLM system prompt injection."""
        ...

    @abstractmethod
    def get_available_actions(self) -> list[dict[str, str]]:
        """Return list of available game actions with descriptions."""
        ...
