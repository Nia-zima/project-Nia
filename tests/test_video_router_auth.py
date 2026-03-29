"""Tests that video router mutation endpoints require system token."""
from fastapi.testclient import TestClient

from backend.core.config import settings
from backend.server import app


def test_video_status_is_public() -> None:
    with TestClient(app) as client:
        res = client.get("/api/video/status")
        assert res.status_code == 200


def test_video_analyze_requires_token() -> None:
    with TestClient(app) as client:
        # Attempt without token — should be rejected before file validation
        res = client.post(
            "/api/video/analyze",
            data={"mode": "react"},
            files={"file": ("test.mp4", b"fake", "video/mp4")},
        )
        assert res.status_code == 401


def test_video_analyze_url_requires_token() -> None:
    with TestClient(app) as client:
        res = client.post(
            "/api/video/analyze_url",
            json={"url": "https://example.com/test.mp4", "mode": "react"},
        )
        assert res.status_code == 401


def test_video_learn_motion_requires_token() -> None:
    with TestClient(app) as client:
        res = client.post(
            "/api/video/learn_motion",
            data={},
            files={"file": ("test.mp4", b"fake", "video/mp4")},
        )
        assert res.status_code == 401


def test_video_learn_motion_url_requires_token() -> None:
    with TestClient(app) as client:
        res = client.post(
            "/api/video/learn_motion_url",
            json={"url": "https://example.com/test.mp4"},
        )
        assert res.status_code == 401
