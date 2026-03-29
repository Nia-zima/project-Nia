from __future__ import annotations

import time
from pathlib import Path

from backend.core.logger import logger

from backend.services.public_status import ensure_public_status as _ensure_public_status


def ensure_public_status(project_root: Path | None = None) -> None:
    """public_status.json が存在しない場合、初期値で作成する"""
    try:
        _ensure_public_status(project_root=project_root)
    except Exception as e:
        logger.warning("Failed to create initial public_status: %s", e)


def cleanup_old_audio_files(static_dir: Path, max_age_hours: int = 24) -> int:
    """起動時に古い音声ファイルを削除（ディスク増殖防止）"""
    audio_dir = static_dir / "audio"
    if not audio_dir.exists():
        return 0

    now = time.time()
    max_age_seconds = max_age_hours * 3600
    deleted_count = 0

    try:
        for filepath in audio_dir.rglob("*.wav"):
            try:
                file_age = now - filepath.stat().st_mtime
                if file_age > max_age_seconds:
                    filepath.unlink(missing_ok=True)
                    deleted_count += 1
            except Exception:
                pass
        return deleted_count
    except Exception as e:
        logger.warning("[GC] Audio cleanup failed: %s", e)
        return 0
