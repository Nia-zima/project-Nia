import pytest

from backend.services import vision_client


@pytest.mark.asyncio
async def test_build_user_input_with_image_skips_when_vision_disabled(monkeypatch) -> None:
    monkeypatch.setattr(vision_client, "read_public_status", lambda default=None: {"vision_enabled": False})
    called = {"count": 0}

    async def _fake_analyze(*args, **kwargs):
        called["count"] += 1
        return "ignored"

    monkeypatch.setattr(vision_client, "analyze_image", _fake_analyze)
    out = await vision_client.build_user_input_with_image("hello", "data:image/png;base64,AAA")
    assert out == "hello"
    assert called["count"] == 0


@pytest.mark.asyncio
async def test_build_user_input_with_image_runs_when_vision_enabled(monkeypatch) -> None:
    monkeypatch.setattr(vision_client, "read_public_status", lambda default=None: {"vision_enabled": True})

    async def _fake_analyze(*args, **kwargs):
        return "画像説明"

    monkeypatch.setattr(vision_client, "analyze_image", _fake_analyze)
    out = await vision_client.build_user_input_with_image("hello", "data:image/png;base64,AAA")
    assert "[画像の説明]" in out
    assert "画像説明" in out
