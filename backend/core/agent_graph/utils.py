import asyncio

from backend.core.logger import logger


def _log_task_exception(t: asyncio.Task):
    try:
        t.result()
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"Background Task Error: {e}", exc_info=True)
