"""
Room Action — execute actions that modify Nia's room.

Design doc: docs/pip_and_room_design.md §3.3
Phase P.2: place, move, remove, color, hang_art.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from backend.core.logger import logger
from backend.services.room.room_state import (
    RoomState,
    RoomObject,
    WallArt,
    VALID_TEMPLATES,
    VALID_POSITIONS,
    save_room_state,
)


@dataclass
class RoomAction:
    """A room modification command issued by Nia."""

    action_type: str = ""       # "place" / "move" / "remove" / "color" / "hang_art"
    target_id: str = ""         # Object ID for move/remove/color
    template: str = ""          # Catalog template for place
    position: str = ""          # Target position
    color: str = ""             # New color for color action
    art_image: str = ""         # Image path for hang_art
    memory_link: str = ""       # drawing_id or other trace reference for hang_art
    name: str = ""              # Custom name for object


class RoomActionError(Exception):
    """Error during room action execution."""
    pass


MAX_OBJECTS = 20


def execute_room_action(room: RoomState, action: RoomAction) -> RoomState:
    """Execute a room action and return the updated RoomState.

    Raises RoomActionError on invalid actions.
    """
    handler = _HANDLERS.get(action.action_type)
    if handler is None:
        raise RoomActionError(f"Unknown action_type: {action.action_type}")

    handler(room, action)

    room.total_actions += 1
    room.last_action_at = time.time()

    # P.4: Pip reacts to room changes
    _apply_pip_reaction(room, action)

    return room


# ── Action handlers ───────────────────────────────────────────


def _handle_place(room: RoomState, action: RoomAction) -> None:
    """Place a new object from catalog."""
    if not action.template:
        raise RoomActionError("template is required for place action")
    if action.template not in VALID_TEMPLATES:
        raise RoomActionError(f"Unknown template: {action.template}")
    if len(room.objects) >= MAX_OBJECTS:
        raise RoomActionError(f"Room is full (max {MAX_OBJECTS} objects)")

    position = action.position or "center"
    if position not in VALID_POSITIONS:
        raise RoomActionError(f"Invalid position: {position}")

    # Find catalog entry for default name
    from backend.services.room.room_state import OBJECT_CATALOG_V1
    catalog_entry = next(
        (c for c in OBJECT_CATALOG_V1 if c["template"] == action.template),
        None,
    )

    obj = {
        "id": uuid.uuid4().hex[:8],
        "type": catalog_entry["type"] if catalog_entry else "furniture",
        "name": action.name or (catalog_entry["name"] if catalog_entry else action.template),
        "template": action.template,
        "position": position,
        "color": action.color or "#FFFFFF",
        "placed_by": "nia",
        "placed_at": time.time(),
        "memory_link": "",
    }
    room.objects.append(obj)
    logger.info("[Room] placed %s at %s", obj["name"], position)


def _handle_move(room: RoomState, action: RoomAction) -> None:
    """Move an existing object to a new position."""
    if not action.target_id:
        raise RoomActionError("target_id is required for move action")
    if not action.position:
        raise RoomActionError("position is required for move action")
    if action.position not in VALID_POSITIONS:
        raise RoomActionError(f"Invalid position: {action.position}")

    obj = _find_object(room, action.target_id)
    if obj is None:
        raise RoomActionError(f"Object not found: {action.target_id}")

    old_pos = obj.get("position", "")
    obj["position"] = action.position
    logger.info("[Room] moved %s from %s to %s", obj["name"], old_pos, action.position)


def _handle_remove(room: RoomState, action: RoomAction) -> None:
    """Remove an object from the room."""
    if not action.target_id:
        raise RoomActionError("target_id is required for remove action")

    idx = _find_object_index(room, action.target_id)
    if idx is None:
        raise RoomActionError(f"Object not found: {action.target_id}")

    removed = room.objects.pop(idx)
    logger.info("[Room] removed %s", removed.get("name", action.target_id))


def _handle_color(room: RoomState, action: RoomAction) -> None:
    """Change color of an object or the wall."""
    if not action.color:
        raise RoomActionError("color is required for color action")

    if action.target_id == "wall" or not action.target_id:
        room.wall_color = action.color
        logger.info("[Room] wall color changed to %s", action.color)
    else:
        obj = _find_object(room, action.target_id)
        if obj is None:
            raise RoomActionError(f"Object not found: {action.target_id}")
        obj["color"] = action.color
        logger.info("[Room] %s color changed to %s", obj["name"], action.color)


def _handle_hang_art(room: RoomState, action: RoomAction) -> None:
    """Hang a piece of art on the wall."""
    if not action.art_image:
        raise RoomActionError("art_image is required for hang_art action")

    art = {
        "id": uuid.uuid4().hex[:8],
        "image_path": action.art_image,
        "frame_id": action.target_id or "",
        "memory_link": action.memory_link or "",
        "created_at": time.time(),
        "description": action.name or "",
    }
    room.wall_art.append(art)
    logger.info("[Room] hung art: %s", action.art_image)


# ── Helpers ───────────────────────────────────────────────────


def _find_object(room: RoomState, object_id: str) -> dict | None:
    """Find an object by ID."""
    for obj in room.objects:
        if isinstance(obj, dict) and obj.get("id") == object_id:
            return obj
    return None


def _find_object_index(room: RoomState, object_id: str) -> int | None:
    """Find object index by ID."""
    for i, obj in enumerate(room.objects):
        if isinstance(obj, dict) and obj.get("id") == object_id:
            return i
    return None


def _apply_pip_reaction(room: RoomState, action: RoomAction) -> None:
    """P.4: Pip reacts to room changes.

    - move/remove → bond penalty + look_around animation
    - hang_art → react_to_art animation
    """
    from backend.services.pip.pip_state import (
        BOND_RULES, apply_bond_delta, dict_to_pip, pip_to_dict,
    )

    pip = dict_to_pip(room.pip_state)

    if action.action_type in ("move", "remove"):
        apply_bond_delta(pip, BOND_RULES["nia_room_change"])
        pip.animation = "look_around"
        logger.debug(
            "[Room] pip room_change reaction: bond=%.3f animation=%s",
            pip.bond, pip.animation,
        )
    elif action.action_type == "hang_art":
        pip.animation = "react_to_art"

    room.pip_state = pip_to_dict(pip)


_HANDLERS = {
    "place": _handle_place,
    "move": _handle_move,
    "remove": _handle_remove,
    "color": _handle_color,
    "hang_art": _handle_hang_art,
}
