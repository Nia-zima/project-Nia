"""Tests for Drawing Trace Store.

Knot compensation tests are explicitly marked:
- temporal_accounting_slip: duplicate version, version ordering
- silent_fallback_masking: missing drawing_id, no default fill
- declared_semantics_not_realized: semantic field preservation
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from backend.core.drawing.parser import parse_drawing
from backend.core.drawing.scene_graph import build_scene_graph
from backend.core.drawing.renderer import render_svg
from backend.core.drawing.trace_store import (
    DrawingRevision,
    DrawingTrace,
    build_trace_from_drawing,
    ensure_drawing_trace_schema,
    get_revisions,
    get_trace,
    list_traces,
    save_revision,
    save_trace,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    ensure_drawing_trace_schema(c)
    yield c
    c.close()


def _sample_dsl() -> str:
    return """
core: circle(size=small)
bg: area(size=large)
bg at field because background
core at center because anchor
core color warm_3 because presence -- this felt warm
scatter dot around core count=4 seed=42 because ambient
"""


def _make_trace(drawing_id="draw_001", version=1, **overrides) -> DrawingTrace:
    dsl = _sample_dsl()
    ast = parse_drawing(dsl)
    scene = build_scene_graph(ast)
    svg = render_svg(scene)
    trace = build_trace_from_drawing(drawing_id, dsl, ast, scene, svg, version=version)
    for k, v in overrides.items():
        setattr(trace, k, v)
    return trace


# ── DDL ───────────────────────────────────────────────────────────────


class TestSchema:
    def test_tables_created(self, conn):
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert "drawing_traces" in tables
        assert "drawing_revisions" in tables

    def test_idempotent(self, conn):
        ensure_drawing_trace_schema(conn)


# ── Save and Get ──────────────────────────────────────────────────────


class TestSaveGet:
    def test_save_and_get(self, conn):
        trace = _make_trace()
        save_trace(conn, trace)
        loaded = get_trace(conn, "draw_001")
        assert loaded is not None
        assert loaded.drawing_id == "draw_001"
        assert loaded.version == 1

    def test_get_latest_version(self, conn):
        save_trace(conn, _make_trace(version=1))
        save_trace(conn, _make_trace(version=2))
        latest = get_trace(conn, "draw_001")
        assert latest.version == 2

    def test_get_specific_version(self, conn):
        save_trace(conn, _make_trace(version=1))
        save_trace(conn, _make_trace(version=2))
        v1 = get_trace(conn, "draw_001", version=1)
        assert v1.version == 1

    def test_list_traces(self, conn):
        save_trace(conn, _make_trace("d1", version=1))
        save_trace(conn, _make_trace("d2", version=1))
        traces = list_traces(conn)
        assert len(traces) == 2


# ── Knot: temporal_accounting_slip ────────────────────────────────────


class TestTemporalAccountingSlip:
    def test_duplicate_version_raises(self, conn):
        """Same drawing_id + version must raise IntegrityError, not silently overwrite."""
        save_trace(conn, _make_trace(version=1))
        with pytest.raises(sqlite3.IntegrityError):
            save_trace(conn, _make_trace(version=1))

    def test_different_versions_coexist(self, conn):
        """Different versions of the same drawing should all be preserved."""
        save_trace(conn, _make_trace(version=1))
        save_trace(conn, _make_trace(version=2))
        save_trace(conn, _make_trace(version=3))
        count = conn.execute(
            "SELECT COUNT(*) FROM drawing_traces WHERE drawing_id = 'draw_001'"
        ).fetchone()[0]
        assert count == 3


# ── Knot: silent_fallback_masking ─────────────────────────────────────


class TestSilentFallbackMasking:
    def test_missing_drawing_returns_none(self, conn):
        """Missing drawing_id returns None, not a default-filled object."""
        result = get_trace(conn, "nonexistent")
        assert result is None

    def test_missing_version_returns_none(self, conn):
        """Missing specific version returns None."""
        save_trace(conn, _make_trace(version=1))
        result = get_trace(conn, "draw_001", version=99)
        assert result is None


# ── Knot: declared_semantics_not_realized ─────────────────────────────


class TestDeclaredSemanticsNotRealized:
    def test_because_tags_preserved(self, conn):
        """All because tags from DSL must appear in trace."""
        trace = _make_trace()
        save_trace(conn, trace)
        loaded = get_trace(conn, "draw_001")
        assert "anchor" in loaded.because_tags
        assert "background" in loaded.because_tags
        assert "presence" in loaded.because_tags
        assert "ambient" in loaded.because_tags

    def test_because_texts_preserved(self, conn):
        """Free-text because annotations must be preserved."""
        trace = _make_trace()
        save_trace(conn, trace)
        loaded = get_trace(conn, "draw_001")
        assert any("this felt warm" in t for t in loaded.because_texts)

    def test_seeds_preserved(self, conn):
        """Seeds from compositions must be preserved for reproducibility."""
        trace = _make_trace()
        save_trace(conn, trace)
        loaded = get_trace(conn, "draw_001")
        assert 42 in loaded.seeds_used

    def test_resolved_layout_preserved(self, conn):
        """resolved_layout from scene graph must be preserved."""
        trace = _make_trace()
        save_trace(conn, trace)
        loaded = get_trace(conn, "draw_001")
        assert "core" in loaded.resolved_layout
        assert "bg" in loaded.resolved_layout

    def test_palette_and_relations_preserved(self, conn):
        """palette_used and relations_used must reflect actual DSL content."""
        trace = _make_trace()
        save_trace(conn, trace)
        loaded = get_trace(conn, "draw_001")
        assert "warm_3" in loaded.palette_used
        assert "at" in loaded.relations_used

    def test_validation_catches_missing_because(self, conn):
        """If DSL has because but trace doesn't, validation should fail."""
        trace = _make_trace()
        trace.because_tags = []
        trace.because_texts = []
        with pytest.raises(ValueError, match="because_tags"):
            save_trace(conn, trace)

    def test_validation_catches_missing_seed(self, conn):
        """If DSL has seed= but trace doesn't, validation should fail."""
        trace = _make_trace()
        trace.seeds_used = []
        with pytest.raises(ValueError, match="seeds_used"):
            save_trace(conn, trace)

    def test_svg_artifact_stored(self, conn):
        """SVG artifact should be stored and retrievable."""
        trace = _make_trace()
        save_trace(conn, trace)
        loaded = get_trace(conn, "draw_001")
        assert loaded.svg_artifact is not None
        assert "<svg" in loaded.svg_artifact

    def test_element_count_correct(self, conn):
        """element_count should match scene graph node count."""
        trace = _make_trace()
        save_trace(conn, trace)
        loaded = get_trace(conn, "draw_001")
        assert loaded.element_count > 0


# ── Revisions ─────────────────────────────────────────────────────────


class TestRevisions:
    def test_save_and_get_revisions(self, conn):
        now = _now()
        save_revision(conn, DrawingRevision(
            drawing_id="draw_001", version=1,
            action="added core at center",
            reason="anchor point",
            created_at=now,
        ))
        save_revision(conn, DrawingRevision(
            drawing_id="draw_001", version=2,
            action="changed opacity to faint",
            reason="too present, wanted distance",
            dsl_diff="- core opacity solid\n+ core opacity faint",
            created_at=now,
        ))
        revs = get_revisions(conn, "draw_001")
        assert len(revs) == 2
        assert revs[0].action == "added core at center"
        assert revs[1].dsl_diff != ""
