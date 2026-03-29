"""Tests for youtube_dl download utility."""
from __future__ import annotations

import os
import pytest
from unittest.mock import patch, MagicMock


def _make_ydl_mock(info_return=None, info_side_effect=None, dl_side_effect=None):
    """Create a mock YoutubeDL that works as context manager."""
    instance = MagicMock()
    if info_side_effect:
        instance.extract_info.side_effect = info_side_effect
    else:
        instance.extract_info.return_value = info_return
    if dl_side_effect:
        instance.download.side_effect = dl_side_effect
    instance.__enter__ = MagicMock(return_value=instance)
    instance.__exit__ = MagicMock(return_value=False)
    return instance


class TestDownloadSync:
    """Tests for _download_sync."""

    @patch("yt_dlp.YoutubeDL")
    def test_too_long_video(self, mock_ydl_cls):
        from backend.services.youtube_dl import _download_sync

        mock_ydl_cls.return_value = _make_ydl_mock(
            info_return={"duration": 9999, "title": "Very Long Video"}
        )

        result = _download_sync("https://youtube.com/watch?v=abc", max_duration=600)
        assert result["success"] is False
        assert "長すぎ" in result["error"]

    @patch("yt_dlp.YoutubeDL")
    def test_info_extraction_failure(self, mock_ydl_cls):
        from backend.services.youtube_dl import _download_sync

        mock_ydl_cls.return_value = _make_ydl_mock(
            info_side_effect=Exception("DownloadError")
        )

        result = _download_sync("https://youtube.com/watch?v=bad")
        assert result["success"] is False

    @patch("yt_dlp.YoutubeDL")
    def test_info_returns_none(self, mock_ydl_cls):
        from backend.services.youtube_dl import _download_sync

        mock_ydl_cls.return_value = _make_ydl_mock(info_return=None)

        result = _download_sync("https://youtube.com/watch?v=none")
        assert result["success"] is False
        assert "取得できませんでした" in result["error"]

    @patch("yt_dlp.YoutubeDL")
    @patch("os.listdir")
    @patch("tempfile.mkdtemp")
    def test_successful_download(self, mock_mkdtemp, mock_listdir, mock_ydl_cls):
        from backend.services.youtube_dl import _download_sync

        mock_mkdtemp.return_value = "/tmp/nia_ytdl_test"
        mock_listdir.return_value = ["video.mp4"]

        # Two separate YoutubeDL instances: info check then download
        info_mock = _make_ydl_mock(info_return={"duration": 120, "title": "Minecraft Tutorial"})
        dl_mock = _make_ydl_mock(info_return={})
        mock_ydl_cls.side_effect = [info_mock, dl_mock]

        result = _download_sync("https://youtube.com/watch?v=good")
        assert result["success"] is True
        assert result["title"] == "Minecraft Tutorial"
        assert result["duration"] == 120
        assert result["path"].endswith("video.mp4")

    @patch("yt_dlp.YoutubeDL")
    @patch("os.listdir")
    @patch("tempfile.mkdtemp")
    def test_no_file_after_download(self, mock_mkdtemp, mock_listdir, mock_ydl_cls):
        from backend.services.youtube_dl import _download_sync

        mock_mkdtemp.return_value = "/tmp/nia_ytdl_empty"
        mock_listdir.return_value = []

        info_mock = _make_ydl_mock(info_return={"duration": 60, "title": "Test"})
        dl_mock = _make_ydl_mock(info_return={})
        mock_ydl_cls.side_effect = [info_mock, dl_mock]

        result = _download_sync("https://youtube.com/watch?v=empty")
        assert result["success"] is False
        assert "見つかりません" in result["error"]


class TestDownloadVideoAsync:
    """Tests for async download_video wrapper."""

    @pytest.mark.asyncio
    @patch("backend.services.youtube_dl._download_sync")
    async def test_async_wrapper_delegates(self, mock_sync):
        from backend.services.youtube_dl import download_video

        mock_sync.return_value = {"success": True, "path": "/tmp/v.mp4", "title": "T", "duration": 60}
        result = await download_video("https://youtube.com/watch?v=x")
        assert result["success"] is True
        mock_sync.assert_called_once()

    @pytest.mark.asyncio
    @patch("backend.services.youtube_dl._download_sync")
    async def test_async_wrapper_handles_exception(self, mock_sync):
        from backend.services.youtube_dl import download_video

        mock_sync.side_effect = RuntimeError("boom")
        result = await download_video("https://youtube.com/watch?v=err")
        assert result["success"] is False
        assert "boom" in result["error"]


class TestVideoRouterUrl:
    """Tests for /video/analyze_url endpoint."""

    @pytest.mark.asyncio
    @patch("backend.services.youtube_dl.download_video")
    async def test_download_failure_returns_400(self, mock_dl):
        from backend.controllers.api.video_router import analyze_video_url, VideoUrlRequest

        mock_dl.return_value = {"success": False, "error": "動画が長すぎます"}
        req = VideoUrlRequest(url="https://youtube.com/watch?v=long", mode="react")

        with pytest.raises(Exception) as exc_info:
            await analyze_video_url(req)
        assert exc_info.value.status_code == 400
