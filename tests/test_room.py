"""Tests for Room system (Phase P.2).

Design doc: docs/pip_and_room_design.md
Tests cover: RoomState, RoomAction, update_loop, room_router, lighting, catalog.
"""
import json
import time
import pytest
from pathlib import Path

from backend.services.room.room_state import (
    RoomState,
    RoomObject,
    WallArt,
    OBJECT_CATALOG_V1,
    VALID_TEMPLATES,
    VALID_POSITIONS,
    get_catalog,
    compute_lighting,
    apply_lamp_bonus,
    load_room_state,
    save_room_state,
)
from backend.services.room.room_action import (
    RoomAction,
    RoomActionError,
    execute_room_action,
    MAX_OBJECTS,
)
from backend.services.room.update_loop import (
    run_single_update,
    _update_favorite_spot,
)
from backend.services.pip.pip_state import PipState, dict_to_pip, pip_to_dict


# ═══════════════════════════════════════════════════════════════
# RoomState Basics
# ═══════════════════════════════════════════════════════════════


class TestRoomState:
    def test_defaults(self):
        room = RoomState()
        assert room.size == "medium"
        assert room.wall_color == "#F5F5F5"
        assert room.objects == []
        assert room.wall_art == []
        assert room.pip_state["bond"] == 0.0

    def test_empty_room_is_default(self):
        room = RoomState(created_at=time.time())
        assert len(room.objects) == 0
        assert room.pip_state["position"] == "center"


class TestCatalog:
    def test_catalog_not_empty(self):
        assert len(OBJECT_CATALOG_V1) > 0

    def test_all_templates_have_names(self):
        for item in OBJECT_CATALOG_V1:
            assert item["template"]
            assert item["name"]
            assert item["type"]

    def test_get_catalog_returns_copy(self):
        c1 = get_catalog()
        c2 = get_catalog()
        assert c1 == c2
        c1.append({"test": True})
        assert len(get_catalog()) == len(OBJECT_CATALOG_V1)

    def test_valid_templates_set(self):
        for item in OBJECT_CATALOG_V1:
            assert item["template"] in VALID_TEMPLATES

    def test_expected_items(self):
        templates = {item["template"] for item in OBJECT_CATALOG_V1}
        assert "desk" in templates
        assert "lamp" in templates
        assert "pip_bed" in templates
        assert "frame" in templates


# ═══════════════════════════════════════════════════════════════
# Lighting
# ═══════════════════════════════════════════════════════════════


class TestLighting:
    def test_morning(self):
        tod, intensity, color = compute_lighting(8)
        assert tod == "morning"
        assert 0.5 < intensity < 1.0

    def test_day(self):
        tod, intensity, color = compute_lighting(12)
        assert tod == "day"
        assert intensity == 1.0

    def test_evening(self):
        tod, intensity, color = compute_lighting(18)
        assert tod == "evening"

    def test_night(self):
        tod, intensity, color = compute_lighting(22)
        assert tod == "night"
        assert intensity < 0.5

    def test_late_night(self):
        tod, intensity, color = compute_lighting(3)
        assert tod == "late_night"
        assert intensity < 0.2

    def test_lamp_bonus(self):
        room = RoomState(light_intensity=0.3)
        room.objects = [{"template": "lamp", "id": "l1"}]
        apply_lamp_bonus(room)
        assert room.light_intensity == pytest.approx(0.5)

    def test_lamp_bonus_caps_at_1(self):
        room = RoomState(light_intensity=0.9)
        room.objects = [{"template": "lamp", "id": "l1"}]
        apply_lamp_bonus(room)
        assert room.light_intensity == 1.0

    def test_no_lamp_no_bonus(self):
        room = RoomState(light_intensity=0.3)
        room.objects = [{"template": "desk", "id": "d1"}]
        apply_lamp_bonus(room)
        assert room.light_intensity == 0.3


# ═══════════════════════════════════════════════════════════════
# Persistence
# ═══════════════════════════════════════════════════════════════


