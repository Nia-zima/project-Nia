from fastapi.testclient import TestClient

from backend.core.config import settings
from backend.server import app


def test_motion_presets_get_is_public() -> None:
    with TestClient(app) as client:
        res = client.get("/api/motion/presets")
        assert res.status_code == 200
        assert "presets" in res.json()


def test_motion_presets_write_requires_system_token() -> None:
    payload = {
        "name": "test_motion_auth",
        "description": "auth test",
        "keyframes_json": "{\"keyframes\":[],\"totalDuration\":100,\"returnDuration\":100}",
        "tags": ["test"],
        "context_hint": "auth",
        "source": "manual",
    }
    with TestClient(app) as client:
        no_header = client.post("/api/motion/presets", json=payload)
        assert no_header.status_code == 401

        wrong_header = client.post(
            "/api/motion/presets",
            json=payload,
            headers={"x-system-token": "wrong-token"},
        )
        assert wrong_header.status_code == 401

        ok = client.post(
            "/api/motion/presets",
            json=payload,
            headers={"x-system-token": settings.IDENTITY_SECRET_KEY},
        )
        assert ok.status_code == 200

        delete_no_header = client.delete("/api/motion/presets/test_motion_auth")
        assert delete_no_header.status_code == 401

        delete_ok = client.delete(
            "/api/motion/presets/test_motion_auth",
            headers={"x-system-token": settings.IDENTITY_SECRET_KEY},
        )
        assert delete_ok.status_code == 200
