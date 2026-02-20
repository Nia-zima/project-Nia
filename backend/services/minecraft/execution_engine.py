"""Execution engine with self-correction loop for Minecraft skills/code."""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from backend.services.minecraft.critique_generator import (
    build_critique_prompt,
    parse_critique_response,
)

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


class ExecutionEngine:
    """Execute code/skills with LLM-based self-correction on failure.

    Flow:
      1. Execute skill or code
      2. On failure → LLM critique → fix code → retry (up to MAX_RETRIES)
      3. On success → optionally save as new skill
    """

    def __init__(
        self,
        skill_executor: Any,
        skill_library: Any,
        llm_call: Any = None,
        get_game_state: Any = None,
    ):
        self._executor = skill_executor
        self._library = skill_library
        self._llm_call = llm_call  # async callable(system, user) -> str
        self._get_game_state = get_game_state  # async callable() -> str

    async def execute_skill(self, name: str, params: dict | None = None) -> dict:
        """Execute a named skill (no retry — skill code is trusted)."""
        result = await self._executor.execute_skill(name, params)
        return self._enrich_result(result, action_type="skill", name=name)

    async def execute_code(
        self,
        code: str,
        *,
        save_as: str | None = None,
        description: str = "",
    ) -> dict:
        """Execute code with self-correction loop.

        Args:
            code: JS code to execute.
            save_as: If provided, save as skill on success.
            description: Skill description (for save_as).

        Returns:
            {success, result/error, retries, saved_skill, ...}
        """
        current_code = code
        retries = 0
        all_errors: list[str] = []

        for attempt in range(1 + MAX_RETRIES):
            result = await self._executor.execute_code(current_code)

            if result.get("success"):
                saved = False
                # Auto-save as skill on success
                if save_as and description:
                    saved = self._try_save_skill(save_as, description, current_code)

                return {
                    "success": True,
                    "result": result.get("result"),
                    "logs": result.get("logs", []),
                    "retries": retries,
                    "saved_skill": save_as if saved else None,
                    "final_code": current_code if retries > 0 else None,
                }

            # Failed
            error = result.get("error", "unknown error")
            all_errors.append(error)
            retries += 1

            if attempt >= MAX_RETRIES:
                break

            # Try self-correction via LLM critique
            fixed_code = await self._critique_and_fix(
                current_code, error, result.get("logs", [])
            )
            if fixed_code is None:
                # LLM gave up or critique unavailable
                break

            logger.info(
                "[ExecutionEngine] Retry %d/%d after critique",
                retries, MAX_RETRIES,
            )
            current_code = fixed_code

        return {
            "success": False,
            "error": all_errors[-1] if all_errors else "unknown",
            "all_errors": all_errors,
            "retries": retries,
        }

    async def _critique_and_fix(
        self, code: str, error: str, logs: list[str]
    ) -> Optional[str]:
        """Ask LLM to analyze failure and produce fixed code."""
        if self._llm_call is None:
            return None

        game_state = ""
        if self._get_game_state:
            try:
                game_state = await self._get_game_state()
            except Exception:
                pass

        system, user = build_critique_prompt(
            code=code, error=error, game_state=game_state, logs=logs,
        )

        try:
            response = await self._llm_call(system, user)
        except Exception:
            logger.exception("[ExecutionEngine] Critique LLM call failed")
            return None

        parsed = parse_critique_response(response)
        if parsed["action"] == "giveup":
            logger.info(
                "[ExecutionEngine] LLM gave up: %s", parsed.get("reason", "")[:100]
            )
            return None

        logger.info(
            "[ExecutionEngine] Critique: %s", parsed.get("explanation", "")[:100]
        )
        return parsed.get("code")

    def _try_save_skill(self, name: str, description: str, code: str) -> bool:
        """Save code as a reusable skill."""
        try:
            self._library.save(name, description, code)
            logger.info("[ExecutionEngine] Saved skill: %s", name)
            return True
        except Exception:
            logger.exception("[ExecutionEngine] Failed to save skill: %s", name)
            return False

    @staticmethod
    def _enrich_result(result: dict, **extra) -> dict:
        result.update(extra)
        return result
