"""YouTube Live Chat fetcher using Data API v3."""
from __future__ import annotations

import asyncio
import logging
import time

import httpx

logger = logging.getLogger("ChatBridge.YouTube")

# YouTube Data API v3 endpoints
_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
_LIVE_CHAT_URL = "https://www.googleapis.com/youtube/v3/liveChat/messages"


class YouTubeLiveChatFetcher:
    """Poll YouTube Live Chat via Data API v3.

    Usage::

        fetcher = YouTubeLiveChatFetcher(video_id="xxx", api_key="yyy")
        await fetcher.poll_loop(enqueue_callback)
    """

    def __init__(self, video_id: str, api_key: str, *, poll_override_sec: int = 0):
        self._video_id = video_id
        self._api_key = api_key
        self._live_chat_id: str | None = None
        self._page_token: str | None = None
        self._poll_interval_sec: float = max(poll_override_sec, 5)
        self._poll_override = poll_override_sec > 0
        self._backoff_sec: float = 5.0

    async def _resolve_live_chat_id(self) -> str:
        """Resolve video_id → activeLiveChatId."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                _VIDEOS_URL,
                params={
                    "part": "liveStreamingDetails",
                    "id": self._video_id,
                    "key": self._api_key,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        items = data.get("items", [])
        if not items:
            raise ValueError(f"Video not found: {self._video_id}")

        details = items[0].get("liveStreamingDetails", {})
        chat_id = details.get("activeLiveChatId")
        if not chat_id:
            raise ValueError(
                f"No active live chat for video {self._video_id}. "
                "Is the stream live?"
            )

        logger.info("[YouTube] resolved liveChatId=%s", chat_id)
        return chat_id

    async def fetch_messages(self) -> list[dict]:
        """Fetch new messages since last page token.

        Returns list of ``{"text", "user_id", "user_name", "timestamp"}``.
        """
        if not self._live_chat_id:
            self._live_chat_id = await self._resolve_live_chat_id()

        params: dict = {
            "liveChatId": self._live_chat_id,
            "part": "snippet,authorDetails",
            "key": self._api_key,
        }
        if self._page_token:
            params["pageToken"] = self._page_token

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(_LIVE_CHAT_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

        # Update pagination state
        self._page_token = data.get("nextPageToken")
        api_interval_ms = data.get("pollingIntervalMillis", 5000)
        if not self._poll_override:
            self._poll_interval_sec = max(api_interval_ms / 1000.0, 2.0)

        messages: list[dict] = []
        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            author = item.get("authorDetails", {})

            # Only process text messages
            if snippet.get("type") != "textMessageEvent":
                continue

            text = snippet.get("displayMessage") or snippet.get("textMessageDetails", {}).get("messageText", "")
            if not text:
                continue

            messages.append({
                "text": text,
                "user_id": author.get("channelId", "unknown"),
                "user_name": author.get("displayName", "YouTubeUser"),
                "timestamp": time.time(),
            })

        return messages

    async def poll_loop(self, enqueue_callback) -> None:
        """Background polling loop. Call with asyncio.create_task().

        Args:
            enqueue_callback: async callable(text, user_id, user_name, source)
        """
        logger.info("[YouTube] starting poll loop for video=%s", self._video_id)

        try:
            self._live_chat_id = await self._resolve_live_chat_id()
        except Exception as e:
            logger.error("[YouTube] failed to resolve liveChatId: %s", e)
            raise

        self._backoff_sec = 5.0

        while True:
            try:
                messages = await self.fetch_messages()
                self._backoff_sec = 5.0  # Reset on success

                for msg in messages:
                    try:
                        await enqueue_callback(
                            text=msg["text"],
                            user_id=msg["user_id"],
                            user_name=msg["user_name"],
                            source="youtube",
                        )
                    except Exception:
                        logger.warning("[YouTube] enqueue failed", exc_info=True)

                if messages:
                    logger.debug("[YouTube] fetched %d messages", len(messages))

            except asyncio.CancelledError:
                logger.info("[YouTube] poll loop cancelled")
                raise
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 403:
                    logger.error("[YouTube] API quota exceeded or forbidden: %s", e)
                    await asyncio.sleep(min(self._backoff_sec, 300))
                    self._backoff_sec = min(self._backoff_sec * 2, 300)
                elif e.response.status_code == 404:
                    logger.error("[YouTube] live chat ended (404)")
                    break
                else:
                    logger.warning("[YouTube] HTTP %d: %s", e.response.status_code, e)
                    await asyncio.sleep(min(self._backoff_sec, 300))
                    self._backoff_sec = min(self._backoff_sec * 2, 300)
            except Exception:
                logger.warning("[YouTube] poll error", exc_info=True)
                await asyncio.sleep(min(self._backoff_sec, 300))
                self._backoff_sec = min(self._backoff_sec * 2, 300)
                continue

            await asyncio.sleep(self._poll_interval_sec)

        logger.info("[YouTube] poll loop ended")
