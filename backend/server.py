# backend/server.py
"""
Single Entry Point for Nia Backend
Refactored in Phase 1 to unify configuration and paths.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Request
from fastapi.responses import PlainTextResponse
from contextlib import asynccontextmanager

from backend.core.config import ensure_dirs, boot_banner, settings
from backend.core.logger import logger
from backend.services.startup_tasks import ensure_public_status, cleanup_old_audio_files

# Initialize directories
ensure_dirs()

# --- Startup Event ---
_retention_task: asyncio.Task | None = None
_idle_task: asyncio.Task | None = None
_room_update_task: asyncio.Task | None = None
_training_dataset_task: asyncio.Task | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Boot Banner (Path Debugging)
    logger.info(boot_banner())
    
    # 2. DB Init (Phase 2)
    init_schema()

    # 2b. Motion Library default presets
    from backend.services.motion_library import motion_library
    motion_library.ensure_defaults()

    # Health Check Log
    hc = health_check()
    logger.info("[BOOT] DB Health: %s", hc)

    # 3. Legacy Init
    ensure_public_status()
    
    # 4. Service Init
    from backend.services.telemetry_logger import telemetry
    from backend.services.chat_history_store import chat_history_store
    from backend.services.checkpointer import checkpointer_service
    await telemetry.init_db()
    await chat_history_store.init_db()
    await checkpointer_service.init_checkpointer()
    
    # 5. Minecraft Bot Integration
    from backend.services.minecraft import init_minecraft
    init_minecraft()

    # 6. GC
    deleted_count = cleanup_old_audio_files(settings.STATIC_DIR, max_age_hours=24)
    if deleted_count > 0:
        logger.info("[GC] Cleaned up %s old audio files from %s", deleted_count, settings.STATIC_DIR / "audio")

    # 6. Retention Full Sweeper (Background)
    global _retention_task
    try:
        if getattr(settings, "RETENTION_FULL_SWEEPER_ENABLED", True):
            _retention_task = asyncio.create_task(retention_full_sweeper_loop(), name="retention_full_sweeper")
    except Exception:
        logger.exception("[RETENTION_FULL] failed to start background sweeper")

    # 起動時フルスイープ（ON時のみ）
    from backend.core.agent_graph.utils import _log_task_exception
    _boot_task = asyncio.create_task(_boot_retention_full(), name="boot_retention_full")
    _boot_task.add_done_callback(_log_task_exception)

    # 7. Idle Detector (Phase R.1 — Autonomous Reflection)
    global _idle_task
    try:
        if getattr(settings, "IDLE_DETECTION_ENABLED", True):
            from backend.services.idle_detector import idle_detector_loop
            _idle_task = asyncio.create_task(idle_detector_loop(), name="idle_detector")
    except Exception:
        logger.exception("[IDLE_DETECTOR] failed to start")

    # 8. Chat Bridge (YouTube / Twitch)
    if getattr(settings, "CHAT_BRIDGE_ENABLED", False):
        try:
            from backend.services.chat_bridge import chat_bridge
            if getattr(settings, "YOUTUBE_LIVE_ENABLED", False) and getattr(settings, "YOUTUBE_VIDEO_ID", ""):
                await chat_bridge.start_youtube()
            if getattr(settings, "TWITCH_LIVE_ENABLED", False) and getattr(settings, "TWITCH_CHANNEL", ""):
                await chat_bridge.start_twitch()
        except Exception:
            logger.exception("[CHAT_BRIDGE] failed to start")

    # 9. Room Update Loop (Phase P.2)
    global _room_update_task
    try:
        if getattr(settings, "ROOM_UPDATE_ENABLED", False):
            from backend.services.room.update_loop import room_update_loop
            _room_update_task = asyncio.create_task(room_update_loop(), name="room_update")
    except Exception:
        logger.exception("[ROOM] failed to start update loop")

    # 10. Training Dataset Snapshot Loop
    global _training_dataset_task
    try:
        if getattr(settings, "TRAINING_DATASET_SNAPSHOT_ENABLED", True):
            from backend.services.training_dataset_snapshot import training_dataset_snapshot_loop
            _training_dataset_task = asyncio.create_task(
                training_dataset_snapshot_loop(),
                name="training_dataset_snapshot",
            )
    except Exception:
        logger.exception("[TRAINING_DATASET] failed to start snapshot loop")

    try:
        yield
    finally:
        if _training_dataset_task:
            _training_dataset_task.cancel()
            try:
                await _training_dataset_task
            except asyncio.CancelledError:
                pass
        if _room_update_task:
            _room_update_task.cancel()
            try:
                await _room_update_task
            except asyncio.CancelledError:
                pass
        if _idle_task:
            _idle_task.cancel()
            try:
                await _idle_task
            except asyncio.CancelledError:
                pass
        if _retention_task:
            _retention_task.cancel()
            try:
                await _retention_task
            except asyncio.CancelledError:
                pass
        try:
            from backend.services.chat_bridge import chat_bridge
            await chat_bridge.stop_all()
        except Exception:
            pass
        try:
            from backend.services.checkpointer import checkpointer_service
            await checkpointer_service.close_checkpointer()
        except Exception:
            logger.exception("[CHECKPOINTER] close failed")

# Defines the single FastAPI application instance
app = FastAPI(
    title="Nia API",
    lifespan=lifespan,
    docs_url="/docs" if settings.API_DOCS_ENABLED else None,
    redoc_url="/redoc" if settings.API_DOCS_ENABLED else None,
    openapi_url="/openapi.json" if settings.API_DOCS_ENABLED else None,
)

# Middleware — CORS
_cors_raw = getattr(settings, "CORS_ALLOWED_ORIGINS", "*")
if _cors_raw.strip() == "*":
    # Open mode: credentials must be False per spec when origin is "*"
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    _cors_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Rate Limiting
from backend.core.rate_limit import limiter
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Block invalid static paths to avoid OS path errors (e.g., "<wav>")
@app.middleware("http")
async def block_bad_static_path(request: Request, call_next):
    p = request.url.path
    if p.startswith("/static/") and ("<" in p or ">" in p):
        return PlainTextResponse("Bad static path", status_code=400)
    return await call_next(request)

# Request Correlation ID
from backend.core.correlation import set_request_id, get_request_id

@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    incoming = request.headers.get("x-request-id")
    rid = set_request_id(incoming if incoming else None)
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    return response

# Unhandled exception handler (includes request_id for tracing)
from fastapi.responses import JSONResponse

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    rid = get_request_id()
    logger.exception("[UNHANDLED] request_id=%s path=%s", rid, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "request_id": rid},
    )

# --- Initializers (Phase 2: Centralized DB) ---

from backend.core.db import init_schema, health_check
import asyncio

from backend.services.retention_sweeper import retention_full_sweeper_loop
from backend.services.chat_history_store import chat_history_store

async def _boot_retention_full():
    if not getattr(settings, "RETENTION_BOOT_FULL", False):
        logger.info("[RETENTION_FULL] skipped (RETENTION_BOOT_FULL=0)")
        return
    since_h = getattr(settings, "RETENTION_BOOT_SINCE_H", 24)
    await chat_history_store.sweep_and_promote_all_threads(since_h=since_h)

# --- Routers ---

from backend.controllers.api.stream_router import router as stream_router
from backend.controllers.api.system_router import router as system_router
from backend.controllers.api.review_router import router as review_router
from backend.controllers.api.tts_router import router as tts_router
from backend.controllers.api.tts_events_router import router as tts_events_router
from backend.controllers.api.actions_router import router as actions_router
from backend.controllers.api.draw_router import router as draw_router
from backend.controllers.api.drawing_router import router as drawing_router
from backend.controllers.api.profile_router import router as profile_router
from backend.controllers.api.livestream_router import router as livestream_router
from backend.controllers.api.voice_router import router as voice_router
from backend.controllers.api.game_router import router as game_router
from backend.controllers.api.video_router import router as video_router
from backend.controllers.api.motion_router import router as motion_router
from backend.controllers.api.identity_router import router as identity_router
from backend.controllers.api.manager_router import router as manager_router
from backend.controllers.pending_memory_router import router as pending_router
from backend.controllers.stats_router import router as stats_router
from backend.controllers.api.memory_query_router import router as memory_router
from backend.controllers.api.room_router import router as room_router
from backend.controllers.api.pip_router import router as pip_router
from backend.controllers.ws_room import router as ws_room_router

app.include_router(stream_router, prefix="/api", tags=["api"])
app.include_router(system_router, prefix="/api", tags=["api"])
app.include_router(profile_router, prefix="/api", tags=["api"])
app.include_router(review_router, prefix="/api", tags=["api"])
app.include_router(actions_router, prefix="/api", tags=["api"])
app.include_router(draw_router, prefix="/api", tags=["api"])
app.include_router(drawing_router, prefix="/api", tags=["drawing"])
app.include_router(tts_router, prefix="/api", tags=["api"])
app.include_router(tts_events_router, prefix="/api", tags=["api"])
app.include_router(livestream_router, prefix="/api", tags=["livestream"])
app.include_router(voice_router, prefix="/api", tags=["voice"])
app.include_router(game_router, prefix="/api", tags=["game"])
app.include_router(video_router, prefix="/api", tags=["video"])
app.include_router(motion_router)
app.include_router(identity_router, prefix="/api", tags=["api"])
app.include_router(manager_router, prefix="/api", tags=["manager"])
app.include_router(pending_router)
app.include_router(stats_router)
app.include_router(memory_router, prefix="/api")
app.include_router(room_router)
app.include_router(pip_router)
app.include_router(ws_room_router, tags=["room-ws"])

# --- Static Mounts ---
(settings.STATIC_DIR / "audio").mkdir(parents=True, exist_ok=True)
(settings.STATIC_DIR / "images").mkdir(parents=True, exist_ok=True)

app.mount("/static/audio", StaticFiles(directory=str(settings.STATIC_DIR / "audio")), name="static_audio")
app.mount("/static/images", StaticFiles(directory=str(settings.STATIC_DIR / "images")), name="static_images")

# --- Endpoints ---

@app.get("/health")
async def health():
    """Health Check showing DB + dependency status"""
    db = health_check()
    llm_ok = await _check_llm_reachable()
    return {
        **db,
        "dependencies": {
            "llm": "ok" if llm_ok else "unreachable",
            "db": db.get("status", "unknown"),
        },
    }


async def _check_llm_reachable() -> bool:
    """Quick LLM ping with 3s timeout."""
    try:
        import aiohttp
        url = settings.OPENAI_BASE_URL.rstrip("/")
        if not url.endswith("/v1"):
            url += "/v1"
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as s:
            async with s.get(f"{url}/models") as r:
                return r.status == 200
    except Exception:
        return False


# --- Frontend Mount (Last Priority) ---
frontend_dir = settings.PROJECT_ROOT / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="static")
