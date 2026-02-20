"""Nia's autonomous Minecraft game loop: Perceive -> Think -> Act -> Reflect."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import deque
from typing import Any, Optional

from backend.core.config import settings
from backend.core.constants.minecraft_brain_prompt import build_brain_prompt

logger = logging.getLogger(__name__)

# --- Response parsing patterns ---
_TAG_THINK = re.compile(r"<THINK>(.*?)</THINK>", re.DOTALL)
_TAG_SKILL = re.compile(
    r"<SKILL\s+name=[\"']([^\"']+)[\"']\s*(?:params=[\"'](.+?)[\"'])?\s*/>",
    re.DOTALL,
)
_TAG_CODE = re.compile(r"<CODE>(.*?)</CODE>", re.DOTALL)
_TAG_CHAT = re.compile(r"<CHAT>(.*?)</CHAT>", re.DOTALL)
_TAG_IDLE = re.compile(r"<IDLE\s*(?:reason=[\"']([^\"']*)[\"'])?\s*/>", re.DOTALL)


def _parse_brain_response(text: str) -> dict[str, Any]:
    """Parse the Brain LLM response into a structured action."""
    think_m = _TAG_THINK.search(text)
    thinking = think_m.group(1).strip() if think_m else ""

    skill_m = _TAG_SKILL.search(text)
    if skill_m:
        params_raw = skill_m.group(2)
        try:
            params = json.loads(params_raw) if params_raw else {}
        except json.JSONDecodeError:
            params = {}
        return {
            "type": "skill",
            "thinking": thinking,
            "name": skill_m.group(1),
            "params": params,
        }

    code_m = _TAG_CODE.search(text)
    if code_m:
        return {
            "type": "code",
            "thinking": thinking,
            "code": code_m.group(1).strip(),
        }

    chat_m = _TAG_CHAT.search(text)
    if chat_m:
        return {
            "type": "chat",
            "thinking": thinking,
            "message": chat_m.group(1).strip(),
        }

    idle_m = _TAG_IDLE.search(text)
    if idle_m:
        return {
            "type": "idle",
            "thinking": thinking,
            "reason": idle_m.group(1) or "",
        }

    # Fallback: treat entire text as chat
    return {"type": "chat", "thinking": thinking, "message": text.strip()}


class NiaGameLoop:
    """Nia's autonomous Perceive-Think-Act-Reflect game loop."""

    def __init__(
        self,
        state_manager: Any,
        skill_executor: Any,
        skill_library: Any,
        goal_manager: Any,
        llm_call: Any = None,
        execution_engine: Any = None,
    ):
        self._state = state_manager
        self._executor = skill_executor
        self._library = skill_library
        self._goals = goal_manager
        self._llm_call = llm_call  # async callable(system, user) -> str
        self._engine = execution_engine  # ExecutionEngine (Phase D)

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._consecutive_fails = 0
        self._recent_actions: deque[str] = deque(maxlen=10)
        self._past_issues: deque[str] = deque(maxlen=5)
        self._on_chat_callbacks: list = []

    # --- Public API ---

    async def start(self) -> None:
        """Start the autonomous game loop."""
        if self._running:
            logger.warning("[GameLoop] Already running")
            return
        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info("[GameLoop] Started")

    async def stop(self) -> None:
        """Stop the game loop gracefully."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("[GameLoop] Stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    def on_chat(self, callback) -> None:
        """Register a callback for CHAT actions: callback(message: str)."""
        self._on_chat_callbacks.append(callback)

    def add_user_goal(self, description: str, priority: int = 1) -> None:
        """Add a goal from the user (via chat)."""
        self._goals.add_goal(description, priority=priority, source="user")

    def get_status(self) -> dict:
        """Return current loop status for API/frontend."""
        return {
            "running": self._running,
            "consecutive_fails": self._consecutive_fails,
            "active_goals": [
                {"description": g.description, "source": g.source}
                for g in self._goals.get_active_goals()
            ],
            "recent_actions": list(self._recent_actions),
        }

    # --- Core loop ---

    async def _run(self) -> None:
        """Main loop: Perceive -> Think -> Act -> Reflect."""
        logger.info("[GameLoop] Loop started, interval=%ds", settings.GAME_LOOP_INTERVAL_SEC)
        while self._running:
            try:
                await self._cycle()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("[GameLoop] Cycle error")
                self._consecutive_fails += 1

            # Determine wait time
            if self._consecutive_fails >= settings.GAME_LOOP_MAX_CONSECUTIVE_FAILS:
                wait = settings.GAME_LOOP_INTERVAL_SEC * settings.GAME_LOOP_IDLE_MULTIPLIER
                logger.info("[GameLoop] Idle mode (%d consecutive fails), waiting %ds", self._consecutive_fails, wait)
            else:
                wait = settings.GAME_LOOP_INTERVAL_SEC

            await asyncio.sleep(wait)

    async def _cycle(self) -> None:
        """Single Perceive-Think-Act-Reflect cycle."""

        # 1. Perceive
        game_state = await self._perceive()
        if not game_state:
            logger.debug("[GameLoop] No game state (bot disconnected?)")
            return

        # 2. Think
        action = await self._think(game_state)
        if action is None:
            return

        logger.info(
            "[GameLoop] Decision: %s | Thinking: %s",
            action["type"],
            action.get("thinking", "")[:80],
        )

        # 3. Act
        result = await self._act(action)

        # 4. Reflect
        await self._reflect(action, result)

    # --- Perceive ---

    async def _perceive(self) -> str:
        """Gather current game state."""
        return await self._state.format_for_llm(depth=1)

    # --- Think ---

    async def _think(self, game_state: str) -> Optional[dict]:
        """Ask the Brain LLM what to do next."""
        if self._llm_call is None:
            logger.warning("[GameLoop] No LLM call configured")
            return None

        # Build context
        learned_skills = self._format_skills()
        current_goals = self._goals.format_for_prompt()
        recent_actions = "\n".join(self._recent_actions) if self._recent_actions else ""

        # Merge in-memory issues with persistent failure memory (Phase E)
        past_issues_parts = list(self._past_issues)
        try:
            from backend.services.minecraft.failure_memory import (
                search_failures,
                format_failures_for_prompt,
            )
            db_failures = search_failures(query=current_goals, limit=3)
            if db_failures:
                past_issues_parts.append(format_failures_for_prompt(db_failures))
        except Exception:
            pass  # failure memory is optional
        past_issues = "\n".join(past_issues_parts)

        system_prompt, user_prompt = build_brain_prompt(
            game_state=game_state,
            learned_skills=learned_skills,
            current_goals=current_goals,
            recent_actions=recent_actions,
            past_issues=past_issues,
        )

        try:
            response = await self._llm_call(system_prompt, user_prompt)
        except Exception:
            logger.exception("[GameLoop] LLM call failed")
            return None

        return _parse_brain_response(response)

    def _format_skills(self) -> str:
        """Format learned skills for the prompt."""
        skills = self._library.list_all()
        if not skills:
            return ""
        lines = []
        for s in skills:
            rate = f"{s['success_rate']:.0%}" if s["total_uses"] > 0 else "未使用"
            lines.append(f"- {s['name']}: {s['description']} (成功率: {rate})")
        return "\n".join(lines)

    # --- Act ---

    async def _act(self, action: dict) -> dict:
        """Execute the decided action."""
        action_type = action["type"]

        if action_type == "skill":
            return await self._act_skill(action["name"], action.get("params", {}))
        elif action_type == "code":
            return await self._act_code(action["code"])
        elif action_type == "chat":
            return await self._act_chat(action["message"])
        elif action_type == "idle":
            return await self._act_idle(action.get("reason", ""))
        else:
            return {"success": False, "error": f"Unknown action type: {action_type}"}

    async def _act_skill(self, name: str, params: dict) -> dict:
        """Execute a named skill."""
        if self._engine:
            return await self._engine.execute_skill(name, params)
        return await self._executor.execute_skill(name, params)

    async def _act_code(self, code: str) -> dict:
        """Execute raw JS code with self-correction (Phase D)."""
        if self._engine:
            return await self._engine.execute_code(code)
        return await self._executor.execute_code(code)

    async def _act_chat(self, message: str) -> dict:
        """Broadcast a chat message (Nia's monologue or report)."""
        for cb in self._on_chat_callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(message)
                else:
                    cb(message)
            except Exception:
                logger.exception("[GameLoop] Chat callback error")
        return {"success": True, "type": "chat", "message": message}

    async def _act_idle(self, reason: str) -> dict:
        """Do nothing for this cycle."""
        logger.info("[GameLoop] Idle: %s", reason or "no reason")
        return {"success": True, "type": "idle", "reason": reason}

    # --- Reflect ---

    async def _reflect(self, action: dict, result: dict) -> None:
        """Update state based on action result."""
        action_type = action["type"]
        success = result.get("success", False)

        retries = result.get("retries", 0)
        retry_info = f" (retries={retries})" if retries else ""

        # Record recent action
        if action_type == "skill":
            status = "OK" if success else f"FAIL: {result.get('error', '?')}"
            self._recent_actions.append(
                f"[SKILL] {action['name']} -> {status}"
            )
        elif action_type == "code":
            status = "OK" if success else f"FAIL: {result.get('error', '?')}"
            snippet = action["code"][:50].replace("\n", " ")
            self._recent_actions.append(f"[CODE] {snippet}... -> {status}{retry_info}")
            # Log saved skill
            saved = result.get("saved_skill")
            if saved:
                self._recent_actions.append(f"[LEARNED] New skill: {saved}")
        elif action_type == "chat":
            self._recent_actions.append(f"[CHAT] {action['message'][:60]}")
        elif action_type == "idle":
            self._recent_actions.append(f"[IDLE] {action.get('reason', '')[:40]}")

        # Track failures
        if action_type in ("skill", "code"):
            if success:
                self._consecutive_fails = 0
            else:
                self._consecutive_fails += 1
                error_msg = result.get("error", "unknown error")
                self._past_issues.append(
                    f"{action_type}={action.get('name', 'code')}: {error_msg}"
                )

        # Auto-complete goals on success
        if success and action_type in ("skill", "code"):
            thinking = action.get("thinking", "")
            for goal in self._goals.get_active_goals():
                # Simple heuristic: if thinking mentions the goal
                if goal.description.lower() in thinking.lower():
                    self._goals.complete_goal(goal.description)
                    self._recent_actions.append(f"[GOAL] Completed: {goal.description}")
                    break
