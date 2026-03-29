"""Tests for rate limiting middleware."""
from __future__ import annotations


def test_limiter_instance_created():
    """Verify that the limiter singleton is importable and configured."""
    from backend.core.rate_limit import limiter
    assert limiter is not None
    assert limiter._default_limits == []


def test_rate_limit_config_defaults():
    """Verify rate limit config defaults are set."""
    from backend.core.config import settings
    assert settings.RATE_LIMIT_ENABLED is True
    assert settings.RATE_LIMIT_CHAT == "30/minute"
    assert settings.RATE_LIMIT_LIVESTREAM == "60/minute"
    assert settings.RATE_LIMIT_VOICE == "10/minute"


def test_rate_limit_can_be_disabled(monkeypatch):
    """Verify rate limiting can be toggled via settings attribute."""
    from backend.core.config import settings
    original = settings.RATE_LIMIT_ENABLED
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    assert settings.RATE_LIMIT_ENABLED is False
    # monkeypatch automatically restores the original value
