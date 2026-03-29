"""Minecraft Bot integration module."""
from __future__ import annotations

import logging
from typing import Optional

from backend.core.config import settings

logger = logging.getLogger(__name__)

minecraft_client: Optional["MinecraftBotClient"] = None
minecraft_state: Optional["MinecraftStateManager"] = None
minecraft_events: Optional["MinecraftEventListener"] = None
skill_library: Optional["SkillLibrary"] = None
skill_retrieval: Optional["SkillRetrieval"] = None
skill_executor: Optional["SkillExecutor"] = None
game_loop: Optional["NiaGameLoop"] = None
goal_manager: Optional["GoalManager"] = None


def init_minecraft() -> None:
    """Initialize Minecraft integration if enabled."""
    global minecraft_client, minecraft_state, minecraft_events
    global skill_library, skill_retrieval, skill_executor
    global game_loop, goal_manager

    if not getattr(settings, "MINECRAFT_ENABLED", False):
        logger.info("[MINECRAFT] Disabled (MINECRAFT_ENABLED=False)")
        return

    from backend.services.minecraft.client import MinecraftBotClient
    from backend.services.minecraft.state_manager import MinecraftStateManager
    from backend.services.minecraft.event_listener import MinecraftEventListener

    bot_url = getattr(settings, "MINECRAFT_BOT_URL", "http://localhost:3100")
    ws_url = getattr(settings, "MINECRAFT_BOT_WS_URL", "ws://localhost:3101")

    minecraft_client = MinecraftBotClient(base_url=bot_url)
    minecraft_state = MinecraftStateManager(client=minecraft_client)
    minecraft_events = MinecraftEventListener(ws_url=ws_url, state_manager=minecraft_state)

    # Voyager Skill System
    if getattr(settings, "MINECRAFT_SKILL_ENABLED", True):
        from backend.services.minecraft.skill_library import SkillLibrary
        from backend.services.minecraft.skill_retrieval import SkillRetrieval
        from backend.services.minecraft.skill_executor import SkillExecutor

        skill_library = SkillLibrary()
        skill_retrieval = SkillRetrieval(skill_library)
        skill_executor = SkillExecutor(skill_library, skill_retrieval)
        logger.info("[MINECRAFT] Skill system initialized")

    # Autonomous Game Loop (Phase C)
    if getattr(settings, "GAME_LOOP_ENABLED", False) and skill_executor:
        from backend.services.minecraft.goal_manager import GoalManager
        from backend.services.minecraft.game_loop import NiaGameLoop

        goal_manager = GoalManager()
        game_loop = NiaGameLoop(
            state_manager=minecraft_state,
            skill_executor=skill_executor,
            skill_library=skill_library,
            goal_manager=goal_manager,
            llm_call=None,  # wired up by agent.py or orchestrator at runtime
        )
        logger.info("[MINECRAFT] Game loop initialized (not started — needs LLM wiring)")

    # Register in GameProfileRegistry
    try:
        from backend.services.game_profiles.registry import game_profile_registry
        from backend.services.game_profiles.minecraft import MinecraftProfile
        profile = MinecraftProfile(client=minecraft_client, state_manager=minecraft_state)
        game_profile_registry.register(profile)
        game_profile_registry.set_active("minecraft")
        logger.info("[MINECRAFT] Registered in GameProfileRegistry")
    except Exception:
        logger.warning("[MINECRAFT] Failed to register in GameProfileRegistry", exc_info=True)

    logger.info("[MINECRAFT] Initialized (bot=%s, ws=%s)", bot_url, ws_url)
    logger.info("[MINECRAFT] Event listener will start on /game/connect")
