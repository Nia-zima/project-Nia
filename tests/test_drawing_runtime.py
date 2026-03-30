"""Tests for Drawing Language LLM tool connection.

Covers:
- draw block extraction from final_text
- single draw block → successful render_drawing action
- multiple draw blocks → pre-gate rejection
- parse error → attempt_store record
- registry/executor wiring
- drawing_id fallback to message_id / stream_id
"""
from __future__ import annotations

import sqlite3
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Draw block extraction ─────────────────────────────────────────────


class TestDrawBlockExtraction:
    """Test ```draw block detection in final_text."""

    def test_single_draw_block(self):
        from backend.core.agent_graph.nodes.actions import _extract_draw_content

        text = "ここは応答テキスト\n```draw\na: circle\na at center\n```\n後続テキスト"
        blocks = _extract_draw_content(text)
        assert len(blocks) == 1
        assert "a: circle" in blocks[0]
        assert "a at center" in blocks[0]

    def test_no_draw_block(self):
        from backend.core.agent_graph.nodes.actions import _extract_draw_content

        text = "普通の応答テキスト"
        blocks = _extract_draw_content(text)
        assert blocks == []

    def test_multiple_draw_blocks(self):
        from backend.core.agent_graph.nodes.actions import _extract_draw_content

        text = "```draw\na: circle\n```\ntext\n```draw\nb: rect\n```"
        blocks = _extract_draw_content(text)
        assert len(blocks) == 2

    def test_empty_draw_block_ignored(self):
        from backend.core.agent_graph.nodes.actions import _extract_draw_content

        text = "```draw\n\n```"
        blocks = _extract_draw_content(text)
        assert blocks == []

    def test_case_insensitive(self):
        from backend.core.agent_graph.nodes.actions import _extract_draw_content

        text = "```Draw\na: dot\n```"
        blocks = _extract_draw_content(text)
        assert len(blocks) == 1

    def test_other_fenced_code_ignored(self):
        from backend.core.agent_graph.nodes.actions import _extract_draw_content

        text = "```python\nprint('hello')\n```\n```draw\na: dot\n```\n```json\n{}\n```"
        blocks = _extract_draw_content(text)
        assert len(blocks) == 1
        assert "a: dot" in blocks[0]


# ── Drawing ID generation ─────────────────────────────────────────────


class TestDrawingId:
    """Test deterministic drawing_id generation."""

    def test_with_message_id(self):
        from backend.core.agent_graph.nodes.actions import _make_drawing_id

        state = {"message_id": "msg_abc", "stream_id": "stream_xyz"}
        did = _make_drawing_id(state, 0)
        assert did == "draw:msg_abc:0"

    def test_fallback_to_stream_id(self):
        from backend.core.agent_graph.nodes.actions import _make_drawing_id

        state = {"message_id": None, "stream_id": "stream_xyz"}
        did = _make_drawing_id(state, 0)
        assert did == "draw:stream_xyz:0"

    def test_no_provenance_returns_none(self):
        from backend.core.agent_graph.nodes.actions import _make_drawing_id

        state = {}
        assert _make_drawing_id(state, 0) is None

    def test_none_values_returns_none(self):
        from backend.core.agent_graph.nodes.actions import _make_drawing_id

        state = {"message_id": None, "stream_id": None}
        assert _make_drawing_id(state, 0) is None

    def test_block_index(self):
        from backend.core.agent_graph.nodes.actions import _make_drawing_id

        state = {"message_id": "msg_1"}
        assert _make_drawing_id(state, 0) == "draw:msg_1:0"
        assert _make_drawing_id(state, 1) == "draw:msg_1:1"


# ── Action processing integration ─────────────────────────────────────


