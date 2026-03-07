"""Request correlation ID for tracing requests across logs."""
from __future__ import annotations

import contextvars
import uuid

# Context variable holding the current request ID.
# Empty string when not inside a request context (e.g. background tasks).
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default=""
)


def get_request_id() -> str:
    """Return the current request ID, or empty string if not set."""
    return request_id_var.get()


def set_request_id(rid: str | None = None) -> str:
    """Set (or auto-generate) a request ID and return it.

    Args:
        rid: Explicit ID to use. If None, a 12-char hex ID is generated.
    """
    if not rid:
        rid = uuid.uuid4().hex[:12]
    request_id_var.set(rid)
    return rid
