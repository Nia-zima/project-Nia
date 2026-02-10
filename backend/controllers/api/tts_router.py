from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.services.voicevox_client import voicevox_client


router = APIRouter()


class TTSRequest(BaseModel):
    text: str
    speaker_id: int = 3  # Default: ずんだもん


@router.post("/tts/generate")
async def tts_generate(req: TTSRequest) -> Dict[str, Any]:
    """Generate TTS audio using VOICEVOX"""
    text = (req.text or "").strip()
    if not text or text == "WAIT":
        return {"ok": True, "skipped": True, "reason": "wait_or_empty"}

    import asyncio
    import time
    loop = asyncio.get_running_loop()
    
    t0 = time.perf_counter()
    url = await loop.run_in_executor(
        None, 
        voicevox_client.generate_audio_to_file, 
        text, 
        req.speaker_id,
        "default"
    )
    gen_ms = int((time.perf_counter() - t0) * 1000)
    
    if not url:
        raise HTTPException(status_code=500, detail="TTS generation failed")

    return {
        "ok": True,
        "data": {
            "url": url,
            "text_content": text,
            "is_silence": False,
            "gen_ms": gen_ms,
        },
    }


@router.get("/tts/speakers")
async def get_speakers() -> List[Dict[str, Any]]:
    """Get available VOICEVOX speakers"""
    return voicevox_client.get_speakers()
