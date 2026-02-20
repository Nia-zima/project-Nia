"""Motion preset API endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.core.auth import verify_system_token
from backend.services.motion_library import motion_library

router = APIRouter(prefix="/api/motion", tags=["motion"])


class MotionPresetCreate(BaseModel):
    name: str
    description: str
    keyframes_json: str
    tags: list[str] = []
    context_hint: str = ""
    source: str = "manual"


@router.get("/presets")
async def list_presets():
    """List all motion presets."""
    return {"presets": motion_library.list_all()}


@router.get("/presets/{name}")
async def get_preset(name: str):
    """Get a preset by name."""
    preset = motion_library.get(name)
    if not preset:
        raise HTTPException(status_code=404, detail=f"Preset '{name}' not found")
    return preset


@router.post("/presets", dependencies=[Depends(verify_system_token)])
async def create_preset(body: MotionPresetCreate):
    """Create or update a motion preset."""
    result = motion_library.save(
        name=body.name,
        description=body.description,
        keyframes_json=body.keyframes_json,
        tags=body.tags,
        context_hint=body.context_hint,
        source=body.source,
    )
    return result


@router.delete("/presets/{name}", dependencies=[Depends(verify_system_token)])
async def delete_preset(name: str):
    """Delete a motion preset."""
    deleted = motion_library.delete(name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Preset '{name}' not found")
    return {"deleted": name}
