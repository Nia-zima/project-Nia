"""Tests for Sleep Cycle diary generation and tweet proposal."""
from __future__ import annotations

import json
import os
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.db import get_conn, init_schema


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _setup_db():
    init_schema()
    conn = get_conn()
    try:
        conn.execute("DELETE FROM daily_reflections")
        conn.execute("DELETE FROM telemetry_kv")
    finally:
        conn.close()
    yield


# ── generate_diary ────────────────────────────────────────────────


class TestGenerateDiary:
    @pytest.mark.asyncio
    async def test_returns_text(self):
        """LLM returns valid diary text."""
        with patch(
            "backend.scripts.sleep_cycle.layers.call_llm",
            new_callable=AsyncMock,
            return_value="今日はOriginといろんな話をした。なんだか嬉しかったな。",
        ):
            from backend.scripts.sleep_cycle.layers import generate_diary

            result = await generate_diary(
                identity="AI VTuber ニア",
                memory_block="- Origin: おはよう → Nia: おはよう！",
                mood="happy",
                impressions=["朝の挨拶が嬉しかった"],
                surprise=None,
            )
        assert result is not None
        assert len(result) >= 30

    @pytest.mark.asyncio
    async def test_uses_mood_and_impressions_in_prompt(self):
        """Prompt includes mood and impressions."""
        mock_llm = AsyncMock(return_value="今日は穏やかな一日だった。驚いたのは新しい話題。")
        with patch("backend.scripts.sleep_cycle.layers.call_llm", mock_llm):
            from backend.scripts.sleep_cycle.layers import generate_diary

            await generate_diary(
                identity="AI VTuber ニア",
                memory_block="- conversation",
                mood="calm",
                impressions=["新しい話題が面白かった"],
                surprise="予想外の質問",
            )
        prompt = mock_llm.call_args[0][0][0]["content"]
        assert "calm" in prompt
        assert "新しい話題が面白かった" in prompt
        assert "予想外の質問" in prompt

    @pytest.mark.asyncio
    async def test_returns_none_on_short_response(self):
        """Too-short LLM response returns None."""
        with patch(
            "backend.scripts.sleep_cycle.layers.call_llm",
            new_callable=AsyncMock,
            return_value="短い",
        ):
            from backend.scripts.sleep_cycle.layers import generate_diary

            result = await generate_diary(
                identity="ニア",
                memory_block="- event",
                mood="neutral",
                impressions=[],
                surprise=None,
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_llm_failure(self):
        """LLM exception returns None gracefully."""
        with patch(
            "backend.scripts.sleep_cycle.layers.call_llm",
            new_callable=AsyncMock,
            side_effect=RuntimeError("LLM down"),
        ):
            from backend.scripts.sleep_cycle.layers import generate_diary

            result = await generate_diary(
                identity="ニア",
                memory_block="- event",
                mood="neutral",
                impressions=[],
                surprise=None,
            )
        assert result is None


# ── _save_diary ───────────────────────────────────────────────────


class TestSaveDiary:
    def test_saves_to_daily_reflections(self):
        """Diary entry saved with phase='diary'."""
        from backend.scripts.sleep_cycle.orchestrator import _save_diary

        _save_diary(
            "今日は楽しかった。Originと話せてよかった。",
            "happy",
            ["楽しい会話"],
            "2026-02-23",
        )
        conn = get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM daily_reflections WHERE phase = 'diary'"
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row["reflection_date"] == "2026-02-23"
        assert row["session_index"] == 0
        content = json.loads(row["content_json"])
        assert "今日は楽しかった" in content["text"]
        assert content["mood"] == "happy"
        assert "楽しい会話" in content["topics"]

    def test_no_duplicate_per_day(self):
        """INSERT OR REPLACE prevents duplicate diary per day."""
        from backend.scripts.sleep_cycle.orchestrator import _save_diary

        _save_diary("日記1", "happy", [], "2026-02-23")
        _save_diary("日記2", "calm", [], "2026-02-23")

        conn = get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM daily_reflections WHERE phase = 'diary' AND reflection_date = '2026-02-23'"
            ).fetchall()
        finally:
            conn.close()
        assert len(rows) == 1
        content = json.loads(rows[0]["content_json"])
        assert "日記2" in content["text"]


