"""Tests for Phase E: failure_memory, context_builder minecraft integration."""
import sqlite3
import time
import uuid
import pytest

from unittest.mock import patch, MagicMock


# --- failure_memory ---

class TestFailureMemory:
    def _setup_db(self, tmp_path):
        """Create an in-memory-like SQLite with semantic_memories table."""
        db_path = tmp_path / "test.sqlite3"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE semantic_memories (
                id TEXT PRIMARY KEY,
                thread_id TEXT,
                content TEXT,
                status TEXT DEFAULT 'inferred',
                confidence REAL DEFAULT 0.5,
                state_tag TEXT,
                supersedes_id TEXT,
                revoked_by_id TEXT,
                revoke_reason TEXT,
                valid_from REAL,
                valid_to REAL,
                staleness_days REAL,
                source_turn_ids TEXT,
                source_event_ids TEXT,
                note TEXT,
                seed_retention REAL,
                vector_sync_pending INTEGER DEFAULT 0,
                created_at REAL,
                updated_at REAL
            )
        """)

        # Insert some failure records
        now = time.time()
        failures = [
            ("鉄のピッケルが必要だった", "game_skill_failure", now - 3600),
            ("作業台が見つからなかった", "game_skill_failure", now - 7200),
            ("木を集めるのに成功した", "game_skill_success", now - 1800),
        ]
        for content, tag, ts in failures:
            conn.execute(
                """INSERT INTO semantic_memories
                   (id, thread_id, content, status, confidence, state_tag,
                    source_turn_ids, source_event_ids, note, seed_retention,
                    vector_sync_pending, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (str(uuid.uuid4()), "minecraft", content, "inferred", 0.5, tag,
                 "", "", "", 0.5, 0, ts, ts),
            )
        conn.commit()
        return conn, db_path

    def test_sql_recent_failures(self, tmp_path):
        conn, db_path = self._setup_db(tmp_path)

        with patch("backend.services.minecraft.failure_memory.get_conn", return_value=conn):
            from backend.services.minecraft.failure_memory import _sql_recent_failures
            results = _sql_recent_failures(limit=5)
            # Should only return failures (state_tag=game_skill_failure), not success
            assert len(results) == 2
            assert all("失敗" in r["content"] or "必要" in r["content"] or "見つからなかった" in r["content"]
                       for r in results)

    def test_search_failures_fallback(self, tmp_path):
        conn, db_path = self._setup_db(tmp_path)

        with patch("backend.services.minecraft.failure_memory.get_conn", return_value=conn):
            from backend.services.minecraft.failure_memory import search_failures
            results = search_failures(query="", limit=5)
            assert len(results) == 2

    def test_format_failures_for_prompt(self):
        from backend.services.minecraft.failure_memory import format_failures_for_prompt
        failures = [
            {"content": "鉄のピッケルが必要だった", "confidence": 0.5, "created_at": time.time()},
            {"content": "作業台が見つからなかった", "confidence": 0.5, "created_at": time.time()},
        ]
        text = format_failures_for_prompt(failures)
        assert "鉄のピッケル" in text
        assert "作業台" in text
        assert text.startswith("- ")

    def test_format_empty(self):
        from backend.services.minecraft.failure_memory import format_failures_for_prompt
        assert format_failures_for_prompt([]) == ""


# --- context_builder minecraft integration ---

class TestContextBuilderMinecraft:
    def test_build_without_minecraft(self):
        """Without include_minecraft, minecraft key should be empty."""
        with patch("backend.services.memory.context_builder.semantic_store") as mock_ss, \
             patch("backend.services.memory.context_builder.working_store") as mock_ws:
            mock_ss.search_active.return_value = []
            mock_ws.list_open.return_value = []

            from backend.services.memory.context_builder import build_memory_context
            result = build_memory_context(thread_id="test")
            assert result.get("minecraft", "") == ""

    def test_build_with_minecraft_flag(self):
        """With include_minecraft=True, minecraft section should attempt to build."""
        with patch("backend.services.memory.context_builder.semantic_store") as mock_ss, \
             patch("backend.services.memory.context_builder.working_store") as mock_ws, \
             patch("backend.services.minecraft.failure_memory.get_conn") as mock_conn:
            mock_ss.search_active.return_value = []
            mock_ws.list_open.return_value = []
            # Mock failure memory to return empty (no DB)
            mock_db = MagicMock()
            mock_db.execute.return_value.fetchall.return_value = []
            mock_conn.return_value = mock_db

            from backend.services.memory.context_builder import build_memory_context
            result = build_memory_context(
                thread_id="test", include_minecraft=True,
            )
            # minecraft key exists (may be empty if no skills/failures)
            assert "minecraft" in result

    def test_format_includes_minecraft(self):
        from backend.services.memory.context_builder import format_memory_sections
        sections = {
            "pinned": "- fact1",
            "working": "",
            "short_term": "",
            "long_term": "",
            "minecraft": "=== LEARNED SKILLS ===\n- collect_wood: 木を集める (80%)",
        }
        text = format_memory_sections(sections)
        assert "LEARNED SKILLS" in text
        assert "collect_wood" in text
