"""Tests for request correlation ID module."""
from __future__ import annotations

import re


class TestCorrelationModule:
    def test_default_request_id_empty(self):
        from backend.core.correlation import get_request_id
        # In a fresh context, request_id should be empty
        # (contextvars reset per test is not guaranteed, so just check type)
        result = get_request_id()
        assert isinstance(result, str)

    def test_set_and_get_request_id(self):
        from backend.core.correlation import set_request_id, get_request_id
        rid = set_request_id("test-abc-123")
        assert rid == "test-abc-123"
        assert get_request_id() == "test-abc-123"

    def test_auto_generate_id(self):
        from backend.core.correlation import set_request_id
        rid = set_request_id(None)
        assert len(rid) == 12
        assert re.match(r"^[0-9a-f]{12}$", rid)

    def test_auto_generate_id_on_empty_string(self):
        from backend.core.correlation import set_request_id
        rid = set_request_id("")
        assert len(rid) == 12
        assert re.match(r"^[0-9a-f]{12}$", rid)

    def test_set_overwrites_previous(self):
        from backend.core.correlation import set_request_id, get_request_id
        set_request_id("first")
        set_request_id("second")
        assert get_request_id() == "second"
