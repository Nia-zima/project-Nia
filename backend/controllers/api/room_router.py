"""
Room API Router — REST endpoints for Nia's room.

Design doc: docs/pip_and_room_design.md §3.3
Phase P.2: GET /state, POST /action, GET /catalog
"""
from __future__ import annotations

from dataclasses import asdict
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.core.config import settings
from backend.core.logger import logger
from backend.services.room.room_state import (
    load_room_state,
    save_room_state,
    get_catalog,
)
from backend.services.room.room_action import (
    RoomAction,
    RoomActionError,
    execute_room_action,
)


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

router = APIRouter(prefix="/api/room", tags=["room"])


# ── Request models ────────────────────────────────────────────


class RoomActionRequest(BaseModel):
    action_type: str
    target_id: str = ""
    template: str = ""
    position: str = ""
    color: str = ""
    art_image: str = ""
    name: str = ""


# ── Endpoints ─────────────────────────────────────────────────


@router.get("/state")
async def get_room_state():
    """Return the current room state."""
    room = load_room_state()
    return _strip_bond(asdict(room))


@router.post("/action")
async def post_room_action(req: RoomActionRequest):
    """Execute a room action (place, move, remove, color, hang_art)."""
    room = load_room_state()
    action = RoomAction(
        action_type=req.action_type,
        target_id=req.target_id,
        template=req.template,
        position=req.position,
        color=req.color,
        art_image=req.art_image,
        name=req.name,
    )
    try:
        room = execute_room_action(room, action)
        save_room_state(room)
        return {"ok": True, "total_actions": room.total_actions}
    except RoomActionError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/catalog")
async def get_room_catalog():
    """Return available objects for placing in the room."""
    return {"catalog": get_catalog()}
