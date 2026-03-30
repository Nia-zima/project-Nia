"""Drawing Trace Store — persistence for Nia's drawing process.

Design: docs/nia_drawing_language.md
The trace is part of the artwork: DSL code, AST, scene graph, because annotations,
revisions, and internal state snapshot are all preserved.

Knot compensation applied:
- temporal_accounting_slip: drawing_id + version as unique key, no silent overwrite
- silent_fallback_masking: missing drawing_id raises ValueError, no default fill
- declared_semantics_not_realized: all semantic fields (because_tags, because_text,
  seed, resolved_layout) are explicitly stored and verified on save
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from backend.core.logger import logger


# ── Schema ────────────────────────────────────────────────────────────


class DrawingTrace(BaseModel):
    """Complete trace of a drawing: code + AST + scene + artifact + metadata."""

    drawing_id: str
    version: int = 1

    # Source
    intent_yaml: Optional[str] = None  # Layer 1 raw intent (None for legacy DSL path)
    dsl_code: str
    ast_json: str  # serialized DrawingAST

    # Scene graph (resolved)
    scene_graph_json: str  # serialized SceneGraph
    resolved_layout: dict[str, tuple[float, float]]

    # Semantic fields (must not be silently dropped)
    because_tags: list[str]  # all because tags used in this drawing
    because_texts: list[str]  # all free-text annotations
    seeds_used: list[int]  # all seeds from compositions

    # Palette and constraints
    palette_used: list[str]
    relations_used: list[str]
    element_count: int = 0

    # Artifact
    svg_artifact: Optional[str] = None
    artifact_path: Optional[str] = None

    # Internal state snapshot (at time of drawing)
    internal_state_snapshot: Optional[dict] = None

    # Timestamps
    created_at: str
    updated_at: str


class DrawingRevision(BaseModel):
    """A single revision within a drawing's history."""

    drawing_id: str
    version: int
    action: str  # what changed
    reason: str  # why (from because or manual)
    dsl_diff: str = ""  # what lines changed
    created_at: str


# ── DDL ───────────────────────────────────────────────────────────────


def ensure_drawing_trace_schema(conn: sqlite3.Connection) -> None:
    """Create drawing trace tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS drawing_traces (
            drawing_id          TEXT NOT NULL,
            version             INTEGER NOT NULL,

            intent_yaml         TEXT,
            dsl_code            TEXT NOT NULL,
            ast_json            TEXT NOT NULL,
            scene_graph_json    TEXT NOT NULL,
            resolved_layout     TEXT NOT NULL,

            because_tags        TEXT NOT NULL,
            because_texts       TEXT NOT NULL,
            seeds_used          TEXT NOT NULL,

            palette_used        TEXT NOT NULL,
            relations_used      TEXT NOT NULL,
            element_count       INTEGER NOT NULL DEFAULT 0,

            svg_artifact        TEXT,
            artifact_path       TEXT,

            internal_state_snapshot TEXT,

            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL,

            PRIMARY KEY (drawing_id, version)
        );

        CREATE INDEX IF NOT EXISTS idx_dt_drawing_id
        ON drawing_traces(drawing_id);
        CREATE INDEX IF NOT EXISTS idx_dt_created
        ON drawing_traces(created_at DESC);
    """)

    # Migration: add intent_yaml column to existing tables
    try:
        conn.execute("ALTER TABLE drawing_traces ADD COLUMN intent_yaml TEXT")
    except Exception:
        pass  # Column already exists

    conn.executescript("""

        CREATE TABLE IF NOT EXISTS drawing_revisions (
            drawing_id          TEXT NOT NULL,
            version             INTEGER NOT NULL,
            action              TEXT NOT NULL,
            reason              TEXT NOT NULL,
            dsl_diff            TEXT NOT NULL DEFAULT '',
            created_at          TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_dr_drawing
        ON drawing_revisions(drawing_id, version);
    """)
    logger.info("[DRAWING_TRACE] Schema ensured: 2 tables")


# ── Save ──────────────────────────────────────────────────────────────


def save_trace(conn: sqlite3.Connection, trace: DrawingTrace) -> None:
    """Save a drawing trace.

    Compensation: temporal_accounting_slip
    - Uses INSERT (not INSERT OR REPLACE) to prevent silent overwrite
    - Duplicate (drawing_id, version) raises IntegrityError
    """
    # declared_semantics_not_realized: verify all semantic fields are present
    _validate_semantic_fields(trace)

    conn.execute(
        """INSERT INTO drawing_traces (
            drawing_id, version,
            intent_yaml, dsl_code, ast_json, scene_graph_json, resolved_layout,
            because_tags, because_texts, seeds_used,
            palette_used, relations_used, element_count,
            svg_artifact, artifact_path,
            internal_state_snapshot,
            created_at, updated_at
        ) VALUES (?,?, ?,?,?,?,?, ?,?,?, ?,?,?, ?,?, ?, ?,?)""",
        (
            trace.drawing_id, trace.version,
            trace.intent_yaml,
            trace.dsl_code, trace.ast_json, trace.scene_graph_json,
            json.dumps(trace.resolved_layout, ensure_ascii=False),
            json.dumps(trace.because_tags), json.dumps(trace.because_texts),
            json.dumps(trace.seeds_used),
            json.dumps(trace.palette_used), json.dumps(trace.relations_used),
            trace.element_count,
            trace.svg_artifact, trace.artifact_path,
            json.dumps(trace.internal_state_snapshot) if trace.internal_state_snapshot else None,
            trace.created_at, trace.updated_at,
        ),
    )


