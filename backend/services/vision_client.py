# backend/services/vision_client.py
from __future__ import annotations

import base64
import binascii
import io
import logging
import re
import time
from typing import Optional, Dict, Any

import httpx
from PIL import Image, ImageOps

from backend.core.config import settings

logger = logging.getLogger("AI_Buddy")

# ===== Config =====
OLLAMA_URL = settings.OLLAMA_BASE_URL
VISION_MODEL = settings.VISION_MODEL

MAX_IMAGE_SIZE = 768          # 長辺最大(px)
JPEG_QUALITY = 82             # 70-90くらいがバランス良い
VISION_TIMEOUT = 120.0        # seconds
VISION_NUM_CTX = 4096         # Visionに渡すコンテキスト（必要なら上げる）
VISION_TEMPERATURE = 0.2      # 安定寄り

_DATAURL_RE = re.compile(r"^data:.*?;base64,", re.IGNORECASE)


# ===== Helpers =====
def _strip_data_url_prefix(b64_or_dataurl: str) -> str:
    """data:image/png;base64,... のプレフィックスを除去して base64 本体だけ返す"""
    if not b64_or_dataurl:
        return b64_or_dataurl

    s = b64_or_dataurl.strip()
    s = _DATAURL_RE.sub("", s)

    # それでも data: なら最後の砦
    if s.startswith("data:"):
        comma = s.find(",")
        if comma == -1:
            return ""
        s = s[comma + 1:]

    return s.strip()


def _safe_b64decode(s: str) -> bytes:
    """validate=Trueで「base64として壊れてる」を即検出"""
    if not s:
        return b""
    try:
        return base64.b64decode(s, validate=True)
    except (binascii.Error, ValueError):
        # まれに改行などが混ざるケースに備えて、空白除去して再トライ
        try:
            compact = "".join(s.split())
            return base64.b64decode(compact, validate=True)
        except Exception:
            return b""


def _resize_and_reencode_to_jpeg_bytes(image_bytes: bytes, max_size: int = MAX_IMAGE_SIZE) -> bytes:
    """
    - EXIF回転を考慮
    - RGBA/PNGなど何でも受けてJPEGへ統一
    - 長辺max_sizeを超えるなら縮小
    """
    img = Image.open(io.BytesIO(image_bytes))
    img = ImageOps.exif_transpose(img)  # iPhone系の回転事故対策

    # JPEG化のためRGBへ
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    elif img.mode == "L":
        img = img.convert("RGB")

    w, h = img.size
    longest = max(w, h)
    if longest > max_size:
        ratio = max_size / float(longest)
        new_w = max(1, int(w * ratio))
        new_h = max(1, int(h * ratio))
        img = img.resize((new_w, new_h), Image.LANCZOS)
        logger.info(f"[VISION] Resized: {w}x{h} -> {new_w}x{new_h}")
    else:
        logger.info(f"[VISION] Image size OK: {w}x{h}")

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return buf.getvalue()


