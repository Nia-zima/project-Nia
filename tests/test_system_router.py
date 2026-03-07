from fastapi.testclient import TestClient

from backend.core.config import settings
from backend.server import app


def test_status_endpoint_is_public() -> None:
    with TestClient(app) as client:
        res = client.get("/api/status")
        assert res.status_code == 200


def test_system_endpoints_require_system_token() -> None:
    with TestClient(app) as client:
        assert client.post("/api/system/vision", json={"enabled": True}).status_code == 401
        assert client.post("/api/system/sleep").status_code == 401


def test_system_vision_accepts_valid_token() -> None:
    with TestClient(app) as client:
        res = client.post(
            "/api/system/vision",
            json={"enabled": True},
            headers={"x-system-token": settings.IDENTITY_SECRET_KEY},
        )
        assert res.status_code == 200
        assert res.json().get("vision_enabled") is True
