"""Drawing runtime — execute the full drawing pipeline for action_processing.

Pipeline: DSL code → parse → scene_graph → render → trace_store → file save → room hang
Failure: record in attempt_store (never silent)

Knot compensation:
- silent_fallback_masking: parse/scene/render errors raise, caller records attempt
- declared_semantics_not_realized: trace_store._validate_semantic_fields() on save
- temporal_accounting_slip: drawing_id is deterministic (caller provides);
  replay skips room hang to prevent wall_art duplicates
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backend.core.db import managed_conn
from backend.core.drawing.attempt_store import (
    DrawingAttempt,
    ensure_drawing_attempt_schema,
    save_attempt,
)
from backend.core.drawing.parser import parse_drawing
from backend.core.drawing.renderer import render_svg
from backend.core.drawing.scene_graph import build_scene_graph
from backend.core.drawing.trace_store import (
    build_trace_from_drawing,
    ensure_drawing_trace_schema,
    get_trace,
    save_trace,
)
from backend.core.logger import logger


class DrawingPipelineError(Exception):
    """Raised when the drawing pipeline fails at any phase."""

    def __init__(self, phase: str, message: str) -> None:
        self.phase = phase
        super().__init__(f"[{phase}] {message}")


async def render_and_store_drawing(payload: dict) -> dict:
    """Execute the full drawing pipeline and persist the result.

    Args:
        payload: Must contain 'drawing_id' and 'dsl_code'.
                 Optional: 'thread_id', 'internal_state'.

    Returns:
        dict with drawing_id, version, svg_artifact on success.

    Raises:
        DrawingPipelineError on parse/scene/render failure (after recording attempt).
    """
    drawing_id: str = payload["drawing_id"]
    dsl_code: str = payload["dsl_code"]
    thread_id: str | None = payload.get("thread_id")
    internal_state: dict | None = payload.get("internal_state")

    now = datetime.now(timezone.utc).isoformat()
    phase = "parse"

    try:
        ast = parse_drawing(dsl_code)
        phase = "scene_graph"
        scene = build_scene_graph(ast)
        phase = "render"
        svg = render_svg(scene)
    except Exception as exc:
        # Record failed attempt — never silent
        _record_attempt(drawing_id, dsl_code, phase, str(exc), thread_id, now)
        raise DrawingPipelineError(phase, str(exc)) from exc

    # Build and save trace
    trace = build_trace_from_drawing(
        drawing_id,
        dsl_code,
        ast,
        scene,
        svg,
        version=1,
        internal_state=internal_state,
    )

    try:
        with managed_conn() as conn:
            ensure_drawing_trace_schema(conn)
            # Idempotent: if same (drawing_id, version) already exists with same DSL,
            # return the existing trace instead of failing on UNIQUE constraint.
            existing = get_trace(conn, drawing_id, version=1)
            if existing is not None:
                if existing.dsl_code == dsl_code:
                    logger.info(
                        "[DRAWING_RUNTIME] replay hit: drawing_id=%s already saved",
                        drawing_id,
                    )
                    return {
                        "drawing_id": drawing_id,
                        "version": existing.version,
                        "svg_artifact": existing.svg_artifact,
                        "element_count": existing.element_count,
                        "because_tags": existing.because_tags,
                        "replay": True,
                    }
                # Same drawing_id but different DSL → genuine version conflict
                _record_attempt(
                    drawing_id, dsl_code, "trace_save",
                    f"drawing_id={drawing_id} version=1 exists with different DSL",
                    thread_id, now,
                )
                raise DrawingPipelineError(
                    "trace_save",
                    f"drawing_id={drawing_id} version=1 already exists with different DSL",
                )
            save_trace(conn, trace)
    except DrawingPipelineError:
        raise
    except Exception as exc:
        # Trace save failed — record attempt for visibility, then re-raise
        _record_attempt(drawing_id, dsl_code, "trace_save", str(exc), thread_id, now)
        raise DrawingPipelineError("trace_save", str(exc)) from exc

    # Save SVG to static dir for room / frontend access
    svg_url = _save_svg_file(drawing_id, svg)

    # Room integration: hang drawing on wall (first-time only, not on replay)
    _hang_drawing_in_room(drawing_id, svg_url, trace.because_tags)

    logger.info(
        "[DRAWING_RUNTIME] success drawing_id=%s elements=%d svg_url=%s",
        drawing_id,
        trace.element_count,
        svg_url or "(not saved)",
    )

    return {
        "drawing_id": drawing_id,
        "version": 1,
        "svg_artifact": svg,
        "svg_url": svg_url,
        "element_count": trace.element_count,
        "because_tags": trace.because_tags,
    }


def _record_attempt(
    drawing_id: str,
    dsl_code: str,
    phase: str,
    error_message: str,
    thread_id: Optional[str],
    now: str,
) -> None:
    """Fire-and-forget attempt recording."""
    try:
        attempt = DrawingAttempt(
            drawing_id=drawing_id,
            dsl_code=dsl_code,
            status=f"{phase}_error",
            error_message=error_message[:2000],
            error_phase=phase,
            thread_id=thread_id,
            created_at=now,
        )
        with managed_conn() as conn:
            ensure_drawing_attempt_schema(conn)
            save_attempt(conn, attempt)
        logger.warning(
            "[DRAWING_RUNTIME] attempt recorded: drawing_id=%s phase=%s error=%s",
            drawing_id,
            phase,
            error_message[:200],
        )
    except Exception:
        logger.error("[DRAWING_RUNTIME] failed to record attempt", exc_info=True)


def _save_svg_file(drawing_id: str, svg: str) -> str | None:
    """Save SVG to static/images/drawings/{sha256(drawing_id)[:16]}.svg.

    Returns the URL path (e.g. /static/images/drawings/a1b2c3d4e5f6g7h8.svg) or None on failure.
    Filename is a truncated SHA-256 hash of drawing_id to prevent path traversal
    and collision between IDs that differ only in separator characters.
    Fire-and-forget: SVG is already in trace_store, this is for room/frontend access.
    """
    try:
        from backend.core.config import settings
        drawings_dir = Path(settings.STATIC_DIR) / "images" / "drawings"
        drawings_dir.mkdir(parents=True, exist_ok=True)

        # Hash drawing_id for collision-free, traversal-safe filename
        safe_name = hashlib.sha256(drawing_id.encode()).hexdigest()[:16]
        file_path = (drawings_dir / f"{safe_name}.svg").resolve()

        # Guard: ensure resolved path stays inside drawings_dir
        if not file_path.is_relative_to(drawings_dir.resolve()):
            logger.warning("[DRAWING_RUNTIME] path traversal blocked: %s", drawing_id)
            return None

        file_path.write_text(svg, encoding="utf-8")

        url = f"/static/images/drawings/{safe_name}.svg"
        logger.debug("[DRAWING_RUNTIME] SVG saved: %s", url)
        return url
    except Exception:
        logger.warning("[DRAWING_RUNTIME] SVG file save failed", exc_info=True)
        return None


def _hang_drawing_in_room(
    drawing_id: str,
    svg_url: str | None,
    because_tags: list[str],
) -> None:
    """Hang drawing on room wall via execute_room_action.

    Gated by DRAWING_ROOM_ENABLED. Skips if svg_url is None.
    Dedupe: skips if wall_art already has this drawing_id as memory_link.
    """
    try:
        from backend.core.config import settings
        if not getattr(settings, "DRAWING_ROOM_ENABLED", False):
            return
        if not svg_url:
            return

        from backend.services.room.room_state import load_room_state, save_room_state
        from backend.services.room.room_action import RoomAction, execute_room_action

        room = load_room_state()

        # Dedupe: don't hang the same drawing twice
        existing_links = {
            a.get("memory_link", "") for a in (room.wall_art or [])
        }
        if drawing_id in existing_links:
            logger.debug(
                "[DRAWING_RUNTIME] room dedupe: drawing_id=%s already on wall",
                drawing_id,
            )
            return

        description = ", ".join(because_tags[:3]) if because_tags else ""
        action = RoomAction(
            action_type="hang_art",
            art_image=svg_url,
            memory_link=drawing_id,
            name=description,
        )
        execute_room_action(room, action)
        save_room_state(room)
        logger.info(
            "[DRAWING_RUNTIME] hung drawing on wall: drawing_id=%s url=%s",
            drawing_id,
            svg_url,
        )
    except Exception:
        logger.warning("[DRAWING_RUNTIME] room hang failed", exc_info=True)