def _b64encode_ascii(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


# ===== Public API =====
async def analyze_image(
    image_b64_or_dataurl: str,
    prompt: str = "この画像を日本語で簡潔に説明して。重要な情報だけ箇条書きで。",
    *,
    timeout_sec: float = VISION_TIMEOUT,
    num_ctx: int = VISION_NUM_CTX,
) -> str:
    """
    Returns: Visionの説明テキスト（失敗時は短いフォールバック文）
    """
    t0 = time.time()

    # 1) dataURL → base64本体
    clean_b64 = _strip_data_url_prefix(image_b64_or_dataurl)
    if not clean_b64:
        logger.warning("[VISION] Empty image payload after stripping dataURL prefix.")
        return "[画像の形式が不正でした。もう一度送ってください]"

    # 2) base64 → bytes
    raw_bytes = _safe_b64decode(clean_b64)
    if not raw_bytes:
        logger.warning("[VISION] Base64 decode failed.")
        return "[画像のデコードに失敗しました。もう一度送ってください]"

    # 3) 縮小＆JPEG化
    try:
        jpeg_bytes = _resize_and_reencode_to_jpeg_bytes(raw_bytes, MAX_IMAGE_SIZE)
    except Exception as e:
        logger.exception("[VISION] Failed to open/convert image: %s", e)
        return "[画像の読み込みに失敗しました。別の画像で試してください]"

    resized_b64 = _b64encode_ascii(jpeg_bytes)

    
    provider = getattr(settings, "VISION_PROVIDER", "ollama").lower()
    
    if provider in ("openai", "lmstudio"):
        return await analyze_image_openai(
            resized_b64,
            prompt=prompt,
            timeout_sec=timeout_sec
        )

    # --- Default: Ollama ---
    # 4) Ollamaへ
    payload: Dict[str, Any] = {
        "model": VISION_MODEL,
        "prompt": prompt,
        "stream": False,
        "images": [resized_b64],
        "options": {
            "num_ctx": num_ctx,
            "temperature": VISION_TEMPERATURE,
        },
    }

    url = f"{OLLAMA_URL}/api/generate"

async def analyze_image_openai(
    base64_image: str,
    prompt: str,
    timeout_sec: float
) -> str:
    """OpenAI互換 (LM Studio) 用"""
    from backend.core.config import settings
    
    # settingsからURL/Key/Modelを取得
    # .envで VISION_BASE_URL, VISION_API_KEY を設定可能にする想定
    # 指定なければ通常の OPENAI_BASE_URL をフォールバック利用
    base_url = getattr(settings, "VISION_BASE_URL", None) or settings.OPENAI_BASE_URL
    api_key = getattr(settings, "VISION_API_KEY", None) or settings.OPENAI_API_KEY
    model = settings.VISION_MODEL
    
    if not base_url.endswith("/v1"):
        base_url = f"{base_url}/v1" if not base_url.endswith("/") else f"{base_url}v1"

    url = f"{base_url}/chat/completions"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    }
                ]
            }
        ],
        "max_tokens": 300,
        "temperature": VISION_TEMPERATURE,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            r = await client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
            
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})
        content = message.get("content", "")
        return content.strip() or "[画像の説明を生成できませんでした]"

    except httpx.TimeoutException:
        logger.warning("[VISION] OpenAI/LMStudio Timeout (%.1fs)", timeout_sec)
        return "[画像の解析がタイムアウトしました]"
    except Exception as e:
        logger.exception("[VISION] OpenAI/LMStudio Error: %s", e)
        return "[画像の解析に失敗しました]"

    try:
        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            r = await client.post(url, json=payload)
            r.raise_for_status()
            data = r.json()
    except httpx.TimeoutException:
        logger.warning("[VISION] Timeout while analyzing image (%.1fs)", timeout_sec)
        return "[画像の解析がタイムアウトしました。画像を軽くするか、もう一度試してください]"
    except httpx.HTTPStatusError as e:
        logger.error("[VISION] HTTP error: %s | body=%s", e, getattr(e.response, "text", ""))
        return "[画像の解析に失敗しました（Vision APIエラー）]"
    except Exception as e:
        logger.exception("[VISION] Unexpected error: %s", e)
        return "[画像の解析に失敗しました（不明なエラー）]"

    resp = (data.get("response") or "").strip()
    dt = time.time() - t0
    logger.info("[VISION] OK (%.2fs). response_len=%d", dt, len(resp))

    if not resp:
        return "[画像は受け取りましたが、内容の説明を生成できませんでした]"
    return resp


# ===== Helper for agent.py =====
async def build_user_input_with_image(user_text: str, image_data: Optional[str]) -> str:
    """
    ユーザー入力と画像を統合し、LLMに渡す文字列を構築。
    画像はVisionで解析し、説明文だけを含める（base64は含めない）。
    """
    text = user_text or ""
    
    if not image_data:
        return text
    
    vision_text = await analyze_image(image_data)
    return f"{text}\n\n[画像の説明]\n{vision_text}"
