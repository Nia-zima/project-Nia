"""Tests for ChatBridge manager."""
from __future__ import annotations

import asyncio
import pytest

from backend.core.db import init_schema


@pytest.fixture(autouse=True)
def _setup():
    init_schema()
    yield


class TestChatBridgeEnqueue:
    @pytest.mark.asyncio
    async def test_enqueue_sets_source_youtube(self):
        from backend.services.chat_bridge import ChatBridge

        bridge = ChatBridge()
        await bridge._enqueue_comment(
            text="ニアちゃんこんにちは！",
            user_id="UC_test",
            user_name="TestUser",
            source="youtube",
        )

        assert bridge._stats["youtube_received"] == 1
        assert bridge._stats["enqueued"] == 1

    @pytest.mark.asyncio
    async def test_enqueue_sets_source_twitch(self):
        from backend.services.chat_bridge import ChatBridge

        bridge = ChatBridge()
        await bridge._enqueue_comment(
            text="ニアさんすごい！面白い配信だね",
            user_id="twitch:viewer1",
            user_name="viewer1",
            source="twitch",
        )

        assert bridge._stats["twitch_received"] == 1
        assert bridge._stats["enqueued"] == 1

    @pytest.mark.asyncio
    async def test_short_text_filtered(self):
        from backend.services.chat_bridge import ChatBridge

        bridge = ChatBridge()
        await bridge._enqueue_comment(
            text="hi",  # Too short (< 5 chars)
            user_id="UC_test",
            user_name="TestUser",
            source="youtube",
        )

        assert bridge._stats["youtube_received"] == 1
        assert bridge._stats["filtered"] == 1
        assert bridge._stats["enqueued"] == 0


class TestChatBridgeLifecycle:
    @pytest.mark.asyncio
    async def test_start_youtube_no_video_id(self):
        from backend.services.chat_bridge import ChatBridge

        bridge = ChatBridge()
        result = await bridge.start_youtube(video_id="")
        assert result["ok"] is False
        assert result["reason"] == "no_video_id"

    @pytest.mark.asyncio
    async def test_start_twitch_no_channel(self):
        from backend.services.chat_bridge import ChatBridge

        bridge = ChatBridge()
        result = await bridge.start_twitch(channel="")
        assert result["ok"] is False
        assert result["reason"] == "no_channel"

    @pytest.mark.asyncio
    async def test_start_youtube_no_api_key(self, monkeypatch):
        from backend.services.chat_bridge import ChatBridge

        monkeypatch.setattr("backend.services.chat_bridge.settings.GOOGLE_API_KEY", "")
        bridge = ChatBridge()
        result = await bridge.start_youtube(video_id="vid123")
        assert result["ok"] is False
        assert result["reason"] == "no_api_key"

    @pytest.mark.asyncio
    async def test_stop_youtube_when_not_running(self):
        from backend.services.chat_bridge import ChatBridge

        bridge = ChatBridge()
        result = await bridge.stop_youtube()
        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_stop_twitch_when_not_running(self):
        from backend.services.chat_bridge import ChatBridge

        bridge = ChatBridge()
        result = await bridge.stop_twitch()
        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_stop_all(self):
        from backend.services.chat_bridge import ChatBridge

        bridge = ChatBridge()
        result = await bridge.stop_all()
        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_status_reflects_state(self):
        from backend.services.chat_bridge import ChatBridge

        bridge = ChatBridge()
        status = bridge.get_status()

        assert status["youtube"]["running"] is False
        assert status["twitch"]["running"] is False
        assert status["enqueued"] == 0

    @pytest.mark.asyncio
    async def test_duplicate_youtube_start_rejected(self, monkeypatch):
        from backend.services.chat_bridge import ChatBridge

        monkeypatch.setattr("backend.services.chat_bridge.settings.GOOGLE_API_KEY", "fake_key")

        bridge = ChatBridge()

        # Simulate a running task
        async def _noop():
            await asyncio.sleep(9999)

        bridge._youtube_task = asyncio.create_task(_noop())
        try:
            result = await bridge.start_youtube(video_id="vid123")
            assert result["ok"] is False
            assert result["reason"] == "already_running"
        finally:
            bridge._youtube_task.cancel()
            try:
                await bridge._youtube_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_duplicate_twitch_start_rejected(self):
        from backend.services.chat_bridge import ChatBridge

        bridge = ChatBridge()

        async def _noop():
            await asyncio.sleep(9999)

        bridge._twitch_task = asyncio.create_task(_noop())
        try:
            result = await bridge.start_twitch(channel="test_ch")
            assert result["ok"] is False
            assert result["reason"] == "already_running"
        finally:
            bridge._twitch_task.cancel()
            try:
                await bridge._twitch_task
            except asyncio.CancelledError:
                pass
