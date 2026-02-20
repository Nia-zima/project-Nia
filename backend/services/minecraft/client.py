"""HTTP client for the Mineflayer bot microservice."""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

import aiohttp

logger = logging.getLogger(__name__)


class MinecraftBotClient:
    """HTTP client to communicate with the Mineflayer bot microservice."""

    def __init__(self, base_url: str = "http://localhost:3100", timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._state_cache: Optional[dict] = None
        self._cache_ts: float = 0
        self._cache_ttl: float = 1.0

    async def get_state(self) -> dict:
        """GET /state with short-lived cache."""
        now = time.monotonic()
        if self._state_cache and (now - self._cache_ts) < self._cache_ttl:
            return self._state_cache

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(f"{self.base_url}/state") as resp:
                    data = await resp.json()
                    self._state_cache = data
                    self._cache_ts = now
                    return data
        except Exception as e:
            logger.warning("[MC_CLIENT] get_state failed: %s", e)
            return {"connected": False, "error": str(e)}

    async def execute_action(self, action: str, params: dict | None = None) -> dict:
        """POST /action to execute a game action."""
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(
                    f"{self.base_url}/action",
                    json={"action": action, "params": params or {}},
                ) as resp:
                    return await resp.json()
        except Exception as e:
            logger.warning("[MC_CLIENT] execute_action failed: %s", e)
            return {"success": False, "error": str(e)}

    async def is_connected(self) -> bool:
        """GET /health to check bot status."""
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(f"{self.base_url}/health") as resp:
                    data = await resp.json()
                    return data.get("connected", False)
        except Exception:
            return False

    async def connect(self, host: str = "localhost", port: int = 25565,
                      username: str = "Nia", version: str = "1.20.4") -> dict:
        """POST /connect to join server."""
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(
                    f"{self.base_url}/connect",
                    json={"host": host, "port": port, "username": username, "version": version},
                ) as resp:
                    return await resp.json()
        except Exception as e:
            logger.warning("[MC_CLIENT] connect failed: %s", e)
            return {"ok": False, "error": str(e)}

    async def disconnect(self) -> dict:
        """POST /disconnect to leave server."""
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(f"{self.base_url}/disconnect") as resp:
                    return await resp.json()
        except Exception as e:
            logger.warning("[MC_CLIENT] disconnect failed: %s", e)
            return {"ok": False, "error": str(e)}
