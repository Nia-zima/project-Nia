"""Text processing utilities and helper functions for the agent module.

All functions are stateless (no module-level mutable state).
"""
import re
import logging
from typing import Optional

from backend.core.config import settings
from backend.services.speech_sanitizer import (
    SILENCE_DEFAULT,
    detect_internal_leak,
    extract_metadata,
    is_critical_leak,
)

logger = logging.getLogger(__name__)

# ── Regex constants ───────────────────────────────────────────

PONDERING_TAG_RE = re.compile(r"\[PONDERING\]", re.IGNORECASE)
HEARING_QUERY_RE = re.compile(r"(聞こえ|聞こえる|声|マイク|音声)", re.IGNORECASE)
UNCERTAIN_RE = re.compile(r"(わからない|分からない|不明|判断できない|難しい|確信がない)")
_PUNCT_ONLY_RE = re.compile(r"^[\s\.\,。．、!！?？…・\-—～〜ー「」『』（）\(\)\[\]【】]+$")

_KEYWORD_SPLIT_RE = re.compile(r"[^\w\u3040-\u30ff\u4e00-\u9fff]+")
_KEYWORD_STOP = {
    "こと", "これ", "それ", "あれ", "よう", "ため", "ので", "から", "けど", "でも",
    "です", "ます", "する", "して", "した", "いる", "ある", "なる", "できる",
}


# ── TTS helpers ───────────────────────────────────────────────

def _split_tts_units(text: str, max_chars: int = 90) -> list[str]:
    s = str(text or "").strip()
    if not s:
        return []
    parts = re.split(r"(?<=[。！？!?\.])\s+|[\r\n]+", s)
    units: list[str] = []
    for part in parts:
        p = str(part or "").strip()
        if not p:
            continue
        if len(p) <= max_chars:
            units.append(p)
            continue
        i = 0
        while i < len(p):
            chunk = p[i : i + max_chars].strip()
            if chunk:
                units.append(chunk)
            i += max_chars
    filtered = [u for u in units if u and not _PUNCT_ONLY_RE.fullmatch(u)]
    return filtered

def _resolve_voice_id(voice_id: Optional[str]) -> str:
    if not voice_id or voice_id == "undefined":
        return str(settings.DEFAULT_VOICE_ID)
    return str(voice_id)

def _current_voice_id(voice_id: str) -> Optional[str]:
    if voice_id == "off":
        return None
    return voice_id


# ── Silence handling ──────────────────────────────────────────

def _handle_silence(
    sanitized: str,
    *,
    has_user_text: bool,
    input_text: str,
    last_sent_text: str,
) -> str:
    return sanitized


# ── User content building ────────────────────────────────────

async def _build_user_content(input_text: str, image_data: Optional[str], *, log_context: str = "", vision_gateway=None) -> str:
    if image_data:
        if vision_gateway is not None:
            content = await vision_gateway.build_user_input(input_text, image_data)
        else:
            from backend.services.vision_client import build_user_input_with_image
            content = await build_user_input_with_image(input_text, image_data)
        if log_context:
            logger.info(f"[AGENT] Image processed via Vision ({log_context}), content length: {len(content)} chars")
        return content
    return input_text


# ── Text processing ──────────────────────────────────────────

def _get_final_message(result: dict) -> str:
    messages = result.get("messages") if isinstance(result, dict) else None
    if messages:
        return messages[-1].content
    return "[SILENCE]"

def _strip_speaker_prefix(text: str) -> str:
    return re.sub(r"^(応答|ニア|Response|A|Speech|Layer\s*3)\s*[:：]\s*", "", text, flags=re.IGNORECASE)


def _strip_hearing_ack(text: str, user_text: str) -> str:
    """Strip '聞こえます' responses only when user asked a hearing-related question."""
    if not text:
        return text
    if user_text and HEARING_QUERY_RE.search(user_text):
        return text
    return re.sub(
        r"^\s*(はい、?\s*)?聞こえ(てる|ている|ます|ています)(?:[。\.！!…]+)?\s*",
        "",
        text,
    )

