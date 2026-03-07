import asyncio
import json

from backend.core.db import get_conn, managed_conn
from backend.core.logger import logger


class TelemetryLogger:
    def __init__(self):
        # Phase 2.6: Unified DB
        pass

    async def init_db(self):
        # Initialized by backend.core.db.init_schema()
        pass

    def _event_sync(self, thread_id: str | None, event_type: str, payload_json: str):
        try:
            with managed_conn() as conn:
                conn.execute(
                    "INSERT INTO events (thread_id, event_type, payload_json) VALUES (?, ?, ?)",
                    (thread_id, event_type, payload_json),
                )
        except Exception:
            logger.exception("[telemetry] failed to write event")

    async def event(self, thread_id: str | None, event_type: str, payload: dict | None = None):
        try:
            from backend.core.correlation import get_request_id
            enriched = dict(payload or {})
            enriched.setdefault("request_id", get_request_id())
            payload_json = json.dumps(enriched, ensure_ascii=False)
            await asyncio.to_thread(self._event_sync, thread_id, event_type, payload_json)
        except Exception:
            logger.exception("[telemetry] failed to dispatch event")

    async def metric(self, name: str, value: float, *, tags: dict | None = None):
        """Record a numeric metric as an event."""
        payload = {"metric_name": name, "value": value, **(tags or {})}
        await self.event(None, "metric", payload)

    async def external_call(
        self,
        service: str,
        *,
        success: bool,
        latency_ms: float,
        status_code: int | None = None,
        error: str | None = None,
    ):
        """Record an external API call outcome."""
        await self.event(None, "external_call", {
            "service": service,
            "success": success,
            "latency_ms": latency_ms,
            "status_code": status_code,
            "error": error[:200] if error else None,
        })


telemetry = TelemetryLogger()
