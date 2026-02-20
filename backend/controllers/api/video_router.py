"""Video analysis API endpoints (Phase F)."""
from __future__ import annotations

import logging
import os
import tempfile
from typing import Optional

import shutil

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from pydantic import BaseModel

from backend.core.auth import verify_system_token
from backend.core.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/video/analyze", dependencies=[Depends(verify_system_token)])
async def analyze_video(
    file: UploadFile = File(...),
    mode: str = Form("learn"),  # "learn" or "react"
    interval_sec: Optional[int] = Form(None),
    max_frames: Optional[int] = Form(None),
):
    """Upload and analyze a video file.

    Modes:
      - learn: Extract gameplay strategies → save to semantic memory
      - react: Get scene descriptions for Nia to react to
    """
    if not getattr(settings, "VIDEO_LEARNING_ENABLED", True):
        raise HTTPException(400, "Video learning is disabled")

    # Validate file type
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in (".mp4", ".webm", ".mkv", ".avi", ".mov"):
        raise HTTPException(400, f"Unsupported video format: {ext}")

    # Save upload to temp file
    with tempfile.NamedTemporaryFile(
        suffix=ext, prefix="nia_video_", delete=False,
    ) as tmp:
        content = await file.read()
        if len(content) > 200 * 1024 * 1024:  # 200MB limit
            raise HTTPException(413, "Video file too large (max 200MB)")
        tmp.write(content)
        tmp_path = tmp.name

    try:
        if mode == "react":
            from backend.services.minecraft.video_learner import react_to_video
            scenes = await react_to_video(
                tmp_path,
                interval_sec=interval_sec or 3,
                max_frames=max_frames or 10,
            )
            return {
                "mode": "react",
                "scenes": scenes,
                "frame_count": len(scenes),
            }
        else:
            from backend.services.minecraft.video_learner import learn_from_video
            result = await learn_from_video(
                tmp_path,
                llm_call=_get_llm_call(),
                interval_sec=interval_sec,
                max_frames=max_frames,
            )
            return {
                "mode": "learn",
                **result,
            }
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


class VideoUrlRequest(BaseModel):
    url: str
    mode: str = "react"  # "learn" or "react"
    interval_sec: Optional[int] = None
    max_frames: Optional[int] = None


@router.post("/video/analyze_url", dependencies=[Depends(verify_system_token)])
async def analyze_video_url(req: VideoUrlRequest):
    """Download a video from URL (YouTube etc.) and analyze it.

    Uses yt-dlp to download, then runs the same pipeline as file upload.
    Max duration: 10 minutes. Max resolution: 720p.
    """
    if not getattr(settings, "VIDEO_LEARNING_ENABLED", True):
        raise HTTPException(400, "Video learning is disabled")

    from backend.services.youtube_dl import download_video

    dl = await download_video(req.url)
    if not dl["success"]:
        raise HTTPException(400, dl.get("error", "ダウンロードに失敗しました"))

    tmp_path = dl["path"]
    tmp_dir = os.path.dirname(tmp_path)

    try:
        if req.mode == "react":
            from backend.services.minecraft.video_learner import react_to_video
            scenes = await react_to_video(
                tmp_path,
                interval_sec=req.interval_sec or 3,
                max_frames=req.max_frames or 10,
            )
            return {
                "mode": "react",
                "title": dl.get("title", ""),
                "duration": dl.get("duration", 0),
                "scenes": scenes,
                "frame_count": len(scenes),
            }
        else:
            from backend.services.minecraft.video_learner import learn_from_video
            result = await learn_from_video(
                tmp_path,
                llm_call=_get_llm_call(),
                interval_sec=req.interval_sec,
                max_frames=req.max_frames,
            )
            return {
                "mode": "learn",
                "title": dl.get("title", ""),
                "duration": dl.get("duration", 0),
                **result,
            }
    finally:
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except OSError:
            pass


@router.post("/video/learn_motion", dependencies=[Depends(verify_system_token)])
async def learn_motion(
    file: UploadFile = File(...),
    interval_sec: Optional[int] = Form(None),
    max_frames: Optional[int] = Form(None),
):
    """Upload a VTuber/animation video and extract motion patterns.

    Extracts gesture patterns → saves to Motion Library + Semantic Memory.
    """
    if not getattr(settings, "VIDEO_LEARNING_ENABLED", True):
        raise HTTPException(400, "Video learning is disabled")

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in (".mp4", ".webm", ".mkv", ".avi", ".mov"):
        raise HTTPException(400, f"Unsupported video format: {ext}")

    with tempfile.NamedTemporaryFile(
        suffix=ext, prefix="nia_motion_", delete=False,
    ) as tmp:
        content = await file.read()
        if len(content) > 200 * 1024 * 1024:
            raise HTTPException(413, "Video file too large (max 200MB)")
        tmp.write(content)
        tmp_path = tmp.name

    try:
        from backend.services.motion_learner import learn_motion_from_video
        result = await learn_motion_from_video(
            tmp_path,
            llm_call=_get_llm_call(),
            interval_sec=interval_sec,
            max_frames=max_frames,
        )
        return {"mode": "motion_learn", **result}
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@router.post("/video/learn_motion_url", dependencies=[Depends(verify_system_token)])
async def learn_motion_url(req: VideoUrlRequest):
    """Download a VTuber/animation video from URL and extract motion patterns."""
    if not getattr(settings, "VIDEO_LEARNING_ENABLED", True):
        raise HTTPException(400, "Video learning is disabled")

    from backend.services.youtube_dl import download_video

    dl = await download_video(req.url)
    if not dl["success"]:
        raise HTTPException(400, dl.get("error", "ダウンロードに失敗しました"))

    tmp_path = dl["path"]
    tmp_dir = os.path.dirname(tmp_path)

    try:
        from backend.services.motion_learner import learn_motion_from_video
        result = await learn_motion_from_video(
            tmp_path,
            llm_call=_get_llm_call(),
            interval_sec=req.interval_sec,
            max_frames=req.max_frames,
        )
        return {
            "mode": "motion_learn",
            "title": dl.get("title", ""),
            "duration": dl.get("duration", 0),
            **result,
        }
    finally:
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except OSError:
            pass


@router.get("/video/status")
async def video_status():
    """Check video learning feature status."""
    return {
        "enabled": getattr(settings, "VIDEO_LEARNING_ENABLED", True),
        "frame_interval_sec": getattr(settings, "VIDEO_FRAME_INTERVAL_SEC", 5),
        "max_frames": getattr(settings, "VIDEO_MAX_FRAMES", 20),
        "concurrency": getattr(settings, "VIDEO_VISION_CONCURRENCY", 4),
    }


def _get_llm_call():
    """Get an LLM call function for strategy extraction."""
    try:
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model=settings.OPENAI_MODEL,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            temperature=0.3,
        )

        async def call(system: str, user: str) -> str:
            from langchain_core.messages import SystemMessage, HumanMessage
            msgs = [SystemMessage(content=system), HumanMessage(content=user)]
            result = await llm.ainvoke(msgs)
            return result.content

        return call
    except Exception:
        logger.warning("[VideoRouter] Could not create LLM call, strategies will be skipped")
        return None