def _sanitize_stream_chunk(
    sentence_raw: str,
    *,
    has_user_text: bool,
    input_text: str,
    last_sent_text: str,
    log_label: str,
) -> tuple[str, str | None]:
    """Non-destructive sanitization for stream chunks."""
    leak = detect_internal_leak(sentence_raw)
    if is_critical_leak(leak):
        logger.warning(f"[Safety] Leak detected in {log_label}: {leak['critical']}")
        return "", "critical_leak"

    sanitized = str(sentence_raw)

    sanitized = _handle_silence(
        sanitized,
        has_user_text=has_user_text,
        input_text=input_text,
        last_sent_text=last_sent_text,
    )

    after_ack = _strip_hearing_ack(sanitized, input_text)
    if not after_ack.strip() and sanitized.strip():
        return "", "hearing_ack_strip"

    return after_ack, None


# ── Metadata extraction ──────────────────────────────────────

def _extract_emotion_tags(text: str):
    if not text:
        return "", [], []
    cleaned, _primary_tag, all_tags, gesture_tags = extract_metadata(text)
    tags = [t.lower() for t in all_tags]
    gestures = [t.lower() for t in gesture_tags]
    return cleaned, tags, gestures

def _final_state_from_text(text: str) -> str:
    if not text:
        return "CONSENT"
    if UNCERTAIN_RE.search(text):
        return "DISSONANCE"
    return "CONSENT"

def _extract_keywords_from_user(text: str, *, max_items: int = 6) -> list[str]:
    if not text:
        return []
    tokens = [t for t in _KEYWORD_SPLIT_RE.split(text) if t]
    picked: list[str] = []
    for t in tokens:
        if len(t) < 2:
            continue
        if t in _KEYWORD_STOP:
            continue
        if t not in picked:
            picked.append(t)
        if len(picked) >= max_items:
            break
    return picked


# ── Content extraction (SSE fallback) ────────────────────────

def _content_to_text(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict):
                parts.append(p.get("text") or p.get("content") or "")
        return "".join(parts)
    return str(content)

def _extract_text(obj) -> str:
    if obj is None:
        return ""
    if isinstance(obj, str):
        s = obj.strip()
        if s in {"safe", "merge", "depth0", "depth1", "dissonance", "safety", "END"}:
            return ""
        return obj
    if hasattr(obj, "content"):
        return _content_to_text(getattr(obj, "content", None))
    if isinstance(obj, dict):
        if "safety_route" in obj or "user_text" in obj or "draft" in obj or "depth1_text" in obj:
            return ""
        if "final_text" in obj:
            return _content_to_text(obj.get("final_text"))
        if "merge" in obj and isinstance(obj.get("merge"), dict):
            return _content_to_text(obj["merge"].get("final_text"))
        for k in ("content", "text", "answer", "final", "output"):
            if k in obj:
                return _content_to_text(obj[k])
    return str(obj)

def _extract_llm_text_from_output(obj) -> str:
    """Handle LLMResult-like outputs safely."""
    if obj is None:
        return ""
    if isinstance(obj, dict):
        if "safety_route" in obj or "user_text" in obj or "draft" in obj or "depth1_text" in obj:
            return ""
        if "final_text" in obj:
            return _content_to_text(obj.get("final_text"))
        if "merge" in obj and isinstance(obj.get("merge"), dict):
            return _content_to_text(obj["merge"].get("final_text"))
    if isinstance(obj, dict) and "generations" in obj:
        generations = obj.get("generations") or []
        for gen_list in generations:
            if not gen_list:
                continue
            for gen in gen_list:
                if isinstance(gen, dict):
                    if gen.get("text"):
                        return _content_to_text(gen.get("text"))
                    if gen.get("message"):
                        return _extract_text(gen.get("message"))
                else:
                    if hasattr(gen, "text"):
                        return _content_to_text(getattr(gen, "text", ""))
                    if hasattr(gen, "message"):
                        return _extract_text(getattr(gen, "message"))
        return ""
    return _extract_text(obj)
