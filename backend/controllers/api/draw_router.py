from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from backend.services.draw_agent_service import draw_agent_service

router = APIRouter()


class DrawStartRequest(BaseModel):
    prompt: str = ""
    width: int = 800
    height: int = 500
    interval_sec: float = 1.2
    max_strokes: int = 40
    timeout_sec: int = 180


class DrawObserveRequest(BaseModel):
    session_id: str
    image_data: str


class DrawStopRequest(BaseModel):
    session_id: Optional[str] = None
    emergency: bool = False


@router.post("/draw/session/start")
async def draw_session_start(req: DrawStartRequest) -> dict:
    return draw_agent_service.start_session(
        prompt=req.prompt,
        width=req.width,
        height=req.height,
        interval_sec=req.interval_sec,
        max_strokes=req.max_strokes,
        timeout_sec=req.timeout_sec,
    )


@router.get("/draw/session/state")
async def draw_session_state() -> dict:
    return draw_agent_service.get_state()


@router.post("/draw/observe")
async def draw_observe(req: DrawObserveRequest) -> dict:
    return draw_agent_service.observe(session_id=req.session_id, image_data=req.image_data)


@router.get("/draw/commands")
async def draw_commands(
    session_id: str = Query(...),
    since_seq: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
) -> dict:
    return draw_agent_service.get_commands(session_id=session_id, since_seq=since_seq, limit=limit)


@router.post("/draw/session/stop")
async def draw_session_stop(req: DrawStopRequest) -> dict:
    return draw_agent_service.stop_session(
        emergency=bool(req.emergency),
        reason="stopped_by_user",
    )
