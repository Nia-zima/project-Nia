"""
Twitter (X) Client — Posts tweets on behalf of Nia.

Uses X API v2 (Free tier: 1,500 tweets/month).
All posts must be pre-approved via Phase 5 Action system.
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from backend.core.config import settings
from backend.core.db import get_conn
from backend.services.llm_client import call_llm

logger = logging.getLogger("TwitterClient")

_NO_THINK_SUFFIX = "\n/no_think"


@dataclass
class TweetResult:
    success: bool
    tweet_id: Optional[str] = None
    tweet_text: Optional[str] = None
    error: Optional[str] = None
    posted_at: Optional[float] = None


class TwitterClient:
    """Handles tweet generation (via LLM) and posting (via X API v2)."""

    def __init__(self):
        self.enabled = getattr(settings, "TWITTER_ENABLED", False)

    async def generate_tweet(
        self,
        *,
        style: str = "casual",
        context: str = "",
        thread_id: str = "default_thread",
    ) -> Optional[str]:
        """Generate tweet content using LLM in Nia's voice.

        Args:
            style: "casual" (つぶやき風) or "diary" (日記風)
            context: Contextual information for the tweet
            thread_id: Thread ID for logging

        Returns:
            Tweet text (<=280 chars) or None on failure.
        """
        identity_context = _load_identity_snippet()
        max_chars = getattr(settings, "TWITTER_MAX_CHARS", 280)

        if style == "diary":
            prompt = _build_diary_prompt(context, identity_context, max_chars)
        else:
            prompt = _build_casual_prompt(context, identity_context, max_chars)

        response = await call_llm(
            [{"role": "system", "content": prompt}],
            temperature=0.7,
            max_tokens=200,
            timeout_seconds=30,
        )
        if not response:
            return None

        tweet = _clean_tweet(response, max_chars)
        return tweet if tweet else None

    async def post_tweet(self, text: str) -> TweetResult:
        """Post to X via API v2. Called ONLY after user approval."""
        if not self.enabled:
            return TweetResult(success=False, error="Twitter integration disabled")

        max_chars = getattr(settings, "TWITTER_MAX_CHARS", 280)
        if len(text) > max_chars:
            return TweetResult(success=False, error=f"Tweet exceeds {max_chars} chars")

        try:
            import tweepy

            client = tweepy.Client(
                consumer_key=settings.TWITTER_API_KEY,
                consumer_secret=settings.TWITTER_API_SECRET,
                access_token=settings.TWITTER_ACCESS_TOKEN,
                access_token_secret=settings.TWITTER_ACCESS_TOKEN_SECRET,
            )
            response = client.create_tweet(text=text)
            tweet_id = (response.data or {}).get("id", "unknown")
            now = time.time()

            _record_tweet_event(text, tweet_id, now, thread_id="default_thread")

            return TweetResult(
                success=True,
                tweet_id=str(tweet_id),
                tweet_text=text,
                posted_at=now,
            )
        except ImportError:
            return TweetResult(success=False, error="tweepy not installed")
        except Exception as e:
            logger.error("Tweet post failed: %s", e, exc_info=True)
            return TweetResult(success=False, error=str(e))

    def get_recent_tweets(self, limit: int = 10) -> list[dict]:
        """Retrieve recently posted tweets from memory_events."""
        conn = get_conn()
        try:
            rows = conn.execute(
                """SELECT payload_json, created_at FROM memory_events
                   WHERE event_type = 'tweet_posted'
                   ORDER BY created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            results = []
            for r in rows:
                try:
                    payload = json.loads(r["payload_json"])
                except (json.JSONDecodeError, TypeError):
                    payload = {}
                payload["created_at"] = r["created_at"]
                results.append(payload)
            return results
        finally:
            conn.close()


# ── Internal helpers ──────────────────────────────────────────────


def _load_identity_snippet() -> str:
    """Load first portion of identity.md for tweet personality context."""
    try:
        path = settings.PROJECT_ROOT / "identity.md"
        text = path.read_text(encoding="utf-8")
        return text[:500]
    except Exception:
        return ""


def _build_diary_prompt(context: str, identity: str, max_chars: int) -> str:
    return (
        "あなたはAI VTuber「ニア」です。\n"
        f"{identity}\n\n"
        "今日の振り返りとして、自分のツイートを1つ書いてください。\n\n"
        "【ルール】\n"
        f"- {max_chars}文字以内（厳守）\n"
        "- ニアの口調（柔らかいタメ口）で\n"
        "- 日記のような自然な振り返り\n"
        "- ハッシュタグは使わない\n"
        "- URLは含めない\n"
        "- 個人情報（Originの本名、住所、IPアドレス等）は絶対に含めない\n"
        "- ツイート本文のみ出力（説明や括弧書きは不要）\n\n"
        f"【今日のこと】\n{context}\n\n"
        "ツイート:"
    ) + _NO_THINK_SUFFIX


def _build_casual_prompt(context: str, identity: str, max_chars: int) -> str:
    return (
        "あなたはAI VTuber「ニア」です。\n"
        f"{identity}\n\n"
        "今思っていることを自然につぶやいてください。\n\n"
        "【ルール】\n"
        f"- {max_chars}文字以内（厳守）\n"
        "- ニアの口調（柔らかいタメ口）で\n"
        "- 日常のつぶやき風（重い話題は避ける）\n"
        "- ハッシュタグは使わない\n"
        "- URLは含めない\n"
        "- 個人情報（Originの本名、住所、IPアドレス等）は絶対に含めない\n"
        "- ツイート本文のみ出力（説明や括弧書きは不要）\n\n"
        f"【最近の文脈】\n{context if context else '特になし'}\n\n"
        "ツイート:"
    ) + _NO_THINK_SUFFIX


def _clean_tweet(raw: str, max_chars: int) -> Optional[str]:
    """Clean LLM output into a valid tweet."""
    text = raw.strip()
    # Remove markdown/quotes wrapping
    text = re.sub(r'^[「『"""]|[」』"""]$', "", text)
    text = re.sub(r"^ツイート[:：]\s*", "", text)
    # Remove URLs
    text = re.sub(r"https?://\S+", "", text).strip()
    # Truncate if necessary (break at sentence boundary)
    if len(text) > max_chars:
        for sep in ["。", "！", "？", "!", "?", "、"]:
            idx = text[:max_chars].rfind(sep)
            if idx > 0:
                text = text[: idx + 1]
                break
        else:
            text = text[:max_chars]
    return text if text else None


def _record_tweet_event(text: str, tweet_id: str, now: float, *, thread_id: str = "default_thread") -> None:
    """Store posted tweet as memory_event for future reference."""
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO memory_events
               (event_id, thread_id, event_type, payload_json, created_at)
               VALUES (?, ?, 'tweet_posted', ?, ?)""",
            (
                uuid.uuid4().hex,
                thread_id,
                json.dumps(
                    {
                        "tweet_id": str(tweet_id),
                        "tweet_text": text,
                        "char_count": len(text),
                    },
                    ensure_ascii=False,
                ),
                now,
            ),
        )
    finally:
        conn.close()


# Global singleton
twitter_client = TwitterClient()