# ── Diary tweet proposal ─────────────────────────────────────────


class TestDiaryTweetProposal:
    @pytest.mark.asyncio
    async def test_diary_does_not_trigger_tweet_from_orchestrator(self):
        """Tweet posting is handled by reflection_engine, not orchestrator."""
        diary_text = "今日はOriginといっぱい話した。嬉しかったな。"
        tweet_text = "今日はたくさん話せて嬉しかった"

        mock_twitter = MagicMock()
        mock_twitter.enabled = True
        mock_twitter.generate_tweet = AsyncMock(return_value=tweet_text)

        with patch.multiple(
            "backend.scripts.sleep_cycle.orchestrator",
            generate_diary=AsyncMock(return_value=diary_text),
        ), patch(
            "backend.scripts.sleep_cycle.layers.call_llm",
            new_callable=AsyncMock,
            return_value='{"impressions": [], "mood": "happy", "surprise": null}',
        ), patch(
            "backend.services.twitter_client.twitter_client", mock_twitter,
        ), patch(
            "backend.scripts.sleep_cycle.orchestrator.settings",
        ) as mock_settings, patch(
            "backend.scripts.sleep_cycle.orchestrator.identity_manager",
        ) as mock_identity, patch(
            "backend.scripts.sleep_cycle.orchestrator.dream_store",
        ), patch(
            "backend.scripts.sleep_cycle.orchestrator._extract_semantics_from_episodic",
            new_callable=AsyncMock,
        ), patch(
            "backend.scripts.sleep_cycle.orchestrator._compress_old_episodic",
            new_callable=AsyncMock,
        ):
            mock_settings.DIARY_ENABLED = True
            mock_settings.TWITTER_AUTO_PROPOSE = True
            mock_settings.LAYER_B_MODE = "proposal"
            mock_settings.EPISODIC_SUMMARY_ENABLED = False
            mock_settings.PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
            mock_identity.get_identity.return_value = "AI VTuber ニア"

            # Insert a daily_reflection so the cycle has data
            conn = get_conn()
            try:
                conn.execute(
                    """INSERT INTO daily_reflections
                       (id, thread_id, reflection_date, session_index, phase,
                        content_json, turn_count, token_count, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)""",
                    (
                        uuid.uuid4().hex,
                        "default_thread",
                        time.strftime("%Y-%m-%d"),
                        0,
                        "daily_log",
                        json.dumps({"summary": "テスト", "key_topics": [], "emotional_moments": []}),
                        5,
                        time.time(),
                    ),
                )
            finally:
                conn.close()

            # Mock Layer A, B, and other phases
            with patch(
                "backend.scripts.sleep_cycle.orchestrator.layer_a_impression_record",
                new_callable=AsyncMock,
                return_value={"impressions": ["test"], "mood": "happy", "surprise": None},
            ), patch(
                "backend.scripts.sleep_cycle.orchestrator.layer_b_guardian_proposal",
                new_callable=AsyncMock,
                return_value=(False, "", 0, 0),
            ), patch(
                "backend.scripts.sleep_cycle.orchestrator._build_dream_text",
                return_value="",
            ):
                from backend.scripts.sleep_cycle.orchestrator import integrated_sleep_cycle
                await integrated_sleep_cycle()

        # Orchestrator no longer posts tweets — that's reflection_engine's job
        mock_twitter.generate_tweet.assert_not_called()


# ── DIARY_ENABLED toggle ─────────────────────────────────────────


