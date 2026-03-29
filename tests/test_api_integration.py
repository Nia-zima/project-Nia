from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from backend.core.config import settings
from backend.services.chat_history_store import chat_history_store
from backend.server import app


def run() -> None:
    with TestClient(app) as client:
        # Health endpoint
        health = client.get("/health")
        assert health.status_code == 200
        health_body = health.json()
        assert isinstance(health_body, dict)

        # Public status
        status = client.get("/api/status")
        assert status.status_code == 200
        status_body = status.json()
        assert "mood" in status_body
        assert "vision_enabled" in status_body

        # Livestream endpoint (empty text should short-circuit)
        live = client.post("/api/livestream_chat", json={"text": "", "thread_id": "test_thread"})
        assert live.status_code == 200
        live_body = live.json()
        assert live_body.get("ok") is True

        # Profile read/write using a temporary filename
        original_profile_path = settings.USER_PROFILE_JSON
        temp_profile_name = "user_profile_test.json"
        temp_profile_path = settings.PROJECT_ROOT / temp_profile_name
        settings.USER_PROFILE_JSON = temp_profile_name

        try:
            if temp_profile_path.exists():
                temp_profile_path.unlink()

            profile_get = client.get("/api/profile")
            assert profile_get.status_code == 200
            profile_body = profile_get.json()
            assert "user_name" in profile_body

            payload = {
                "user_name": "Integration Test",
                "bio": "",
                "interests": [],
                "traits": [],
            }
            profile_post = client.post("/api/profile", json=payload)
            assert profile_post.status_code == 200
            saved = profile_post.json().get("profile", {})
            assert saved.get("user_name") == "Integration Test"
            assert temp_profile_path.exists()
        finally:
            settings.USER_PROFILE_JSON = original_profile_path
            if temp_profile_path.exists():
                temp_profile_path.unlink()

        # History endpoint with seeded message
        thread_id = "history_integration"
        asyncio.run(
            chat_history_store.append_message(
                thread_id=thread_id,
                turn_id=1,
                role="user",
                content={"text": "Hello History"},
                attachments=[],
            )
        )
        history = client.get(f"/api/history/{thread_id}")
        assert history.status_code == 200
        history_body = history.json()
        assert history_body.get("ok") is True
        items = history_body.get("history", [])
        assert any(item.get("content", {}).get("text") == "Hello History" for item in items)


if __name__ == "__main__":
    run()
    print("OK")