class TestPersistence:
    def test_save_and_load(self, tmp_path):
        p = tmp_path / "room_state.json"
        room = RoomState(created_at=123.0, wall_color="#FF0000")
        room.objects.append({
            "id": "obj1", "type": "furniture", "name": "desk",
            "template": "desk", "position": "center",
        })
        save_room_state(room, p)
        assert p.exists()

        loaded = load_room_state(p)
        assert loaded.wall_color == "#FF0000"
        assert loaded.created_at == 123.0
        assert len(loaded.objects) == 1
        assert loaded.objects[0]["id"] == "obj1"

    def test_load_nonexistent_returns_default(self, tmp_path):
        p = tmp_path / "nope.json"
        room = load_room_state(p)
        assert room.size == "medium"
        assert room.created_at > 0

    def test_load_corrupted_returns_default(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("not json {{{")
        room = load_room_state(p)
        assert room.size == "medium"


# ═══════════════════════════════════════════════════════════════
# Room Actions
# ═══════════════════════════════════════════════════════════════


class TestRoomActions:
    def test_place_object(self):
        room = RoomState()
        action = RoomAction(action_type="place", template="desk", position="center")
        result = execute_room_action(room, action)
        assert len(result.objects) == 1
        assert result.objects[0]["template"] == "desk"
        assert result.objects[0]["name"] == "机"
        assert result.total_actions == 1

    def test_place_with_custom_name(self):
        room = RoomState()
        action = RoomAction(action_type="place", template="lamp", position="corner_ne", name="マイランプ")
        execute_room_action(room, action)
        assert room.objects[0]["name"] == "マイランプ"

    def test_place_invalid_template(self):
        room = RoomState()
        action = RoomAction(action_type="place", template="spaceship")
        with pytest.raises(RoomActionError, match="Unknown template"):
            execute_room_action(room, action)

    def test_place_no_template(self):
        room = RoomState()
        action = RoomAction(action_type="place")
        with pytest.raises(RoomActionError, match="template is required"):
            execute_room_action(room, action)

    def test_place_invalid_position(self):
        room = RoomState()
        action = RoomAction(action_type="place", template="desk", position="mars")
        with pytest.raises(RoomActionError, match="Invalid position"):
            execute_room_action(room, action)

    def test_place_max_objects(self):
        room = RoomState()
        for i in range(MAX_OBJECTS):
            room.objects.append({"id": f"obj{i}", "template": "desk"})
        action = RoomAction(action_type="place", template="chair", position="center")
        with pytest.raises(RoomActionError, match="full"):
            execute_room_action(room, action)

    def test_move_object(self):
        room = RoomState()
        room.objects.append({"id": "obj1", "name": "desk", "template": "desk", "position": "center"})
        action = RoomAction(action_type="move", target_id="obj1", position="near_window")
        execute_room_action(room, action)
        assert room.objects[0]["position"] == "near_window"

    def test_move_nonexistent(self):
        room = RoomState()
        action = RoomAction(action_type="move", target_id="nope", position="center")
        with pytest.raises(RoomActionError, match="not found"):
            execute_room_action(room, action)

    def test_remove_object(self):
        room = RoomState()
        room.objects.append({"id": "obj1", "name": "desk", "template": "desk"})
        action = RoomAction(action_type="remove", target_id="obj1")
        execute_room_action(room, action)
        assert len(room.objects) == 0

    def test_remove_nonexistent(self):
        room = RoomState()
        action = RoomAction(action_type="remove", target_id="nope")
        with pytest.raises(RoomActionError, match="not found"):
            execute_room_action(room, action)

    def test_color_wall(self):
        room = RoomState()
        action = RoomAction(action_type="color", target_id="wall", color="#8B5CF6")
        execute_room_action(room, action)
        assert room.wall_color == "#8B5CF6"

    def test_color_object(self):
        room = RoomState()
        room.objects.append({"id": "obj1", "name": "desk", "template": "desk", "color": "#FFF"})
        action = RoomAction(action_type="color", target_id="obj1", color="#000")
        execute_room_action(room, action)
        assert room.objects[0]["color"] == "#000"

    def test_color_no_color(self):
        room = RoomState()
        action = RoomAction(action_type="color", target_id="wall")
        with pytest.raises(RoomActionError, match="color is required"):
            execute_room_action(room, action)

    def test_hang_art(self):
        room = RoomState()
        action = RoomAction(action_type="hang_art", art_image="/art/sunset.png", name="夕焼け")
        execute_room_action(room, action)
        assert len(room.wall_art) == 1
        assert room.wall_art[0]["image_path"] == "/art/sunset.png"
        assert room.wall_art[0]["description"] == "夕焼け"

    def test_hang_art_no_image(self):
        room = RoomState()
        action = RoomAction(action_type="hang_art")
        with pytest.raises(RoomActionError, match="art_image is required"):
            execute_room_action(room, action)

    def test_unknown_action_type(self):
        room = RoomState()
        action = RoomAction(action_type="teleport")
        with pytest.raises(RoomActionError, match="Unknown action_type"):
            execute_room_action(room, action)

    def test_action_increments_counter(self):
        room = RoomState()
        action = RoomAction(action_type="place", template="desk", position="center")
        execute_room_action(room, action)
        assert room.total_actions == 1
        action2 = RoomAction(action_type="place", template="chair", position="corner_ne")
        execute_room_action(room, action2)
        assert room.total_actions == 2


# ═══════════════════════════════════════════════════════════════
# Update Loop (single tick)
# ═══════════════════════════════════════════════════════════════


class TestUpdateLoop:
    def test_single_update_sets_lighting(self):
        room = RoomState()
        result = run_single_update(room)
        assert result.time_of_day in ("morning", "day", "evening", "night", "late_night")
        assert 0.0 <= result.light_intensity <= 1.0

    def test_single_update_records_position(self):
        room = RoomState()
        assert len(room.pip_position_history) == 0
        run_single_update(room)
        assert len(room.pip_position_history) == 1

    def test_pip_energy_drains(self):
        room = RoomState()
        room.pip_state["energy"] = 0.5
        room.pip_state["mood"] = "idle"
        run_single_update(room)
        assert room.pip_state["energy"] < 0.5

    def test_dict_pip_roundtrip(self):
        pip = PipState(bond=0.42, mood="curious", energy=0.8)
        d = pip_to_dict(pip)
        pip2 = dict_to_pip(d)
        assert pip2.bond == pytest.approx(0.42, abs=0.001)
        assert pip2.mood == "curious"
        assert pip2.energy == pytest.approx(0.8, abs=0.001)


class TestFavoriteSpot:
    def test_no_favorite_low_bond(self):
        pip = PipState(bond=0.2)
        history = ["center"] * 100
        _update_favorite_spot(pip, history)
        assert pip.favorite_spot == ""

    def test_favorite_forms_with_high_bond(self):
        pip = PipState(bond=0.5)
        history = ["corner_ne"] * 80 + ["center"] * 20
        _update_favorite_spot(pip, history)
        assert pip.favorite_spot == "corner_ne"

    def test_favorite_excludes_near_nia(self):
        pip = PipState(bond=0.5)
        # near_nia is most common but should be excluded
        history = ["near_nia"] * 50 + ["corner_ne"] * 30 + ["center"] * 20
        _update_favorite_spot(pip, history)
        assert pip.favorite_spot == "corner_ne"

    def test_not_enough_data(self):
        pip = PipState(bond=0.5)
        history = ["center"] * 30  # less than MIN_POSITIONS_FOR_FAVORITE
        _update_favorite_spot(pip, history)
        # favorite_spot unchanged
        assert pip.favorite_spot == ""


# ═══════════════════════════════════════════════════════════════
# Room Router (API integration)
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def room_client(tmp_path, monkeypatch):
    """Create a test client with a temp room_state.json."""
    import backend.services.room.room_state as _rs
    monkeypatch.setattr(_rs, "ROOM_STATE_PATH", tmp_path / "room_state.json")

    from fastapi.testclient import TestClient
    from backend.controllers.api.room_router import router
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestRoomRouter:
    def test_get_state_empty(self, room_client):
        resp = room_client.get("/api/room/state")
        assert resp.status_code == 200
        data = resp.json()
        assert data["size"] == "medium"
        assert data["objects"] == []

    def test_get_catalog(self, room_client):
        resp = room_client.get("/api/room/catalog")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["catalog"]) == len(OBJECT_CATALOG_V1)

    def test_place_and_get(self, room_client):
        resp = room_client.post("/api/room/action", json={
            "action_type": "place",
            "template": "desk",
            "position": "center",
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        state = room_client.get("/api/room/state").json()
        assert len(state["objects"]) == 1
        assert state["objects"][0]["template"] == "desk"

    def test_invalid_action(self, room_client):
        resp = room_client.post("/api/room/action", json={
            "action_type": "place",
            "template": "spaceship",
        })
        assert resp.status_code == 400

    def test_remove_via_api(self, room_client):
        # Place first
        room_client.post("/api/room/action", json={
            "action_type": "place",
            "template": "lamp",
            "position": "corner_ne",
        })
        state = room_client.get("/api/room/state").json()
        obj_id = state["objects"][0]["id"]

        # Remove
        resp = room_client.post("/api/room/action", json={
            "action_type": "remove",
            "target_id": obj_id,
        })
        assert resp.status_code == 200

        state = room_client.get("/api/room/state").json()
        assert len(state["objects"]) == 0
