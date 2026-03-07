"""Shared retry utilities with exponential backoff + jitter.

Pattern extracted from backend/services/llm_client.py (L50-94).
"""
from __future__ import annotations

import asyncio
import logging
import random
import time

logger = logging.getLogger(__name__)


async def retry_async(
    fn,
    *,
    max_retries: int = 2,
    base_delay: float = 1.0,
    max_delay: float = 15.0,
    retryable_exceptions: tuple = (Exception,),
    service_name: str = "unknown",
):
    """Retry an async callable with exponential backoff + jitter.

    Args:
        fn: Async callable (no arguments) to retry.
        max_retries: Maximum number of retries (0 = no retry).
        base_delay: Base delay in seconds.
        max_delay: Maximum delay cap in seconds.
        retryable_exceptions: Tuple of exception types that trigger retry.
        service_name: Name for logging.

    Returns:
        The return value of fn().

    Raises:
        The last exception if all retries are exhausted.
    """
    attempt = 0
    while True:
        try:
            result = await fn()
            _record_success(service_name)
            return result
        except retryable_exceptions as e:
            if attempt >= max_retries:
                logger.error("[%s] failed after %d attempts: %r", service_name, attempt + 1, e)
                _record_error(service_name, str(e))
                raise
            delay = min(base_delay * (2 ** attempt) + random.uniform(0, 0.5), max_delay)
            logger.warning(
                "[%s] retry %d/%d in %.1fs: %r",
                service_name, attempt + 1, max_retries, delay, e,
            )
            await asyncio.sleep(delay)
            attempt += 1


def retry_sync(
    fn,
    *,
    max_retries: int = 2,
    base_delay: float = 1.0,
    max_delay: float = 15.0,
    retryable_exceptions: tuple = (Exception,),
    service_name: str = "unknown",
):
    """Synchronous variant of retry_async.

    Same parameters and behavior, but uses time.sleep instead of asyncio.sleep.
    """
    attempt = 0
    while True:
        try:
            result = fn()
            _record_success(service_name)
            return result
        except retryable_exceptions as e:
            if attempt >= max_retries:
                logger.error("[%s] failed after %d attempts: %r", service_name, attempt + 1, e)
                _record_error(service_name, str(e))
                raise
            delay = min(base_delay * (2 ** attempt) + random.uniform(0, 0.5), max_delay)
            logger.warning(
                "[%s] retry %d/%d in %.1fs: %r",
                service_name, attempt + 1, max_retries, delay, e,
            )
            time.sleep(delay)
            attempt += 1


def _record_success(service_name: str) -> None:
    try:
        from backend.core.service_health import service_health
        service_health.record_success(service_name)
    except Exception:
        pass


def _record_error(service_name: str, error: str) -> None:
    try:
        from backend.core.service_health import service_health
        service_health.record_error(service_name, error)
    except Exception:
        pass
