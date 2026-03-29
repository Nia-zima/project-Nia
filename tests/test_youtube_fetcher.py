"""Tests for YouTube Live Chat fetcher."""
from __future__ import annotations

import asyncio
import json
import pytest

from backend.services.chat_bridge.youtube_fetcher import YouTubeLiveChatFetcher


# ── Helpers ──────────────────────────────────────────────────────


def _videos_response(live_chat_id: str = "LC_abc123") -> dict:
    """Mock YouTube videos API response."""
    return {
        "items": [
            {
                "liveStreamingDetails": {
                    "activeLiveChatId": live_chat_id,
                }
            }
        ]
    }


def _live_chat_response(
    messages: list[dict] | None = None,
    next_page_token: str = "token_2",
    polling_interval_ms: int = 5000,
) -> dict:
    """Mock YouTube liveChatMessages API response."""
    items = []
    for msg in (messages or []):
        items.append({
            "snippet": {
                "type": "textMessageEvent",
                "displayMessage": msg["text"],
            },
            "authorDetails": {
                "channelId": msg.get("user_id", "UC_test"),
                "displayName": msg.get("user_name", "TestUser"),
            },
        })
    return {
        "items": items,
        "nextPageToken": next_page_token,
        "pollingIntervalMillis": polling_interval_ms,
    }


class FakeHTTPResponse:
    """Fake httpx response."""

    def __init__(self, data: dict, status_code: int = 200):
        self._data = data
        self.status_code = status_code

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("GET", "https://example.com"),
                response=self,
            )


class FakeAsyncClient:
    """Fake httpx.AsyncClient that returns pre-configured responses."""

    def __init__(self, responses: list[FakeHTTPResponse]):
        self._responses = responses
        self._call_idx = 0
        self.captured_urls: list[str] = []

    async def get(self, url, **kwargs):
        self.captured_urls.append(url)
        resp = self._responses[min(self._call_idx, len(self._responses) - 1)]
        self._call_idx += 1
        return resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


# ── Tests ────────────────────────────────────────────────────────


class TestResolveLiveChatId:
    @pytest.mark.asyncio
    async def test_resolve_success(self, monkeypatch):
        client = FakeAsyncClient([FakeHTTPResponse(_videos_response("LC_test"))])
        monkeypatch.setattr("backend.services.chat_bridge.youtube_fetcher.httpx.AsyncClient", lambda **kw: client)

        fetcher = YouTubeLiveChatFetcher(video_id="vid123", api_key="key123")
        chat_id = await fetcher._resolve_live_chat_id()

        assert chat_id == "LC_test"
        assert "youtube/v3/videos" in client.captured_urls[0]

    @pytest.mark.asyncio
    async def test_resolve_no_items(self, monkeypatch):
        client = FakeAsyncClient([FakeHTTPResponse({"items": []})])
        monkeypatch.setattr("backend.services.chat_bridge.youtube_fetcher.httpx.AsyncClient", lambda **kw: client)

        fetcher = YouTubeLiveChatFetcher(video_id="bad_id", api_key="key123")
        with pytest.raises(ValueError, match="Video not found"):
            await fetcher._resolve_live_chat_id()

    @pytest.mark.asyncio
    async def test_resolve_no_active_chat(self, monkeypatch):
        data = {"items": [{"liveStreamingDetails": {}}]}
        client = FakeAsyncClient([FakeHTTPResponse(data)])
        monkeypatch.setattr("backend.services.chat_bridge.youtube_fetcher.httpx.AsyncClient", lambda **kw: client)

        fetcher = YouTubeLiveChatFetcher(video_id="vid_offline", api_key="key123")
        with pytest.raises(ValueError, match="No active live chat"):
            await fetcher._resolve_live_chat_id()


class TestFetchMessages:
    @pytest.mark.asyncio
    async def test_parses_messages(self, monkeypatch):
        videos_resp = FakeHTTPResponse(_videos_response())
        chat_resp = FakeHTTPResponse(_live_chat_response(
            messages=[
                {"text": "こんにちは！", "user_id": "UC_a", "user_name": "Alice"},
                {"text": "ニアちゃん可愛い", "user_id": "UC_b", "user_name": "Bob"},
            ],
            next_page_token="page_2",
            polling_interval_ms=8000,
        ))
        client = FakeAsyncClient([videos_resp, chat_resp])
        monkeypatch.setattr("backend.services.chat_bridge.youtube_fetcher.httpx.AsyncClient", lambda **kw: client)

        fetcher = YouTubeLiveChatFetcher(video_id="vid", api_key="key")
        msgs = await fetcher.fetch_messages()

        assert len(msgs) == 2
        assert msgs[0]["text"] == "こんにちは！"
        assert msgs[0]["user_name"] == "Alice"
        assert msgs[1]["user_id"] == "UC_b"

    @pytest.mark.asyncio
    async def test_updates_page_token(self, monkeypatch):
        videos_resp = FakeHTTPResponse(_videos_response())
        chat_resp = FakeHTTPResponse(_live_chat_response(
            messages=[], next_page_token="new_token",
        ))
        client = FakeAsyncClient([videos_resp, chat_resp])
        monkeypatch.setattr("backend.services.chat_bridge.youtube_fetcher.httpx.AsyncClient", lambda **kw: client)

        fetcher = YouTubeLiveChatFetcher(video_id="vid", api_key="key")
        await fetcher.fetch_messages()

        assert fetcher._page_token == "new_token"

    @pytest.mark.asyncio
    async def test_poll_interval_from_api(self, monkeypatch):
        videos_resp = FakeHTTPResponse(_videos_response())
        chat_resp = FakeHTTPResponse(_live_chat_response(
            messages=[], polling_interval_ms=12000,
        ))
        client = FakeAsyncClient([videos_resp, chat_resp])
        monkeypatch.setattr("backend.services.chat_bridge.youtube_fetcher.httpx.AsyncClient", lambda **kw: client)

        fetcher = YouTubeLiveChatFetcher(video_id="vid", api_key="key")
        await fetcher.fetch_messages()

        assert fetcher._poll_interval_sec == 12.0

    @pytest.mark.asyncio
    async def test_poll_override_ignores_api_interval(self, monkeypatch):
        videos_resp = FakeHTTPResponse(_videos_response())
        chat_resp = FakeHTTPResponse(_live_chat_response(
            messages=[], polling_interval_ms=12000,
        ))
        client = FakeAsyncClient([videos_resp, chat_resp])
        monkeypatch.setattr("backend.services.chat_bridge.youtube_fetcher.httpx.AsyncClient", lambda **kw: client)

        fetcher = YouTubeLiveChatFetcher(video_id="vid", api_key="key", poll_override_sec=10)
        await fetcher.fetch_messages()

        assert fetcher._poll_interval_sec == 10  # Override, not 12
