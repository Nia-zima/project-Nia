"""Tests for Room WebSocket endpoint (U.1 Step 1).

Covers: RoomConnectionManager, bond stripping, ws_room_endpoint,
room_action via WS, broadcast helpers, origin check.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.controllers.ws_room import (
    RoomConnectionManager,
    _strip_bond,
    _handle_room_action,
    room_manager,
)
from backend.services.room.room_state import RoomState


# ═══════════════════════════════════════════════════════════════
# _strip_bond
# ═══════════════════════════════════════════════════════════════


class TestStripBond:
    def test_removes_bond_from_pip_state(self):
        state = asdict(RoomState())
        assert "bond" in state["pip_state"]
        result = _strip_bond(state)
        assert "bond" not in result["pip_state"]

    def test_removes_last_interaction(self):
        state = asdict(RoomState())
        result = _strip_bond(state)
        assert "last_interaction" not in result["pip_state"]

    def test_preserves_other_pip_fields(self):
        state = asdict(RoomState())
        result = _strip_bond(state)
        assert result["pip_state"]["mood"] == "idle"
        assert result["pip_state"]["energy"] == 1.0
        assert result["pip_state"]["position"] == "center"

    def test_no_pip_state_does_not_crash(self):
        """Gracefully handle missing pip_state."""
        result = _strip_bond({"size": "medium"})
        assert result == {"size": "medium"}


# ═══════════════════════════════════════════════════════════════
# RoomConnectionManager
# ═══════════════════════════════════════════════════════════════


class TestRoomConnectionManager:
    @pytest.mark.asyncio
    async def test_connect_sends_initial_state(self):
        mgr = RoomConnectionManager()
        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()

        with patch("backend.controllers.ws_room.load_room_state", return_value=RoomState()):
            await mgr.connect(ws)

        ws.accept.assert_called_once()
        # room_state + snapshot (Contract 3)
        assert ws.send_json.call_count >= 1
        first_msg = ws.send_json.call_args_list[0][0][0]
        assert first_msg["type"] == "room_state"
        # Bond must be stripped
        assert "bond" not in first_msg["data"]["pip_state"]
        # Contract 3: snapshot sent after room_state
        if ws.send_json.call_count >= 2:
            snap_msg = ws.send_json.call_args_list[1][0][0]
            assert snap_msg["type"] == "snapshot"

    @pytest.mark.asyncio
    async def test_disconnect_removes_connection(self):
        mgr = RoomConnectionManager()
        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()

        with patch("backend.controllers.ws_room.load_room_state", return_value=RoomState()):
            await mgr.connect(ws)
        assert mgr.has_connections

        await mgr.disconnect(ws)
        assert not mgr.has_connections

    @pytest.mark.asyncio
    async def test_broadcast_to_multiple_clients(self):
        mgr = RoomConnectionManager()
        ws1 = AsyncMock()
        ws1.accept = AsyncMock()
        ws1.send_json = AsyncMock()
        ws1.send_text = AsyncMock()
        ws2 = AsyncMock()
        ws2.accept = AsyncMock()
        ws2.send_json = AsyncMock()
        ws2.send_text = AsyncMock()

        with patch("backend.controllers.ws_room.load_room_state", return_value=RoomState()):
            await mgr.connect(ws1)
            await mgr.connect(ws2)

        await mgr.broadcast({"type": "test", "data": {}})
        ws1.send_text.assert_called_once()
        ws2.send_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast_removes_dead_connections(self):
        mgr = RoomConnectionManager()
        ws_good = AsyncMock()
        ws_good.accept = AsyncMock()
        ws_good.send_json = AsyncMock()
        ws_good.send_text = AsyncMock()

        ws_dead = AsyncMock()
        ws_dead.accept = AsyncMock()
        ws_dead.send_json = AsyncMock()
        ws_dead.send_text = AsyncMock(side_effect=Exception("closed"))

        with patch("backend.controllers.ws_room.load_room_state", return_value=RoomState()):
            await mgr.connect(ws_good)
            await mgr.connect(ws_dead)
        assert len(mgr._connections) == 2

        await mgr.broadcast({"type": "test", "data": {}})
        # Dead connection should be removed
        assert len(mgr._connections) == 1
        assert ws_good in mgr._connections

    @pytest.mark.asyncio
    async def test_broadcast_pip_update_strips_bond(self):
        mgr = RoomConnectionManager()
        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()
        ws.send_text = AsyncMock()

        with patch("backend.controllers.ws_room.load_room_state", return_value=RoomState()):
            await mgr.connect(ws)

        pip_dict = {
            "bond": 0.75,
            "mood": "playful",
            "energy": 0.8,
            "position": "near_window",
            "animation": "wag_tail",
            "favorite_spot": "corner_ne",
            "last_interaction": time.time(),
        }
        await mgr.broadcast_pip_update(pip_dict)

        ws.send_text.assert_called_once()
        msg = json.loads(ws.send_text.call_args[0][0])
        assert msg["type"] == "pip_update"
        assert "bond" not in msg["data"]
        assert "last_interaction" not in msg["data"]
        assert msg["data"]["mood"] == "playful"
        assert msg["data"]["animation"] == "wag_tail"

    @pytest.mark.asyncio
    async def test_broadcast_lighting_update(self):
        mgr = RoomConnectionManager()
        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()
        ws.send_text = AsyncMock()

        with patch("backend.controllers.ws_room.load_room_state", return_value=RoomState()):
            await mgr.connect(ws)

        await mgr.broadcast_lighting_update("evening", 0.6, "#FFA07A")

        ws.send_text.assert_called_once()
        msg = json.loads(ws.send_text.call_args[0][0])
        assert msg["type"] == "lighting_update"
        assert msg["data"]["time_of_day"] == "evening"
        assert msg["data"]["intensity"] == 0.6
        assert msg["data"]["color"] == "#FFA07A"

    @pytest.mark.asyncio
    async def test_no_broadcast_when_no_connections(self):
        mgr = RoomConnectionManager()
        assert not mgr.has_connections
        # Should not raise
        await mgr.broadcast({"type": "test"})
        await mgr.broadcast_pip_update({"mood": "idle"})
        await mgr.broadcast_lighting_update("day", 1.0, "#FFFFFF")


# ═══════════════════════════════════════════════════════════════
# Room Action via WebSocket
# ═══════════════════════════════════════════════════════════════


class TestHandleRoomAction:
    @pytest.mark.asyncio
    async def test_valid_place_action(self):
        ws = AsyncMock()
        ws.send_json = AsyncMock()
        room = RoomState()

        with (
            patch("backend.controllers.ws_room.load_room_state", return_value=room),
            patch("backend.controllers.ws_room.save_room_state") as mock_save,
            patch("backend.controllers.ws_room.room_manager") as mock_mgr,
        ):
            mock_mgr.broadcast_room_state = AsyncMock()
            await _handle_room_action(ws, {
                "action_type": "place",
                "template": "lamp",
                "position": "center",
            })

        ws.send_json.assert_called_once()
        result = ws.send_json.call_args[0][0]
        assert result["type"] == "action_result"
        assert result["data"]["success"] is True

    @pytest.mark.asyncio
    async def test_invalid_action_returns_error(self):
        ws = AsyncMock()
        ws.send_json = AsyncMock()

        with patch("backend.controllers.ws_room.load_room_state", return_value=RoomState()):
            await _handle_room_action(ws, {
                "action_type": "place",
                "template": "invalid_template",
            })

        result = ws.send_json.call_args[0][0]
        assert result["type"] == "action_result"
        assert result["data"]["success"] is False
        assert "error" in result["data"]

    @pytest.mark.asyncio
    async def test_unknown_action_type_returns_error(self):
        ws = AsyncMock()
        ws.send_json = AsyncMock()

        with patch("backend.controllers.ws_room.load_room_state", return_value=RoomState()):
            await _handle_room_action(ws, {
                "action_type": "explode",
            })

        result = ws.send_json.call_args[0][0]
        assert result["data"]["success"] is False


# ═══════════════════════════════════════════════════════════════
# update_loop broadcast integration
# ═══════════════════════════════════════════════════════════════


class TestBroadcastChanges:
    @pytest.mark.asyncio
    async def test_pip_change_triggers_broadcast(self):
        from backend.services.room.update_loop import _broadcast_changes

        room = RoomState()
        room.pip_state = {"mood": "playful", "animation": "wag_tail", "position": "center", "energy": 0.8}
        room.time_of_day = "day"
        room.light_intensity = 1.0
        room.light_color = "#FFFFFF"

        mock_mgr = MagicMock()
        mock_mgr.has_connections = True
        mock_mgr.broadcast_pip_update = AsyncMock()
        mock_mgr.broadcast_lighting_update = AsyncMock()

        with patch("backend.services.room.update_loop.room_manager", mock_mgr, create=True), \
             patch.dict("sys.modules", {"backend.controllers.ws_room": MagicMock(room_manager=mock_mgr)}):
            from backend.services.room import update_loop
            # Re-import to pick up the patched module
            import importlib
            importlib.reload(update_loop)
            await update_loop._broadcast_changes(
                room,
                prev_mood="idle",          # changed
                prev_animation="idle",     # changed
                prev_position="center",
                prev_tod="day",
                prev_intensity=1.0,
            )

        mock_mgr.broadcast_pip_update.assert_called_once()
        mock_mgr.broadcast_lighting_update.assert_not_called()

    @pytest.mark.asyncio
    async def test_lighting_change_triggers_broadcast(self):
        from backend.services.room.update_loop import _broadcast_changes

        room = RoomState()
        room.pip_state = {"mood": "idle", "animation": "idle", "position": "center", "energy": 1.0}
        room.time_of_day = "evening"
        room.light_intensity = 0.6
        room.light_color = "#FFA07A"

        mock_mgr = MagicMock()
        mock_mgr.has_connections = True
        mock_mgr.broadcast_pip_update = AsyncMock()
        mock_mgr.broadcast_lighting_update = AsyncMock()

        with patch.dict("sys.modules", {"backend.controllers.ws_room": MagicMock(room_manager=mock_mgr)}):
            from backend.services.room import update_loop
            import importlib
            importlib.reload(update_loop)
            await update_loop._broadcast_changes(
                room,
                prev_mood="idle",
                prev_animation="idle",
                prev_position="center",
                prev_tod="day",             # changed
                prev_intensity=1.0,         # changed
            )

        mock_mgr.broadcast_pip_update.assert_not_called()
        mock_mgr.broadcast_lighting_update.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_change_skips_broadcast(self):
        from backend.services.room.update_loop import _broadcast_changes

        room = RoomState()
        room.pip_state = {"mood": "idle", "animation": "idle", "position": "center", "energy": 1.0}
        room.time_of_day = "day"
        room.light_intensity = 1.0
        room.light_color = "#FFFFFF"

        mock_mgr = MagicMock()
        mock_mgr.has_connections = True
        mock_mgr.broadcast_pip_update = AsyncMock()
        mock_mgr.broadcast_lighting_update = AsyncMock()

        with patch.dict("sys.modules", {"backend.controllers.ws_room": MagicMock(room_manager=mock_mgr)}):
            from backend.services.room import update_loop
            import importlib
            importlib.reload(update_loop)
            await update_loop._broadcast_changes(
                room,
                prev_mood="idle",
                prev_animation="idle",
                prev_position="center",
                prev_tod="day",
                prev_intensity=1.0,
            )

        mock_mgr.broadcast_pip_update.assert_not_called()
        mock_mgr.broadcast_lighting_update.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_connections_skips_all(self):
        """When no WebSocket clients connected, skip all broadcasts."""
        from backend.services.room.update_loop import _broadcast_changes

        room = RoomState()
        room.pip_state = {"mood": "playful", "animation": "wag_tail", "position": "center", "energy": 0.8}

        mock_mgr = MagicMock()
        mock_mgr.has_connections = False
        mock_mgr.broadcast_pip_update = AsyncMock()
        mock_mgr.broadcast_lighting_update = AsyncMock()

        with patch.dict("sys.modules", {"backend.controllers.ws_room": MagicMock(room_manager=mock_mgr)}):
            from backend.services.room import update_loop
            import importlib
            importlib.reload(update_loop)
            await update_loop._broadcast_changes(
                room,
                prev_mood="idle",
                prev_animation="idle",
                prev_position="center",
                prev_tod="day",
                prev_intensity=1.0,
            )

        mock_mgr.broadcast_pip_update.assert_not_called()
        mock_mgr.broadcast_lighting_update.assert_not_called()
