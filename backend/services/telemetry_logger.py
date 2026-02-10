import asyncio
import json

from backend.core.db import get_conn
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
            with get_conn() as conn:
                conn.execute(
                    "INSERT INTO events (thread_id, event_type, payload_json) VALUES (?, ?, ?)",
                    (thread_id, event_type, payload_json),
                )
        except Exception:
            logger.exception("[telemetry] failed to write event")

    async def event(self, thread_id: str | None, event_type: str, payload: dict | None = None):
        try:
            payload_json = json.dumps(payload or {}, ensure_ascii=False)
            await asyncio.to_thread(self._event_sync, thread_id, event_type, payload_json)
        except Exception:
            logger.exception("[telemetry] failed to dispatch event")

telemetry = TelemetryLogger()
