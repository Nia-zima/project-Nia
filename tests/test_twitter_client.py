"""Tests for Twitter client — tweet generation, cleaning, and posting."""
import pytest
from unittest.mock import AsyncMock, patch


# ── _clean_tweet tests ────────────────────────────────────────────


class TestCleanTweet:
    def test_basic_text(self):
        from backend.services.twitter_client import _clean_tweet
        assert _clean_tweet("今日はいい天気だったので散歩してきました。", 280) == "今日はいい天気だったので散歩してきました。"

    def test_strips_japanese_quotes(self):
        from backend.services.twitter_client import _clean_tweet
        assert _clean_tweet("「今日はいい天気だったので散歩してきました。」", 280) == "今日はいい天気だったので散歩してきました。"

    def test_strips_tweet_prefix(self):
        from backend.services.twitter_client import _clean_tweet
        assert _clean_tweet("ツイート: 今日はいい天気だったので散歩した。", 280) == "今日はいい天気だったので散歩した。"

    def test_strips_tweet_prefix_fullwidth(self):
        from backend.services.twitter_client import _clean_tweet
        assert _clean_tweet("ツイート：今日はいい天気だったので散歩した。", 280) == "今日はいい天気だったので散歩した。"

    def test_truncates_long_text(self):
        from backend.services.twitter_client import _clean_tweet
        long_text = "あ" * 300
        result = _clean_tweet(long_text, 280)
        assert result is not None
        assert len(result) <= 280

    def test_truncates_at_sentence_boundary(self):
        from backend.services.twitter_client import _clean_tweet
        text = "最初の文です。二番目の文。" + "あ" * 270
        result = _clean_tweet(text, 280)
        assert result is not None
        assert result.endswith("。")
        assert len(result) <= 280

    def test_strips_urls(self):
        from backend.services.twitter_client import _clean_tweet
        result = _clean_tweet("今日は面白い記事を見つけたよ https://example.com 読んでみてね", 280)
        assert result is not None
        assert "http" not in result

    def test_returns_none_for_empty(self):
        from backend.services.twitter_client import _clean_tweet
        assert _clean_tweet("", 280) is None

    def test_returns_none_for_whitespace(self):
        from backend.services.twitter_client import _clean_tweet
        assert _clean_tweet("   ", 280) is None

    def test_rejects_garbage_output(self):
        """LLM garbage output (non-Japanese, too short) is rejected."""
        from backend.services.twitter_client import _clean_tweet
        for garbage in ["руб", "_nullable", "麽", "tou", "голос", "giản"]:
            assert _clean_tweet(garbage, 280) is None, f"Should reject: {garbage}"

    def test_rejects_meta_commentary(self):
        """LLM instruction echoing is rejected."""
        from backend.services.twitter_client import _clean_tweet
        assert _clean_tweet("字数制限厳守のため、作成いたします。", 280) is None

    def test_strips_mumble_prefix(self):
        """LLM meta-prefixes like 呟き: are stripped."""
        from backend.services.twitter_client import _clean_tweet
        result = _clean_tweet("呟き: 今日はなんだかぼんやりした一日だった。", 280)
        assert result == "今日はなんだかぼんやりした一日だった。"


# ── generate_tweet tests ─────────────────────────────────────────


