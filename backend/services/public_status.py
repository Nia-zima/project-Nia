from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Set

from backend.core.config import settings

# スレッドセーフティ: 非同期環境での read/write 排他制御
_status_lock = asyncio.Lock()


def _default_status() -> Dict[str, Any]:
    return {
        "chapter_title": "Initializing...",
        "vibe": "Awaking",
        "note": "System is starting up.",
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def _resolve_project_root(project_root: Optional[Path]) -> Path:
    return project_root or settings.PROJECT_ROOT


def get_public_status_path(project_root: Optional[Path] = None) -> Path:
    root = _resolve_project_root(project_root)
    return root / settings.PUBLIC_STATUS_JSON


def read_public_status(
    *,
    project_root: Optional[Path] = None,
    default: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    path = get_public_status_path(project_root)
    if not path.exists():
        return default or {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default or {}


def write_public_status(
    data: Dict[str, Any],
    *,
    project_root: Optional[Path] = None,
) -> None:
    path = get_public_status_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def ensure_public_status(
    *,
    project_root: Optional[Path] = None,
    initial_data: Optional[Dict[str, Any]] = None,
) -> None:
    path = get_public_status_path(project_root)
    if path.exists():
        return
    write_public_status(initial_data or _default_status(), project_root=project_root)


def update_public_status(
    updates: Dict[str, Any],
    *,
    project_root: Optional[Path] = None,
    allowed_keys: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    current = read_public_status(project_root=project_root, default=_default_status())

    if allowed_keys is not None:
        updates = {k: v for k, v in updates.items() if k in allowed_keys}

    if updates:
        current.update(updates)
        current["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        write_public_status(current, project_root=project_root)

    return current


async def async_update_public_status(
    updates: Dict[str, Any],
    *,
    project_root: Optional[Path] = None,
    allowed_keys: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """スレッドセーフな非同期版 update_public_status"""
    async with _status_lock:
        return update_public_status(
            updates,
            project_root=project_root,
            allowed_keys=allowed_keys,
        )


async def async_read_public_status(
    *,
    project_root: Optional[Path] = None,
    default: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """スレッドセーフな非同期版 read_public_status"""
    async with _status_lock:
        return read_public_status(project_root=project_root, default=default)
