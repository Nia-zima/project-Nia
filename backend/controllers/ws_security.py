"""Shared WebSocket security helpers."""
from __future__ import annotations

from os import getenv


def allowed_ws_origins() -> set[str]:
    """Return the set of allowed WebSocket origins from env config."""
    raw = getenv("WS_ALLOWED_ORIGINS") or getenv(
        "VOICE_WS_ALLOWED_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,"
        "http://localhost:3001,http://127.0.0.1:3001",
    )
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def is_ws_origin_allowed(origin: str | None) -> bool:
    """Return True only if origin is present AND in the allow-list.

    When allowed origins include '*', any origin (including absent) is accepted.
    This is needed for Unity WS clients which don't send an Origin header.
    """
    allowed = allowed_ws_origins()
    if "*" in allowed:
        return True
    if not origin:
        return False
    return origin.strip().lower() in allowed


# Maximum WebSocket message size in bytes
WS_MAX_MESSAGE_BYTES: int = int(getenv("WS_MAX_MESSAGE_BYTES", str(512 * 1024)))

# WebSocket receive timeout in seconds
WS_RECEIVE_TIMEOUT_SEC: float = float(getenv("WS_RECEIVE_TIMEOUT_SEC", "300"))
