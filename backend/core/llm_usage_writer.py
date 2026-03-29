"""Fire-and-forget writer for per-call LLM usage metadata."""
from __future__ import annotations

import time
import uuid
from typing import Any

from backend.core.db import managed_conn
from backend.core.logger import logger


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except Exception:
        try:
            return int(float(value))
        except Exception:
            return None


def extract_usage_metadata(resp: Any) -> dict[str, int | str | None]:
    """Extract token usage from common LangChain response shapes."""
    usage = getattr(resp, "usage_metadata", None) or {}
    response_metadata = getattr(resp, "response_metadata", None) or {}
    extra = getattr(resp, "additional_kwargs", None) or {}
    token_usage = (
        response_metadata.get("token_usage")
        or response_metadata.get("usage")
        or response_metadata.get("usage_metadata")
        or {}
    )

    prompt_tokens = _as_int(
        usage.get("input_tokens")
        or usage.get("prompt_tokens")
        or token_usage.get("input_tokens")
        or token_usage.get("prompt_tokens")
    )
    completion_tokens = _as_int(
        usage.get("output_tokens")
        or usage.get("completion_tokens")
        or token_usage.get("output_tokens")
        or token_usage.get("completion_tokens")
    )
    total_tokens = _as_int(
        usage.get("total_tokens")
        or token_usage.get("total_tokens")
    )
    if total_tokens is None and (prompt_tokens is not None or completion_tokens is not None):
        total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)

    finish_reason = (
        response_metadata.get("finish_reason")
        or response_metadata.get("stop_reason")
        or extra.get("finish_reason")
        or extra.get("stop_reason")
    )
    finish_reason = str(finish_reason) if finish_reason else None

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "finish_reason": finish_reason,
    }


def record_llm_usage(
    *,
    thread_id: str,
    turn_id: str,
    stage: str,
    message_id: str | None = None,
    stream_id: str | None = None,
    model_profile: str | None = None,
    model_provider: str | None = None,
    model_name: str | None = None,
    depth2_mode: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    finish_reason: str | None = None,
) -> str | None:
    """Persist one LLM usage row. Never raises."""
    try:
        row_id = uuid.uuid4().hex
        now = time.time()
        with managed_conn() as conn:
            conn.execute(
                """INSERT INTO llm_usage_records
                   (id, thread_id, turn_id, message_id, stream_id,
                    stage, model_profile, model_provider, model_name, depth2_mode,
                    prompt_tokens, completion_tokens, total_tokens, finish_reason,
                    created_at)
                   VALUES (?, ?, ?, ?, ?,
                           ?, ?, ?, ?, ?,
                           ?, ?, ?, ?,
                           ?)""",
                (
                    row_id,
                    thread_id,
                    turn_id,
                    message_id,
                    stream_id,
                    stage,
                    model_profile,
                    model_provider,
                    model_name,
                    depth2_mode,
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                    finish_reason,
                    now,
                ),
            )
        return row_id
    except Exception:
        logger.warning("[LLM_USAGE] write failed", exc_info=True)
        return None


def record_llm_usage_from_response(
    *,
    resp: Any,
    thread_id: str,
    turn_id: str,
    stage: str,
    message_id: str | None = None,
    stream_id: str | None = None,
    model_profile: str | None = None,
    model_provider: str | None = None,
    model_name: str | None = None,
    depth2_mode: str | None = None,
) -> str | None:
    """Extract usage from a LangChain response and persist it."""
    usage = extract_usage_metadata(resp)
    return record_llm_usage(
        thread_id=thread_id,
        turn_id=turn_id,
        stage=stage,
        message_id=message_id,
        stream_id=stream_id,
        model_profile=model_profile,
        model_provider=model_provider,
        model_name=model_name,
        depth2_mode=depth2_mode,
        prompt_tokens=usage["prompt_tokens"],
        completion_tokens=usage["completion_tokens"],
        total_tokens=usage["total_tokens"],
        finish_reason=usage["finish_reason"],
    )
