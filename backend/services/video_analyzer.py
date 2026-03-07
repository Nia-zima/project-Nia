"""Video analysis pipeline: ffmpeg frame extraction + Vision model analysis."""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

from backend.core.config import settings

logger = logging.getLogger(__name__)


async def extract_frames(
    video_path: str,
    *,
    interval_sec: int | None = None,
    max_frames: int | None = None,
) -> list[bytes]:
    """Extract frames from a video file using ffmpeg.

    Args:
        video_path: Path to the video file.
        interval_sec: Seconds between frames (default from settings).
        max_frames: Maximum frames to extract (default from settings).

    Returns:
        List of JPEG image bytes.
    """
    interval = interval_sec or settings.VIDEO_FRAME_INTERVAL_SEC
    max_f = max_frames or settings.VIDEO_MAX_FRAMES

    if not Path(video_path).exists():
        logger.error("[VideoAnalyzer] File not found: %s", video_path)
        return []

    with tempfile.TemporaryDirectory(prefix="nia_frames_") as tmpdir:
        output_pattern = os.path.join(tmpdir, "frame_%04d.jpg")

        cmd = [
            "ffmpeg", "-i", video_path,
            "-vf", f"fps=1/{interval}",
            "-frames:v", str(max_f),
            "-q:v", "2",  # high quality JPEG
            output_pattern,
            "-y", "-loglevel", "warning",
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

            if proc.returncode != 0:
                logger.error(
                    "[VideoAnalyzer] ffmpeg failed (rc=%d): %s",
                    proc.returncode, stderr.decode()[:300],
                )
                return []
        except asyncio.TimeoutError:
            logger.error("[VideoAnalyzer] ffmpeg timed out")
            proc.kill()
            await proc.wait()
            return []
        except FileNotFoundError:
            logger.error("[VideoAnalyzer] ffmpeg not found in PATH")
            return []

        # Collect frame files sorted by name
        frame_files = sorted(Path(tmpdir).glob("frame_*.jpg"))
        frames = []
        for f in frame_files[:max_f]:
            frames.append(f.read_bytes())

        logger.info(
            "[VideoAnalyzer] Extracted %d frames from %s (interval=%ds)",
            len(frames), Path(video_path).name, interval,
        )
        return frames


async def analyze_frames(
    frames: list[bytes],
    *,
    prompt: str = "この画像はMinecraftのゲーム画面です。何が起きているか簡潔に日本語で説明して。",
    concurrency: int | None = None,
) -> list[str]:
    """Analyze frames with the Vision model (Qwen3-VL).

    Args:
        frames: List of JPEG image bytes.
        prompt: Vision prompt for each frame.
        concurrency: Max concurrent vision calls (default from settings).

    Returns:
        List of description strings, one per frame.
    """
    from backend.services.vision_client import analyze_image

    max_concurrent = concurrency or settings.VIDEO_VISION_CONCURRENCY
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _analyze_one(frame_bytes: bytes) -> str:
        b64 = base64.b64encode(frame_bytes).decode("ascii")
        async with semaphore:
            try:
                return await analyze_image(b64, prompt=prompt)
            except Exception:
                logger.warning("[VideoAnalyzer] Frame analysis failed", exc_info=True)
                return ""

    tasks = [_analyze_one(f) for f in frames]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r and not r.startswith("[")]


async def analyze_video(
    video_path: str,
    *,
    prompt: str = "この画像はMinecraftのゲーム画面です。何が起きているか簡潔に日本語で説明して。",
    interval_sec: int | None = None,
    max_frames: int | None = None,
) -> list[str]:
    """Full pipeline: extract frames + analyze each with Vision.

    Returns list of frame descriptions.
    """
    frames = await extract_frames(
        video_path, interval_sec=interval_sec, max_frames=max_frames,
    )
    if not frames:
        return []

    return await analyze_frames(frames, prompt=prompt)
