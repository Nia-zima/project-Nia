"""Tests for backend/services/llm_client.py."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from backend.services.llm_client import _strip_think_blocks, _chat_completions_url, call_llm


# ── Helpers for aiohttp mocking ──────────────────────────────────

class FakeResponse:
    """Lightweight stand-in for aiohttp.ClientResponse."""

    def __init__(self, status, *, json_data=None, text_data="", headers=None):
        self.status = status
        self._json = json_data
        self._text = text_data
        self.headers = headers or {}

    async def json(self):
        return self._json

    async def text(self):
        return self._text


class FakeACM:
    """Async context manager that returns a fixed value."""

    def __init__(self, value):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, *args):
        pass


class FakeSession:
    """Fake aiohttp.ClientSession supporting sequential responses."""

    def __init__(self, responses: list[FakeResponse]):
        self._responses = responses
        self._call_idx = 0
        self.captured_calls: list[dict] = []

    def post(self, url, *, json=None, headers=None):
        self.captured_calls.append({"url": url, "json": json, "headers": headers})
        resp = self._responses[min(self._call_idx, len(self._responses) - 1)]
        self._call_idx += 1
        return FakeACM(resp)


class FakeSessionRaising:
    """Fake session that raises on the first N calls, then succeeds."""

    def __init__(self, error: Exception, fail_count: int, success_resp: FakeResponse):
        self._error = error
        self._fail_count = fail_count
        self._success_resp = success_resp
        self._call_idx = 0

    def post(self, url, *, json=None, headers=None):
        self._call_idx += 1
        if self._call_idx <= self._fail_count:
            raise self._error
        return FakeACM(self._success_resp)


def _patch_llm(fake_session, **settings_overrides):
    """Return a context manager that patches settings + aiohttp.ClientSession."""
    s = MagicMock()
    s.OPENAI_BASE_URL = "http://localhost:1234/v1"
    s.OPENAI_MODEL = "test-model"
    s.OPENAI_API_KEY = "test-key"
    for k, v in settings_overrides.items():
        setattr(s, k, v)

    class _PatchCtx:
        def __enter__(self_):
            self_._p1 = patch("backend.services.llm_client.settings", s)
            self_._p2 = patch("backend.services.llm_client.aiohttp.ClientSession", return_value=FakeACM(fake_session))
            self_._p3 = patch("backend.services.llm_client.asyncio.sleep", return_value=None)
            # asyncio.sleep must be an awaitable
            import asyncio

            async def _noop_sleep(d):
                pass

            self_._p3 = patch("backend.services.llm_client.asyncio.sleep", side_effect=_noop_sleep)
            self_._p1.start()
            self_._p2.start()
            self_._p3.start()
            return self_

        def __exit__(self_, *args):
            self_._p3.stop()
            self_._p2.stop()
            self_._p1.stop()

    return _PatchCtx()


# ── _strip_think_blocks ──────────────────────────────────────────

class TestStripThinkBlocks:
    def test_no_think_tag(self):
        assert _strip_think_blocks("普通のテキスト") == "普通のテキスト"

    def test_single_think_block(self):
        assert _strip_think_blocks("<think>内部推論...</think>こんにちは") == "こんにちは"

    def test_multiline_think_block(self):
        assert _strip_think_blocks("<think>\nstep 1\nstep 2\n</think>\n結果だよ") == "結果だよ"

    def test_multiple_think_blocks(self):
        assert _strip_think_blocks("<think>A</think>途中<think>B</think>最後") == "途中最後"

    def test_empty_string(self):
        assert _strip_think_blocks("") == ""

    def test_only_think_block_salvages_inner(self):
        # Model put all content inside <think> — salvage it for structured output
        assert _strip_think_blocks("<think>全部推論</think>") == "全部推論"

    def test_empty_think_block_returns_empty(self):
        assert _strip_think_blocks("<think></think>") == ""
        assert _strip_think_blocks("<think>  </think>") == ""


# ── _chat_completions_url ────────────────────────────────────────

class TestChatCompletionsUrl:
    def test_base_without_v1(self):
        with patch("backend.services.llm_client.settings") as mock_s:
            mock_s.OPENAI_BASE_URL = "http://localhost:1234"
            assert _chat_completions_url() == "http://localhost:1234/v1/chat/completions"

    def test_base_with_v1(self):
        with patch("backend.services.llm_client.settings") as mock_s:
            mock_s.OPENAI_BASE_URL = "http://localhost:1234/v1"
            assert _chat_completions_url() == "http://localhost:1234/v1/chat/completions"

    def test_trailing_slash(self):
        with patch("backend.services.llm_client.settings") as mock_s:
            mock_s.OPENAI_BASE_URL = "http://localhost:1234/"
            assert _chat_completions_url() == "http://localhost:1234/v1/chat/completions"

    def test_v1_with_trailing_slash(self):
        with patch("backend.services.llm_client.settings") as mock_s:
            mock_s.OPENAI_BASE_URL = "http://localhost:1234/v1/"
            assert _chat_completions_url() == "http://localhost:1234/v1/chat/completions"


# ── call_llm ─────────────────────────────────────────────────────

class TestCallLlm:
    @pytest.mark.asyncio
    async def test_success(self):
        resp = FakeResponse(200, json_data={"choices": [{"message": {"content": "こんにちは"}}]})
        session = FakeSession([resp])
        with _patch_llm(session):
            result = await call_llm([{"role": "user", "content": "hi"}])
            assert result == "こんにちは"

    @pytest.mark.asyncio
    async def test_strips_think_blocks(self):
        resp = FakeResponse(200, json_data={"choices": [{"message": {"content": "<think>hmm</think>答え"}}]})
        session = FakeSession([resp])
        with _patch_llm(session):
            result = await call_llm([{"role": "user", "content": "hi"}])
            assert result == "答え"

    @pytest.mark.asyncio
    async def test_non_retryable_error(self):
        resp = FakeResponse(400, text_data="Bad Request")
        session = FakeSession([resp])
        with _patch_llm(session):
            result = await call_llm([{"role": "user", "content": "hi"}], max_retries=0)
            assert result is None

    @pytest.mark.asyncio
    async def test_retryable_then_success(self):
        """429 → 200 on retry."""
        fail = FakeResponse(429, text_data="Rate limited")
        ok = FakeResponse(200, json_data={"choices": [{"message": {"content": "ok"}}]})
        session = FakeSession([fail, ok])
        with _patch_llm(session):
            result = await call_llm(
                [{"role": "user", "content": "hi"}],
                max_retries=3,
                base_delay_sec=0.01,
            )
            assert result == "ok"
            assert session._call_idx == 2

    @pytest.mark.asyncio
    async def test_retry_after_header(self):
        """Retry-After header is respected."""
        fail = FakeResponse(429, text_data="wait", headers={"Retry-After": "0.01"})
        ok = FakeResponse(200, json_data={"choices": [{"message": {"content": "done"}}]})
        session = FakeSession([fail, ok])
        with _patch_llm(session):
            result = await call_llm(
                [{"role": "user", "content": "hi"}],
                max_retries=3,
                base_delay_sec=0.01,
            )
            assert result == "done"

    @pytest.mark.asyncio
    async def test_server_error_retries(self):
        """500/502/503/504 are retryable."""
        for status in (500, 502, 503, 504):
            fail = FakeResponse(status, text_data="error")
            ok = FakeResponse(200, json_data={"choices": [{"message": {"content": "ok"}}]})
            session = FakeSession([fail, ok])
            with _patch_llm(session):
                result = await call_llm(
                    [{"role": "user", "content": "hi"}],
                    max_retries=2,
                    base_delay_sec=0.01,
                )
                assert result == "ok", f"status {status} should be retryable"

    @pytest.mark.asyncio
    async def test_connection_error_retry(self):
        """Connection error triggers retry, then succeeds."""
        ok = FakeResponse(200, json_data={"choices": [{"message": {"content": "recovered"}}]})
        session = FakeSessionRaising(ConnectionError("refused"), fail_count=2, success_resp=ok)
        with _patch_llm(session):
            result = await call_llm(
                [{"role": "user", "content": "hi"}],
                max_retries=3,
                base_delay_sec=0.01,
            )
            assert result == "recovered"

    @pytest.mark.asyncio
    async def test_max_retries_exceeded_returns_none(self):
        """All retries fail → None."""
        fail = FakeResponse(500, text_data="Internal Server Error")
        session = FakeSession([fail])  # always returns same fail response
        with _patch_llm(session):
            result = await call_llm(
                [{"role": "user", "content": "hi"}],
                max_retries=1,
                base_delay_sec=0.01,
            )
            assert result is None

    @pytest.mark.asyncio
    async def test_no_api_key_omits_auth_header(self):
        """When OPENAI_API_KEY is empty, Authorization header is not sent."""
        resp = FakeResponse(200, json_data={"choices": [{"message": {"content": "ok"}}]})
        session = FakeSession([resp])
        with _patch_llm(session, OPENAI_API_KEY=""):
            result = await call_llm([{"role": "user", "content": "hi"}])
            assert result == "ok"
            assert "Authorization" not in session.captured_calls[0]["headers"]

    @pytest.mark.asyncio
    async def test_empty_content_returns_as_is(self):
        """Empty content string is returned without stripping."""
        resp = FakeResponse(200, json_data={"choices": [{"message": {"content": ""}}]})
        session = FakeSession([resp])
        with _patch_llm(session):
            result = await call_llm([{"role": "user", "content": "hi"}])
            assert result == ""

    @pytest.mark.asyncio
    async def test_null_content_returns_none(self):
        """null content is returned as None."""
        resp = FakeResponse(200, json_data={"choices": [{"message": {"content": None}}]})
        session = FakeSession([resp])
        with _patch_llm(session):
            result = await call_llm([{"role": "user", "content": "hi"}])
            assert result is None
