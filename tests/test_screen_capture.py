"""Tests for screen capture module."""
import base64
import pytest
from unittest.mock import patch, MagicMock


class TestParseRegion:
    def test_valid_region(self):
        from backend.services.gaming.screen_capture import _parse_region
        assert _parse_region("100,200,1280,720") == (100, 200, 1280, 720)

    def test_empty_string(self):
        from backend.services.gaming.screen_capture import _parse_region
        assert _parse_region("") is None

    def test_none_like(self):
        from backend.services.gaming.screen_capture import _parse_region
        assert _parse_region("   ") is None

    def test_wrong_part_count(self):
        from backend.services.gaming.screen_capture import _parse_region
        assert _parse_region("100,200") is None

    def test_non_integer(self):
        from backend.services.gaming.screen_capture import _parse_region
        assert _parse_region("100,abc,300,400") is None

    def test_with_spaces(self):
        from backend.services.gaming.screen_capture import _parse_region
        assert _parse_region(" 10 , 20 , 800 , 600 ") == (10, 20, 800, 600)


class TestScreenCapture:
    def test_from_config_string_empty(self):
        from backend.services.gaming.screen_capture import ScreenCapture
        sc = ScreenCapture.from_config_string("")
        assert sc._region is None

    def test_from_config_string_valid(self):
        from backend.services.gaming.screen_capture import ScreenCapture
        sc = ScreenCapture.from_config_string("0,0,1920,1080")
        assert sc._region == (0, 0, 1920, 1080)

    @patch("backend.services.gaming.screen_capture.mss", create=True)
    def test_capture_bytes_returns_bytes(self, mock_mss_module):
        """Mocking mss to avoid actual screen capture in CI."""
        from backend.services.gaming.screen_capture import ScreenCapture
        import struct

        # Create a minimal valid BGRA image (2x2 pixels)
        width, height = 2, 2
        bgra_data = b"\x00\x00\xff\xff" * (width * height)  # Red pixels in BGRA

        mock_shot = MagicMock()
        mock_shot.size = (width, height)
        mock_shot.bgra = bgra_data

        mock_sct = MagicMock()
        mock_sct.monitors = [{}, {"left": 0, "top": 0, "width": 1920, "height": 1080}]
        mock_sct.grab.return_value = mock_shot
        mock_sct.__enter__ = MagicMock(return_value=mock_sct)
        mock_sct.__exit__ = MagicMock(return_value=False)

        mock_mss_module.mss.return_value = mock_sct

        # Patch the import inside capture_bytes
        with patch.dict("sys.modules", {"mss": mock_mss_module}):
            sc = ScreenCapture()
            result = sc.capture_bytes()
            assert isinstance(result, bytes)
            assert len(result) > 0

    @patch("backend.services.gaming.screen_capture.mss", create=True)
    def test_capture_base64_returns_string(self, mock_mss_module):
        from backend.services.gaming.screen_capture import ScreenCapture

        width, height = 2, 2
        bgra_data = b"\x00\x00\xff\xff" * (width * height)

        mock_shot = MagicMock()
        mock_shot.size = (width, height)
        mock_shot.bgra = bgra_data

        mock_sct = MagicMock()
        mock_sct.monitors = [{}, {"left": 0, "top": 0, "width": 1920, "height": 1080}]
        mock_sct.grab.return_value = mock_shot
        mock_sct.__enter__ = MagicMock(return_value=mock_sct)
        mock_sct.__exit__ = MagicMock(return_value=False)

        mock_mss_module.mss.return_value = mock_sct

        with patch.dict("sys.modules", {"mss": mock_mss_module}):
            sc = ScreenCapture()
            result = sc.capture_base64()
            assert isinstance(result, str)
            # Verify it's valid base64
            decoded = base64.b64decode(result)
            assert len(decoded) > 0