class TestActionProcessingDraw:
    """Test draw block handling inside action_processing."""

    @pytest.fixture()
    def _patch_deps(self):
        """Patch dependencies for action_processing."""
        with (
            patch("backend.core.actions.gate.ActionGate.request_action") as gate_method,
            patch("backend.core.actions.registry.ActionRegistry.get") as reg_get,
            patch("backend.core.actions.executor.ActionExecutor.execute") as exe_method,
            patch("backend.services.telemetry_logger.telemetry", new_callable=MagicMock) as _tel,
        ):
            from backend.core.actions.types import Action, ActionCategory, RiskLevel, ActionDecision

            draw_action = Action(
                id="render_drawing",
                name="ドローイング生成",
                category=ActionCategory.DISPLAY,
                risk_level=RiskLevel.SAFE,
                description="draw DSL",
                payload={},
            )
            reg_get.return_value = draw_action
            gate_method.return_value = ActionDecision(
                should_execute=True, reason="SAFE"
            )
            exe_method.return_value = {
                "status": "success",
                "result": {
                    "drawing_id": "draw:test:0",
                    "version": 1,
                    "svg_artifact": "<svg></svg>",
                },
            }
            _tel.event = AsyncMock()
            yield {"gate": gate_method, "registry": reg_get, "executor": exe_method}

    @pytest.mark.asyncio
    async def test_single_block_proposed(self, _patch_deps, monkeypatch):
        from backend.core.agent_graph.nodes.actions import action_processing
        from backend.core.config import settings
        monkeypatch.setattr(settings, "DRAWING_INTENT_ONLY", False)

        state = {
            "selected_depth": 0,
            "confidence": 0.5,
            "final_text": "描いてみた\n```draw\na: circle\na at center\n```",
            "thread_id": "t1",
            "message_id": "m1",
        }
        result = await action_processing(state)
        assert len(result["approved_actions"]) == 1
        assert result["approved_actions"][0]["action_id"] == "render_drawing"
        assert result["rejected_actions"] == []

    @pytest.mark.asyncio
    async def test_multiple_blocks_rejected(self, _patch_deps):
        from backend.core.agent_graph.nodes.actions import action_processing

        state = {
            "selected_depth": 0,
            "confidence": 0.5,
            "final_text": "```draw\na: circle\n```\ntext\n```draw\nb: rect\n```",
            "thread_id": "t1",
            "message_id": "m1",
        }
        result = await action_processing(state)
        # No proposals, just rejection
        assert len(result["rejected_actions"]) == 1
        assert "multiple_draw_blocks" in result["rejected_actions"][0]["reason"]
        assert result["approved_actions"] == []

    @pytest.mark.asyncio
    async def test_no_draw_block_no_action(self):
        """No draw block → no render_drawing in proposals."""
        from backend.core.agent_graph.nodes.actions import action_processing

        state = {
            "selected_depth": 0,
            "confidence": 0.5,
            "final_text": "普通の応答です",
            "thread_id": "t1",
        }
        result = await action_processing(state)
        action_ids = [a.get("action_id") for a in result.get("proposed_actions", [])]
        assert "render_drawing" not in action_ids

    @pytest.mark.asyncio
    async def test_no_provenance_rejected(self, _patch_deps):
        """Draw block with no message_id/stream_id → pre-gate rejection."""
        from backend.core.agent_graph.nodes.actions import action_processing

        state = {
            "selected_depth": 0,
            "confidence": 0.5,
            "final_text": "```draw\na: circle\na at center\n```",
            "thread_id": "t1",
            # no message_id, no stream_id
        }
        result = await action_processing(state)
        assert len(result["rejected_actions"]) == 1
        assert "no_provenance_id" in result["rejected_actions"][0]["reason"]
        assert result["approved_actions"] == []

    @pytest.mark.asyncio
    async def test_invalid_dsl_returns_error_status(self, _patch_deps, monkeypatch):
        """Invalid DSL → executor returns error → action_results.status == 'error'."""
        from backend.core.agent_graph.nodes.actions import action_processing
        from backend.core.config import settings
        monkeypatch.setattr(settings, "DRAWING_INTENT_ONLY", False)

        _patch_deps["executor"].return_value = {
            "status": "error",
            "message": "parse failed",
        }
        state = {
            "selected_depth": 0,
            "confidence": 0.5,
            "final_text": "```draw\n%%% invalid\n```",
            "thread_id": "t1",
            "message_id": "m_err",
        }
        result = await action_processing(state)
        errors = [r for r in result["action_results"] if r["status"] == "error"]
        assert len(errors) >= 1

    @pytest.mark.asyncio
    async def test_no_action_preserves_existing_rejected_actions(self):
        """Early return with no proposals still preserves existing rejected_actions."""
        from backend.core.agent_graph.nodes.actions import action_processing

        existing_reject = {
            "action_id": "some_old_action",
            "status": "REJECTED",
            "reason": "prior rejection",
        }
        state = {
            "selected_depth": 0,
            "confidence": 0.5,
            "final_text": "普通の応答",
            "thread_id": "t1",
            "rejected_actions": [existing_reject],
        }
        result = await action_processing(state)
        assert len(result["rejected_actions"]) == 1
        assert result["rejected_actions"][0]["action_id"] == "some_old_action"

    @pytest.mark.asyncio
    async def test_test_mode_skips(self):
        """test_mode skips all actions including draw."""
        from backend.core.agent_graph.nodes.actions import action_processing

        state = {
            "selected_depth": 0,
            "confidence": 0.5,
            "final_text": "```draw\na: circle\n```",
            "test_mode": True,
        }
        result = await action_processing(state)
        assert result["proposed_actions"] == []
        assert result["approved_actions"] == []


