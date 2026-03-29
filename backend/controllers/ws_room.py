"""
WebSocket endpoint for Nia's Room — real-time state sync with Unity.

Design doc: docs/pip_and_room_design.md, docs/pip_room_temporal_livestream_integration.md §8
Plan: U.1+U.3 Step 1a + Contract 3

Server → Client messages:
  {"type": "room_state", "data": {…full RoomState…}}
  {"type": "pip_update", "data": {"mood", "animation", "position", "energy"}}
  {"type": "lighting_update", "data": {"time_of_day", "intensity", "color"}}
  {"type": "snapshot", …}           — sent on connect (Contract 3)
  {"type": "state", "key": …}       — conversation state transition (Contract 3)
  {"type": "motion", …}             — motion events (Contract 3)

Client → Server messages:
  {"type": "room_action", "data": {"action_type", "template", "position", …}}
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import asdict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.controllers.ws_security import (
    is_ws_origin_allowed,
    WS_MAX_MESSAGE_BYTES,
    WS_RECEIVE_TIMEOUT_SEC,
)
from backend.core.logger import logger
from backend.services.room.room_state import load_room_state, save_room_state, RoomState
from backend.services.room.room_action import (
    RoomAction,
    RoomActionError,
    execute_room_action,
)

router = APIRouter()


def _strip_bond(state_dict: dict) -> dict:
    """Remove bond value from pip_state before sending to clients.

    CLAUDE.md rule: 「Pipの Bond値を露出しない」
    Bond must never be visible to Nia or viewers.
    """
    pip = state_dict.get("pip_state")
    if isinstance(pip, dict):
        pip.pop("bond", None)
        pip.pop("last_interaction", None)
    return state_dict


class RoomConnectionManager:
    """Manage active WebSocket connections for room state sync."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()
        # Contract 3: track current conversation state for snapshot
        from backend.services.room.motion_events import ConversationState
        self._conversation_state: ConversationState = ConversationState.IDLE
        # Contract 3: Global motion prev state (NOT thread-scoped).
        # Room/Pip are global, so motion events must compare against last
        # *broadcast* state, not per-thread telemetry_kv.
        self._motion_prev_pip_visible: str | None = None
        self._motion_prev_time_of_day: str | None = None
        self._motion_prev_pip_position_near: bool = False

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.append(ws)

        # Send initial full state
        room = load_room_state()
        state_dict = _strip_bond(asdict(room))
        await ws.send_json({"type": "room_state", "data": state_dict})

        # Contract 3: Send snapshot so late subscribers know current state
        try:
            from backend.services.room.motion_events import (
                ConversationState,
                build_snapshot,
            )
            from backend.services.room.runtime_facts import (
                PipVisible,
                TimeOfDay,
                hour_to_time_of_day,
                mood_to_visible,
            )
            from datetime import datetime

            pip = room.pip_state or {}
            snapshot = build_snapshot(
                conversation_state=self._conversation_state,
                pip_visible=mood_to_visible(pip.get("mood", "idle")),
                pip_position_near=pip.get("position", "") in ("near_nia", "next_to_nia"),
                time_of_day=hour_to_time_of_day(datetime.now().hour),
            )
            await ws.send_json(snapshot)
        except Exception:
            pass  # non-critical: snapshot is a bonus

        logger.info("[WS_ROOM] client connected (total: %d)", len(self._connections))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            if ws in self._connections:
                self._connections.remove(ws)
        logger.info("[WS_ROOM] client disconnected (total: %d)", len(self._connections))

    @property
    def has_connections(self) -> bool:
        return len(self._connections) > 0

    async def broadcast(self, message: dict) -> None:
        """Broadcast a JSON message to all connected clients."""
        if not self._connections:
            return
        dead: list[WebSocket] = []
        payload = json.dumps(message, ensure_ascii=False)
        async with self._lock:
            for ws in self._connections:
                try:
                    await ws.send_text(payload)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self._connections.remove(ws)
        if dead:
            logger.debug("[WS_ROOM] removed %d dead connections", len(dead))

    async def broadcast_room_state(self, room: RoomState) -> None:
        """Broadcast full room state (used on initial sync or major changes)."""
        state_dict = _strip_bond(asdict(room))
        await self.broadcast({"type": "room_state", "data": state_dict})

    async def broadcast_pip_update(self, pip_dict: dict) -> None:
        """Broadcast Pip state changes (mood, animation, position, energy)."""
        safe = {
            "mood": pip_dict.get("mood", "idle"),
            "animation": pip_dict.get("animation", "idle"),
            "position": pip_dict.get("position", "center"),
            "energy": pip_dict.get("energy", 1.0),
            "favorite_spot": pip_dict.get("favorite_spot", ""),
        }
        await self.broadcast({"type": "pip_update", "data": safe})

    async def broadcast_lighting_update(
        self, time_of_day: str, intensity: float, color: str
    ) -> None:
        """Broadcast lighting changes."""
        await self.broadcast({
            "type": "lighting_update",
            "data": {
                "time_of_day": time_of_day,
                "intensity": intensity,
                "color": color,
            },
        })

    # ── Contract 3: Motion events ──

    async def broadcast_conversation_state(self, state: str) -> None:
        """Broadcast conversation state transition."""
        from backend.services.room.motion_events import (
            ConversationState,
            build_conversation_state_message,
        )
        cs = ConversationState(state)
        self._conversation_state = cs
        await self.broadcast(build_conversation_state_message(cs))

    async def broadcast_motion_events(self, events: list) -> None:
        """Broadcast motion events to all connected clients."""
        for event in events:
            await self.broadcast(event.to_ws_message())


