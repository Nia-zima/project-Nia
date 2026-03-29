"""High-level skill/code execution interface for Minecraft."""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from backend.core.config import settings
from backend.services.minecraft.skill_library import SkillLibrary
from backend.services.minecraft.skill_retrieval import SkillRetrieval

logger = logging.getLogger(__name__)


class SkillExecutor:
    """Executes skills or raw code via the minecraft-bot HTTP API."""

    def __init__(self, library: SkillLibrary, retrieval: SkillRetrieval):
        self._library = library
        self._retrieval = retrieval
        self._bot_url = settings.MINECRAFT_BOT_URL
        self._timeout = settings.MINECRAFT_CODE_TIMEOUT / 1000  # ms → sec

    async def execute_skill(self, name: str, args: dict[str, Any] | None = None) -> dict:
        """
        Execute a named skill via the bot.

        Returns {success, result/error, skill}.
        """
        skill = self._library.get(name)
        if not skill:
            return {"success": False, "error": f"Skill '{name}' not found"}

        try:
            async with httpx.AsyncClient(timeout=self._timeout + 5) as client:
                r = await client.post(
                    f"{self._bot_url}/execute_skill",
                    json={"name": name, "args": args or {}},
                )
                if not r.is_success:
                    result = {"success": False, "error": f"HTTP {r.status_code}"}
                else:
                    result = r.json()
        except httpx.TimeoutException:
            result = {"success": False, "error": "Execution timed out"}
        except Exception as e:
            result = {"success": False, "error": str(e)}

        # Record result
        self._library.record_result(name, result.get("success", False))
        logger.info(
            "[SkillExecutor] %s: %s",
            name,
            "success" if result.get("success") else result.get("error", "failed"),
        )
        return result

    async def execute_code(self, code: str) -> dict:
        """
        Execute raw JS code via the bot sandbox.

        Returns {success, result/error, logs}.
        """
        try:
            async with httpx.AsyncClient(timeout=self._timeout + 5) as client:
                r = await client.post(
                    f"{self._bot_url}/execute_code",
                    json={"code": code, "timeout": settings.MINECRAFT_CODE_TIMEOUT},
                )
                if not r.is_success:
                    result = {"success": False, "error": f"HTTP {r.status_code}", "logs": []}
                else:
                    result = r.json()
        except httpx.TimeoutException:
            result = {"success": False, "error": "Execution timed out", "logs": []}
        except Exception as e:
            result = {"success": False, "error": str(e), "logs": []}

        logger.info(
            "[SkillExecutor] code exec: %s (logs: %d)",
            "success" if result.get("success") else result.get("error", "failed"),
            len(result.get("logs", [])),
        )
        return result

    async def save_and_execute(
        self,
        name: str,
        code: str,
        description: str,
        args: dict[str, Any] | None = None,
    ) -> dict:
        """Save code as a skill on both bot and Python side, then execute."""
        # Save to bot side (skills/*.js)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    f"{self._bot_url}/save_skill",
                    json={"name": name, "code": code, "description": description},
                )
        except Exception as e:
            logger.warning("[SkillExecutor] Failed to save skill on bot: %s", e)

        # Save to SQLite
        self._library.save(name, description, code)
        self._retrieval.invalidate()

        # Execute
        return await self.execute_skill(name, args)

    def search_skills(self, query: str, top_k: int = 5) -> list[dict]:
        """Search skills by semantic similarity."""
        return self._retrieval.search(query, top_k=top_k)
