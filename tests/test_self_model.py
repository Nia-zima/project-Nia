"""Tests for Self-Model Generation (Phase N.3)."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from backend.core.db import init_schema
from backend.services.memory.self_model import (
    SelfModel,
    _format_reflections,
    _format_insights,
    _format_awareness_stats,
    _format_prev_model,
    _is_identity_stale,
    _mark_identity_updated,
    _parse_self_model,
    _propose_identity_recent_learnings,
    _save_self_model,
    generate_self_model,
)
from conftest import make_semantic


@pytest.fixture(autouse=True)
def _setup_db():
    init_schema()
    yield


# ── Formatting ──────────────────────────────────────────────


class TestFormatting:
    def test_format_reflections_empty(self):
        result = _format_reflections([])
        assert "ありません" in result

    def test_format_reflections_with_data(self):
        data = [
            {"phase": "daily_log", "content": {"text": "今日は猫の話をした"}},
        ]
        result = _format_reflections(data)
        assert "猫の話" in result

    def test_format_insights_empty(self):
        result = _format_insights([])
        assert "ありません" in result

    def test_format_insights_with_data(self):
        mem = make_semantic(content="ユーザーは夜型の傾向がある")
        result = _format_insights([mem])
        assert "夜型" in result

    def test_format_awareness_stats_empty(self):
        result = _format_awareness_stats({})
        assert "なし" in result

    def test_format_awareness_stats_with_data(self):
        result = _format_awareness_stats({"awareness_average": "0.25"})
        assert "0.25" in result

    def test_format_prev_model_none(self):
        result = _format_prev_model(None)
        assert "初回" in result

    def test_format_prev_model_with_data(self):
        model = SelfModel(
            current_state="安定",
            growth_edges=["感情表現"],
            recent_changes=["冗談に反応"],
            relationship_note="信頼が積み上がっている",
        )
        result = _format_prev_model(model)
        assert "安定" in result
        assert "感情表現" in result


# ── _parse_self_model ───────────────────────────────────────


class TestParseSelfModel:
    def test_valid_json(self):
        output = json.dumps({
            "current_state": "落ち着いている",
            "growth_edges": ["感情表現", "抽象的思考"],
            "recent_changes": ["冗談に反応できた"],
            "relationship_note": "信頼関係が深まっている",
        })
        model = _parse_self_model(output, None)
        assert model.current_state == "落ち着いている"
        assert len(model.growth_edges) == 2
        assert len(model.recent_changes) == 1

    def test_json_in_code_block(self):
        output = '```json\n{"current_state": "テスト", "growth_edges": [], "recent_changes": [], "relationship_note": ""}\n```'
        model = _parse_self_model(output, None)
        assert model.current_state == "テスト"

    def test_invalid_json_falls_back_to_prev(self):
        prev = SelfModel(current_state="前回の状態")
        model = _parse_self_model("not json", prev)
        assert model.current_state == "前回の状態"

    def test_none_output_falls_back_to_prev(self):
        prev = SelfModel(current_state="前回")
        model = _parse_self_model(None, prev)
        assert model.current_state == "前回"

    def test_none_output_no_prev_returns_empty(self):
        model = _parse_self_model(None, None)
        assert model.current_state == ""

    def test_growth_edges_capped_at_3(self):
        output = json.dumps({
            "current_state": "test",
            "growth_edges": ["a", "b", "c", "d", "e"],
            "recent_changes": [],
            "relationship_note": "",
        })
        model = _parse_self_model(output, None)
        assert len(model.growth_edges) == 3


# ── _save_self_model ────────────────────────────────────────


class TestSaveSelfModel:
    def test_saves_to_archive(self, tmp_path):
        model = SelfModel(
            current_state="テスト状態",
            growth_edges=["edge1"],
            timestamp=time.time(),
        )
        with patch("backend.services.memory.self_model.settings") as mock_s:
            mock_s.SELF_MODEL_ARCHIVE_DIR = str(tmp_path)
            _save_self_model(model)

        path = tmp_path / "self_model.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["current_state"] == "テスト状態"

    def test_appends_without_duplicate_date(self, tmp_path):
        model1 = SelfModel(current_state="first", timestamp=time.time())
        model2 = SelfModel(current_state="second", timestamp=time.time())

        with patch("backend.services.memory.self_model.settings") as mock_s:
            mock_s.SELF_MODEL_ARCHIVE_DIR = str(tmp_path)
            _save_self_model(model1)
            _save_self_model(model2)

        path = tmp_path / "self_model.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        # Same date → replaced, not duplicated
        assert len(data) == 1
        assert data[0]["current_state"] == "second"


# ── _propose_identity_recent_learnings ─────────────────────


class TestProposeIdentity:
    def test_saves_proposal_to_db(self):
        """Proposals are saved to DB, not written to identity.md."""
        from backend.core.db import managed_conn

        model = SelfModel(
            current_state="新しい状態",
            growth_edges=["成長1"],
            recent_changes=["変化1"],
            relationship_note="関係メモ",
        )
        _propose_identity_recent_learnings(model)

        with managed_conn() as conn:
            row = conn.execute(
                "SELECT proposal FROM identity_proposals ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        assert row is not None
        assert "新しい状態" in row["proposal"]
        assert "成長1" in row["proposal"]

    def test_empty_model_no_proposal(self):
        """Empty model should not create a proposal."""
        from backend.core.db import managed_conn

        with managed_conn() as conn:
            before = conn.execute("SELECT COUNT(*) FROM identity_proposals").fetchone()[0]

        model = SelfModel()
        _propose_identity_recent_learnings(model)

        with managed_conn() as conn:
            after = conn.execute("SELECT COUNT(*) FROM identity_proposals").fetchone()[0]
        assert after == before


# ── generate_self_model (integration) ──────────────────────


class TestGenerateSelfModel:
    @pytest.mark.asyncio
    async def test_disabled_returns_none(self):
        with patch("backend.services.memory.self_model.settings") as mock_s:
            mock_s.SELF_MODEL_ENABLED = False
            result = await generate_self_model("t1")
        assert result is None

    @pytest.mark.asyncio
    async def test_generates_with_llm(self, tmp_path):
        from backend.core.db import managed_conn

        llm_response = json.dumps({
            "current_state": "生成テスト",
            "growth_edges": ["テスト成長"],
            "recent_changes": [],
            "relationship_note": "テスト関係",
        })

        identity = tmp_path / "identity.md"
        identity.write_text("# Identity\n\n## Recent Learnings\nOld.\n", encoding="utf-8")

        with patch("backend.services.memory.self_model.settings") as mock_s:
            mock_s.SELF_MODEL_ENABLED = True
            mock_s.SELF_MODEL_ARCHIVE_DIR = str(tmp_path)
            mock_s.SELF_MODEL_IDENTITY_PATH = str(identity)
            mock_s.SELF_MODEL_PROMPT_TIMEOUT = 30
            mock_s.SELF_MODEL_INSIGHTS_LIMIT = 10
            mock_s.SELF_MODEL_UPDATE_ON_CHANGE_ONLY = False
            with patch("backend.services.llm_client.call_llm", new_callable=AsyncMock, return_value=llm_response):
                result = await generate_self_model("t1")

        assert result is not None
        assert result.current_state == "生成テスト"
        assert "テスト成長" in result.growth_edges

        # Verify archive saved
        archive = json.loads((tmp_path / "self_model.json").read_text(encoding="utf-8"))
        assert len(archive) == 1

        # Verify identity.md NOT directly modified (approval-only)
        content = identity.read_text(encoding="utf-8")
        assert "Old." in content  # Original content preserved

        # Verify proposal saved to DB instead
        with managed_conn() as conn:
            row = conn.execute(
                "SELECT proposal FROM identity_proposals ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        assert row is not None
        assert "生成テスト" in row["proposal"]

    @pytest.mark.asyncio
    async def test_llm_failure_uses_fallback(self, tmp_path):
        identity = tmp_path / "identity.md"
        identity.write_text("# Identity\n\n## Recent Learnings\n", encoding="utf-8")

        with patch("backend.services.memory.self_model.settings") as mock_s:
            mock_s.SELF_MODEL_ENABLED = True
            mock_s.SELF_MODEL_ARCHIVE_DIR = str(tmp_path)
            mock_s.SELF_MODEL_IDENTITY_PATH = str(identity)
            mock_s.SELF_MODEL_PROMPT_TIMEOUT = 30
            mock_s.SELF_MODEL_INSIGHTS_LIMIT = 10
            mock_s.SELF_MODEL_UPDATE_ON_CHANGE_ONLY = False
            with patch("backend.services.llm_client.call_llm", new_callable=AsyncMock, return_value=None):
                result = await generate_self_model("t1")

        # Should return empty model (no crash)
        assert result is not None
        assert result.current_state == ""


# ── Staleness Tracking ─────────────────────────────────────


class TestStalenessTracking:
    def test_stale_when_never_tracked(self):
        """First run: no telemetry entry → treat as stale."""
        from backend.core.db import managed_conn

        with managed_conn() as conn:
            conn.execute(
                "DELETE FROM telemetry_kv WHERE k = 'self_model_last_identity_update'"
            )
        assert _is_identity_stale(3) is True

    def test_not_stale_after_mark(self):
        """Just updated → not stale."""
        _mark_identity_updated()
        assert _is_identity_stale(3) is False

    def test_stale_after_max_days(self):
        """Old timestamp → stale."""
        from backend.core.db import managed_conn

        four_days_ago = time.time() - 4 * 86400
        with managed_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO telemetry_kv (k, v, updated_at) VALUES (?, ?, ?)",
                ("self_model_last_identity_update", str(four_days_ago), int(four_days_ago)),
            )
        assert _is_identity_stale(3) is True

    def test_not_stale_within_window(self):
        """Recent timestamp within window → not stale."""
        from backend.core.db import managed_conn

        two_days_ago = time.time() - 2 * 86400
        with managed_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO telemetry_kv (k, v, updated_at) VALUES (?, ?, ?)",
                ("self_model_last_identity_update", str(two_days_ago), int(two_days_ago)),
            )
        assert _is_identity_stale(3) is False

    @pytest.mark.asyncio
    async def test_stale_forces_proposal(self, tmp_path):
        """When content unchanged but stale, proposal should still be created."""
        from backend.core.db import managed_conn

        # Set last update to 5 days ago
        five_days_ago = time.time() - 5 * 86400
        with managed_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO telemetry_kv (k, v, updated_at) VALUES (?, ?, ?)",
                ("self_model_last_identity_update", str(five_days_ago), int(five_days_ago)),
            )

        # Create a previous model in archive (same content as LLM will return)
        prev_data = {
            "current_state": "同じ状態",
            "growth_edges": ["同じ成長"],
            "recent_changes": [],
            "relationship_note": "同じ関係",
            "my_words": "同じ言葉",
        }
        archive_path = tmp_path / "self_model.json"
        archive_path.write_text(json.dumps([{
            "date": "2026-03-02",
            **prev_data,
            "generated_at": five_days_ago,
            "turn_id": "sleep_cycle",
        }]), encoding="utf-8")

        identity = tmp_path / "identity.md"
        identity.write_text(
            "# Identity\n\n### ■ 僕の言葉で\n\n古い言葉\n\n## Recent Learnings\n\nOld.\n",
            encoding="utf-8",
        )

        # LLM returns same content → normally skipped, but stale → proposal created
        llm_response = json.dumps(prev_data)

        with patch("backend.services.memory.self_model.settings") as mock_s:
            mock_s.SELF_MODEL_ENABLED = True
            mock_s.SELF_MODEL_ARCHIVE_DIR = str(tmp_path)
            mock_s.SELF_MODEL_IDENTITY_PATH = str(identity)
            mock_s.SELF_MODEL_PROMPT_TIMEOUT = 30
            mock_s.SELF_MODEL_INSIGHTS_LIMIT = 10
            mock_s.SELF_MODEL_UPDATE_ON_CHANGE_ONLY = True
            mock_s.SELF_MODEL_MAX_STALE_DAYS = 3
            with patch("backend.services.llm_client.call_llm", new_callable=AsyncMock, return_value=llm_response):
                result = await generate_self_model("t1")

        # identity.md NOT directly modified
        content = identity.read_text(encoding="utf-8")
        assert "Old." in content

        # But proposals saved to DB
        with managed_conn() as conn:
            rows = conn.execute(
                "SELECT proposal FROM identity_proposals ORDER BY created_at DESC LIMIT 2"
            ).fetchall()
        proposals = [r["proposal"] for r in rows]
        assert any("同じ状態" in p for p in proposals)
        assert any("同じ言葉" in p for p in proposals)

    @pytest.mark.asyncio
    async def test_no_proposal_when_unchanged_and_fresh(self, tmp_path):
        """When content unchanged and recently updated, no proposal created."""
        from backend.core.db import managed_conn

        # Mark as recently updated
        _mark_identity_updated()

        # Count proposals before
        with managed_conn() as conn:
            before = conn.execute("SELECT COUNT(*) FROM identity_proposals").fetchone()[0]

        prev_data = {
            "current_state": "同じ状態",
            "growth_edges": ["同じ成長"],
            "recent_changes": [],
            "relationship_note": "同じ関係",
            "my_words": "同じ言葉",
        }
        archive_path = tmp_path / "self_model.json"
        archive_path.write_text(json.dumps([{
            "date": "2026-03-02",
            **prev_data,
            "generated_at": time.time() - 86400,
            "turn_id": "sleep_cycle",
        }]), encoding="utf-8")

        identity = tmp_path / "identity.md"
        identity.write_text(
            "# Identity\n\n### ■ 僕の言葉で\n\n古い言葉\n\n## Recent Learnings\n\nOld.\n",
            encoding="utf-8",
        )

        llm_response = json.dumps(prev_data)

        with patch("backend.services.memory.self_model.settings") as mock_s:
            mock_s.SELF_MODEL_ENABLED = True
            mock_s.SELF_MODEL_ARCHIVE_DIR = str(tmp_path)
            mock_s.SELF_MODEL_IDENTITY_PATH = str(identity)
            mock_s.SELF_MODEL_PROMPT_TIMEOUT = 30
            mock_s.SELF_MODEL_INSIGHTS_LIMIT = 10
            mock_s.SELF_MODEL_UPDATE_ON_CHANGE_ONLY = True
            mock_s.SELF_MODEL_MAX_STALE_DAYS = 3
            with patch("backend.services.llm_client.call_llm", new_callable=AsyncMock, return_value=llm_response):
                result = await generate_self_model("t1")

        # identity.md NOT modified
        content = identity.read_text(encoding="utf-8")
        assert "Old." in content
        assert "古い言葉" in content

        # No new proposals created
        with managed_conn() as conn:
            after = conn.execute("SELECT COUNT(*) FROM identity_proposals").fetchone()[0]
        assert after == before