# Global singleton — imported by update_loop.py for broadcasting
room_manager = RoomConnectionManager()


@router.websocket("/ws/room")
async def ws_room_endpoint(ws: WebSocket):
    """WebSocket endpoint for room state synchronization."""
    # Origin check
    origin = ws.headers.get("origin")
    if not is_ws_origin_allowed(origin):
        logger.warning("[WS_ROOM] rejected origin: %s", origin)
        await ws.close(code=4003, reason="Origin not allowed")
        return

    await room_manager.connect(ws)
    try:
        while True:
            try:
                raw = await asyncio.wait_for(
                    ws.receive_text(),
                    timeout=WS_RECEIVE_TIMEOUT_SEC,
                )
            except asyncio.TimeoutError:
                # Keep-alive timeout — close gracefully
                await ws.close(code=1000, reason="Timeout")
                break

            if len(raw.encode("utf-8")) > WS_MAX_MESSAGE_BYTES:
                await ws.send_json({"type": "error", "data": {"message": "Message too large"}})
                continue

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_json({"type": "error", "data": {"message": "Invalid JSON"}})
                continue

            msg_type = msg.get("type", "")
            if msg_type == "room_action":
                await _handle_room_action(ws, msg.get("data", {}))
            elif msg_type == "ping":
                await ws.send_json({"type": "pong"})
            else:
                await ws.send_json({
                    "type": "error",
                    "data": {"message": f"Unknown message type: {msg_type}"},
                })

    except WebSocketDisconnect as e:
        logger.info(f"[WS_ROOM] client disconnected (code={e.code})")
    except RuntimeError as e:
        if "Unexpected ASGI message" in str(e) or "client" in str(e).lower():
            logger.info("[WS_ROOM] client disconnected abruptly")
        else:
            logger.warning("[WS_ROOM] unexpected RuntimeError", exc_info=True)
    except Exception:
        logger.warning("[WS_ROOM] unexpected error", exc_info=True)
    finally:
        await room_manager.disconnect(ws)


async def _handle_room_action(ws: WebSocket, data: dict) -> None:
    """Process a room action from Unity client."""
    try:
        action = RoomAction(
            action_type=data.get("action_type", ""),
            target_id=data.get("target_id", ""),
            template=data.get("template", ""),
            position=data.get("position", ""),
            color=data.get("color", ""),
            art_image=data.get("art_image", ""),
            name=data.get("name", ""),
        )
        room = load_room_state()
        room = execute_room_action(room, action)
        save_room_state(room)

        # Broadcast updated state to all clients
        await room_manager.broadcast_room_state(room)

        await ws.send_json({"type": "action_result", "data": {"success": True}})

    except RoomActionError as e:
        await ws.send_json({
            "type": "action_result",
            "data": {"success": False, "error": str(e)},
        })
    except Exception:
        logger.warning("[WS_ROOM] room_action failed", exc_info=True)
        await ws.send_json({
            "type": "action_result",
            "data": {"success": False, "error": "Internal error"},
        })
