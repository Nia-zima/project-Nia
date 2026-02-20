"""Input controller using pydirectinput for game automation."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

MAX_HOLD_DURATION = 10.0  # Seconds — cap to prevent indefinite sleep


@dataclass
class ActionMapping:
    """Maps a semantic action name to a physical input operation."""
    type: str         # "key_press" | "key_hold" | "key_release" | "mouse_click" | "mouse_move"
    key: str = ""     # Key name for keyboard actions ("w", "space", "enter", etc.)
    button: str = ""  # Mouse button ("left", "right", "middle")
    duration: float = 0.0  # Seconds to hold for key_hold


@dataclass
class GameConfig:
    """Configuration for a specific game."""
    game_id: str
    game_name: str
    vision_prompt: str
    actions: dict[str, dict[str, Any]] = field(default_factory=dict)
    loop_interval_sec: int = 3


class InputController:
    """Translates semantic action names into physical keyboard/mouse inputs."""

    def __init__(self, action_map: dict[str, ActionMapping]):
        self._action_map = action_map

    @staticmethod
    def load_action_map(actions_config: dict[str, dict[str, Any]]) -> dict[str, ActionMapping]:
        """Build ActionMapping dict from a game config's actions dict."""
        result: dict[str, ActionMapping] = {}
        for name, cfg in actions_config.items():
            result[name] = ActionMapping(
                type=cfg.get("type", "key_press"),
                key=cfg.get("key", ""),
                button=cfg.get("button", ""),
                duration=float(cfg.get("duration", 0.0)),
            )
        return result

    async def execute(self, action_name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute an action by name. Returns {success, action, detail}."""
        params = params or {}

        mapping = self._action_map.get(action_name)
        if mapping is None:
            return {
                "success": False,
                "action": action_name,
                "error": f"Unknown action: {action_name}",
            }

        try:
            import pydirectinput

            if mapping.type == "key_press":
                key = params.get("key") or mapping.key
                pydirectinput.press(key)
                return {"success": True, "action": action_name, "detail": f"press({key})"}

            elif mapping.type == "key_hold":
                key = params.get("key") or mapping.key
                raw_dur = params.get("duration") if "duration" in params else None
                duration = min(float(raw_dur) if raw_dur is not None else (mapping.duration or 0.3), MAX_HOLD_DURATION)
                pydirectinput.keyDown(key)
                await asyncio.sleep(duration)
                pydirectinput.keyUp(key)
                return {"success": True, "action": action_name, "detail": f"hold({key}, {duration}s)"}

            elif mapping.type == "key_release":
                key = params.get("key") or mapping.key
                pydirectinput.keyUp(key)
                return {"success": True, "action": action_name, "detail": f"release({key})"}

            elif mapping.type == "mouse_click":
                button = params.get("button") or mapping.button or "left"
                x = params.get("x")
                y = params.get("y")
                if x is not None and y is not None:
                    pydirectinput.click(int(x), int(y), button=button)
                else:
                    pydirectinput.click(button=button)
                return {"success": True, "action": action_name, "detail": f"click({button})"}

            elif mapping.type == "mouse_move":
                x = int(params.get("x", 0))
                y = int(params.get("y", 0))
                relative = params.get("relative", True)
                if relative:
                    pydirectinput.moveRel(x, y)
                else:
                    pydirectinput.moveTo(x, y)
                return {"success": True, "action": action_name, "detail": f"move({x},{y})"}

            else:
                return {
                    "success": False,
                    "action": action_name,
                    "error": f"Unknown mapping type: {mapping.type}",
                }

        except ImportError:
            logger.error("[InputController] pydirectinput is not installed")
            return {"success": False, "action": action_name, "error": "pydirectinput not installed"}
        except Exception as e:
            logger.exception("[InputController] Action failed: %s", action_name)
            return {"success": False, "action": action_name, "error": str(e)}
