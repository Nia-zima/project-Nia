"""Tests for Room Context (Phase P.5).

Design doc: docs/pip_and_room_design.md
"""
import re
import pytest

from backend.services.room.room_state import RoomState
from backend.services.room import room_context
from backend.services.room.room_context import build_room_context


def _room(**overrides) -> RoomState:
    """Create a RoomState with optional overrides."""
    defaults = {
        "time_of_day": "day",
        "light_intensity": 1.0,
        "light_color": "#FFFFFF",
        "objects": [],
        "wall_art": [],
        "pip_state": {
            "bond": 0.0,
            "mood": "idle",
            "energy": 1.0,
            "position": "center",
            "animation": "idle",
            "favorite_spot": "",
            "last_interaction": 0.0,
        },
    }
    defaults.update(overrides)
    return RoomState(**defaults)


class TestBuildRoomContext:
    """Test build_room_context() text generation."""

    def test_empty_room_has_basic_content(self, monkeypatch):
        """Default room still shows time + pip + empty room message."""
        monkeypatch.setattr(
            "backend.services.room.room_context.load_room_state",
            lambda: _room(),
        )
        result = build_room_context()
        assert "=== 部屋の様子 ===" in result
        assert "何も置いていない" in result

    def test_time_descriptions(self, monkeypatch):
        """Each time_of_day maps to a distinct description."""
        for tod, expected_text in [
            ("morning", "朝"),
            ("day", "昼"),
            ("evening", "夕方"),
            ("night", "夜"),
            ("late_night", "深夜"),
        ]:
            monkeypatch.setattr(
                "backend.services.room.room_context.load_room_state",
                lambda tod=tod: _room(time_of_day=tod),
            )
            result = build_room_context()
            assert expected_text in result, f"Expected '{expected_text}' for {tod}"

    def test_pip_mood_text(self, monkeypatch):
        """Pip mood maps to descriptive text via shared visible-state mapper."""
        for mood, expected in [
            ("sleeping", "眠っている"),
            ("curious", "こちらを見ている"),
            ("comfort", "そばにいる"),    # PipVisible.NEAR
            ("empathy", "そばにいる"),    # PipVisible.NEAR
        ]:
            monkeypatch.setattr(
                "backend.services.room.room_context.load_room_state",
                lambda mood=mood: _room(pip_state={
                    "bond": 0.0, "mood": mood, "energy": 1.0,
                    "position": "center", "animation": "idle",
                    "favorite_spot": "", "last_interaction": 0.0,
                }),
            )
            result = build_room_context()
            assert expected in result, f"Expected '{expected}' for mood={mood}"

    def test_bond_not_exposed(self, monkeypatch):
        """Bond numeric value MUST NEVER appear in output."""
        monkeypatch.setattr(
            "backend.services.room.room_context.load_room_state",
            lambda: _room(pip_state={
                "bond": 0.847, "mood": "comfort", "energy": 0.6,
                "position": "near_nia", "animation": "snuggle",
                "favorite_spot": "corner_ne", "last_interaction": 0.0,
            }),
        )
        result = build_room_context()
        assert "0.847" not in result
        assert "bond" not in result.lower()
        # No floating point numbers should appear
        assert not re.search(r"\d+\.\d+", result)

    def test_objects_summary(self, monkeypatch):
        """Objects are listed by name."""
        monkeypatch.setattr(
            "backend.services.room.room_context.load_room_state",
            lambda: _room(objects=[
                {"name": "机", "template": "desk", "position": "center"},
                {"name": "椅子", "template": "chair", "position": "near_wall_n"},
            ]),
        )
        result = build_room_context()
        assert "机" in result
        assert "椅子" in result

    def test_wall_art_count_single(self, monkeypatch):
        """Single art piece uses singular form."""
        monkeypatch.setattr(
            "backend.services.room.room_context.load_room_state",
            lambda: _room(wall_art=[{"id": "a1", "image_path": "/art/1.png"}]),
        )
        result = build_room_context()
        assert "1枚" in result

    def test_wall_art_count_multiple(self, monkeypatch):
        """Multiple art pieces show count."""
        monkeypatch.setattr(
            "backend.services.room.room_context.load_room_state",
            lambda: _room(wall_art=[
                {"id": "a1"}, {"id": "a2"}, {"id": "a3"},
            ]),
        )
        result = build_room_context()
        assert "3枚" in result

    def test_favorite_spot_text(self, monkeypatch):
        """Favorite spot is described with Japanese position name."""
        monkeypatch.setattr(
            "backend.services.room.room_context.load_room_state",
            lambda: _room(pip_state={
                "bond": 0.5, "mood": "idle", "energy": 1.0,
                "position": "corner_ne", "animation": "idle",
                "favorite_spot": "near_window", "last_interaction": 0.0,
            }),
        )
        result = build_room_context()
        assert "窓際" in result
        assert "お気に入り" in result

    def test_favorite_spot_center_ignored(self, monkeypatch):
        """Center position is not described as favorite (too generic)."""
        monkeypatch.setattr(
            "backend.services.room.room_context.load_room_state",
            lambda: _room(pip_state={
                "bond": 0.5, "mood": "idle", "energy": 1.0,
                "position": "center", "animation": "idle",
                "favorite_spot": "center", "last_interaction": 0.0,
            }),
        )
        result = build_room_context()
        assert "お気に入り" not in result

    def test_load_failure_returns_empty(self, monkeypatch):
        """If room state fails to load, return empty string."""
        def _fail():
            raise FileNotFoundError("no room state")
        monkeypatch.setattr(
            "backend.services.room.room_context.load_room_state",
            _fail,
        )
        result = build_room_context()
        assert result == ""
