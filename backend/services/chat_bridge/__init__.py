"""Chat Bridge — YouTube + Twitch live chat → livestream_queue."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid

from backend.core.config import settings
from backend.services.livestream_queue import (
    Comment,
    UserRole,
    get_livestream_queue,
)
from backend.controllers.api.livestream_router import (
    _detect_addressed_to_nia,
    _calculate_info_sufficiency,
)
from backend.core.confidence.metrics import SteeringRiskCalculator

logger = logging.getLogger("ChatBridge")


class ChatBridge:
    """Unified manager for YouTube + Twitch chat bridges."""

    def __init__(self):
        self._youtube_task: asyncio.Task | None = None
        self._twitch_task: asyncio.Task | None = None
        self._stats = {
            "youtube_received": 0,
            "twitch_received": 0,
            "enqueued": 0,
            "filtered": 0,
        }
        self._started_at: dict[str, float] = {}

    # ── YouTube ──────────────────────────────────────────────────

    async def start_youtube(self, video_id: str | None = None) -> dict:
        """Start YouTube Live Chat polling."""
        if self._youtube_task and not self._youtube_task.done():
            return {"ok": False, "reason": "already_running"}

        vid = video_id or getattr(settings, "YOUTUBE_VIDEO_ID", "")
        api_key = getattr(settings, "GOOGLE_API_KEY", "")
        if not vid:
            return {"ok": False, "reason": "no_video_id"}
        if not api_key:
            return {"ok": False, "reason": "no_api_key"}

        from backend.services.chat_bridge.youtube_fetcher import YouTubeLiveChatFetcher

        poll_override = getattr(settings, "YOUTUBE_POLL_INTERVAL_SEC", 0)
        fetcher = YouTubeLiveChatFetcher(
            video_id=vid,
            api_key=api_key,
            poll_override_sec=poll_override,
        )

        self._youtube_task = asyncio.create_task(
            fetcher.poll_loop(self._enqueue_comment),
            name="chat_bridge_youtube",
        )
        self._started_at["youtube"] = time.time()
        logger.info("[ChatBridge] YouTube started for video=%s", vid)
        return {"ok": True, "video_id": vid}

    async def stop_youtube(self) -> dict:
        """Stop YouTube polling."""
        if self._youtube_task and not self._youtube_task.done():
            self._youtube_task.cancel()
            try:
                await self._youtube_task
            except asyncio.CancelledError:
                pass
        self._youtube_task = None
        self._started_at.pop("youtube", None)
        logger.info("[ChatBridge] YouTube stopped")
        return {"ok": True}

    # ── Twitch ───────────────────────────────────────────────────

    async def start_twitch(self, channel: str | None = None) -> dict:
        """Start Twitch IRC listener."""
        if self._twitch_task and not self._twitch_task.done():
            return {"ok": False, "reason": "already_running"}

        ch = channel or getattr(settings, "TWITCH_CHANNEL", "")
        if not ch:
            return {"ok": False, "reason": "no_channel"}

        from backend.services.chat_bridge.twitch_fetcher import TwitchIRCFetcher

        nick = getattr(settings, "TWITCH_NICK", "justinfan12345")
        oauth = getattr(settings, "TWITCH_OAUTH_TOKEN", "")
        fetcher = TwitchIRCFetcher(channel=ch, nick=nick, oauth=oauth)

        self._twitch_task = asyncio.create_task(
            fetcher.listen_loop(self._enqueue_comment),
            name="chat_bridge_twitch",
        )
        self._started_at["twitch"] = time.time()
        logger.info("[ChatBridge] Twitch started for #%s", ch)
        return {"ok": True, "channel": ch}

    async def stop_twitch(self) -> dict:
        """Stop Twitch IRC listener."""
        if self._twitch_task and not self._twitch_task.done():
            self._twitch_task.cancel()
            try:
                await self._twitch_task
            except asyncio.CancelledError:
                pass
        self._twitch_task = None
        self._started_at.pop("twitch", None)
        logger.info("[ChatBridge] Twitch stopped")
        return {"ok": True}

    # ── Control ──────────────────────────────────────────────────

    async def stop_all(self) -> dict:
        """Stop all bridges."""
        results = {}
        results["youtube"] = await self.stop_youtube()
        results["twitch"] = await self.stop_twitch()
        return {"ok": True, "results": results}

    def get_status(self) -> dict:
        """Return connection status and stats."""
        return {
            "youtube": {
                "running": bool(self._youtube_task and not self._youtube_task.done()),
                "received": self._stats["youtube_received"],
                "started_at": self._started_at.get("youtube"),
            },
            "twitch": {
                "running": bool(self._twitch_task and not self._twitch_task.done()),
                "received": self._stats["twitch_received"],
                "started_at": self._started_at.get("twitch"),
            },
            "enqueued": self._stats["enqueued"],
            "filtered": self._stats["filtered"],
        }

    # ── Enqueue ──────────────────────────────────────────────────

    async def _enqueue_comment(
        self, text: str, user_id: str, user_name: str, source: str
    ) -> None:
        """Shared enqueue logic for both platforms."""
        # Track stats
        if source == "youtube":
            self._stats["youtube_received"] += 1
        elif source == "twitch":
            self._stats["twitch_received"] += 1

        # Compute metrics (reuse existing helpers)
        steering_risk = SteeringRiskCalculator.calculate(text)
        info_sufficiency = _calculate_info_sufficiency(text)
        addressed = _detect_addressed_to_nia(text)

        comment = Comment(
            id=uuid.uuid4().hex,
            text=text,
            user_id=user_id,
            user_name=user_name,
            role=UserRole.VIEWER,
            timestamp=time.time(),
            steering_risk=steering_risk,
            info_sufficiency=info_sufficiency,
            addressed_to_nia=addressed,
            source=source,
        )

        queue = get_livestream_queue()
        result = await queue.enqueue(comment)

        if result.queued:
            self._stats["enqueued"] += 1
        else:
            self._stats["filtered"] += 1


# Singleton
chat_bridge = ChatBridge()
