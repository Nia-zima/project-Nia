"""Lightweight service health tracker.

Records last success/error for external services. Not a circuit breaker —
just a "last known state" tracker for the /system/diagnostics endpoint.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class ServiceStatus:
    name: str
    last_success: float = 0.0
    last_error: float = 0.0
    last_error_msg: str = ""
    success_count: int = 0
    error_count: int = 0


class ServiceHealthTracker:
    def __init__(self):
        self._services: dict[str, ServiceStatus] = {}
        self._lock = threading.Lock()

    def record_success(self, name: str) -> None:
        with self._lock:
            s = self._services.setdefault(name, ServiceStatus(name=name))
            s.last_success = time.time()
            s.success_count += 1

    def record_error(self, name: str, error: str) -> None:
        with self._lock:
            s = self._services.setdefault(name, ServiceStatus(name=name))
            s.last_error = time.time()
            s.last_error_msg = error[:200] if error else ""
            s.error_count += 1

    def get_all(self) -> dict[str, dict]:
        with self._lock:
            return {
                name: {
                    "last_success": s.last_success,
                    "last_error": s.last_error,
                    "last_error_msg": s.last_error_msg,
                    "success_count": s.success_count,
                    "error_count": s.error_count,
                    "healthy": s.last_success >= s.last_error,
                }
                for name, s in self._services.items()
            }


# Global singleton
service_health = ServiceHealthTracker()
