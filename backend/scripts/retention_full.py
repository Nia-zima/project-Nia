import argparse
import asyncio

from backend.core.logger import setup_logging, logger
from backend.core.config import settings
from backend.services.chat_history_store import chat_history_store

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--since-h", type=int, default=24)
    args = parser.parse_args()

    setup_logging()
    logger.info("[RETENTION_FULL_CLI] start since_h=%s", args.since_h)
    await chat_history_store.sweep_and_promote_all_threads(since_h=args.since_h)
    logger.info("[RETENTION_FULL_CLI] done")

if __name__ == "__main__":
    asyncio.run(main())
