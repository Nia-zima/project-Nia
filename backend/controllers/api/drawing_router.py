"""Drawing trace viewer API + test-render endpoint.

Separate from draw_router.py (live drawing sessions).
Prefix: /api/drawing/*
"""
from __future__ import annotations

import hashlib
import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.core.db import managed_conn
from backend.core.drawing.attempt_store import (
    ensure_drawing_attempt_schema,
)
from backend.core.drawing.trace_store import (
    ensure_drawing_trace_schema,
)
from backend.core.logger import logger

router = APIRouter()


def _derive_svg_url(drawing_id: str) -> str:
    """Derive the static SVG URL from drawing_id using the same hash as runtime.py."""
    safe_name = hashlib.sha256(drawing_id.encode()).hexdigest()[:16]
    return f"/static/images/drawings/{safe_name}.svg"


@router.get("/drawing/traces")
async def list_drawing_traces(
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    """List recent drawing traces (latest version of each drawing)."""
    try:
        with managed_conn() as conn:
            ensure_drawing_trace_schema(conn)
            rows = conn.execute(
                """SELECT drawing_id, version, element_count,
                          because_tags, palette_used, relations_used,
                          created_at
                   FROM drawing_traces dt
                   WHERE version = (
                       SELECT MAX(version) FROM drawing_traces
                       WHERE drawing_id = dt.drawing_id
                   )
                   ORDER BY created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()

        items = []
        for r in rows:
            items.append({
                "drawing_id": r["drawing_id"],
                "version": r["version"],
                "element_count": r["element_count"],
                "because_tags": json.loads(r["because_tags"]),
                "palette_used": json.loads(r["palette_used"]),
                "relations_used": json.loads(r["relations_used"]),
                "created_at": r["created_at"],
            })
        return {"items": items, "count": len(items)}
    except Exception as e:
        logger.warning("[DRAWING_ROUTER] list_traces failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/drawing/traces/{drawing_id}")
async def get_drawing_trace(
    drawing_id: str,
    version: Optional[int] = Query(None),
) -> dict:
    """Get a specific drawing trace with full detail.

    AST and scene_graph are returned as parsed JSON (not raw strings).
    """
    try:
        with managed_conn() as conn:
            ensure_drawing_trace_schema(conn)
            if version is not None:
                row = conn.execute(
                    "SELECT * FROM drawing_traces WHERE drawing_id = ? AND version = ?",
                    (drawing_id, version),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM drawing_traces WHERE drawing_id = ? ORDER BY version DESC LIMIT 1",
                    (drawing_id,),
                ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail=f"drawing_id={drawing_id} not found")

        d = dict(row)

        # Return svg_url only if the static file actually exists
        svg_url = d.get("artifact_path") or _derive_svg_url(d["drawing_id"])
        svg_missing = False
        try:
            from backend.core.config import settings as _cfg
            from pathlib import Path
            # svg_url is e.g. /static/images/drawings/abc123.svg
            # strip /static/ prefix to get path relative to STATIC_DIR
            rel = svg_url.removeprefix("/static/")
            if not (Path(_cfg.STATIC_DIR) / rel).exists():
                svg_url = None
                svg_missing = True
        except Exception:
            pass

        return {
            "drawing_id": d["drawing_id"],
            "version": d["version"],
            "dsl_code": d["dsl_code"],
            "ast": json.loads(d["ast_json"]),
            "scene_graph": json.loads(d["scene_graph_json"]),
            "resolved_layout": json.loads(d["resolved_layout"]),
            "because_tags": json.loads(d["because_tags"]),
            "because_texts": json.loads(d["because_texts"]),
            "seeds_used": json.loads(d["seeds_used"]),
            "palette_used": json.loads(d["palette_used"]),
            "relations_used": json.loads(d["relations_used"]),
            "element_count": d["element_count"],
            "svg_url": svg_url,
            "svg_missing": svg_missing,
            "internal_state_snapshot": (
                json.loads(d["internal_state_snapshot"])
                if d["internal_state_snapshot"]
                else None
            ),
            "created_at": d["created_at"],
            "updated_at": d["updated_at"],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("[DRAWING_ROUTER] get_trace failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/drawing/attempts")
async def list_drawing_attempts(
    limit: int = Query(20, ge=1, le=100),
    drawing_id: Optional[str] = Query(None),
) -> dict:
    """List failed drawing attempts. Optional drawing_id filter."""
    try:
        with managed_conn() as conn:
            ensure_drawing_attempt_schema(conn)
            if drawing_id:
                rows = conn.execute(
                    """SELECT * FROM drawing_attempts
                       WHERE drawing_id = ?
                       ORDER BY created_at DESC LIMIT ?""",
                    (drawing_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM drawing_attempts ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()

        items = [dict(r) for r in rows]
        return {"items": items, "count": len(items)}
    except Exception as e:
        logger.warning("[DRAWING_ROUTER] list_attempts failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ── Test Render (no side effects) ─────────────────────────────────────


class TestRenderRequest(BaseModel):
    dsl_code: Optional[str] = None
    intent_yaml: Optional[str] = None


@router.post("/drawing/test-render")
async def test_render(req: TestRenderRequest) -> dict:
    """Run the full drawing pipeline with NO side effects.

    No trace_store, no attempt_store, no room hang, no memory commit.
    Returns the full pipeline output including intermediate representations.

    Accepts either:
    - intent_yaml: YAML intent (Layer 1 → 2 → 3 → 4)
    - dsl_code: raw DSL (Layer 3 → 4, legacy)
    """
    from backend.core.drawing.parser import parse_drawing, _normalize_dsl
    from backend.core.drawing.scene_graph import build_scene_graph
    from backend.core.drawing.renderer import render_svg

    result: dict = {
        "raw_dsl": None,
        "normalized_dsl": None,
        "repairs_applied": False,
        "intent_parsed": False,
        "generated_dsl": None,
        "ast": None,
        "scene_graph": None,
        "svg_artifact": None,
        "error_phase": None,
        "error_message": None,
    }

    # Layer 1→2: Intent YAML → DSL
    if req.intent_yaml:
        phase = "intent_parse"
        try:
            import yaml
            from backend.core.drawing.intent_schema import DrawingIntent
            from backend.core.drawing.intent_parser import intent_to_dsl

            raw = yaml.safe_load(req.intent_yaml)
            if not isinstance(raw, dict):
                raise ValueError("Intent YAML must be a mapping")
            if "intent" in raw and isinstance(raw["intent"], dict):
                raw = raw["intent"]
            intent = DrawingIntent.model_validate(raw)
            dsl_code = intent_to_dsl(intent)
            result["intent_parsed"] = True
            result["generated_dsl"] = dsl_code
        except Exception as e:
            result["error_phase"] = phase
            result["error_message"] = str(e)
            return result
    elif req.dsl_code:
        dsl_code = req.dsl_code
    else:
        result["error_phase"] = "input"
        result["error_message"] = "Either intent_yaml or dsl_code is required"
        return result

    # Layer 3: DSL → parse → scene_graph → render
    raw_dsl = dsl_code
    normalized_dsl = _normalize_dsl(raw_dsl)
    repairs_applied = normalized_dsl != raw_dsl

    result["raw_dsl"] = raw_dsl
    result["normalized_dsl"] = normalized_dsl
    result["repairs_applied"] = repairs_applied

    phase = "parse"
    try:
        ast = parse_drawing(normalized_dsl)
        result["ast"] = ast.model_dump()

        phase = "scene_graph"
        scene = build_scene_graph(ast)
        result["scene_graph"] = {
            "nodes": [
                {
                    "name": n.name,
                    "type": n.element_type.value,
                    "x": round(n.x, 1),
                    "y": round(n.y, 1),
                    "width": round(n.width, 1),
                    "height": round(n.height, 1),
                    "color": n.color,
                    "opacity": n.opacity,
                    "layer": n.layer,
                    "because_tags": n.because_tags,
                    "because_text": n.because_text,
                }
                for n in scene.nodes
            ],
            "canvas": {"width": scene.canvas.width, "height": scene.canvas.height},
        }

        phase = "render"
        svg = render_svg(scene)
        result["svg_artifact"] = svg

    except Exception as e:
        result["error_phase"] = phase
        result["error_message"] = str(e)

    return result
