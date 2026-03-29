"""Game integration API endpoints (Minecraft + Screen-based games)."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query, status
from pydantic import BaseModel

from backend.controllers.ws_security import is_ws_origin_allowed
from backend.core.auth import verify_system_token

router = APIRouter()
logger = logging.getLogger(__name__)


class ActionRequest(BaseModel):
    action: str
    params: dict[str, Any] = {}


class ConnectRequest(BaseModel):
    host: str = "localhost"
    port: int = 25565
    username: str = "Nia"
    version: str = "1.20.4"


class ScreenGameStartRequest(BaseModel):
    game_config_id: str = "generic"


class ProfileSwitchRequest(BaseModel):
    game_id: str


def _get_client():
    from backend.services.minecraft import minecraft_client
    return minecraft_client


def _get_state_manager():
    from backend.services.minecraft import minecraft_state
    return minecraft_state


def _get_event_listener():
    from backend.services.minecraft import minecraft_events
    return minecraft_events


@router.get("/game/status")
async def game_status():
    """Bot connection status."""
    client = _get_client()
    if not client:
        return {"connected": False, "enabled": False}
    connected = await client.is_connected()
    return {"connected": connected, "enabled": True, "game": "minecraft"}


@router.get("/game/state")
async def game_state():
    """Current game state snapshot."""
    client = _get_client()
    if not client:
        return {"connected": False, "error": "Minecraft not enabled"}
    return await client.get_state()


@router.post("/game/action", dependencies=[Depends(verify_system_token)])
async def game_action(req: ActionRequest):
    """Execute a game action."""
    client = _get_client()
    if not client:
        return {"success": False, "error": "Minecraft not enabled"}
    return await client.execute_action(req.action, req.params)


@router.post("/game/connect", dependencies=[Depends(verify_system_token)])
async def game_connect(req: ConnectRequest):
    """Connect bot to Minecraft server."""
    client = _get_client()
    if not client:
        return {"ok": False, "error": "Minecraft not enabled"}

    result = await client.connect(
        host=req.host, port=req.port,
        username=req.username, version=req.version,
    )

    # Start event listener
    events = _get_event_listener()
    if events:
        await events.start()

    return result


@router.post("/game/disconnect", dependencies=[Depends(verify_system_token)])
async def game_disconnect():
    """Disconnect bot from Minecraft server."""
    client = _get_client()
    if not client:
        return {"ok": False, "error": "Minecraft not enabled"}

    events = _get_event_listener()
    if events:
        await events.stop()

    return await client.disconnect()


@router.get("/game/events")
async def game_events(limit: int = Query(20, ge=1, le=100)):
    """Recent game events."""
    mgr = _get_state_manager()
    if not mgr:
        return {"events": []}
    return {"events": mgr.get_recent_events(max_events=limit)}


@router.websocket("/game/ws")
async def game_ws(websocket: WebSocket):
    """WebSocket for real-time game events to frontend."""
    origin = websocket.headers.get("origin")
    if not is_ws_origin_allowed(origin):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()

    events = _get_event_listener()
    if not events:
        await websocket.close(code=1011, reason="Minecraft not enabled")
        return

    queue: asyncio.Queue = asyncio.Queue(maxsize=100)

    def on_event(event: dict):
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            pass

    events.on_event(on_event)

    async def _sender():
        """Send game events to client."""
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                await websocket.send_json(event)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping", "ts": 0})

    async def _receiver():
        """Read from client to detect disconnection."""
        while True:
            data = await websocket.receive()
            logger.debug("[GAME_WS] Received: %s", data)

    sender_task = asyncio.create_task(_sender())
    receiver_task = asyncio.create_task(_receiver())
    try:
        done, pending = await asyncio.wait(
            [sender_task, receiver_task],
            return_when=asyncio.FIRST_EXCEPTION,
        )
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc and not isinstance(exc, WebSocketDisconnect):
                logger.warning("[GAME_WS] Connection closed: %s", exc)
    except WebSocketDisconnect:
        logger.info("[GAME_WS] Client disconnected (WebSocketDisconnect)")
    except Exception as e:
        logger.warning("[GAME_WS] Connection closed: %s: %s", type(e).__name__, e)
    finally:
        sender_task.cancel()
        receiver_task.cancel()
        events.remove_callback(on_event)
        logger.info("[GAME_WS] Cleanup done")


# =============================================================================
# Screen-based Game Endpoints
# =============================================================================


@router.post("/game/screen/start", dependencies=[Depends(verify_system_token)])
async def screen_game_start(req: ScreenGameStartRequest):
    """Start a screen-capture-based game session."""
    from backend.services.gaming import init_screen_gaming, generic_game_loop
    ok = init_screen_gaming(req.game_config_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Failed to initialize screen gaming")
    return {"ok": True, "game_config_id": req.game_config_id}


@router.post("/game/screen/stop", dependencies=[Depends(verify_system_token)])
async def screen_game_stop():
    """Stop the screen-capture game session."""
    from backend.services.gaming import shutdown_screen_gaming
    shutdown_screen_gaming()
    return {"ok": True}


@router.get("/game/screen/status")
async def screen_game_status():
    """Get screen game loop status."""
    from backend.services.gaming import generic_game_loop
    if not generic_game_loop:
        return {"running": False, "enabled": False}
    return {**generic_game_loop.get_status(), "enabled": True}


# =============================================================================
# Game Profile Management
# =============================================================================


@router.get("/game/profiles")
async def list_game_profiles():
    """List all registered game profiles."""
    from backend.services.game_profiles.registry import game_profile_registry
    return {"profiles": game_profile_registry.list_profiles()}


@router.post("/game/profiles/switch", dependencies=[Depends(verify_system_token)])
async def switch_game_profile(req: ProfileSwitchRequest):
    """Switch active game profile."""
    from backend.services.game_profiles.registry import game_profile_registry
    ok = game_profile_registry.set_active(req.game_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Unknown profile: {req.game_id}")
    return {"ok": True, "active": req.game_id}


@router.get("/game/configs")
async def list_game_configs():
    """List available screen game configurations."""
    from backend.services.gaming.game_configs import list_configs
    return {"configs": list_configs()}
