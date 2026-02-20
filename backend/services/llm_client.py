from __future__ import annotations

import aiohttp
import asyncio
import logging
import random
import re
from typing import Any, Dict, List, Optional

from backend.core.config import settings

logger = logging.getLogger("LLMClient")

_THINK_RE = re.compile(r"<think>[\s\S]*?</think>", re.DOTALL)


def _strip_think_blocks(text: str) -> str:
    """Remove <think>...</think> blocks (Qwen3 reasoning traces)."""
    return _THINK_RE.sub("", text).strip()


def _chat_completions_url() -> str:
    base = settings.OPENAI_BASE_URL.rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    return f"{base}/chat/completions"


async def call_llm(
    messages: List[Dict[str, Any]],
    *,
    temperature: float = 0.4,
    max_tokens: int = 1000,
    timeout_seconds: int = 60,
    max_retries: int = 3,
    base_delay_sec: float = 1.0,
) -> Optional[str]:
    payload = {
        "model": settings.OPENAI_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    url = _chat_completions_url()
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    headers = {"Content-Type": "application/json"}
    if settings.OPENAI_API_KEY:
        headers["Authorization"] = f"Bearer {settings.OPENAI_API_KEY}"

    attempt = 0
    while True:
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        raw = data["choices"][0]["message"]["content"]
                        return _strip_think_blocks(raw) if raw else raw

                    body = await resp.text()
                    if resp.status in (408, 429, 500, 502, 503, 504) and attempt < max_retries:
                        retry_after = resp.headers.get("Retry-After")
                        if retry_after:
                            try:
                                delay = float(retry_after)
                            except Exception:
                                delay = base_delay_sec * (2 ** attempt)
                        else:
                            delay = base_delay_sec * (2 ** attempt)

                        # small jitter to avoid thundering herd
                        delay = min(delay + random.uniform(0, 0.5), 30.0)
                        logger.warning(
                            "LLM retryable error status=%s attempt=%s delay=%.2fs body=%s",
                            resp.status,
                            attempt + 1,
                            delay,
                            body[:200],
                        )
                        await asyncio.sleep(delay)
                        attempt += 1
                        continue

                    logger.error("LLM Error: status=%s body=%s", resp.status, body[:400])
                    return None
        except Exception as e:
            if attempt < max_retries:
                delay = min(base_delay_sec * (2 ** attempt) + random.uniform(0, 0.5), 30.0)
                logger.warning("LLM connection error attempt=%s delay=%.2fs err=%r", attempt + 1, delay, e)
                await asyncio.sleep(delay)
                attempt += 1
                continue
            logger.error("LLM connection failed after %s attempts: %r", max_retries + 1, e)
            return None
