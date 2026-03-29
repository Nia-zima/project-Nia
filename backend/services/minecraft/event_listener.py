"""WebSocket listener for Mineflayer bot events."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

import aiohttp

if TYPE_CHECKING:
    from backend.services.minecraft.state_manager import MinecraftStateManager

logger = logging.getLogger(__name__)


class MinecraftEventListener:
    """Listens to game events from the Mineflayer bot via WebSocket."""

    def __init__(self, ws_url: str, state_manager: "MinecraftStateManager"):
        self.ws_url = ws_url
        self.state_manager = state_manager
        self._task: asyncio.Task | None = None
        self._running = False
        self._frontend_callbacks: list = []

    async def start(self) -> None:
        """Start listening in background task."""
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._listen_loop(), name="mc_event_listener")
        logger.info("[MC_EVENTS] Listener started")

    async def stop(self) -> None:
        """Stop listening."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("[MC_EVENTS] Listener stopped")

    def on_event(self, callback) -> None:
        """Register frontend event callback."""
        self._frontend_callbacks.append(callback)

    def remove_callback(self, callback) -> None:
        """Unregister frontend event callback."""
        try:
            self._frontend_callbacks.remove(callback)
        except ValueError:
            pass

    async def _listen_loop(self) -> None:
        """Reconnecting WebSocket listener loop."""
        backoff = 1.0
        while self._running:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(self.ws_url) as ws:
                        logger.info("[MC_EVENTS] Connected to %s", self.ws_url)
                        backoff = 1.0
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                try:
                                    event = json.loads(msg.data)
                                    self.state_manager.record_event(event)
                                    for cb in list(self._frontend_callbacks):
                                        try:
                                            cb(event)
                                        except Exception:
                                            logger.debug("[MC_EVENTS] Callback error", exc_info=True)
                                except json.JSONDecodeError:
                                    pass
                            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                break
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("[MC_EVENTS] Connection lost: %s, retry in %.0fs", e, backoff)

            if self._running:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
