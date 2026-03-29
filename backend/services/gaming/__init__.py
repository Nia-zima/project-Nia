"""Screen-based game integration module."""
from __future__ import annotations

import logging
from typing import Optional

from backend.core.config import settings

logger = logging.getLogger(__name__)

screen_profile: Optional["ScreenGameProfile"] = None
generic_game_loop: Optional["GenericGameLoop"] = None


async def _default_llm_call(system: str, user: str) -> str:
    """Default LLM call adapter for GenericGameLoop."""
    from backend.services.llm_client import call_llm
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    return await call_llm(messages, temperature=0.5, max_tokens=300, timeout_seconds=30)


def init_screen_gaming(game_config_id: str = "generic") -> bool:
    """Initialize screen-capture-based game operation.

    Returns True if initialized successfully, False otherwise.
    """
    global screen_profile, generic_game_loop

    if not getattr(settings, "SCREEN_GAME_ENABLED", False):
        logger.info("[SCREEN_GAMING] Disabled (SCREEN_GAME_ENABLED=False)")
        return False

    from backend.services.gaming.game_configs import get_config
    from backend.services.gaming.screen_capture import ScreenCapture
    from backend.services.gaming.input_controller import InputController
    from backend.services.gaming.screen_profile import ScreenGameProfile
    from backend.services.gaming.game_loop import GenericGameLoop
    from backend.services.game_profiles.registry import game_profile_registry

    config = get_config(game_config_id)
    if config is None:
        logger.error("[SCREEN_GAMING] Unknown game config: %s", game_config_id)
        return False

    # Build components
    region_str = getattr(settings, "SCREEN_CAPTURE_REGION", "")
    capture = ScreenCapture.from_config_string(region_str)

    action_map = InputController.load_action_map(config.actions)
    controller = InputController(action_map)

    profile = ScreenGameProfile(config=config, capture=capture, controller=controller)

    loop = GenericGameLoop(
        profile=profile,
        llm_call=_default_llm_call,
        interval_sec=config.loop_interval_sec,
    )

    # Register in global profile registry
    game_profile_registry.register(profile)
    game_profile_registry.set_active(config.game_id)

    screen_profile = profile
    generic_game_loop = loop

    logger.info(
        "[SCREEN_GAMING] Initialized: game=%s (%s), interval=%ds",
        config.game_id, config.game_name, config.loop_interval_sec,
    )
    return True


def shutdown_screen_gaming() -> None:
    """Stop and clean up screen gaming resources."""
    global screen_profile, generic_game_loop

    if generic_game_loop and generic_game_loop.is_running:
        import asyncio
        try:
            running_loop = asyncio.get_running_loop()
            running_loop.create_task(generic_game_loop.stop())
        except RuntimeError:
            # No running event loop — create one to shut down
            try:
                asyncio.run(generic_game_loop.stop())
            except Exception:
                logger.warning("[SCREEN_GAMING] Failed to stop game loop gracefully")

    from backend.services.game_profiles.registry import game_profile_registry
    if screen_profile:
        game_profile_registry.clear_active()

    screen_profile = None
    generic_game_loop = None
    logger.info("[SCREEN_GAMING] Shutdown complete")