class TestDiaryDisabled:
    @pytest.mark.asyncio
    async def test_diary_skipped_when_disabled(self):
        """generate_diary is not called when DIARY_ENABLED=False."""
        mock_generate = AsyncMock(return_value="should not be called")

        with patch.multiple(
            "backend.scripts.sleep_cycle.orchestrator",
            generate_diary=mock_generate,
        ), patch(
            "backend.scripts.sleep_cycle.layers.call_llm",
            new_callable=AsyncMock,
            return_value='{"impressions": [], "mood": "neutral", "surprise": null}',
        ), patch(
            "backend.scripts.sleep_cycle.orchestrator.settings",
        ) as mock_settings, patch(
            "backend.scripts.sleep_cycle.orchestrator.identity_manager",
        ) as mock_identity, patch(
            "backend.scripts.sleep_cycle.orchestrator.dream_store",
        ), patch(
            "backend.scripts.sleep_cycle.orchestrator._extract_semantics_from_episodic",
            new_callable=AsyncMock,
        ), patch(
            "backend.scripts.sleep_cycle.orchestrator._compress_old_episodic",
            new_callable=AsyncMock,
        ):
            mock_settings.DIARY_ENABLED = False
            mock_settings.TWITTER_AUTO_PROPOSE = False
            mock_settings.LAYER_B_MODE = "proposal"
            mock_settings.EPISODIC_SUMMARY_ENABLED = False
            mock_identity.get_identity.return_value = "ニア"

            conn = get_conn()
            try:
                conn.execute(
                    """INSERT INTO daily_reflections
                       (id, thread_id, reflection_date, session_index, phase,
                        content_json, turn_count, token_count, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)""",
                    (
                        uuid.uuid4().hex,
                        "default_thread",
                        time.strftime("%Y-%m-%d"),
                        0,
                        "daily_log",
                        json.dumps({"summary": "test", "key_topics": [], "emotional_moments": []}),
                        5,
                        time.time(),
                    ),
                )
            finally:
                conn.close()

            with patch(
                "backend.scripts.sleep_cycle.orchestrator.layer_a_impression_record",
                new_callable=AsyncMock,
                return_value={"impressions": [], "mood": "neutral", "surprise": None},
            ), patch(
                "backend.scripts.sleep_cycle.orchestrator.layer_b_guardian_proposal",
                new_callable=AsyncMock,
                return_value=(False, "", 0, 0),
            ), patch(
                "backend.scripts.sleep_cycle.orchestrator._build_dream_text",
                return_value="",
            ):
                from backend.scripts.sleep_cycle.orchestrator import integrated_sleep_cycle
                await integrated_sleep_cycle()

        mock_generate.assert_not_called()


# ── GET /diary/recent endpoint ────────────────────────────────────


class TestDiaryEndpoint:
    def test_get_recent_diaries(self):
        """GET /diary/recent returns diary entries."""
        # Insert diary entries
        conn = get_conn()
        try:
            for i, date in enumerate(["2026-02-21", "2026-02-22", "2026-02-23"]):
                conn.execute(
                    """INSERT INTO daily_reflections
                       (id, thread_id, reflection_date, session_index, phase,
                        content_json, turn_count, token_count, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)""",
                    (
                        uuid.uuid4().hex,
                        "default_thread",
                        date,
                        0,
                        "diary",
                        json.dumps({"text": f"日記{i+1}", "mood": "happy", "topics": []}),
                        0,
                        time.time() + i,
                    ),
                )
        finally:
            conn.close()

        from fastapi.testclient import TestClient
        from backend.controllers.api.actions_router import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        resp = client.get("/diary/recent?limit=2")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["date"] == "2026-02-23"
        assert data[0]["content"]["text"] == "日記3"
        assert data[1]["date"] == "2026-02-22"

    def test_get_recent_diaries_empty(self):
        """GET /diary/recent returns empty list when no diaries."""
        from fastapi.testclient import TestClient
        from backend.controllers.api.actions_router import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        resp = client.get("/diary/recent")
        assert resp.status_code == 200
        assert resp.json() == []