# ── Registry / Executor wiring ────────────────────────────────────────


class TestRegistryExecutorWiring:
    """Verify render_drawing is registered and has a handler."""

    def test_registry_has_render_drawing(self):
        from backend.core.actions.registry import action_registry

        action = action_registry.get("render_drawing")
        assert action is not None
        assert action.id == "render_drawing"
        assert action.risk_level.name == "SAFE"

    def test_executor_has_handler(self):
        from backend.core.actions.executor import action_executor

        handler = action_executor._get_handler("render_drawing")
        assert handler is not None


# ── Drawing runtime (render_and_store_drawing) ────────────────────────


class TestDrawingRuntime:
    """Test the drawing pipeline runtime."""

    VALID_DSL = "a: circle\na at center"

    @pytest.mark.asyncio
    async def test_success_returns_svg(self):
        from backend.core.drawing.runtime import render_and_store_drawing
        from backend.core.drawing.trace_store import ensure_drawing_trace_schema
        from backend.core.drawing.attempt_store import ensure_drawing_attempt_schema

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        ensure_drawing_trace_schema(conn)
        ensure_drawing_attempt_schema(conn)

        with patch("backend.core.drawing.runtime.managed_conn") as mock_conn_ctx:
            mock_conn_ctx.return_value.__enter__ = MagicMock(return_value=conn)
            mock_conn_ctx.return_value.__exit__ = MagicMock(return_value=False)

            result = await render_and_store_drawing({
                "drawing_id": "draw:test:0",
                "dsl_code": self.VALID_DSL,
                "thread_id": "t1",
            })

        assert result["drawing_id"] == "draw:test:0"
        assert result["version"] == 1
        assert "<svg" in result["svg_artifact"]
        assert result["element_count"] >= 1

    @pytest.mark.asyncio
    async def test_parse_error_records_attempt(self):
        from backend.core.drawing.runtime import render_and_store_drawing, DrawingPipelineError
        from backend.core.drawing.attempt_store import ensure_drawing_attempt_schema, list_attempts

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        ensure_drawing_attempt_schema(conn)

        with patch("backend.core.drawing.runtime.managed_conn") as mock_conn_ctx:
            mock_conn_ctx.return_value.__enter__ = MagicMock(return_value=conn)
            mock_conn_ctx.return_value.__exit__ = MagicMock(return_value=False)

            with pytest.raises(DrawingPipelineError, match="parse"):
                await render_and_store_drawing({
                    "drawing_id": "draw:bad:0",
                    "dsl_code": "this is not valid DSL %%% !!!",
                    "thread_id": "t1",
                })

            attempts = list_attempts(conn)
            assert len(attempts) == 1
            assert attempts[0].error_phase == "parse"

    @pytest.mark.asyncio
    async def test_replay_same_dsl_returns_existing(self):
        """Same drawing_id + same DSL on retry → returns existing trace, not error."""
        from backend.core.drawing.runtime import render_and_store_drawing
        from backend.core.drawing.trace_store import ensure_drawing_trace_schema

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        ensure_drawing_trace_schema(conn)
        from backend.core.drawing.attempt_store import ensure_drawing_attempt_schema
        ensure_drawing_attempt_schema(conn)

        with patch("backend.core.drawing.runtime.managed_conn") as mock_conn_ctx:
            mock_conn_ctx.return_value.__enter__ = MagicMock(return_value=conn)
            mock_conn_ctx.return_value.__exit__ = MagicMock(return_value=False)

            # First call succeeds
            r1 = await render_and_store_drawing({
                "drawing_id": "draw:replay:0",
                "dsl_code": self.VALID_DSL,
                "thread_id": "t1",
            })
            assert r1["drawing_id"] == "draw:replay:0"
            assert r1.get("replay") is None or r1.get("replay") is not True

            # Second call with same DSL → idempotent replay
            r2 = await render_and_store_drawing({
                "drawing_id": "draw:replay:0",
                "dsl_code": self.VALID_DSL,
                "thread_id": "t1",
            })
            assert r2["drawing_id"] == "draw:replay:0"
            assert r2["replay"] is True
            assert "<svg" in r2["svg_artifact"]

    @pytest.mark.asyncio
    async def test_replay_different_dsl_fails(self):
        """Same drawing_id + different DSL → error, not silent overwrite."""
        from backend.core.drawing.runtime import render_and_store_drawing, DrawingPipelineError
        from backend.core.drawing.trace_store import ensure_drawing_trace_schema
        from backend.core.drawing.attempt_store import ensure_drawing_attempt_schema

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        ensure_drawing_trace_schema(conn)
        ensure_drawing_attempt_schema(conn)

        with patch("backend.core.drawing.runtime.managed_conn") as mock_conn_ctx:
            mock_conn_ctx.return_value.__enter__ = MagicMock(return_value=conn)
            mock_conn_ctx.return_value.__exit__ = MagicMock(return_value=False)

            await render_and_store_drawing({
                "drawing_id": "draw:conflict:0",
                "dsl_code": self.VALID_DSL,
                "thread_id": "t1",
            })

            with pytest.raises(DrawingPipelineError, match="different DSL"):
                await render_and_store_drawing({
                    "drawing_id": "draw:conflict:0",
                    "dsl_code": "b: rect\nb at center",
                    "thread_id": "t1",
                })

    @pytest.mark.asyncio
    async def test_scene_error_records_attempt(self):
        from backend.core.drawing.runtime import render_and_store_drawing, DrawingPipelineError
        from backend.core.drawing.attempt_store import ensure_drawing_attempt_schema, list_attempts

        bad_dsl = "a: circle\nb at center"  # b not declared
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        ensure_drawing_attempt_schema(conn)

        with patch("backend.core.drawing.runtime.managed_conn") as mock_conn_ctx:
            mock_conn_ctx.return_value.__enter__ = MagicMock(return_value=conn)
            mock_conn_ctx.return_value.__exit__ = MagicMock(return_value=False)

            with pytest.raises(DrawingPipelineError):
                await render_and_store_drawing({
                    "drawing_id": "draw:scene_err:0",
                    "dsl_code": bad_dsl,
                    "thread_id": "t1",
                })

            attempts = list_attempts(conn)
            assert len(attempts) == 1
            assert attempts[0].error_phase == "scene_graph"


