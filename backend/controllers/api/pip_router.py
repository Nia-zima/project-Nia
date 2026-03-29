"""
Pip API Router — endpoints for unity to fetch Pip and Scrap state.

Phase A: Simply exposes the state from RoomState.
"""
from fastapi import APIRouter
from pydantic import BaseModel
import random
import time

from backend.core.logger import logger
from backend.services.room.room_state import load_room_state
from backend.services.pip.pip_scrap_store import pip_scrap_store
from backend.services.pip.pip_somatic_touch import pip_somatic_touch

router = APIRouter(prefix="/api/pip", tags=["pip"])

class PipStateResponse(BaseModel):
    mood: str
    energy: float
    position: str
    animation: str
    scrap_count: int
    current_scrap_id: str
    # Note: Bond is intentionally omitted as per design ("hide the mechanism")

class PipScrapCountResponse(BaseModel):
    count: int

@router.get("/state", response_model=PipStateResponse)
async def get_pip_state() -> PipStateResponse:
    """Return the current visible state of Pip (excluding bond)."""
    room = load_room_state()
    pip = room.pip_state
    
    return PipStateResponse(
        mood=pip.get("mood", "idle"),
        energy=pip.get("energy", 1.0),
        position=pip.get("position", "center"),
        animation=pip.get("animation", "idle"),
        scrap_count=pip.get("scrap_count", 0),
        current_scrap_id=pip.get("current_scrap_id", "")
    )

@router.get("/scraps/count", response_model=PipScrapCountResponse)
async def get_pip_scrap_count() -> PipScrapCountResponse:
    """Return just the scrap count for visual filling."""
    room = load_room_state()
    # Or from room.pip_scrap_count if tracking globally, but Pip object owns it here:
    count = room.pip_state.get("scrap_count", 0)
    
    return PipScrapCountResponse(count=count)

class PipTouchResponse(BaseModel):
    scrap_id: str | None
    scrap_type: str | None
    touch_timestamp: float

@router.post("/touch", response_model=PipTouchResponse)
async def touch_pip() -> PipTouchResponse:
    """
    Phase C: Interacting with Pip.
    Returns a random currently stored scrap and logs the event.
    No somatic injection to Nia yet (shadow mode).
    """
    now = time.time()
    
    # 1. Select a scrap (weighted or random)
    # Using 'fragmented_dialogue' or 'orphaned_emotion' for now.
    recent_scraps = pip_scrap_store.get_recent_scraps(limit=50)
    
    selected_scrap = None
    if recent_scraps:
        selected_scrap = random.choice(recent_scraps)
        
    # 2. Extract bond from RoomState
    room = load_room_state()
    current_bond = room.pip_state.get("bond", 0.0)
    
    # 3. Log the touch event
    scrap_id = selected_scrap.id if selected_scrap else None
    scrap_type = selected_scrap.scrap_type if selected_scrap else None
    
    # 4. Generate Somatic Feeling (Shadow mode - only logs)
    somatic_text = pip_somatic_touch.process_touch(selected_scrap, current_bond)
    
    logger.info(
        f"[PipTouch] User touched Pip. Selected scrap: {scrap_id} ({scrap_type}). "
        f"Bond: {current_bond:.2f}. "
        f"Shadow output: {somatic_text if somatic_text else 'None'}"
    )
    
    return PipTouchResponse(
        scrap_id=scrap_id,
        scrap_type=scrap_type,
        touch_timestamp=now
    )
