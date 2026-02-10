import json
from typing import List

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.core.config import settings

router = APIRouter()


class UserProfile(BaseModel):
    user_name: str
    bio: str = ""
    interests: List[str] = []
    traits: List[str] = []


@router.get("/profile")
async def get_user_profile():
    rel_path = getattr(settings, "USER_PROFILE_JSON", "data/user_profile.json")
    json_path = settings.PROJECT_ROOT / rel_path

    res = {
        "user_name": "Origin",
        "bio": "",
        "interests": [],
        "traits": [],
    }

    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    # Base merge
                    res.update(data)
                    
                    # Mapping legacy nested structure (preferences.interests -> interests)
                    if "preferences" in data and isinstance(data["preferences"], dict):
                        prefs = data["preferences"]
                        if not res.get("interests") and "interests" in prefs:
                            res["interests"] = prefs["interests"]
                        if not res.get("traits") and "traits" in prefs:
                            res["traits"] = prefs["traits"]
                    
                    # Final safety check for required frontend fields
                    if not isinstance(res.get("interests"), list):
                        res["interests"] = []
                    if not isinstance(res.get("traits"), list):
                        res["traits"] = []
                    
                    return res
        except Exception as e:
            print(f"Profile load catch: {e}")

    return res


@router.post("/profile")
async def update_user_profile(profile: UserProfile):
    rel_path = getattr(settings, "USER_PROFILE_JSON", "data/user_profile.json")
    json_path = settings.PROJECT_ROOT / rel_path

    # Load existing to preserve 'stats' or extra fields not in model
    existing = {}
    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass

    # Merge updates
    updated_data = {**existing, **profile.model_dump()}

    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(updated_data, f, ensure_ascii=False, indent=2)
        return {"status": "success", "profile": updated_data}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
