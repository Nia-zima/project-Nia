"""Tests for WebSocket security helpers."""
from __future__ import annotations

from unittest.mock import patch


class TestIsWsOriginAllowed:
    def test_none_origin_rejected(self):
        from backend.controllers.ws_security import is_ws_origin_allowed
        assert is_ws_origin_allowed(None) is False

    def test_empty_origin_rejected(self):
        from backend.controllers.ws_security import is_ws_origin_allowed
        assert is_ws_origin_allowed("") is False

    def test_allowed_origin_accepted(self):
        from backend.controllers.ws_security import is_ws_origin_allowed
        assert is_ws_origin_allowed("http://localhost:3000") is True

    def test_allowed_origin_case_insensitive(self):
        from backend.controllers.ws_security import is_ws_origin_allowed
        assert is_ws_origin_allowed("HTTP://LOCALHOST:3000") is True

    def test_unknown_origin_rejected(self):
        from backend.controllers.ws_security import is_ws_origin_allowed
        assert is_ws_origin_allowed("http://evil.com") is False

    def test_wildcard_allows_all(self):
        """When WS_ALLOWED_ORIGINS=*, any non-None origin is accepted."""
        with patch("backend.controllers.ws_security.allowed_ws_origins", return_value={"*"}):
            from backend.controllers.ws_security import is_ws_origin_allowed
            assert is_ws_origin_allowed("http://anything.com") is True

    def test_wildcard_still_rejects_none(self):
        """Even with wildcard config, None origin should be rejected."""
        with patch("backend.controllers.ws_security.allowed_ws_origins", return_value={"*"}):
            from backend.controllers.ws_security import is_ws_origin_allowed
            assert is_ws_origin_allowed(None) is False


class TestConstants:
    def test_default_max_message_bytes(self):
        from backend.controllers.ws_security import WS_MAX_MESSAGE_BYTES
        assert WS_MAX_MESSAGE_BYTES == 512 * 1024

    def test_default_receive_timeout(self):
        from backend.controllers.ws_security import WS_RECEIVE_TIMEOUT_SEC
        assert WS_RECEIVE_TIMEOUT_SEC == 300.0
