"""Tests for Reflection Engine (Phase R.2)."""
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock

import pytest

from backend.core.db import get_conn, init_schema


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _setup_db():
    init_schema()
    conn = get_conn()
    try:
        conn.execute("DELETE FROM memory_index")  # FK → memory_events
        conn.execute("DELETE FROM memory_events")
        conn.execute("DELETE FROM semantic_memories")
        conn.execute("DELETE FROM daily_reflections")
        conn.execute("DELETE FROM telemetry_kv")
        conn.execute("DELETE FROM x_post_proposals")
    finally:
        conn.close()
    yield


# ── Helpers ───────────────────────────────────────────────────────


def _insert_event(thread_id: str, user_text: str, ai_response: str, *, created_at: float | None = None):
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO memory_events
               (event_id, thread_id, event_type, payload_json, created_at, schema_version)
               VALUES (?, ?, 'conversation_turn', ?, ?, 1)""",
            (
                uuid.uuid4().hex,
                thread_id,
                json.dumps({"user_text": user_text, "ai_response": ai_response}),
                created_at or time.time(),
            ),
        )
    finally:
        conn.close()


DAILY_LOG_JSON = json.dumps({
    "summary": "Memory Retrieval の設計を進めた。Query-Aware Retrieval のアーキテクチャを議論。",
    "key_topics": ["Memory Retrieval", "Query-Aware Retrieval"],
    "emotional_moments": ["設計が決まった時にOriginが満足していた"],
    "unresolved": ["Phase M.2 の Pinned Reorder"],
}, ensure_ascii=False)

INSIGHTS_JSON = json.dumps([
    {
        "content": "OriginはPythonとFastAPIでバックエンド開発をしている",
        "category": "origin_fact",
        "confidence": 0.9,
        "reasoning": "会話中に明言された",
    },
    {
        "content": "Originは設計を先に固めてから実装する方針を好む",
        "category": "origin_preference",
        "confidence": 0.8,
        "reasoning": "実装前にドキュメントを作成する行動パターン",
    },
], ensure_ascii=False)


# ── Tests ─────────────────────────────────────────────────────────


class TestFullPipeline:
    @pytest.mark.asyncio
    async def test_full_pipeline(self, monkeypatch):
        """3 events → daily_log + distillation saved + semantic_memories created."""
        _insert_event("t1", "Memory Retrieval を改善したい", "設計から始めましょう")
        _insert_event("t1", "Query-Aware にしよう", "それがいいですね")
        _insert_event("t1", "埋め込みモデルも統一しよう", "了解です")

        call_count = 0

        async def mock_llm(messages, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return DAILY_LOG_JSON
            return INSIGHTS_JSON

        monkeypatch.setattr("backend.services.reflection_engine.call_llm", mock_llm)

        from backend.services.reflection_engine import run_reflection
        result = await run_reflection("t1")

        assert result["success"] is True
        assert result["daily_log_saved"] is True
        assert result["distillation_saved"] is True
        assert result["insights_count"] == 2

        # Verify daily_reflections
        conn = get_conn()
        try:
            rows = conn.execute("SELECT * FROM daily_reflections WHERE thread_id='t1'").fetchall()
            assert len(rows) == 2
            phases = {r["phase"] for r in rows}
            assert phases == {"daily_log", "distillation"}
        finally:
            conn.close()

        # Verify semantic_memories
        conn = get_conn()
        try:
            rows = conn.execute("SELECT * FROM semantic_memories WHERE thread_id='t1'").fetchall()
            assert len(rows) == 2
            for r in rows:
                assert r["status"] == "inferred"
                assert "reflection:" in r["note"]
        finally:
            conn.close()


class TestNoEvents:
    @pytest.mark.asyncio
    async def test_no_events_returns_success(self, monkeypatch):
        """No events → success=True, no DB changes, no LLM calls."""
        call_count = 0

        async def mock_llm(messages, **kwargs):
            nonlocal call_count
            call_count += 1
            return "should not be called"

        monkeypatch.setattr("backend.services.reflection_engine.call_llm", mock_llm)

        from backend.services.reflection_engine import run_reflection
        result = await run_reflection("t1")

        assert result["success"] is True
        assert call_count == 0

        conn = get_conn()
        try:
            rows = conn.execute("SELECT * FROM daily_reflections").fetchall()
            assert len(rows) == 0
        finally:
            conn.close()


class TestPhase1Failure:
    @pytest.mark.asyncio
    async def test_phase1_failure_skips_phase2(self, monkeypatch):
        """call_llm returns None → no daily_log saved, Phase 2 skipped."""
        _insert_event("t1", "テスト", "テスト回答")

        async def mock_llm(messages, **kwargs):
            return None

        monkeypatch.setattr("backend.services.reflection_engine.call_llm", mock_llm)

        from backend.services.reflection_engine import run_reflection
        result = await run_reflection("t1")

        assert result["success"] is False
        assert result["daily_log_saved"] is False
        assert result["distillation_saved"] is False
        assert len(result["errors"]) > 0


class TestPhase2FailurePreservesPhase1:
    @pytest.mark.asyncio
    async def test_phase2_failure_preserves_phase1(self, monkeypatch):
        """Phase 1 succeeds, Phase 2 fails → daily_log still saved."""
        _insert_event("t1", "テスト会話", "OK")

        call_count = 0

        async def mock_llm(messages, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return DAILY_LOG_JSON
            raise RuntimeError("LLM down for distillation")

        monkeypatch.setattr("backend.services.reflection_engine.call_llm", mock_llm)

        from backend.services.reflection_engine import run_reflection
        result = await run_reflection("t1")

        assert result["success"] is True  # partial success
        assert result["daily_log_saved"] is True
        assert result["distillation_saved"] is False

        conn = get_conn()
        try:
            rows = conn.execute("SELECT * FROM daily_reflections WHERE thread_id='t1'").fetchall()
            assert len(rows) == 1
            assert rows[0]["phase"] == "daily_log"
        finally:
            conn.close()


class TestSessionIndex:
    @pytest.mark.asyncio
    async def test_session_index_increments(self, monkeypatch):
        """Two reflections on same day → session_index 0, then 1."""
        _insert_event("t1", "最初の会話", "最初の回答", created_at=time.time() - 100)

        call_count = 0

        async def mock_llm(messages, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count % 2 == 1:
                return DAILY_LOG_JSON
            return "[]"

        monkeypatch.setattr("backend.services.reflection_engine.call_llm", mock_llm)

        from backend.services.reflection_engine import run_reflection

        # First reflection
        result1 = await run_reflection("t1")
        assert result1["daily_log_saved"] is True

        # Insert more events after first reflection
        _insert_event("t1", "二回目の会話", "二回目の回答")

        # Second reflection
        result2 = await run_reflection("t1")
        assert result2["daily_log_saved"] is True

        conn = get_conn()
        try:
            rows = conn.execute(
                "SELECT session_index FROM daily_reflections WHERE phase='daily_log' ORDER BY session_index"
            ).fetchall()
            assert len(rows) == 2
            assert rows[0]["session_index"] == 0
            assert rows[1]["session_index"] == 1
        finally:
            conn.close()


class TestEventBoundary:
    @pytest.mark.asyncio
    async def test_respects_event_boundary(self, monkeypatch):
        """Only events after the last reflection are processed."""
        old_time = time.time() - 3600
        new_time = time.time()

        _insert_event("t1", "古い会話", "古い回答", created_at=old_time)

        # Simulate a previous reflection
        conn = get_conn()
        try:
            conn.execute(
                """INSERT INTO daily_reflections
                   (id, thread_id, reflection_date, session_index, phase,
                    content_json, turn_count, created_at)
                   VALUES (?, 't1', '2026-02-19', 0, 'daily_log', '{}', 1, ?)""",
                (uuid.uuid4().hex, old_time + 1),
            )
        finally:
            conn.close()

        # Insert a new event after previous reflection
        _insert_event("t1", "新しい会話", "新しい回答", created_at=new_time)

        captured_events = []

        async def mock_llm(messages, **kwargs):
            # Capture the prompt to verify only new events are included
            prompt_text = messages[0]["content"]
            captured_events.append(prompt_text)
            return DAILY_LOG_JSON

        monkeypatch.setattr("backend.services.reflection_engine.call_llm", mock_llm)

        from backend.services.reflection_engine import run_reflection
        result = await run_reflection("t1")

        assert result["daily_log_saved"] is True
        assert len(captured_events) >= 1
        # Old event should NOT be in the prompt
        assert "古い会話" not in captured_events[0]
        # New event should be in the prompt
        assert "新しい会話" in captured_events[0]


class TestDeduplication:
    @pytest.mark.asyncio
    async def test_deduplication(self, monkeypatch):
        """Near-duplicate claims are deduplicated."""
        _insert_event("t1", "テスト", "回答")

        duplicate_insights = json.dumps([
            {"content": "OriginはPythonが好きだ", "category": "origin_fact", "confidence": 0.8, "reasoning": ""},
            {"content": "OriginはPythonが好き", "category": "origin_fact", "confidence": 0.7, "reasoning": ""},
            {"content": "Originは設計を先に固める", "category": "origin_preference", "confidence": 0.6, "reasoning": ""},
        ], ensure_ascii=False)

        call_count = 0

        async def mock_llm(messages, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return DAILY_LOG_JSON
            return duplicate_insights

        monkeypatch.setattr("backend.services.reflection_engine.call_llm", mock_llm)

        from backend.services.reflection_engine import run_reflection
        result = await run_reflection("t1")

        assert result["success"] is True
        # Two near-duplicates ("Pythonが好きだ" vs "Pythonが好き") should merge
        assert result["insights_count"] == 2  # 3 → 2 after dedup


class TestSeedRetention:
    @pytest.mark.asyncio
    async def test_seed_retention_formula(self, monkeypatch):
        """confidence=0.8 → seed_retention = 0.5 + 0.8*0.4 = 0.82."""
        _insert_event("t1", "テスト", "回答")

        insights_08 = json.dumps([
            {"content": "Originの好きな食べ物はカレー", "category": "origin_fact", "confidence": 0.8, "reasoning": ""},
        ], ensure_ascii=False)

        call_count = 0

        async def mock_llm(messages, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return DAILY_LOG_JSON
            return insights_08

        monkeypatch.setattr("backend.services.reflection_engine.call_llm", mock_llm)

        from backend.services.reflection_engine import run_reflection
        result = await run_reflection("t1")

        assert result["insights_count"] == 1

        conn = get_conn()
        try:
            row = conn.execute("SELECT seed_retention, confidence FROM semantic_memories WHERE thread_id='t1'").fetchone()
            assert row is not None
            assert abs(row["confidence"] - 0.8) < 0.01
            assert abs(row["seed_retention"] - 0.82) < 0.01
        finally:
            conn.close()


# ── R.4: Cross-day Distillation Tests ────────────────────────────


def _insert_daily_reflection(
    thread_id: str,
    reflection_date: str,
    session_index: int,
    content: dict,
    turn_count: int = 5,
    *,
    created_at: float | None = None,
):
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO daily_reflections
               (id, thread_id, reflection_date, session_index, phase,
                content_json, turn_count, token_count, created_at)
               VALUES (?, ?, ?, ?, 'daily_log', ?, ?, 0, ?)""",
            (
                uuid.uuid4().hex,
                thread_id,
                reflection_date,
                session_index,
                json.dumps(content, ensure_ascii=False),
                turn_count,
                created_at if created_at is not None else time.time() - 86400 * 7,
            ),
        )
    finally:
        conn.close()


