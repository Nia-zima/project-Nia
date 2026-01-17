# backend/server.py
"""
Single Entry Point for Nia Backend
Refactored in Phase 1 to unify configuration and paths.
"""
from __future__ import annotations

import json
import os
import time
import glob
from datetime import datetime
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from backend.core.config import PROJECT_ROOT, STATIC_DIR, ensure_dirs, boot_banner

# Initialize directories
ensure_dirs()

# Defines the single FastAPI application instance
app = FastAPI(title="Nia API")

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Legacy Helper Functions (to be refactored later) ---
# Phase 1 ではロジックを変えずにパスだけ config に寄せる

def ensure_public_status():
    """public_status.json が存在しない場合、初期値で作成する"""
    public_json_path = PROJECT_ROOT / "public_status.json"
    if not public_json_path.exists():
        initial_data = {
            "chapter_title": "Initializing...",
            "vibe": "Awaking",
            "note": "System is starting up.",
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M")
        }
        try:
            with open(public_json_path, "w", encoding="utf-8") as f:
                json.dump(initial_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Failed to create initial public_status: {e}")

def cleanup_old_audio_files(max_age_hours: int = 24):
    """起動時に古い音声ファイルを削除（ディスク増殖防止）"""
    audio_dir = STATIC_DIR / "audio"
    if not audio_dir.exists():
        return
    
    now = time.time()
    max_age_seconds = max_age_hours * 3600
    deleted_count = 0
    
    try:
        # glob works with strings
        for filepath in glob.glob(str(audio_dir / "**" / "*.wav"), recursive=True):
            try:
                file_age = now - os.path.getmtime(filepath)
                if file_age > max_age_seconds:
                    os.remove(filepath)
                    deleted_count += 1
            except Exception:
                pass
        
        if deleted_count > 0:
            print(f"[GC] Cleaned up {deleted_count} old audio files from {audio_dir}")
    except Exception as e:
        print(f"[GC] Audio cleanup failed: {e}")

# --- Initializers (Phase 2: Centralized DB) ---
from backend.core.db import init_schema, health_check

# --- Startup Event ---
@app.on_event("startup")
async def startup_event():
    # 1. Boot Banner (Path Debugging)
    print(boot_banner())
    
    # 2. DB Init (Phase 2)
    init_schema()
    
    # Health Check Log
    hc = health_check()
    print(f"[BOOT] DB Health: {hc}")
    
    # 3. Legacy Init
    ensure_public_status()
    
    # 4. Service Init
    from backend.services.telemetry_logger import telemetry
    from backend.services.chat_history_store import chat_history_store
    await telemetry.init_db()
    await chat_history_store.init_db()
    
    # 5. GC
    cleanup_old_audio_files(max_age_hours=24)

# --- Routers ---
from backend.controllers.api_router import router as api_router
from backend.controllers.pending_memory_router import router as pending_router
from backend.controllers.stats_router import router as stats_router

app.include_router(api_router)
app.include_router(pending_router)
app.include_router(stats_router)

# --- Static Mounts ---
(STATIC_DIR / "audio").mkdir(parents=True, exist_ok=True)
(STATIC_DIR / "images").mkdir(parents=True, exist_ok=True)

app.mount("/static/audio", StaticFiles(directory=str(STATIC_DIR / "audio")), name="static_audio")
app.mount("/static/images", StaticFiles(directory=str(STATIC_DIR / "images")), name="static_images")

# --- Endpoints ---

@app.get("/health")
def health():
    """Health Check showing DB status"""
    return health_check()


@app.get("/api/status")
async def get_status():
    public_json_path = PROJECT_ROOT / "public_status.json"
    if not public_json_path.exists():
        return JSONResponse({"status": "offline", "chapter_title": "Sleeping...", "vibe": "...", "note": ""})
    try:
        with open(public_json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"status": "error"}

# --- Frontend Mount (Last Priority) ---
frontend_dir = PROJECT_ROOT / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="static")
