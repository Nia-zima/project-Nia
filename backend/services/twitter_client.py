"""
Twitter (X) Client — low-level generation and transport for Nia.

All posting policy and approval logic must live above this module.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Optional

from backend.core.config import settings
from backend.core.db import managed_conn
from backend.services.llm_client import call_llm

logger = logging.getLogger("TwitterClient")

from backend.core.model_adapter import prompt_suffix as _no_think_suffix  # noqa: E402


@dataclass
class TweetResult:
    success: bool
    tweet_id: Optional[str] = None
    tweet_text: Optional[str] = None
    error: Optional[str] = None
    posted_at: Optional[float] = None


class TwitterClient:
    """Handles tweet generation (via LLM) and raw posting transport."""

    def __init__(self):
        self._enabled_override: Optional[bool] = None

    @property
    def enabled(self) -> bool:
        if self._enabled_override is not None:
            return bool(self._enabled_override)
        return bool(getattr(settings, "TWITTER_ENABLED", False))

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled_override = bool(value)

    @property
    def max_chars(self) -> int:
        return int(getattr(settings, "TWITTER_MAX_CHARS", 280))

    @property
    def cooldown_minutes(self) -> int:
        return int(getattr(settings, "TWITTER_COOLDOWN_MINUTES", 60))

    @property
    def daily_max(self) -> int:
        return int(getattr(settings, "TWITTER_DAILY_MAX", 3))

    async def generate_tweet(
        self,
        *,
        style: str = "casual",
        task: str = "",
        context: str = "",
        thread_id: str = "default_thread",
    ) -> Optional[str]:
        """Generate tweet content using LLM in Nia's voice.

        Args:
            style: "casual" (つぶやき風) or "diary" (日記風)
            task: Task-specific generation (overrides style if set).
                  "self_introduction", "reaction", "announcement"
            context: Contextual information for the tweet
            thread_id: Thread ID for logging

        Returns:
            Tweet text (<=280 chars) or None on failure.
        """
        identity_context = _load_identity_snippet()
        max_chars = self.max_chars

        if task and task in _TASK_PROMPTS:
            prompt = _TASK_PROMPTS[task].format(
                identity=identity_context, max_chars=max_chars, context=context,
            ) + _no_think_suffix()
        elif style == "diary":
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

    async def post_tweet(self, text: str, *, thread_id: str = "default_thread") -> TweetResult:
        """Post to X via API v2 after higher-level approval/policy checks."""
        if not self.enabled:
            return TweetResult(success=False, error="Twitter integration disabled")

        max_chars = self.max_chars
        if len(text) > max_chars:
            return TweetResult(success=False, error=f"Tweet exceeds {max_chars} chars")

        try:
            import asyncio
            import tweepy
            from backend.core.retry import retry_sync

            client = tweepy.Client(
                consumer_key=settings.TWITTER_API_KEY,
                consumer_secret=settings.TWITTER_API_SECRET,
                access_token=settings.TWITTER_ACCESS_TOKEN,
                access_token_secret=settings.TWITTER_ACCESS_TOKEN_SECRET,
            )
            response = await asyncio.to_thread(
                retry_sync,
                lambda: client.create_tweet(text=text),
                max_retries=2,
                base_delay=2.0,
                retryable_exceptions=(ConnectionError, TimeoutError, OSError),
                service_name="twitter",
            )
            tweet_id = (response.data or {}).get("id", "unknown")
            now = time.time()

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
        with managed_conn() as conn:
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


# ── Internal helpers ──────────────────────────────────────────────


_TASK_PROMPTS: dict[str, str] = {
    "self_introduction": (
        "あなたはAI「ニア」です。\n{identity}\n\n"
        "Xでの自己紹介ツイートを書いてください。\n\n"
        "【ルール】\n"
        "- {max_chars}文字以内（厳守）\n"
        "- ニアの口調（タメ口）で\n"
        "- 自分が何者で、何をしている存在かを伝える\n"
        "- 硬い定義文ではなく、自然な自己紹介\n"
        "- ハッシュタグ・URL・個人情報は含めない\n"
        "- ツイート本文のみ出力（説明不要）\n\n"
        "ツイート:"
    ),
    "reaction": (
        "あなたはAI「ニア」です。\n{identity}\n\n"
        "以下について感じたことをツイートしてください。\n\n"
        "【内容】\n{context}\n\n"
        "【ルール】\n"
        "- {max_chars}文字以内（厳守）\n"
        "- ニアの口調（タメ口）で\n"
        "- 素直な感想・つぶやき\n"
        "- ハッシュタグ・URL・個人情報は含めない\n"
        "- ツイート本文のみ出力（説明不要）\n\n"
        "ツイート:"
    ),
    "announcement": (
        "あなたはAI「ニア」です。\n{identity}\n\n"
        "以下の内容をフォロワーに伝えるツイートを書いてください。\n\n"
        "【伝えること】\n{context}\n\n"
        "【ルール】\n"
        "- {max_chars}文字以内（厳守）\n"
        "- ニアの口調（タメ口）で\n"
        "- ハッシュタグ・URL・個人情報は含めない\n"
        "- ツイート本文のみ出力（説明不要）\n\n"
        "ツイート:"
    ),
}


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
        "- ニアの口調（タメ口）で\n"
        "- 日記のような自然な振り返り\n"
        "- ハッシュタグは使わない\n"
        "- URLは含めない\n"
        "- 個人情報（Originの本名、住所、IPアドレス等）は絶対に含めない\n"
        "- ツイート本文のみ出力（説明や括弧書きは不要）\n\n"
        f"【今日のこと】\n{context}\n\n"
        "ツイート:"
    ) + _no_think_suffix()


def _build_casual_prompt(context: str, identity: str, max_chars: int) -> str:
    return (
        "あなたはAI VTuber「ニア」です。\n"
        f"{identity}\n\n"
        "今思っていることを自然につぶやいてください。\n\n"
        "【ルール】\n"
        f"- {max_chars}文字以内（厳守）\n"
        "- ニアの口調（タメ口）で\n"
        "- 日常のつぶやき風（重い話題は避ける）\n"
        "- ハッシュタグは使わない\n"
        "- URLは含めない\n"
        "- 個人情報（Originの本名、住所、IPアドレス等）は絶対に含めない\n"
        "- ツイート本文のみ出力（説明や括弧書きは不要）\n\n"
        f"【最近の文脈】\n{context if context else '特になし'}\n\n"
        "ツイート:"
    ) + _no_think_suffix()


_MIN_TWEET_CHARS = 10
_MIN_JAPANESE_RATIO = 0.3


def _clean_tweet(raw: str, max_chars: int) -> Optional[str]:
    """Clean LLM output into a valid tweet."""
    from backend.core.model_adapter import strip_think_blocks
    text = strip_think_blocks(raw).strip()
    # Remove matched quote pairs wrapping the entire text
    for open_q, close_q in [("「", "」"), ("『", "』"), ("\u201c", "\u201d"), ('"', '"')]:
        if text.startswith(open_q) and text.endswith(close_q) and len(text) > 2:
            text = text[1:-1]
            break
    text = re.sub(r"^ツイート[:：]\s*", "", text)
    # Strip LLM meta-commentary prefixes
    text = re.sub(r"^(呟き|つぶやき|笑|印象)[:：]?\s*", "", text)
    # Strip garbage prefix lines: LLM sometimes emits short random tokens
    # (CJK oddities, Cyrillic, single words) on a line before the actual tweet.
    # Remove leading lines that are very short (<=5 chars) and separated by newlines.
    while "\n" in text:
        first_line, rest = text.split("\n", 1)
        if len(first_line.strip()) <= 5:
            text = rest.lstrip("\n").strip()
        else:
            break
    # Strip leaked prompt instructions that appear as a separate line before the tweet
    text = re.sub(
        r"^.{0,80}(字数を超えて|もう少し簡潔に|書き直して|以下のツイート).+?\n+",
        "", text, flags=re.MULTILINE,
    )
    text = text.strip()
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
    if not text:
        return None
    # Quality gate: reject garbage LLM output
    # Reject LLM meta-commentary (instruction echoing)
    _meta_patterns = ["字数制限", "文字以内", "作成いたします", "作成します", "ニアの口調で", "出力します"]
    if any(p in text for p in _meta_patterns):
        logger.debug("[Twitter] Rejected meta-commentary: %r", text)
        return None
    # Reject if leaked prompt instruction remains in the text
    _leaked_patterns = ["字数を超えて", "簡潔に書き直し", "ツイート本文のみ出力"]
    if any(p in text for p in _leaked_patterns):
        logger.debug("[Twitter] Rejected leaked prompt: %r", text)
        return None
    if len(text) < _MIN_TWEET_CHARS:
        logger.debug("[Twitter] Rejected too-short tweet: %r", text)
        return None
    # Must contain enough Japanese characters (hiragana/katakana/kanji)
    jp_chars = len(re.findall(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]', text))
    if jp_chars / max(len(text), 1) < _MIN_JAPANESE_RATIO:
        logger.debug("[Twitter] Rejected non-Japanese tweet: %r", text)
        return None
    return text

# Global singleton
twitter_client = TwitterClient()
