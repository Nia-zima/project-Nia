"""Minecraft game profile implementation."""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

from backend.services.game_profiles.base import GameProfile

if TYPE_CHECKING:
    from backend.services.minecraft.client import MinecraftBotClient
    from backend.services.minecraft.state_manager import MinecraftStateManager


class MinecraftProfile(GameProfile):
    """Minecraft game profile using Mineflayer bot."""

    def __init__(self, client: "MinecraftBotClient", state_manager: "MinecraftStateManager"):
        self._client = client
        self._state_manager = state_manager

    @property
    def game_id(self) -> str:
        return "minecraft"

    @property
    def game_name(self) -> str:
        return "Minecraft"

    async def get_state(self) -> dict[str, Any]:
        return await self._client.get_state()

    async def execute_action(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        return await self._client.execute_action(action, params)

    async def is_connected(self) -> bool:
        return await self._client.is_connected()

    def format_state_for_llm(self, state: dict[str, Any], depth: int) -> str:
        # Delegate to state_manager's synchronous formatting logic
        # (state_manager.format_for_llm is async, but profile needs sync)
        # This is used by the registry for profile listing, not for actual injection
        if not state.get("connected"):
            return ""
        pos = state.get("position", {})
        return f"Minecraft | Pos: ({pos.get('x', 0)}, {pos.get('y', 0)}, {pos.get('z', 0)}) | HP: {state.get('health', 20)}/20"

    def get_available_actions(self) -> list[dict[str, str]]:
        return [
            {"id": "mc_chat", "name": "ゲーム内チャット", "risk": "safe"},
            {"id": "mc_move", "name": "移動", "risk": "safe"},
            {"id": "mc_mine", "name": "ブロック採掘", "risk": "low"},
            {"id": "mc_place", "name": "ブロック設置", "risk": "low"},
            {"id": "mc_craft", "name": "クラフト", "risk": "low"},
            {"id": "mc_attack", "name": "攻撃", "risk": "medium"},
        ]
