"""Checkpointer DB のクリーンアップスクリプト。

手動実行:
    python -m backend.scripts.cleanup_checkpoints
    python -m backend.scripts.cleanup_checkpoints --days 3

Sleep Cycle からも呼び出し可能（run_cleanup()）。
"""
from __future__ import annotations

import argparse
import asyncio
import sys


async def run_cleanup(retention_days: int | None = None) -> dict:
    from backend.services.checkpointer import checkpointer_service
    return await checkpointer_service.cleanup_old_checkpoints(retention_days)


def main() -> None:
    parser = argparse.ArgumentParser(description="Cleanup old checkpoints")
    parser.add_argument("--days", type=int, default=None, help="Retention days (default: from config)")
    args = parser.parse_args()

    result = asyncio.run(run_cleanup(args.days))
    print(
        f"Cleanup done: {result['deleted_checkpoints']} checkpoints, "
        f"{result['deleted_writes']} writes removed, "
        f"{result['freed_mb']:.1f} MB freed"
    )


if __name__ == "__main__":
    main()
