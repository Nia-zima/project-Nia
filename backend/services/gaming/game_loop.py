"""Generic game loop: Perceive-Think-Act-Reflect for any GameProfile."""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Any, Callable, Optional

from backend.core.config import settings
from backend.services.game_profiles.base import GameProfile
from backend.services.gaming.brain import build_brain_prompt, parse_brain_response

logger = logging.getLogger(__name__)


class GenericGameLoop:
    """Autonomous Perceive-Think-Act-Reflect loop that works with any GameProfile."""

    def __init__(
        self,
        profile: GameProfile,
        llm_call: Optional[Callable] = None,
        interval_sec: Optional[int] = None,
    ):
        self._profile = profile
        self._llm_call = llm_call  # async callable(system: str, user: str) -> str
        self._interval = interval_sec or getattr(
            settings, "SCREEN_GAME_LOOP_INTERVAL_SEC", 3
        )

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._consecutive_fails = 0
        self._recent_actions: deque[str] = deque(maxlen=10)
        self._goals: list[str] = []
        self._on_chat_callbacks: list[Callable] = []

    # --- Public API ---

    async def start(self) -> None:
        async with self._lock:
            if self._running:
                logger.warning("[GenericGameLoop] Already running")
                return
            self._running = True
            self._task = asyncio.create_task(self._run())
            logger.info("[GenericGameLoop] Started (game=%s, interval=%ds)",
                         self._profile.game_id, self._interval)

    async def stop(self) -> None:
        async with self._lock:
            self._running = False
            if self._task:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
                self._task = None
            logger.info("[GenericGameLoop] Stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    def on_chat(self, callback: Callable) -> None:
        self._on_chat_callbacks.append(callback)

    def add_goal(self, description: str) -> None:
        self._goals.append(description)

    def get_status(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "game_id": self._profile.game_id,
            "game_name": self._profile.game_name,
            "consecutive_fails": self._consecutive_fails,
            "goals": list(self._goals),
            "recent_actions": list(self._recent_actions),
        }

    # --- Core loop ---

    async def _run(self) -> None:
        max_consecutive = getattr(settings, "GAME_LOOP_MAX_CONSECUTIVE_FAILS", 3)
        idle_multiplier = getattr(settings, "GAME_LOOP_IDLE_MULTIPLIER", 4)

        while self._running:
            try:
                await self._cycle()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("[GenericGameLoop] Cycle error")
                self._consecutive_fails += 1

            if self._consecutive_fails >= max_consecutive:
                wait = self._interval * idle_multiplier
                logger.info("[GenericGameLoop] Idle mode (%d fails), waiting %ds",
                            self._consecutive_fails, wait)
            else:
                wait = self._interval

            await asyncio.sleep(wait)

    async def _cycle(self) -> None:
        """Single Perceive-Think-Act-Reflect cycle."""
        # 1. Perceive
        state = await self._perceive()
        if state is None:
            return

        game_state_str = self._profile.format_state_for_llm(state, depth=1)

        # 2. Think
        action = await self._think(game_state_str)
        if action is None:
            return

        logger.info("[GenericGameLoop] Decision: %s | Thinking: %s",
                     action["type"], action.get("thinking", "")[:80])

        # 3. Act
        result = await self._act(action)

        # 4. Reflect
        self._reflect(action, result)

    # --- Perceive ---

    async def _perceive(self) -> Optional[dict[str, Any]]:
        try:
            state = await self._profile.get_state()
            if not state:
                logger.debug("[GenericGameLoop] Empty state from profile")
                return None
            return state
        except Exception:
            logger.exception("[GenericGameLoop] Perceive failed")
            return None

    # --- Think ---

    async def _think(self, game_state_str: str) -> Optional[dict[str, Any]]:
        if self._llm_call is None:
            logger.warning("[GenericGameLoop] No LLM call configured")
            return None

        actions_list = self._profile.get_available_actions()
        actions_str = "\n".join(
            f"- {a['id']}" for a in actions_list
        )
        recent = "\n".join(self._recent_actions) if self._recent_actions else ""
        goals_str = "\n".join(f"- {g}" for g in self._goals) if self._goals else ""

        system_prompt, user_prompt = build_brain_prompt(
            game_state=game_state_str,
            available_actions=actions_str,
            recent_actions=recent,
            goals=goals_str,
        )

        try:
            response = await self._llm_call(system_prompt, user_prompt)
        except Exception:
            logger.exception("[GenericGameLoop] LLM call failed")
            return None

        return parse_brain_response(response)

    # --- Act ---

    async def _act(self, action: dict[str, Any]) -> dict[str, Any]:
        action_type = action["type"]

        if action_type == "action":
            try:
                result = await self._profile.execute_action(
                    action["name"], action.get("params", {})
                )
                return result
            except Exception as e:
                logger.exception("[GenericGameLoop] Action failed: %s", action["name"])
                return {"success": False, "error": str(e)}

        elif action_type == "chat":
            message = action.get("message", "")
            for cb in self._on_chat_callbacks:
                try:
                    if asyncio.iscoroutinefunction(cb):
                        await cb(message)
                    else:
                        cb(message)
                except Exception:
                    logger.exception("[GenericGameLoop] Chat callback error")
            return {"success": True, "type": "chat", "message": message}

        elif action_type == "idle":
            reason = action.get("reason", "")
            logger.info("[GenericGameLoop] Idle: %s", reason or "no reason")
            return {"success": True, "type": "idle", "reason": reason}

        return {"success": False, "error": f"Unknown action type: {action_type}"}

    # --- Reflect ---

    def _reflect(self, action: dict[str, Any], result: dict[str, Any]) -> None:
        action_type = action["type"]
        success = result.get("success", False)

        if action_type == "action":
            name = action.get("name", "?")
            status = "OK" if success else f"FAIL: {result.get('error', '?')}"
            self._recent_actions.append(f"[ACTION] {name} -> {status}")
            if success:
                self._consecutive_fails = 0
            else:
                self._consecutive_fails += 1

        elif action_type == "chat":
            msg = action.get("message", "")[:60]
            self._recent_actions.append(f"[CHAT] {msg}")

        elif action_type == "idle":
            reason = action.get("reason", "")[:40]
            self._recent_actions.append(f"[IDLE] {reason}")
