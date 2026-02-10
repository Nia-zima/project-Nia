# backend/services/image_store.py
"""
画像をファイル保存してURLを返すサービス。
音声B案と同じ方式で、base64ではなくURLで配信する。
"""
import base64
import io
import uuid
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image

from backend.core.config import settings
from backend.core.logger import logger


def _strip_data_url_prefix(b64_or_dataurl: str) -> str:
    """data:image/png;base64,... のプレフィックスを除去"""
    if not b64_or_dataurl:
        return b64_or_dataurl
    if b64_or_dataurl.startswith("data:"):
        comma = b64_or_dataurl.find(",")
        if comma != -1:
            return b64_or_dataurl[comma + 1:]
    return b64_or_dataurl


def save_image_dataurl_to_file(
    image_dataurl: str,
    thread_id: str = "default_thread",
    max_size: int = 1280,          # 長辺
    quality: int = 85,             # JPEG品質
    base_dir: Optional[Path] = None # static/images の実体パス
) -> Tuple[Optional[str], Optional[str]]:
    """
    dataURL(base64)をファイルに保存してURLを返す。
    
    Returns: (url_path, error)
    url_path例: /static/images/default_thread/xxxx.jpg
    """
    try:
        if base_dir is None:
            base_dir = settings.STATIC_DIR / "images"
        elif not isinstance(base_dir, Path):
            base_dir = Path(base_dir)

        base_dir.mkdir(parents=True, exist_ok=True)

        clean_b64 = _strip_data_url_prefix(image_dataurl)
        if not clean_b64:
            return None, "Empty image data"
            
        raw = base64.b64decode(clean_b64)

        img = Image.open(io.BytesIO(raw))
        img = img.convert("RGB")  # JPEG前提でRGBへ

        # リサイズ（長辺max_sizeに収める）
        w, h = img.size
        long_side = max(w, h)
        if long_side > max_size:
            ratio = max_size / long_side
            new_w = int(w * ratio)
            new_h = int(h * ratio)
            img = img.resize((new_w, new_h), Image.LANCZOS)
            logger.info(f"[IMAGE] Resized: {w}x{h} -> {new_w}x{new_h}")
        else:
            logger.info(f"[IMAGE] Size OK: {w}x{h}")

        # 保存先
        thread_dir = base_dir / thread_id
        thread_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{uuid.uuid4().hex}.jpg"
        filepath = thread_dir / filename

        img.save(filepath, format="JPEG", quality=quality, optimize=True)

        url = f"/static/images/{thread_id}/{filename}"
        logger.info(f"[IMAGE] Saved: {url}")
        return url, None

    except Exception as e:
        logger.error(f"[IMAGE] Failed to save image: {e}")
        return None, str(e)
