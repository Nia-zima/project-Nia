"""Game state management and LLM context formatting."""
from __future__ import annotations

import logging
from collections import deque
from typing import Any, TYPE_CHECKING

from backend.core.config import settings

if TYPE_CHECKING:
    from backend.services.minecraft.client import MinecraftBotClient

logger = logging.getLogger(__name__)


class MinecraftStateManager:
    """Manages game state for LLM context injection."""

    def __init__(self, client: "MinecraftBotClient"):
        self.client = client
        self._recent_events: deque[dict] = deque(maxlen=50)

    def record_event(self, event: dict) -> None:
        """Record an incoming game event."""
        self._recent_events.append(event)

    async def format_for_llm(self, depth: int = 0) -> str:
        """
        Format game state for LLM system prompt injection.

        depth0: minimal (position, health)
        depth1/2: full (inventory, nearby entities, recent events)
        """
        state = await self.client.get_state()
        if not state.get("connected"):
            return ""

        pos = state.get("position")
        if not pos:
            return ""

        lines = []

        # 基本情報 (全depth共通)
        pos_str = f"({pos.get('x', 0)}, {pos.get('y', 0)}, {pos.get('z', 0)})"
        biome = state.get("biome", "unknown")
        time_info = state.get("time", {})
        period = time_info.get("period", "unknown")
        rain = " (Rain)" if time_info.get("isRaining") else ""
        lines.append(f"Position: {pos_str} | Biome: {biome} | Time: {period}{rain}")

        health = state.get("health", 20)
        food = state.get("food", 20)
        exp = state.get("experience", {})
        xp_level = exp.get("level", 0)
        lines.append(f"Health: {health}/20 | Food: {food}/20 | XP Level: {xp_level}")

        max_chars = getattr(settings, "MINECRAFT_CONTEXT_DEPTH0_CHARS", 200)

        if depth >= 1:
            max_chars = getattr(settings, "MINECRAFT_CONTEXT_FULL_CHARS", 800)

            # インベントリ
            inventory = state.get("inventory", [])
            if inventory:
                items = [f"{it.get('name', '?')} x{it.get('count', 0)}" for it in inventory[:10]]
                lines.append(f"Inventory: {', '.join(items)}")

            # 近接エンティティ
            entities = state.get("nearbyEntities", [])
            if entities:
                ent_strs = [f"{e.get('name', '?')} ({e.get('distance', '?')}m)" for e in entities[:8]]
                lines.append(f"Nearby: {', '.join(ent_strs)}")

            # 注目ブロック
            blocks = state.get("nearbyBlocks", [])
            if blocks:
                block_strs = [b.get("name", "?") for b in blocks[:5]]
                lines.append(f"Notable blocks: {', '.join(block_strs)}")

            # 最近のイベント
            recent = list(self._recent_events)[-5:]
            if recent:
                event_strs = []
                for ev in recent:
                    ev_type = ev.get("type", "")
                    ev_data = ev.get("data", {})
                    if ev_type == "chat":
                        event_strs.append(f"[{ev_data.get('username', '?')}] \"{ev_data.get('message', '')}\"")
                    elif ev_type == "damage":
                        event_strs.append(f"Took damage (HP: {ev_data.get('health', '?')})")
                    elif ev_type == "death":
                        event_strs.append("Died!")
                    elif ev_type == "collect":
                        event_strs.append(f"Collected {ev_data.get('item', '?')}")
                    else:
                        event_strs.append(ev_type)
                if event_strs:
                    lines.append(f"Recent: {' | '.join(event_strs)}")

        result = "\n".join(lines)
        return result[:max_chars]

    async def format_for_memory(self) -> dict[str, Any]:
        """Format game state snapshot for episodic memory."""
        state = await self.client.get_state()
        if not state.get("connected"):
            return {}

        return {
            "game": "minecraft",
            "position": state.get("position"),
            "health": state.get("health"),
            "food": state.get("food"),
            "biome": state.get("biome"),
            "inventory_count": len(state.get("inventory", [])),
            "recent_events": [
                {"type": ev.get("type"), "data": ev.get("data")}
                for ev in list(self._recent_events)[-5:]
            ],
        }

    def get_recent_events(self, max_events: int = 20) -> list[dict]:
        """Return recent game events."""
        return list(self._recent_events)[-max_events:]

    def format_skill_context(self, skills: list[dict]) -> str:
        """Format learned skills list for LLM context injection."""
        if not skills:
            return ""
        lines = ["=== LEARNED SKILLS ==="]
        for s in skills[:20]:  # cap to avoid excessive length
            rate = f"{s['success_rate']:.0%}" if s.get("total_uses", 0) > 0 else "未使用"
            lines.append(f"- {s['name']}: {s['description']} ({rate})")
        return "\n".join(lines)
