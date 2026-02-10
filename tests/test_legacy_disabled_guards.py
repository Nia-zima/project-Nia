import sys
import asyncio
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from backend.core.config import settings
from backend.services.chat_history_store import chat_history_store
from backend.services.memory_manager import memory_manager


def test_chat_history_store_legacy_disabled_paths_are_safe():
    old_tbl = bool(getattr(settings, "LEGACY_MEMORY_TABLES_ENABLED", False))
    settings.LEGACY_MEMORY_TABLES_ENABLED = False
    try:
        threads = asyncio.run(chat_history_store.list_recent_threads(since_hours=24, limit=10))
        assert isinstance(threads, list)

        ltm = asyncio.run(chat_history_store.get_long_term_captures(thread_id="default_thread", limit=10))
        assert ltm == []

        recent = asyncio.run(chat_history_store.get_recent_captures("default_thread", limit=10, window_hours=1))
        assert recent == []

        asyncio.run(chat_history_store.update_capture_retention("dummy", retention=0.5, stage="long_term"))
        asyncio.run(chat_history_store.sweep_and_promote("default_thread", mode="light", limit=10))
        processed = asyncio.run(chat_history_store.process_vector_sync_queue(limit=10))
        assert processed == 0
    finally:
        settings.LEGACY_MEMORY_TABLES_ENABLED = old_tbl


def test_memory_manager_integrity_skips_when_legacy_disabled():
    old_tbl = bool(getattr(settings, "LEGACY_MEMORY_TABLES_ENABLED", False))
    settings.LEGACY_MEMORY_TABLES_ENABLED = False
    try:
        result = asyncio.run(memory_manager.run_integrity_check(force=True, client_host="127.0.0.1"))
        assert result.get("ok") is True
        assert result.get("skipped") is True
    finally:
        settings.LEGACY_MEMORY_TABLES_ENABLED = old_tbl