class TestGenerateTweet:
    @pytest.mark.asyncio
    async def test_casual_style(self):
        with patch(
            "backend.services.twitter_client.call_llm", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = "今日はいい天気だったなぁ。"
            from backend.services.twitter_client import twitter_client
            result = await twitter_client.generate_tweet(style="casual", context="test")
            assert result == "今日はいい天気だったなぁ。"
            mock_llm.assert_called_once()

    @pytest.mark.asyncio
    async def test_diary_style(self):
        with patch(
            "backend.services.twitter_client.call_llm", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = "今日はOriginとたくさん話した。楽しかった。"
            from backend.services.twitter_client import twitter_client
            result = await twitter_client.generate_tweet(
                style="diary", context="技術の話をした"
            )
            assert result is not None
            assert len(result) <= 280

    @pytest.mark.asyncio
    async def test_returns_none_on_llm_failure(self):
        with patch(
            "backend.services.twitter_client.call_llm", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = None
            from backend.services.twitter_client import twitter_client
            result = await twitter_client.generate_tweet(style="casual", context="test")
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_empty_response(self):
        with patch(
            "backend.services.twitter_client.call_llm", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = "   "
            from backend.services.twitter_client import twitter_client
            result = await twitter_client.generate_tweet(style="casual", context="test")
            assert result is None


# ── post_tweet tests ─────────────────────────────────────────────


class TestPostTweet:
    @pytest.mark.asyncio
    async def test_disabled_returns_error(self):
        from backend.services.twitter_client import TwitterClient
        client = TwitterClient()
        client.enabled = False
        result = await client.post_tweet("test tweet")
        assert not result.success
        assert "disabled" in (result.error or "")

    @pytest.mark.asyncio
    async def test_exceeds_max_chars(self):
        from backend.services.twitter_client import TwitterClient
        client = TwitterClient()
        client.enabled = True
        result = await client.post_tweet("あ" * 300)
        assert not result.success
        assert "exceeds" in (result.error or "")

    @pytest.mark.asyncio
    async def test_tweepy_not_installed(self):
        from backend.services.twitter_client import TwitterClient
        client = TwitterClient()
        client.enabled = True
        with patch.dict("sys.modules", {"tweepy": None}):
            result = await client.post_tweet("テスト")
            assert not result.success


# ── Executor handler tests ───────────────────────────────────────


class TestExecutorHandler:
    @pytest.mark.asyncio
    async def test_handle_post_tweet_success(self):
        mock_result = {
            "success": True,
            "tweet_id": "12345",
            "tweet_text": "テストツイート",
            "proposal": {"proposal_id": "prop-1"},
        }
        with patch(
            "backend.services.x_post_service.x_post_service"
        ) as mock_service:
            mock_service.publish_approved_text = AsyncMock(return_value=mock_result)
            from backend.core.actions.executor import action_executor
            result = await action_executor._handle_post_tweet(
                {"tweet_text": "テストツイート", "thread_id": "default_thread", "_pending_id": "p1"}
            )
            assert result["posted"] is True
            assert result["tweet_id"] == "12345"
            assert result["proposal_id"] == "prop-1"

    @pytest.mark.asyncio
    async def test_handle_post_tweet_missing_text(self):
        from backend.core.actions.executor import action_executor
        with pytest.raises(ValueError, match="tweet_text is required"):
            await action_executor._handle_post_tweet({"tweet_text": ""})

    @pytest.mark.asyncio
    async def test_handle_post_tweet_failure(self):
        mock_result = {"success": False, "error": "API error", "proposal": {"proposal_id": "prop-1"}}
        with patch(
            "backend.services.x_post_service.x_post_service"
        ) as mock_service:
            mock_service.publish_approved_text = AsyncMock(return_value=mock_result)
            from backend.core.actions.executor import action_executor
            with pytest.raises(RuntimeError, match="Tweet failed"):
                await action_executor._handle_post_tweet(
                    {"tweet_text": "テスト", "thread_id": "default_thread"}
                )


# ── Action registration tests ────────────────────────────────────


class TestActionRegistration:
    def test_post_tweet_registered(self):
        from backend.core.actions import action_registry
        action = action_registry.get("post_tweet")
        assert action is not None
        assert action.name == "ツイート投稿"
        assert action.requires_confirmation is True

    def test_post_tweet_is_medium_risk(self):
        from backend.core.actions import action_registry
        from backend.core.actions.types import RiskLevel
        action = action_registry.get("post_tweet")
        assert action is not None
        assert action.risk_level == RiskLevel.MEDIUM

    def test_post_tweet_is_communication(self):
        from backend.core.actions import action_registry
        from backend.core.actions.types import ActionCategory
        action = action_registry.get("post_tweet")
        assert action is not None
        assert action.category == ActionCategory.COMMUNICATION
