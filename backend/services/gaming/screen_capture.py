"""Screen capture module using mss for fast screenshots."""
from __future__ import annotations

import base64
import io
import logging
from typing import Optional

from PIL import Image

logger = logging.getLogger(__name__)

# Match vision_client.py constants
_MAX_IMAGE_SIZE = 768
_JPEG_QUALITY = 82


def _parse_region(s: str) -> Optional[tuple[int, int, int, int]]:
    """Parse "x,y,w,h" string into a tuple, or None for fullscreen."""
    if not s or not s.strip():
        return None
    parts = [p.strip() for p in s.split(",")]
    if len(parts) != 4:
        logger.warning("[ScreenCapture] Invalid region format: %r (expected x,y,w,h)", s)
        return None
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]))
    except ValueError:
        logger.warning("[ScreenCapture] Non-integer region values: %r", s)
        return None


class ScreenCapture:
    """Captures the screen (or a region) and returns JPEG bytes or base64."""

    def __init__(self, region: Optional[tuple[int, int, int, int]] = None):
        self._region = region

    @classmethod
    def from_config_string(cls, region_str: str) -> "ScreenCapture":
        return cls(region=_parse_region(region_str))

    def capture_bytes(self) -> bytes:
        """Capture screen → PIL Image → resized JPEG bytes."""
        import mss

        with mss.mss() as sct:
            if self._region:
                x, y, w, h = self._region
                monitor = {"left": x, "top": y, "width": w, "height": h}
            else:
                monitor = sct.monitors[1]  # primary monitor

            shot = sct.grab(monitor)

        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

        # Resize if needed (match vision_client.py pattern)
        w, h = img.size
        longest = max(w, h)
        if longest > _MAX_IMAGE_SIZE:
            ratio = _MAX_IMAGE_SIZE / float(longest)
            new_w = max(1, int(w * ratio))
            new_h = max(1, int(h * ratio))
            img = img.resize((new_w, new_h), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
        return buf.getvalue()

    def capture_base64(self) -> str:
        """Capture screen → base64 encoded JPEG string."""
        jpeg_bytes = self.capture_bytes()
        return base64.b64encode(jpeg_bytes).decode("ascii")
