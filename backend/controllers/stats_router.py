"""
Stats Router - 会話統計と内部状態のAPI
"""
from fastapi import APIRouter

from backend.controllers.stats.summary_router import router as summary_router
from backend.controllers.stats.state_router import router as state_router
from backend.controllers.stats.memory_router import router as memory_router

router = APIRouter(prefix="/api/stats", tags=["Statistics"])

router.include_router(summary_router)
router.include_router(state_router)
router.include_router(memory_router)