CROSS_DAY_INSIGHTS_JSON = json.dumps([
    {
        "content": "Originは常に設計を先に固めてから実装に入る",
        "category": "user_trait",
        "confidence": 0.55,
        "reasoning": "2/15, 2/16, 2/17 すべてで設計フェーズが先行",
    },
    {
        "content": "技術的な難題に直面すると二人とも集中力が上がる",
        "category": "relationship_pattern",
        "confidence": 0.5,
        "reasoning": "2/16, 2/17 で難題への取り組みが見られた",
    },
], ensure_ascii=False)


class TestCrossDaySkipsWhenInsufficient:
    @pytest.mark.asyncio
    async def test_skips_when_less_than_3_days(self, monkeypatch):
        """1 prior day + today's log = 2 days → cross-day skipped."""
        _insert_event("t1", "テスト", "回答")

        # Insert only 1 prior day (Phase 1 will save today → total 2 dates)
        _insert_daily_reflection("t1", "2026-02-18", 0, {
            "summary": "キャッシュ層の設計", "key_topics": ["Cache"], "emotional_moments": [], "unresolved": [],
        })

        call_count = 0

        async def mock_llm(messages, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return DAILY_LOG_JSON
            if call_count == 2:
                return INSIGHTS_JSON
            # Phase 3 should NOT be called
            raise AssertionError("Phase 3 LLM should not be called with < 3 days")

        monkeypatch.setattr("backend.services.reflection_engine.call_llm", mock_llm)

        from backend.services.reflection_engine import run_reflection
        result = await run_reflection("t1")

        assert result["success"] is True
        assert result.get("cross_day_count", 0) == 0
        assert call_count == 2  # Only Phase 1 + Phase 2


class TestCrossDayExtractsPatterns:
    @pytest.mark.asyncio
    async def test_extracts_patterns_with_3_days(self, monkeypatch):
        """3+ days of data → patterns extracted and saved to semantic_memories."""
        _insert_event("t1", "テスト", "回答")

        # Insert 3 days of daily_reflections (within 7-day lookback window)
        from datetime import date, timedelta
        _base = date.today()
        _insert_daily_reflection("t1", (_base - timedelta(days=3)).isoformat(), 0, {
            "summary": "設計フェーズ開始", "key_topics": ["Architecture"], "emotional_moments": [], "unresolved": [],
        })
        _insert_daily_reflection("t1", (_base - timedelta(days=2)).isoformat(), 0, {
            "summary": "設計の継続", "key_topics": ["Design"], "emotional_moments": [], "unresolved": [],
        })
        _insert_daily_reflection("t1", (_base - timedelta(days=1)).isoformat(), 0, {
            "summary": "実装フェーズへ", "key_topics": ["Implementation"], "emotional_moments": [], "unresolved": [],
        })

        call_count = 0

        async def mock_llm(messages, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return DAILY_LOG_JSON
            if call_count == 2:
                return INSIGHTS_JSON
            # Phase 3: cross-day
            return CROSS_DAY_INSIGHTS_JSON

        monkeypatch.setattr("backend.services.reflection_engine.call_llm", mock_llm)

        from backend.services.reflection_engine import run_reflection
        result = await run_reflection("t1")

        assert result["success"] is True
        assert result["cross_day_count"] == 2
        assert call_count == 3  # Phase 1 + 2 + 3

        # Verify semantic_memories have cross-day insights
        conn = get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM semantic_memories WHERE thread_id='t1' AND state_tag='insight'"
            ).fetchall()
            assert len(rows) == 2
            for r in rows:
                assert r["status"] == "inferred"
                assert "cross_day:" in r["note"]
        finally:
            conn.close()


class TestCrossDayConfidenceCap:
    @pytest.mark.asyncio
    async def test_4_days_cap_at_06(self, monkeypatch):
        """3 prior days + today = 4 days → confidence capped at 0.6."""
        _insert_event("t1", "テスト", "回答")

        for i in range(1, 4):  # 3 prior days (+ today from Phase 1 = 4 total)
            day_str = (date.today() - timedelta(days=i)).isoformat()
            _insert_daily_reflection("t1", day_str, 0, {
                "summary": f"Day {i} summary",
                "key_topics": [f"topic{i}"],
                "emotional_moments": [],
                "unresolved": [],
            })

        # LLM returns confidence 0.9, should be capped to 0.6
        high_conf_insights = json.dumps([{
            "content": "Originは毎日コードレビューをする",
            "category": "user_trait",
            "confidence": 0.9,
            "reasoning": "4日間すべてで確認",
        }], ensure_ascii=False)

        call_count = 0

        async def mock_llm(messages, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return DAILY_LOG_JSON
            if call_count == 2:
                return "[]"
            return high_conf_insights

        monkeypatch.setattr("backend.services.reflection_engine.call_llm", mock_llm)

        from backend.services.reflection_engine import run_reflection
        result = await run_reflection("t1")

        assert result["cross_day_count"] == 1

        conn = get_conn()
        try:
            row = conn.execute(
                "SELECT confidence FROM semantic_memories WHERE thread_id='t1' AND state_tag='insight'"
            ).fetchone()
            assert row is not None
            assert row["confidence"] <= 0.6
        finally:
            conn.close()

    @pytest.mark.asyncio
    async def test_7_days_cap_at_09(self, monkeypatch):
        """7 days → confidence capped at 0.9."""
        _insert_event("t1", "テスト", "回答")

        for i in range(1, 8):  # 7 days
            day_str = (date.today() - timedelta(days=i)).isoformat()
            _insert_daily_reflection("t1", day_str, 0, {
                "summary": f"Day {i} summary",
                "key_topics": [f"topic{i}"],
                "emotional_moments": [],
                "unresolved": [],
            })

        high_conf_insights = json.dumps([{
            "content": "Originは設計を先に固める",
            "category": "user_trait",
            "confidence": 0.95,
            "reasoning": "7日間で一貫して確認",
        }], ensure_ascii=False)

        call_count = 0

        async def mock_llm(messages, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return DAILY_LOG_JSON
            if call_count == 2:
                return "[]"
            return high_conf_insights

        monkeypatch.setattr("backend.services.reflection_engine.call_llm", mock_llm)

        from backend.services.reflection_engine import run_reflection
        result = await run_reflection("t1")

        assert result["cross_day_count"] == 1

        conn = get_conn()
        try:
            row = conn.execute(
                "SELECT confidence FROM semantic_memories WHERE thread_id='t1' AND state_tag='insight'"
            ).fetchone()
            assert row is not None
            assert row["confidence"] <= 0.9
        finally:
            conn.close()


class TestCrossDayStateTag:
    @pytest.mark.asyncio
    async def test_state_tag_is_insight(self, monkeypatch):
        """Cross-day insights are saved with state_tag='insight'."""
        _insert_event("t1", "テスト", "回答")

        for i in range(1, 4):  # 3 prior days
            day_str = (date.today() - timedelta(days=i)).isoformat()
            _insert_daily_reflection("t1", day_str, 0, {
                "summary": f"Day {i} summary",
                "key_topics": [f"topic{i}"],
                "emotional_moments": [],
                "unresolved": [],
            })

        call_count = 0

        async def mock_llm(messages, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return DAILY_LOG_JSON
            if call_count == 2:
                return INSIGHTS_JSON  # Phase 2 with origin_fact etc.
            return CROSS_DAY_INSIGHTS_JSON

        monkeypatch.setattr("backend.services.reflection_engine.call_llm", mock_llm)

        from backend.services.reflection_engine import run_reflection
        result = await run_reflection("t1")

        conn = get_conn()
        try:
            # Phase 2 insights have state_tag != "insight"
            phase2_rows = conn.execute(
                "SELECT state_tag FROM semantic_memories WHERE thread_id='t1' AND state_tag != 'insight'"
            ).fetchall()
            assert len(phase2_rows) > 0  # Phase 2 produced some

            # Phase 3 insights have state_tag = "insight"
            phase3_rows = conn.execute(
                "SELECT state_tag, note FROM semantic_memories WHERE thread_id='t1' AND state_tag = 'insight'"
            ).fetchall()
            assert len(phase3_rows) == 2
            for r in phase3_rows:
                assert r["state_tag"] == "insight"
                assert "cross_day:" in r["note"]
        finally:
            conn.close()


class TestTweetProposalPhase:
    @pytest.mark.asyncio
    async def test_phase_t_creates_proposal_instead_of_posting(self, monkeypatch):
        _insert_event("t1", "Memory Retrieval を改善したい", "設計から始めましょう")

        call_count = 0

        async def mock_llm(messages, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return DAILY_LOG_JSON
            return "[]"

        proposal_calls = []

        async def mock_propose(*, thread_id, daily_log, source_ref):
            proposal_calls.append(
                {
                    "thread_id": thread_id,
                    "daily_log": daily_log,
                    "source_ref": source_ref,
                }
            )
            return {
                "proposal_id": "prop-1",
                "tweet_text": "今日は設計の話を進めた",
            }

        post_calls = []

        async def mock_post_tweet(*args, **kwargs):
            post_calls.append((args, kwargs))
            raise AssertionError("reflection should not post directly")

        monkeypatch.setattr("backend.services.reflection_engine.call_llm", mock_llm)
        monkeypatch.setattr(
            "backend.services.x_post_service.x_post_service.propose_reflection_daily_log",
            mock_propose,
        )
        monkeypatch.setattr(
            "backend.services.twitter_client.twitter_client.post_tweet",
            mock_post_tweet,
        )
        monkeypatch.setattr("backend.services.reflection_engine.settings.TWITTER_AUTO_PROPOSE", True)

        from backend.services.reflection_engine import run_reflection

        result = await run_reflection("t1")

        assert result["success"] is True
        assert result["daily_log_saved"] is True
        assert result["tweet_proposed"] is True
        assert result["tweet_proposal_id"] == "prop-1"
        assert len(proposal_calls) == 1
        assert proposal_calls[0]["thread_id"] == "t1"
        assert post_calls == []

    @pytest.mark.asyncio
    async def test_reflection_proposal_skips_nero_meeting_thread(self, monkeypatch):
        from backend.services.x_post_service import x_post_service

        twitter_mock = AsyncMock(return_value="これは提案されない")
        monkeypatch.setattr(
            "backend.services.twitter_client.twitter_client.generate_tweet",
            twitter_mock,
        )
        monkeypatch.setattr("backend.services.twitter_client.twitter_client.enabled", True)

        proposal = await x_post_service.propose_reflection_daily_log(
            thread_id="nero_meeting_20260307_123000",
            daily_log={"summary": "内部会話", "key_topics": ["internal"]},
            source_ref="daily-log-1",
        )

        assert proposal is None
        twitter_mock.assert_not_called()

        conn = get_conn()
        try:
            row = conn.execute("SELECT COUNT(*) FROM x_post_proposals").fetchone()
            assert row[0] == 0
        finally:
            conn.close()
