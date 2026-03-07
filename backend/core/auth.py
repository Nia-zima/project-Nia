"""Shared authentication dependencies for FastAPI routes."""
from __future__ import annotations

import secrets

from fastapi import Header, HTTPException

from backend.core.config import settings


def verify_system_token(x_system_token: str | None = Header(default=None)) -> None:
    """Require a valid X-System-Token header.

    Used for admin/system endpoints (sleep cycle, identity updates, etc.).
    Raises 401 if the token is missing or doesn't match IDENTITY_SECRET_KEY.
    """
    expected = getattr(settings, "IDENTITY_SECRET_KEY", "")
    if not expected or not x_system_token or not secrets.compare_digest(x_system_token, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing system token")
