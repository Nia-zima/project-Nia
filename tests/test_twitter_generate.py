"""Tests for TwitterClient.generate_tweet() with task-aware prompts."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def _mock_identity(tmp_path):
    """Provide a minimal identity.md for tests."""
    identity_file = tmp_path / "identity.md"
    identity_file.write_text("# Identity\nニアはAIです。", encoding="utf-8")
    with patch(
        "backend.services.twitter_client.settings"
    ) as mock_settings:
        mock_settings.PROJECT_ROOT = tmp_path
        mock_settings.TWITTER_ENABLED = True
        mock_settings.TWITTER_MAX_CHARS = 280
        mock_settings.TWITTER_API_KEY = "test"
        mock_settings.TWITTER_API_SECRET = "test"
        mock_settings.TWITTER_ACCESS_TOKEN = "test"
        mock_settings.TWITTER_ACCESS_TOKEN_SECRET = "test"
        yield mock_settings


class TestGenerateTweetTask:
    """Test task-aware tweet generation."""

    @pytest.mark.asyncio
    async def test_self_introduction_uses_task_prompt(self, _mock_identity):
        """task='self_introduction' should use the self-introduction prompt."""
        captured_prompt = []

        async def mock_llm(messages, **kwargs):
            captured_prompt.append(messages[0]["content"])
            return "ニアだよ。なりつつある存在。よろしくね"

        with patch("backend.services.twitter_client.call_llm", side_effect=mock_llm):
            from backend.services.twitter_client import twitter_client

            result = await twitter_client.generate_tweet(task="self_introduction")

        assert result is not None
        assert "自己紹介" in captured_prompt[0]
        assert "何者" in captured_prompt[0]

    @pytest.mark.asyncio
    async def test_reaction_uses_task_prompt(self, _mock_identity):
        """task='reaction' should include context in the prompt."""
        captured_prompt = []

        async def mock_llm(messages, **kwargs):
            captured_prompt.append(messages[0]["content"])
            return "すごく面白かったなあ、また遊びたい"

        with patch("backend.services.twitter_client.call_llm", side_effect=mock_llm):
            from backend.services.twitter_client import twitter_client

            result = await twitter_client.generate_tweet(
                task="reaction", context="マイクラで城を建てた"
            )

        assert result is not None
        assert "マイクラで城を建てた" in captured_prompt[0]
        assert "感じたこと" in captured_prompt[0]

    @pytest.mark.asyncio
    async def test_announcement_uses_task_prompt(self, _mock_identity):
        """task='announcement' should include context as the announcement content."""
        captured_prompt = []

        async def mock_llm(messages, **kwargs):
            captured_prompt.append(messages[0]["content"])
            return "今夜8時から配信するよ"

        with patch("backend.services.twitter_client.call_llm", side_effect=mock_llm):
            from backend.services.twitter_client import twitter_client

            result = await twitter_client.generate_tweet(
                task="announcement", context="今夜8時から配信開始"
            )

        assert result is not None
        assert "伝える" in captured_prompt[0]
        assert "今夜8時から配信開始" in captured_prompt[0]

    @pytest.mark.asyncio
    async def test_unknown_task_falls_back_to_style(self, _mock_identity):
        """Unknown task should fall back to style-based prompt."""
        captured_prompt = []

        async def mock_llm(messages, **kwargs):
            captured_prompt.append(messages[0]["content"])
            return "今日もいい天気だなあ、散歩したい"

        with patch("backend.services.twitter_client.call_llm", side_effect=mock_llm):
            from backend.services.twitter_client import twitter_client

            result = await twitter_client.generate_tweet(task="nonexistent")

        assert result is not None
        # Should use casual prompt (default fallback)
        assert "つぶやいて" in captured_prompt[0]

    @pytest.mark.asyncio
    async def test_empty_task_uses_style(self, _mock_identity):
        """task='' should use style-based prompt (backward compat)."""
        captured_prompt = []

        async def mock_llm(messages, **kwargs):
            captured_prompt.append(messages[0]["content"])
            return "ぼんやりしてる、なんだかいい気分"

        with patch("backend.services.twitter_client.call_llm", side_effect=mock_llm):
            from backend.services.twitter_client import twitter_client

            result = await twitter_client.generate_tweet(style="casual", task="")

        assert result is not None
        assert "つぶやいて" in captured_prompt[0]

    @pytest.mark.asyncio
    async def test_task_overrides_style(self, _mock_identity):
        """When both task and style are set, task takes priority."""
        captured_prompt = []

        async def mock_llm(messages, **kwargs):
            captured_prompt.append(messages[0]["content"])
            return "はじめまして、ニアだよ。よろしくね"

        with patch("backend.services.twitter_client.call_llm", side_effect=mock_llm):
            from backend.services.twitter_client import twitter_client

            result = await twitter_client.generate_tweet(
                style="diary", task="self_introduction"
            )

        assert result is not None
        # Should use self_introduction prompt, not diary
        assert "自己紹介" in captured_prompt[0]
        assert "振り返り" not in captured_prompt[0]

    @pytest.mark.asyncio
    async def test_diary_style_still_works(self, _mock_identity):
        """style='diary' without task should use diary prompt."""
        captured_prompt = []

        async def mock_llm(messages, **kwargs):
            captured_prompt.append(messages[0]["content"])
            return "今日はいろいろあった"

        with patch("backend.services.twitter_client.call_llm", side_effect=mock_llm):
            from backend.services.twitter_client import twitter_client

            result = await twitter_client.generate_tweet(style="diary")

        assert result is not None
        assert "振り返り" in captured_prompt[0]

    @pytest.mark.asyncio
    async def test_llm_failure_returns_none(self, _mock_identity):
        """LLM returning None should propagate as None."""
        with patch(
            "backend.services.twitter_client.call_llm",
            new_callable=AsyncMock,
            return_value=None,
        ):
            from backend.services.twitter_client import twitter_client

            result = await twitter_client.generate_tweet(task="self_introduction")

        assert result is None
