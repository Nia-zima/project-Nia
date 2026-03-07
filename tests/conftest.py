"""Shared test fixtures and helpers for the project-nia test suite."""
from __future__ import annotations

import os
import time
import uuid
import tempfile
import sys
import types
import shutil
import importlib.machinery
from pathlib import Path

# Ensure fast retention profile for all tests (must be before backend imports)
os.environ.setdefault("RETENTION_PROFILE", "fast")

# Keep pytest temp files inside the workspace to avoid OS temp permission issues.
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# ── TEST DB ISOLATION ──────────────────────────────────────────────
# Redirect DB_PATH to a test-only database so pytest never touches
# the production data/nia.sqlite3.
_TEST_DB_PATH = PROJECT_ROOT / "data" / "nia_test.sqlite3"
_TMP_ROOT = PROJECT_ROOT / "data" / "pytest_tmp_root"
_TMP_ROOT.mkdir(parents=True, exist_ok=True)
for _k in ("TMP", "TEMP", "TMPDIR"):
    os.environ[_k] = str(_TMP_ROOT)
tempfile.tempdir = str(_TMP_ROOT)


class _WorkspaceTemporaryDirectory:
    """TemporaryDirectory replacement with workspace-local deterministic perms."""

    def __init__(self, suffix=None, prefix=None, dir=None, ignore_cleanup_errors=False):
        base = Path(dir) if dir else (PROJECT_ROOT / "data" / "pytest_tempdirs")
        base.mkdir(parents=True, exist_ok=True)
        _prefix = prefix if prefix is not None else "tmp"
        _suffix = suffix if suffix is not None else ""
        self._path = base / f"{_prefix}{uuid.uuid4().hex}{_suffix}"
        self._path.mkdir(parents=True, exist_ok=False)
        self.name = str(self._path)
        self._ignore_cleanup_errors = bool(ignore_cleanup_errors)

    def __enter__(self):
        return self.name

    def __exit__(self, exc_type, exc, tb):
        self.cleanup()
        return False

    def cleanup(self):
        try:
            shutil.rmtree(self.name, ignore_errors=True)
        except Exception:
            if not self._ignore_cleanup_errors:
                raise


tempfile.TemporaryDirectory = _WorkspaceTemporaryDirectory

# Unit tests mock yt_dlp.YoutubeDL; provide a tiny fallback module if missing.
if "yt_dlp" not in sys.modules:
    try:
        __import__("yt_dlp")
    except Exception:
        _stub = types.ModuleType("yt_dlp")

        class _DummyYoutubeDL:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def extract_info(self, *args, **kwargs):
                raise RuntimeError("yt_dlp is not installed")

            def download(self, *args, **kwargs):
                raise RuntimeError("yt_dlp is not installed")

        _stub.YoutubeDL = _DummyYoutubeDL
        _stub.__spec__ = importlib.machinery.ModuleSpec("yt_dlp", loader=None)
        sys.modules["yt_dlp"] = _stub

# Some Windows environments can raise PermissionError in pytest's
# dead-symlink cleanup. Keep session finish from crashing on cleanup only.
try:
    import _pytest.pathlib as _pytest_pathlib
    import _pytest.tmpdir as _pytest_tmpdir

    _orig_cleanup_dead_symlinks = _pytest_pathlib.cleanup_dead_symlinks

    def _safe_cleanup_dead_symlinks(root):
        try:
            _orig_cleanup_dead_symlinks(root)
        except PermissionError:
            return

    _pytest_pathlib.cleanup_dead_symlinks = _safe_cleanup_dead_symlinks
    _pytest_tmpdir.cleanup_dead_symlinks = _safe_cleanup_dead_symlinks
except Exception:
    pass

import pytest  # noqa: E402

from backend.core.config import settings as _settings  # noqa: E402
from backend.core.db import get_conn, init_schema  # noqa: E402
from backend.services.memory.models import SemanticMemory, WorkingItem  # noqa: E402

# Overwrite settings.DB_PATH BEFORE any DB access.
# This ensures every get_conn() / managed_conn() call in all tests
# uses data/nia_test.sqlite3 instead of the production data/nia.sqlite3.
_settings.DB_PATH = _TEST_DB_PATH


# ── Pytest runtime config ───────────────────────────────────────────


def pytest_configure(config):
    # Use a unique basetemp per run to avoid Windows permission collisions
    # when pytest tries to clean an old base directory.
    base = PROJECT_ROOT / "data" / "pytest_runtime" / f"base_{int(time.time() * 1000)}"
    base.mkdir(parents=True, exist_ok=True)
    config.option.basetemp = str(base)


# ── Session-scoped schema init ───────────────────────────────────────


@pytest.fixture(autouse=True, scope="session")
def _init_schema():
    """Ensure DB schema exists once per test session."""
    init_schema()


@pytest.fixture
def tmp_path():
    """Workspace-local tmp_path replacement to avoid OS temp ACL issues."""
    root = PROJECT_ROOT / "data" / "pytest_tmp_local"
    root.mkdir(parents=True, exist_ok=True)
    p = root / f"tmp_{uuid.uuid4().hex}"
    p.mkdir(parents=True, exist_ok=True)
    try:
        yield p
    finally:
        shutil.rmtree(p, ignore_errors=True)


# ── Shared helpers ───────────────────────────────────────────────────


def make_semantic(
    *,
    id: str | None = None,
    thread_id: str = "t1",
    content: str = "test fact",
    status: str = "confirmed",
    confidence: float = 0.8,
    state_tag: str | None = None,
    updated_at: float | None = None,
    supersedes_id: str | None = None,
) -> SemanticMemory:
    """Create a SemanticMemory instance for testing."""
    now = time.time()
    return SemanticMemory(
        id=id or str(uuid.uuid4()),
        thread_id=thread_id,
        content=content,
        valid_from=now,
        created_at=now,
        updated_at=updated_at or now,
        status=status,
        confidence=confidence,
        state_tag=state_tag,
        supersedes_id=supersedes_id,
    )


def make_working(
    *,
    id: str | None = None,
    thread_id: str = "t1",
    item_type: str = "question",
    content: str = "pending question",
    priority: int = 3,
    stale_turn_count: int = 0,
) -> WorkingItem:
    """Create a WorkingItem instance for testing."""
    now = time.time()
    return WorkingItem(
        id=id or str(uuid.uuid4()),
        thread_id=thread_id,
        item_type=item_type,
        content=content,
        priority=priority,
        created_turn_id="turn0",
        created_at=now,
        updated_at=now,
        stale_turn_count=stale_turn_count,
    )