# ── SVG file save ─────────────────────────────────────────────────────


class TestSvgFileSave:
    """Test SVG file saving to static dir."""

    def test_save_creates_file(self, tmp_path):
        from backend.core.drawing.runtime import _save_svg_file
        import hashlib

        with patch("backend.core.config.settings") as mock_settings:
            mock_settings.STATIC_DIR = tmp_path
            url = _save_svg_file("draw:msg1:0", "<svg>test</svg>")

        expected_hash = hashlib.sha256(b"draw:msg1:0").hexdigest()[:16]
        assert url == f"/static/images/drawings/{expected_hash}.svg"
        saved = (tmp_path / "images" / "drawings" / f"{expected_hash}.svg").read_text()
        assert saved == "<svg>test</svg>"

    def test_save_failure_returns_none(self):
        from backend.core.drawing.runtime import _save_svg_file

        with patch("pathlib.Path.mkdir", side_effect=OSError("disk full")):
            url = _save_svg_file("draw:x:0", "<svg/>")

        assert url is None

    def test_different_ids_produce_different_filenames(self, tmp_path):
        from backend.core.drawing.runtime import _save_svg_file

        with patch("backend.core.config.settings") as mock_settings:
            mock_settings.STATIC_DIR = tmp_path
            url1 = _save_svg_file("draw:a_b:0", "<svg>1</svg>")
            url2 = _save_svg_file("draw:a:b:0", "<svg>2</svg>")

        assert url1 != url2

    def test_traversal_input_stays_in_drawings_dir(self, tmp_path):
        from backend.core.drawing.runtime import _save_svg_file

        with patch("backend.core.config.settings") as mock_settings:
            mock_settings.STATIC_DIR = tmp_path
            url = _save_svg_file("../../etc/passwd", "<svg>evil</svg>")

        # Should succeed (hash makes it safe) and stay inside drawings dir
        assert url is not None
        assert "/static/images/drawings/" in url
        # Verify no file outside drawings dir
        assert not (tmp_path / "etc").exists()


# ── Room hang integration ─────────────────────────────────────────────


