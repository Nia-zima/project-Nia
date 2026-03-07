"""Tests for enhanced telemetry logger."""
from __future__ import annotations

import json
from unittest.mock import patch

from backend.core.db import managed_conn


class TestTelemetryMetric:
    async def test_metric_stored(self):
        from backend.services.telemetry_logger import telemetry

        await telemetry.metric("llm_latency", 150.0, tags={"model": "qwen3"})

        with managed_conn() as conn:
            row = conn.execute(
                "SELECT payload_json FROM events WHERE event_type = 'metric' "
                "ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        assert row is not None
        payload = json.loads(row["payload_json"])
        assert payload["metric_name"] == "llm_latency"
        assert payload["value"] == 150.0
        assert payload["model"] == "qwen3"

    async def test_external_call_stored(self):
        from backend.services.telemetry_logger import telemetry

        await telemetry.external_call(
            "twitter",
            success=False,
            latency_ms=2500.0,
            status_code=503,
            error="service unavailable",
        )

        with managed_conn() as conn:
            row = conn.execute(
                "SELECT payload_json FROM events WHERE event_type = 'external_call' "
                "ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        assert row is not None
        payload = json.loads(row["payload_json"])
        assert payload["service"] == "twitter"
        assert payload["success"] is False
        assert payload["latency_ms"] == 2500.0
        assert payload["status_code"] == 503
        assert payload["error"] == "service unavailable"

    async def test_event_includes_request_id(self):
        from backend.core.correlation import set_request_id
        from backend.services.telemetry_logger import telemetry

        set_request_id("test-rid-abc")
        await telemetry.event("t1", "test_event", {"key": "value"})

        with managed_conn() as conn:
            row = conn.execute(
                "SELECT payload_json FROM events WHERE event_type = 'test_event' "
                "ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        assert row is not None
        payload = json.loads(row["payload_json"])
        assert payload["request_id"] == "test-rid-abc"
        assert payload["key"] == "value"

    async def test_external_call_truncates_error(self):
        from backend.services.telemetry_logger import telemetry

        long_error = "x" * 500
        await telemetry.external_call(
            "svc", success=False, latency_ms=100.0, error=long_error
        )

        with managed_conn() as conn:
            row = conn.execute(
                "SELECT payload_json FROM events WHERE event_type = 'external_call' "
                "ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        payload = json.loads(row["payload_json"])
        assert len(payload["error"]) == 200
