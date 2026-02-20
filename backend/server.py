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
    from backend.services.memory_manager import memory_manager
    await telemetry.init_db()
    await chat_history_store.init_db()
    await memory_manager.init_checkpointer()
    
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
    asyncio.create_task(_boot_retention_full())

    # 7. Idle Detector (Phase R.1 — Autonomous Reflection)
    global _idle_task
    try:
        if getattr(settings, "IDLE_DETECTION_ENABLED", True):
            from backend.services.idle_detector import idle_detector_loop
            _idle_task = asyncio.create_task(idle_detector_loop(), name="idle_detector")
    except Exception:
        logger.exception("[IDLE_DETECTOR] failed to start")

    try:
        yield
    finally:
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
            from backend.services.memory_manager import memory_manager
            await memory_manager.close_checkpointer()
        except Exception:
            logger.exception("[CHECKPOINTER] close failed")

# Defines the single FastAPI application instance
app = FastAPI(title="Nia API", lifespan=lifespan)

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

# Block invalid static paths to avoid OS path errors (e.g., "<wav>")
@app.middleware("http")
async def block_bad_static_path(request: Request, call_next):
    p = request.url.path
    if p.startswith("/static/") and ("<" in p or ">" in p):
        return PlainTextResponse("Bad static path", status_code=400)
    return await call_next(request)

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
from backend.controllers.api.profile_router import router as profile_router
from backend.controllers.api.livestream_router import router as livestream_router
from backend.controllers.api.voice_router import router as voice_router
from backend.controllers.api.game_router import router as game_router
from backend.controllers.api.video_router import router as video_router
from backend.controllers.api.motion_router import router as motion_router
from backend.controllers.api.identity_router import router as identity_router
from backend.controllers.pending_memory_router import router as pending_router
from backend.controllers.stats_router import router as stats_router
from backend.api.memory_router import router as memory_router

app.include_router(stream_router, prefix="/api", tags=["api"])
app.include_router(system_router, prefix="/api", tags=["api"])
app.include_router(profile_router, prefix="/api", tags=["api"])
app.include_router(review_router, prefix="/api", tags=["api"])
app.include_router(actions_router, prefix="/api", tags=["api"])
app.include_router(draw_router, prefix="/api", tags=["api"])
app.include_router(tts_router, prefix="/api", tags=["api"])
app.include_router(tts_events_router, prefix="/api", tags=["api"])
app.include_router(livestream_router, prefix="/api", tags=["livestream"])
app.include_router(voice_router, prefix="/api", tags=["voice"])
app.include_router(game_router, prefix="/api", tags=["game"])
app.include_router(video_router, prefix="/api", tags=["video"])
app.include_router(motion_router)
app.include_router(identity_router, prefix="/api", tags=["api"])
app.include_router(pending_router)
app.include_router(stats_router)
app.include_router(memory_router, prefix="/api")

# --- Static Mounts ---
(settings.STATIC_DIR / "audio").mkdir(parents=True, exist_ok=True)
(settings.STATIC_DIR / "images").mkdir(parents=True, exist_ok=True)

app.mount("/static/audio", StaticFiles(directory=str(settings.STATIC_DIR / "audio")), name="static_audio")
app.mount("/static/images", StaticFiles(directory=str(settings.STATIC_DIR / "images")), name="static_images")

# --- Endpoints ---

@app.get("/health")
def health():
    """Health Check showing DB status"""
    return health_check()


# --- Frontend Mount (Last Priority) ---
frontend_dir = settings.PROJECT_ROOT / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="static")
