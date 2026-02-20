"""Tests that game router mutation endpoints require system token."""
from fastapi.testclient import TestClient

from backend.core.config import settings
from backend.server import app


def test_game_status_is_public() -> None:
    with TestClient(app) as client:
        res = client.get("/api/game/status")
        assert res.status_code == 200


def test_game_state_is_public() -> None:
    with TestClient(app) as client:
        res = client.get("/api/game/state")
        assert res.status_code == 200


def test_game_connect_requires_token() -> None:
    with TestClient(app) as client:
        res = client.post("/api/game/connect", json={"host": "localhost", "port": 25565})
        assert res.status_code == 401


def test_game_disconnect_requires_token() -> None:
    with TestClient(app) as client:
        res = client.post("/api/game/disconnect")
        assert res.status_code == 401


def test_game_action_requires_token() -> None:
    with TestClient(app) as client:
        res = client.post("/api/game/action", json={"action": "test", "params": {}})
        assert res.status_code == 401


def test_game_action_accepts_valid_token() -> None:
    with TestClient(app) as client:
        res = client.post(
            "/api/game/action",
            json={"action": "test", "params": {}},
            headers={"x-system-token": settings.IDENTITY_SECRET_KEY},
        )
        # Should not be 401 (may be other error if Minecraft not enabled, but not auth error)
        assert res.status_code != 401