def save_revision(conn: sqlite3.Connection, rev: DrawingRevision) -> None:
    """Save a drawing revision entry."""
    conn.execute(
        """INSERT INTO drawing_revisions (drawing_id, version, action, reason, dsl_diff, created_at)
        VALUES (?,?,?,?,?,?)""",
        (rev.drawing_id, rev.version, rev.action, rev.reason, rev.dsl_diff, rev.created_at),
    )


# ── Get ───────────────────────────────────────────────────────────────


def get_trace(conn: sqlite3.Connection, drawing_id: str, version: Optional[int] = None) -> Optional[DrawingTrace]:
    """Get a drawing trace by ID and optional version.

    Compensation: silent_fallback_masking
    - Returns None for missing drawing_id (no default fill)
    - If version is None, returns the latest version
    """
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
        return None
    return _row_to_trace(row)


def list_traces(conn: sqlite3.Connection, *, limit: int = 20) -> list[DrawingTrace]:
    """List recent drawing traces (latest version of each drawing)."""
    rows = conn.execute(
        """SELECT * FROM drawing_traces dt
           WHERE version = (SELECT MAX(version) FROM drawing_traces WHERE drawing_id = dt.drawing_id)
           ORDER BY created_at DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [_row_to_trace(r) for r in rows]


def get_revisions(conn: sqlite3.Connection, drawing_id: str) -> list[DrawingRevision]:
    """Get all revisions for a drawing."""
    rows = conn.execute(
        "SELECT * FROM drawing_revisions WHERE drawing_id = ? ORDER BY version, created_at",
        (drawing_id,),
    ).fetchall()
    return [DrawingRevision(**dict(r)) for r in rows]


# ── Helpers ───────────────────────────────────────────────────────────


def _validate_semantic_fields(trace: DrawingTrace) -> None:
    """Compensation: declared_semantics_not_realized.

    Verify that semantic fields from the DSL are not silently empty
    when the DSL code contains them.
    """
    if "because" in trace.dsl_code and not trace.because_tags and not trace.because_texts:
        raise ValueError(
            "DSL contains 'because' annotations but trace has empty because_tags and because_texts. "
            "Semantic fields must be preserved from parser through to trace."
        )

    if "seed=" in trace.dsl_code and not trace.seeds_used:
        raise ValueError(
            "DSL contains 'seed=' but trace has empty seeds_used. "
            "Seeds must be preserved for reproducibility."
        )


def _row_to_trace(row: sqlite3.Row) -> DrawingTrace:
    d = dict(row)
    d["resolved_layout"] = json.loads(d["resolved_layout"])
    d["because_tags"] = json.loads(d["because_tags"])
    d["because_texts"] = json.loads(d["because_texts"])
    d["seeds_used"] = json.loads(d["seeds_used"])
    d["palette_used"] = json.loads(d["palette_used"])
    d["relations_used"] = json.loads(d["relations_used"])
    if d["internal_state_snapshot"]:
        d["internal_state_snapshot"] = json.loads(d["internal_state_snapshot"])
    return DrawingTrace(**d)


# ── Extract trace from drawing pipeline ───────────────────────────────


def build_trace_from_drawing(
    drawing_id: str,
    dsl_code: str,
    ast: "DrawingAST",
    scene: "SceneGraph",
    svg: str,
    *,
    version: int = 1,
    internal_state: Optional[dict] = None,
    intent_yaml: Optional[str] = None,
) -> DrawingTrace:
    """Build a DrawingTrace from the full drawing pipeline output.

    This is the bridge between the drawing engine and persistence.
    Ensures all semantic fields are captured.
    """
    now = datetime.now(timezone.utc).isoformat()

    # Collect all because tags and texts from AST
    all_tags: list[str] = []
    all_texts: list[str] = []
    for stmt in ast.placements:
        if stmt.because:
            all_tags.extend(stmt.because.tags)
            if stmt.because.free_text:
                all_texts.append(stmt.because.free_text)
    for mod in ast.modifiers:
        if mod.because:
            all_tags.extend(mod.because.tags)
            if mod.because.free_text:
                all_texts.append(mod.because.free_text)
    for comp in ast.compositions:
        if comp.because:
            all_tags.extend(comp.because.tags)
            if comp.because.free_text:
                all_texts.append(comp.because.free_text)

    # Collect seeds
    seeds = [c.seed for c in ast.compositions if c.seed is not None]

    # Collect palette and relations
    palette = list({m.value for m in ast.modifiers if m.attribute == "color"})
    relations = list({s.relation.value for s in ast.placements})

    # resolved_layout from scene graph
    layout = {name: (round(pos[0], 1), round(pos[1], 1)) for name, pos in scene.resolved_layout.items()}

    import json as _json
    return DrawingTrace(
        drawing_id=drawing_id,
        version=version,
        intent_yaml=intent_yaml,
        dsl_code=dsl_code,
        ast_json=ast.model_dump_json(),
        scene_graph_json=_json.dumps({
            "nodes": [
                {"name": n.name, "type": n.element_type.value, "x": n.x, "y": n.y,
                 "color": n.color, "opacity": n.opacity, "layer": n.layer,
                 "because_tags": n.because_tags, "because_text": n.because_text}
                for n in scene.nodes
            ],
            "canvas": {"width": scene.canvas.width, "height": scene.canvas.height},
        }),
        resolved_layout=layout,
        because_tags=list(set(all_tags)),
        because_texts=all_texts,
        seeds_used=seeds,
        palette_used=palette,
        relations_used=relations,
        element_count=len(scene.nodes),
        svg_artifact=svg,
        internal_state_snapshot=internal_state,
        created_at=now,
        updated_at=now,
    )
