"""Screen-based game profile using screen capture + Vision API + pydirectinput."""
from __future__ import annotations

import logging
from collections import deque
from typing import Any

from backend.core.config import settings
from backend.services.game_profiles.base import GameProfile
from backend.services.gaming.input_controller import GameConfig, InputController
from backend.services.gaming.screen_capture import ScreenCapture

logger = logging.getLogger(__name__)


class ScreenGameProfile(GameProfile):
    """GameProfile implementation for screen-capture-based games."""

    def __init__(
        self,
        config: GameConfig,
        capture: ScreenCapture,
        controller: InputController,
    ):
        self._config = config
        self._capture = capture
        self._controller = controller
        buf_size = getattr(settings, "SCREEN_GAME_FRAME_BUFFER_SIZE", 3)
        self._frame_buffer: deque[str] = deque(maxlen=buf_size)
        self._last_analysis: str = ""

    @property
    def game_id(self) -> str:
        return self._config.game_id

    @property
    def game_name(self) -> str:
        return self._config.game_name

    async def get_state(self) -> dict[str, Any]:
        """Capture screen → Vision API → structured state dict."""
        from backend.services.vision_client import analyze_image

        b64 = self._capture.capture_base64()
        provider = getattr(settings, "GAME_VISION_PROVIDER", "gemini")
        analysis = await analyze_image(
            b64,
            self._config.vision_prompt,
            provider=provider,
        )
        self._frame_buffer.append(analysis)
        self._last_analysis = analysis
        return {
            "analysis": analysis,
            "frame_history": list(self._frame_buffer),
            "connected": True,
        }

    async def execute_action(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Execute action via pydirectinput."""
        return await self._controller.execute(action, params)

    async def is_connected(self) -> bool:
        """Screen capture is always available."""
        return True

    def format_state_for_llm(self, state: dict[str, Any], depth: int) -> str:
        """Format vision analysis for LLM context injection."""
        analysis = state.get("analysis", "")
        history = state.get("frame_history", [])

        if depth == 0:
            return analysis[:400]

        # depth1+: include frame history for temporal awareness
        parts = [f"[現在] {analysis}"]
        for i, prev in enumerate(reversed(history[:-1])):
            parts.append(f"[{i + 1}フレーム前] {prev[:200]}")
        return "\n".join(parts)[:1200]

    def get_available_actions(self) -> list[dict[str, str]]:
        """Return actions defined in the game config."""
        return [
            {"id": k, "name": k, "risk": "safe"}
            for k in self._config.actions
        ]
