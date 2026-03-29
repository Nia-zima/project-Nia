"""Tests for shared retry utilities."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


class TestRetryAsync:
    async def test_succeeds_first_try(self):
        from backend.core.retry import retry_async

        fn = AsyncMock(return_value="ok")
        result = await retry_async(fn, max_retries=2, service_name="test")
        assert result == "ok"
        assert fn.call_count == 1

    async def test_succeeds_after_failure(self):
        from backend.core.retry import retry_async

        fn = AsyncMock(side_effect=[ConnectionError("fail"), "ok"])
        with patch("backend.core.retry.asyncio.sleep", new_callable=AsyncMock):
            result = await retry_async(
                fn,
                max_retries=2,
                base_delay=0.01,
                retryable_exceptions=(ConnectionError,),
                service_name="test",
            )
        assert result == "ok"
        assert fn.call_count == 2

    async def test_exhausts_retries(self):
        from backend.core.retry import retry_async
        import pytest

        fn = AsyncMock(side_effect=ConnectionError("always fails"))
        with patch("backend.core.retry.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ConnectionError):
                await retry_async(
                    fn,
                    max_retries=2,
                    base_delay=0.01,
                    retryable_exceptions=(ConnectionError,),
                    service_name="test",
                )
        assert fn.call_count == 3  # initial + 2 retries

    async def test_non_retryable_exception_raises_immediately(self):
        from backend.core.retry import retry_async
        import pytest

        fn = AsyncMock(side_effect=ValueError("not retryable"))
        with pytest.raises(ValueError):
            await retry_async(
                fn,
                max_retries=2,
                retryable_exceptions=(ConnectionError,),
                service_name="test",
            )
        assert fn.call_count == 1


class TestRetrySync:
    def test_succeeds_first_try(self):
        from backend.core.retry import retry_sync

        fn = MagicMock(return_value="ok")
        with patch("backend.core.retry.time.sleep"):
            result = retry_sync(fn, max_retries=2, service_name="test")
        assert result == "ok"

    def test_succeeds_after_failure(self):
        from backend.core.retry import retry_sync

        fn = MagicMock(side_effect=[TimeoutError("fail"), "ok"])
        with patch("backend.core.retry.time.sleep"):
            result = retry_sync(
                fn,
                max_retries=2,
                base_delay=0.01,
                retryable_exceptions=(TimeoutError,),
                service_name="test",
            )
        assert result == "ok"
        assert fn.call_count == 2

    def test_exhausts_retries(self):
        from backend.core.retry import retry_sync
        import pytest

        fn = MagicMock(side_effect=TimeoutError("always"))
        with patch("backend.core.retry.time.sleep"):
            with pytest.raises(TimeoutError):
                retry_sync(
                    fn,
                    max_retries=1,
                    base_delay=0.01,
                    retryable_exceptions=(TimeoutError,),
                    service_name="test",
                )
        assert fn.call_count == 2  # initial + 1 retry
