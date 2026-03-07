"""YouTube video downloader using yt-dlp."""
from __future__ import annotations

import logging
import os
import tempfile
from typing import Optional

logger = logging.getLogger(__name__)

# Max video duration in seconds (10 minutes)
MAX_DURATION_SEC = 600


async def download_video(
    url: str,
    *,
    max_duration: int = MAX_DURATION_SEC,
    max_height: int = 720,
) -> dict:
    """Download a video from YouTube (or other yt-dlp supported sites).

    Args:
        url: Video URL.
        max_duration: Max duration in seconds (reject longer videos).
        max_height: Max video height for download (720p default).

    Returns:
        {"success": True, "path": str, "title": str, "duration": int}
        or {"success": False, "error": str}
    """
    import asyncio

    try:
        return await asyncio.to_thread(
            _download_sync, url, max_duration=max_duration, max_height=max_height,
        )
    except Exception as e:
        logger.exception("[YouTubeDL] Download failed: %s", url)
        return {"success": False, "error": str(e)}


def _download_sync(
    url: str,
    *,
    max_duration: int = MAX_DURATION_SEC,
    max_height: int = 720,
) -> dict:
    """Synchronous download implementation."""
    try:
        import yt_dlp
    except Exception:
        return {
            "success": False,
            "error": "yt_dlp がインストールされていません",
        }

    # First, extract info to check duration
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
        except Exception as e:
            return {"success": False, "error": f"動画を取得できません: {e}"}

    if info is None:
        return {"success": False, "error": "動画情報を取得できませんでした"}

    duration = info.get("duration") or 0
    title = info.get("title", "unknown")

    if duration > max_duration:
        return {
            "success": False,
            "error": f"動画が長すぎます（{duration}秒）。上限は{max_duration}秒です。",
        }

    # Download to temp file
    tmp_dir = tempfile.mkdtemp(prefix="nia_ytdl_")
    output_template = os.path.join(tmp_dir, "video.%(ext)s")

    ydl_opts = {
        "format": f"bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]/best",
        "outtmpl": output_template,
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            ydl.download([url])
        except Exception as e:
            return {"success": False, "error": f"ダウンロード失敗: {e}"}

    # Find the downloaded file
    files = [f for f in os.listdir(tmp_dir) if f.startswith("video.")]
    if not files:
        return {"success": False, "error": "ダウンロードされたファイルが見つかりません"}

    filepath = os.path.join(tmp_dir, files[0])
    logger.info(
        "[YouTubeDL] Downloaded: %s (%ds) → %s",
        title, duration, filepath,
    )

    return {
        "success": True,
        "path": filepath,
        "tmp_dir": tmp_dir,
        "title": title,
        "duration": duration,
    }
