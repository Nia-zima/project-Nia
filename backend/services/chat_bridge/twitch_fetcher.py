"""Twitch IRC (TMI) read-only chat fetcher."""
from __future__ import annotations

import asyncio
import logging
import re
import time

logger = logging.getLogger("ChatBridge.Twitch")

# Twitch IRC (TMI) server
_IRC_HOST = "irc.chat.twitch.tv"
_IRC_PORT = 6667

# PRIVMSG pattern: :nick!nick@nick.tmi.twitch.tv PRIVMSG #channel :message
_PRIVMSG_RE = re.compile(
    r"^:(\w+)!\w+@\w+\.tmi\.twitch\.tv PRIVMSG #\w+ :(.+)$"
)


def parse_privmsg(raw: str) -> dict | None:
    """Parse a Twitch IRC PRIVMSG line.

    Returns ``{"user_name": ..., "user_id": ..., "text": ...}`` or None.
    """
    raw = raw.strip()
    m = _PRIVMSG_RE.match(raw)
    if not m:
        return None
    return {
        "user_name": m.group(1),
        "user_id": f"twitch:{m.group(1)}",
        "text": m.group(2).strip(),
    }


class TwitchIRCFetcher:
    """Read-only Twitch chat via IRC.

    Default: anonymous (justinfan) — no OAuth required for reading.

    Usage::

        fetcher = TwitchIRCFetcher(channel="channelname")
        await fetcher.listen_loop(enqueue_callback)
    """

    def __init__(
        self,
        channel: str,
        nick: str = "justinfan12345",
        oauth: str = "",
    ):
        self._channel = channel.lstrip("#").lower()
        self._nick = nick
        self._oauth = oauth

    async def _connect(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """Open IRC connection and join channel."""
        reader, writer = await asyncio.open_connection(_IRC_HOST, _IRC_PORT)

        # Authenticate
        if self._oauth:
            writer.write(f"PASS oauth:{self._oauth.lstrip('oauth:')}\r\n".encode())
        else:
            writer.write(b"PASS SCHMOOPIIE\r\n")
        writer.write(f"NICK {self._nick}\r\n".encode())
        await writer.drain()

        # Join channel
        writer.write(f"JOIN #{self._channel}\r\n".encode())
        await writer.drain()

        logger.info("[Twitch] connected to #%s as %s", self._channel, self._nick)
        return reader, writer

    async def listen_loop(self, enqueue_callback) -> None:
        """Background listen loop. Call with asyncio.create_task().

        Args:
            enqueue_callback: async callable(text, user_id, user_name, source)
        """
        backoff_sec = 5.0

        while True:
            writer = None
            try:
                reader, writer = await self._connect()
                backoff_sec = 5.0  # Reset on successful connect

                while True:
                    raw_line = await asyncio.wait_for(reader.readline(), timeout=120)
                    if not raw_line:
                        logger.warning("[Twitch] connection closed by server")
                        break

                    line = raw_line.decode("utf-8", errors="replace").strip()

                    # Respond to PING to keep connection alive
                    if line.startswith("PING"):
                        writer.write(b"PONG :tmi.twitch.tv\r\n")
                        await writer.drain()
                        continue

                    # Parse PRIVMSG
                    msg = parse_privmsg(line)
                    if msg:
                        try:
                            await enqueue_callback(
                                text=msg["text"],
                                user_id=msg["user_id"],
                                user_name=msg["user_name"],
                                source="twitch",
                            )
                        except Exception:
                            logger.warning("[Twitch] enqueue failed", exc_info=True)

            except asyncio.CancelledError:
                logger.info("[Twitch] listen loop cancelled")
                raise
            except asyncio.TimeoutError:
                logger.warning("[Twitch] read timeout, reconnecting...")
            except Exception:
                logger.warning("[Twitch] connection error", exc_info=True)
            finally:
                if writer:
                    try:
                        writer.close()
                        await writer.wait_closed()
                    except Exception:
                        pass

            logger.info("[Twitch] reconnecting in %.0fs...", backoff_sec)
            await asyncio.sleep(backoff_sec)
            backoff_sec = min(backoff_sec * 2, 300)
