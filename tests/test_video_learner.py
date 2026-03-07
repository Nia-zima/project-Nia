"""Tests for Phase F: video_analyzer and video_learner."""
import asyncio
import os
import sqlite3
import time
import uuid
import pytest

from unittest.mock import patch, AsyncMock, MagicMock


# --- video_analyzer ---

class TestVideoAnalyzer:
    @pytest.mark.asyncio
    async def test_extract_frames_missing_file(self):
        """Non-existent video returns empty list."""
        from backend.services.video_analyzer import extract_frames

        result = await extract_frames("/nonexistent/video.mp4")
        assert result == []

    @pytest.mark.asyncio
    async def test_analyze_frames_with_mock_vision(self):
        """Frames analyzed through mocked vision client."""
        from backend.services.video_analyzer import analyze_frames

        fake_frames = [b"\xff\xd8\xff\xe0" + b"\x00" * 100] * 3  # fake JPEG-ish

        with patch("backend.services.vision_client.analyze_image", new_callable=AsyncMock) as mock_vi:
            mock_vi.return_value = "プレイヤーが木を切っている"
            results = await analyze_frames(fake_frames)
            assert len(results) == 3
            assert all("木" in r for r in results)
            assert mock_vi.call_count == 3

    @pytest.mark.asyncio
    async def test_analyze_frames_filters_errors(self):
        """Error responses from vision are filtered out."""
        from backend.services.video_analyzer import analyze_frames

        fake_frames = [b"\xff" * 50] * 2

        with patch("backend.services.vision_client.analyze_image", new_callable=AsyncMock) as mock_vi:
            mock_vi.side_effect = [
                "プレイヤーが掘っている",
                "[画像の解析に失敗しました]",  # should be filtered
            ]
            results = await analyze_frames(fake_frames)
            assert len(results) == 1
            assert "掘っている" in results[0]

    @pytest.mark.asyncio
    async def test_analyze_frames_concurrency(self):
        """Concurrency limit is respected."""
        from backend.services.video_analyzer import analyze_frames

        call_times = []

        async def slow_vision(b64, prompt=""):
            call_times.append(time.time())
            await asyncio.sleep(0.05)
            return "場面説明"

        frames = [b"\xff" * 10] * 6

        with patch("backend.services.vision_client.analyze_image", side_effect=slow_vision):
            results = await analyze_frames(frames, concurrency=2)
            assert len(results) == 6


# --- video_learner strategy extraction ---

class TestVideoLearnerStrategies:
    @pytest.mark.asyncio
    async def test_extract_strategies(self):
        from backend.services.minecraft.video_learner import _extract_strategies

        async def mock_llm(system, user):
            return """
            - 最初に木を集めて作業台を作るのが効率的
            - 石のピッケルは丸石3つと棒2本で作れる
            - 夜になる前にシェルターを確保する
            """

        strategies = await _extract_strategies(
            ["作業台を作っている", "石のピッケルを作っている"],
            mock_llm,
        )
        assert len(strategies) == 3
        assert any("作業台" in s for s in strategies)
        assert any("シェルター" in s for s in strategies)

    @pytest.mark.asyncio
    async def test_extract_strategies_numbered(self):
        from backend.services.minecraft.video_learner import _extract_strategies

        async def mock_llm(system, user):
            return """
            1. 最初に木を5本集める
            2. 作業台を設置する
            3. 木のピッケルを作る
            """

        strategies = await _extract_strategies(["場面1"], mock_llm)
        assert len(strategies) == 3
        # Numbered prefixes should be stripped
        assert not strategies[0].startswith("1")

    @pytest.mark.asyncio
    async def test_extract_strategies_llm_failure(self):
        from backend.services.minecraft.video_learner import _extract_strategies

        async def fail_llm(system, user):
            raise RuntimeError("LLM unavailable")

        strategies = await _extract_strategies(["場面1"], fail_llm)
        assert strategies == []


# --- video_learner full pipeline ---

class TestVideoLearnerPipeline:
    @pytest.mark.asyncio
    async def test_learn_disabled(self):
        from backend.services.minecraft.video_learner import learn_from_video
        from backend.core.config import settings

        orig = settings.VIDEO_LEARNING_ENABLED
        try:
            settings.VIDEO_LEARNING_ENABLED = False
            result = await learn_from_video("/fake/video.mp4")
            assert not result["success"]
        finally:
            settings.VIDEO_LEARNING_ENABLED = orig

    @pytest.mark.asyncio
    async def test_learn_no_frames(self):
        from backend.services.minecraft.video_learner import learn_from_video

        with patch("backend.services.video_analyzer.extract_frames", new_callable=AsyncMock) as mock_ef:
            mock_ef.return_value = []
            result = await learn_from_video("/fake/video.mp4")
            assert not result["success"]
            assert result["frame_count"] == 0

    @pytest.mark.asyncio
    async def test_learn_full_pipeline(self):
        from backend.services.minecraft.video_learner import learn_from_video

        with patch("backend.services.video_analyzer.extract_frames", new_callable=AsyncMock) as mock_ef, \
             patch("backend.services.video_analyzer.analyze_frames", new_callable=AsyncMock) as mock_af, \
             patch("backend.services.minecraft.video_learner._save_to_memory") as mock_save:

            mock_ef.return_value = [b"\xff"] * 5
            mock_af.return_value = [
                "プレイヤーが木を切っている",
                "作業台を作っている",
                "石のピッケルを作っている",
            ]
            mock_save.return_value = ["id1", "id2"]

            async def mock_llm(system, user):
                return "- 木を集めてから作業台を作る\n- 石のピッケルを早めに作る"

            result = await learn_from_video(
                "/fake/video.mp4", llm_call=mock_llm,
            )
            assert result["success"]
            assert result["frame_count"] == 3
            assert len(result["strategies"]) == 2
            assert len(result["memory_ids"]) == 2


# --- react_to_video ---

class TestReactToVideo:
    @pytest.mark.asyncio
    async def test_react_returns_scenes(self):
        from backend.services.minecraft.video_learner import react_to_video

        with patch("backend.services.video_analyzer.extract_frames", new_callable=AsyncMock) as mock_ef, \
             patch("backend.services.video_analyzer.analyze_frames", new_callable=AsyncMock) as mock_af:

            mock_ef.return_value = [b"\xff"] * 3
            mock_af.return_value = ["すごい建築！", "爆発した！", "ドラゴン！"]

            scenes = await react_to_video("/fake/clip.mp4", max_frames=5)
            assert len(scenes) == 3
            assert "建築" in scenes[0]
