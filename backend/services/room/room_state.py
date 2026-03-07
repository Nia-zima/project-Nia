"""
Room State — data models and persistence for Nia's room.

Design doc: docs/pip_and_room_design.md §3-4
Phase P.2: empty room + object catalog + time-linked lighting + Pip state.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

from backend.core.config import settings
from backend.core.logger import logger


# ── Data models ───────────────────────────────────────────────


@dataclass
class RoomObject:
    """An object placed in Nia's room."""

    id: str = ""
    type: str = ""              # "furniture" / "decoration" / "pip_item"
    name: str = ""              # Display name (Nia can rename)
    template: str = ""          # Catalog template key
    position: str = ""          # Named position in room
    color: str = "#FFFFFF"
    placed_by: str = "nia"
    placed_at: float = 0.0
    memory_link: str = ""       # Related memory ID (for art)


@dataclass
class WallArt:
    """A piece of art hung on the wall."""

    id: str = ""
    image_path: str = ""
    frame_id: str = ""          # Which frame it's in
    memory_link: str = ""
    created_at: float = 0.0
    description: str = ""


@dataclass
class NeroCompanionState:
    """State of the Nero companion (the observing polyhedron)."""

    state: str = "idle"  # idle, mirroring, answer, observing, unstable
    intensity: float = 1.0
    position: str = "floating_near_ceiling"


@dataclass
class RoomState:
    """Full state of Nia's room."""

    # Space
    size: str = "medium"
    wall_color: str = "#F5F5F5"
    floor_material: str = "wood"

    # Light and time
    time_of_day: str = "day"
    light_intensity: float = 1.0
    light_color: str = "#FFFFFF"

    # Objects
    objects: list[dict] = field(default_factory=list)

    # Wall art
    wall_art: list[dict] = field(default_factory=list)
    stored_art: list[dict] = field(default_factory=list)

    # Pip (serialized as dict for JSON compatibility)
    pip_state: dict = field(default_factory=lambda: {
        "bond": 0.0,
        "mood": "idle",
        "energy": 1.0,
        "position": "center",
        "animation": "idle",
        "favorite_spot": "",
        "last_interaction": 0.0,
        "scrap_count": 0,
        "current_scrap_id": "",
    })
    pip_position_history: list[str] = field(default_factory=list)
    pip_scrap_count: int = 0  # Unity側のPipScrapVisualizer連携用

    # Nero Companion (serialized as dict)
    nero_state: dict = field(default_factory=lambda: {
        "state": "idle",
        "intensity": 1.0,
        "position": "floating_near_ceiling",
    })

    # Meta
    created_at: float = 0.0
    total_actions: int = 0
    last_action_at: float = 0.0


# ── Object Catalog ────────────────────────────────────────────


OBJECT_CATALOG_V1: list[dict] = [
    # Furniture
    {"type": "furniture",   "template": "desk",      "name": "机"},
    {"type": "furniture",   "template": "chair",     "name": "椅子"},
    {"type": "furniture",   "template": "bookshelf", "name": "本棚"},
    {"type": "furniture",   "template": "bed",       "name": "ベッド"},
    {"type": "furniture",   "template": "lamp",      "name": "ランプ"},
    {"type": "furniture",   "template": "rug",       "name": "ラグ"},
    {"type": "furniture",   "template": "cushion",   "name": "クッション"},
    # Decoration
    {"type": "decoration",  "template": "plant",     "name": "植物"},
    {"type": "decoration",  "template": "clock",     "name": "時計"},
    {"type": "decoration",  "template": "frame",     "name": "額縁"},
    # Pip items
    {"type": "pip_item",    "template": "pip_bed",   "name": "Pipのベッド"},
    {"type": "pip_item",    "template": "pip_bowl",  "name": "Pipのお皿"},
]

VALID_TEMPLATES = {item["template"] for item in OBJECT_CATALOG_V1}


def get_catalog() -> list[dict]:
    """Return the available object catalog."""
    return list(OBJECT_CATALOG_V1)


# ── Named positions ──────────────────────────────────────────

VALID_POSITIONS = {
    "center", "near_wall_north", "near_wall_south", "near_wall_east", "near_wall_west",
    "corner_ne", "corner_nw", "corner_se", "corner_sw",
    "near_window", "near_door", "near_nia", "next_to_nia",
    "corner",  # generic corner (used by Pip for sleep)
}


# ── Lighting ──────────────────────────────────────────────────


def compute_lighting(hour: int) -> tuple[str, float, str]:
    """Compute (time_of_day, light_intensity, light_color) from hour (0-23)."""
    if 6 <= hour < 10:
        return "morning", 0.7, "#FFE4B5"
    elif 10 <= hour < 17:
        return "day", 1.0, "#FFFFFF"
    elif 17 <= hour < 20:
        return "evening", 0.6, "#FFA07A"
    elif 20 <= hour < 23:
        return "night", 0.3, "#4169E1"
    else:
        return "late_night", 0.1, "#191970"


def apply_lamp_bonus(room: RoomState) -> None:
    """If Nia placed a lamp, boost light intensity."""
    lamps = [o for o in room.objects if isinstance(o, dict) and o.get("template") == "lamp"]
    if lamps:
        room.light_intensity = min(1.0, room.light_intensity + 0.2)


# ── Persistence ───────────────────────────────────────────────


ROOM_STATE_PATH = settings.DATA_DIR / "room_state.json"


def load_room_state(path: Path | None = None) -> RoomState:
    """Load room state from JSON file. Returns empty room if file doesn't exist."""
    p = path or ROOM_STATE_PATH
    try:
        if p.exists():
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            return RoomState(**{
                k: v for k, v in data.items()
                if k in RoomState.__dataclass_fields__
            })
    except Exception:
        logger.warning("[Room] Failed to load room_state.json, using default", exc_info=True)

    return RoomState(created_at=time.time())


def save_room_state(room: RoomState, path: Path | None = None) -> None:
    """Save room state to JSON file."""
    p = path or ROOM_STATE_PATH
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(asdict(room), f, indent=2, ensure_ascii=False)
    except Exception:
        logger.warning("[Room] Failed to save room_state.json", exc_info=True)
