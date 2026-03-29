"""Tests for Gemini vision provider."""
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestAnalyzeImageGemini:
    @pytest.mark.asyncio
    async def test_success(self):
        from backend.services.vision_client import analyze_image_gemini

        mock_response = {
            "candidates": [{
                "content": {
                    "parts": [{"text": "ゲーム画面にプレイヤーが表示されている"}]
                }
            }]
        }

        mock_httpx_response = MagicMock()
        mock_httpx_response.json.return_value = mock_response
        mock_httpx_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_httpx_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.services.vision_client.httpx.AsyncClient", return_value=mock_client):
            with patch("backend.services.vision_client.settings") as mock_settings:
                mock_settings.GOOGLE_API_KEY = "test-api-key"
                mock_settings.GEMINI_MODEL = "gemini-2.0-flash-lite"
                result = await analyze_image_gemini("base64data", "describe", 30.0)

        assert "プレイヤー" in result

    @pytest.mark.asyncio
    async def test_no_api_key(self):
        from backend.services.vision_client import analyze_image_gemini

        with patch("backend.services.vision_client.settings") as mock_settings:
            mock_settings.GOOGLE_API_KEY = ""
            result = await analyze_image_gemini("base64data", "describe", 30.0)

        assert "APIキー" in result

    @pytest.mark.asyncio
    async def test_empty_candidates(self):
        from backend.services.vision_client import analyze_image_gemini

        mock_response = {"candidates": []}
        mock_httpx_response = MagicMock()
        mock_httpx_response.json.return_value = mock_response
        mock_httpx_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_httpx_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.services.vision_client.httpx.AsyncClient", return_value=mock_client):
            with patch("backend.services.vision_client.settings") as mock_settings:
                mock_settings.GOOGLE_API_KEY = "test-key"
                mock_settings.GEMINI_MODEL = "gemini-2.0-flash-lite"
                result = await analyze_image_gemini("base64data", "describe", 30.0)

        assert "空" in result

    @pytest.mark.asyncio
    async def test_timeout(self):
        import httpx
        from backend.services.vision_client import analyze_image_gemini

        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.TimeoutException("timeout")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.services.vision_client.httpx.AsyncClient", return_value=mock_client):
            with patch("backend.services.vision_client.settings") as mock_settings:
                mock_settings.GOOGLE_API_KEY = "test-key"
                mock_settings.GEMINI_MODEL = "gemini-2.0-flash-lite"
                result = await analyze_image_gemini("base64data", "describe", 5.0)

        assert "タイムアウト" in result


class TestProviderDispatch:
    @pytest.mark.asyncio
    async def test_gemini_provider_dispatch(self):
        """Verify that provider='gemini' routes to analyze_image_gemini."""
        with patch("backend.services.vision_client.analyze_image_gemini", new_callable=AsyncMock) as mock_gemini:
            mock_gemini.return_value = "gemini result"
            from backend.services.vision_client import analyze_image

            # Use a minimal valid JPEG (just enough to pass decode + resize)
            # Create a real tiny image
            import base64
            from PIL import Image
            import io
            img = Image.new("RGB", (4, 4), color="red")
            buf = io.BytesIO()
            img.save(buf, format="JPEG")
            b64 = base64.b64encode(buf.getvalue()).decode()

            result = await analyze_image(b64, "test prompt", provider="gemini")
            assert result == "gemini result"
            mock_gemini.assert_called_once()

    @pytest.mark.asyncio
    async def test_default_provider_not_gemini(self):
        """Verify that default provider does NOT route to Gemini."""
        with patch("backend.services.vision_client.analyze_image_gemini", new_callable=AsyncMock) as mock_gemini:
            with patch("backend.services.vision_client.settings") as mock_settings:
                mock_settings.VISION_PROVIDER = "ollama"
                mock_settings.OLLAMA_BASE_URL = "http://localhost:11434"
                mock_settings.VISION_MODEL = "test"

                # The actual Ollama call will fail, but Gemini should not be called
                import base64
                from PIL import Image
                import io
                img = Image.new("RGB", (4, 4), color="red")
                buf = io.BytesIO()
                img.save(buf, format="JPEG")
                b64 = base64.b64encode(buf.getvalue()).decode()

                from backend.services.vision_client import analyze_image
                # This will try to hit Ollama and fail, but that's fine
                _ = await analyze_image(b64, "test", provider=None)
                mock_gemini.assert_not_called()
