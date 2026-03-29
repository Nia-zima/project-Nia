import asyncio
import json

from fastapi import APIRouter, Request
from starlette.responses import StreamingResponse

from backend.services.tts.tts_event_bus import tts_event_bus
from backend.core.logger import logger

router = APIRouter()


def _sse_pack(ev: dict) -> str:
    return f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"


@router.get("/tts_events/{thread_id}")
async def tts_events(thread_id: str, request: Request):
    async def gen():
        logger.info("[TTS_EVENTS] connect thread_id=%s", thread_id)
        agen = tts_event_bus.subscribe(thread_id)
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(agen.__anext__(), timeout=60.0)
                    yield _sse_pack(ev)
                except asyncio.TimeoutError:
                    # keep-alive ping to prevent proxies from closing idle SSE
                    yield ": ping\n\n"
                except StopAsyncIteration:
                    break
        except asyncio.CancelledError:
            return
        finally:
            try:
                await agen.aclose()
            except Exception:
                logger.debug("[TTS_EVENTS] agen.aclose() error (normal on disconnect)", exc_info=True)
            logger.info("[TTS_EVENTS] disconnect thread_id=%s", thread_id)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