class TestRoomHang:
    """Test drawing-to-room wall integration."""

    def test_hang_drawing_when_enabled(self):
        from backend.core.drawing.runtime import _hang_drawing_in_room
        from backend.services.room.room_state import RoomState

        room = RoomState()
        with (
            patch("backend.core.config.settings") as mock_settings,
            patch("backend.services.room.room_state.load_room_state", return_value=room),
            patch("backend.services.room.room_state.save_room_state") as mock_save,
            patch("backend.services.room.room_action.execute_room_action", wraps=lambda r, a: r.wall_art.append({
                "id": "test",
                "image_path": a.art_image,
                "memory_link": a.memory_link,
                "description": a.name,
            })) as mock_exec,
        ):
            mock_settings.DRAWING_ROOM_ENABLED = True
            _hang_drawing_in_room("draw:m1:0", "/static/images/drawings/draw_m1_0.svg", ["anchor", "presence"])

        assert mock_exec.called
        assert mock_save.called

    def test_hang_skipped_when_disabled(self):
        from backend.core.drawing.runtime import _hang_drawing_in_room

        with patch("backend.core.config.settings") as mock_settings:
            mock_settings.DRAWING_ROOM_ENABLED = False
            _hang_drawing_in_room("draw:m1:0", "/static/test.svg", [])

    def test_hang_skipped_when_no_url(self):
        from backend.core.drawing.runtime import _hang_drawing_in_room

        with patch("backend.core.config.settings") as mock_settings:
            mock_settings.DRAWING_ROOM_ENABLED = True
            _hang_drawing_in_room("draw:m1:0", None, [])

    def test_hang_dedupes_on_memory_link(self):
        from backend.core.drawing.runtime import _hang_drawing_in_room
        from backend.services.room.room_state import RoomState

        room = RoomState()
        room.wall_art = [{"id": "old", "memory_link": "draw:m1:0", "image_path": "/old.svg"}]

        with (
            patch("backend.core.config.settings") as mock_settings,
            patch("backend.services.room.room_state.load_room_state", return_value=room),
            patch("backend.services.room.room_action.execute_room_action") as mock_exec,
        ):
            mock_settings.DRAWING_ROOM_ENABLED = True
            _hang_drawing_in_room("draw:m1:0", "/static/test.svg", [])

        assert not mock_exec.called  # Deduped

    @pytest.mark.asyncio
    async def test_replay_does_not_hang(self):
        """replay=True result should not trigger room hang (tested via runtime flow)."""
        from backend.core.drawing.runtime import render_and_store_drawing
        from backend.core.drawing.trace_store import ensure_drawing_trace_schema
        from backend.core.drawing.attempt_store import ensure_drawing_attempt_schema

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        ensure_drawing_trace_schema(conn)
        ensure_drawing_attempt_schema(conn)

        with (
            patch("backend.core.drawing.runtime.managed_conn") as mock_conn_ctx,
            patch("backend.core.drawing.runtime._save_svg_file", return_value="/static/test.svg"),
            patch("backend.core.drawing.runtime._hang_drawing_in_room") as mock_hang,
        ):
            mock_conn_ctx.return_value.__enter__ = MagicMock(return_value=conn)
            mock_conn_ctx.return_value.__exit__ = MagicMock(return_value=False)

            # First call
            await render_and_store_drawing({
                "drawing_id": "draw:replay_room:0",
                "dsl_code": "a: circle\na at center",
            })
            assert mock_hang.call_count == 1

            # Replay call — should NOT call hang again
            mock_hang.reset_mock()
            result = await render_and_store_drawing({
                "drawing_id": "draw:replay_room:0",
                "dsl_code": "a: circle\na at center",
            })
            assert result.get("replay") is True
            assert mock_hang.call_count == 0


# ── Attempt store ─────────────────────────────────────────────────────


class TestAttemptStore:
    """Test drawing_attempts table and operations."""

    @pytest.fixture()
    def conn(self):
        from backend.core.drawing.attempt_store import ensure_drawing_attempt_schema
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        ensure_drawing_attempt_schema(c)
        yield c
        c.close()

    def test_schema_creation(self, conn):
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert "drawing_attempts" in tables

    def test_save_and_list(self, conn):
        from backend.core.drawing.attempt_store import DrawingAttempt, save_attempt, list_attempts

        attempt = DrawingAttempt(
            drawing_id="draw:test:0",
            dsl_code="bad dsl",
            status="parse_error",
            error_message="Unexpected token",
            error_phase="parse",
            thread_id="t1",
            created_at="2026-03-28T12:00:00Z",
        )
        save_attempt(conn, attempt)

        attempts = list_attempts(conn)
        assert len(attempts) == 1
        assert attempts[0].drawing_id == "draw:test:0"
        assert attempts[0].status == "parse_error"
        assert attempts[0].error_phase == "parse"

    def test_idempotent_schema(self, conn):
        """ensure_drawing_attempt_schema can be called multiple times."""
        from backend.core.drawing.attempt_store import ensure_drawing_attempt_schema
        ensure_drawing_attempt_schema(conn)  # second call
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert "drawing_attempts" in tables
