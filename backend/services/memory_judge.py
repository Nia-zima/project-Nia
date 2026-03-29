from __future__ import annotations
# backend/services/memory_judge.py
from backend.services.retention_config import get_retention_config
import hashlib
import json
import re
import time
import math
from typing import Any, Dict, List, Optional

URL_RE = re.compile(r"https?://\S+")
TOKEN_RE = re.compile(r"[A-Za-z0-9_]{2,}|[ぁ-んァ-ヶ一-龠]{2,}")

STOP = {"これ", "それ", "あれ", "こと", "もの", "感じ", "本当", "ありがとう", "よろしく"}

DAY = 86400.0

def _norm(s: str) -> str:
    s = (s or "").replace("\r\n", "\n").strip()
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s

def _hash_text(thread_id: str, raw_text: str) -> str:
    base = f"{thread_id}\n{_norm(raw_text)}".encode("utf-8", "ignore")
    return hashlib.sha256(base).hexdigest()

def _extract_links(text: str) -> List[str]:
    return list(dict.fromkeys(URL_RE.findall(text or "")))

def _extract_keywords(text: str, k: int = 12) -> List[str]:
    tokens = TOKEN_RE.findall(text or "")
    out: List[str] = []
    for t in tokens:
        if t in STOP:
            continue
        if len(t) < 2:
            continue
        out.append(t)
    freq: Dict[str, int] = {}
    for t in out:
        freq[t] = freq.get(t, 0) + 1
    ranked = sorted(freq.items(), key=lambda x: (-x[1], -len(x[0])))
    return [t for t, _ in ranked[:k]]

def _surprise(text: str) -> float:
    t = text or ""
    if not t:
        return 0.0
    bangs = t.count("!") + t.count("！")
    ques = t.count("?") + t.count("？")
    emoji = len(re.findall(r"[\U0001F300-\U0001FAFF]", t))
    ln = max(1, len(t))
    score = (bangs * 2 + ques * 1.5 + emoji * 1.2) / (ln / 40)
    return max(0.0, min(1.0, score / 6.0))

def compute_retention(state_tag: Optional[str], surprise: float, *, keyword_count: int = 0, entity_count: int = 0) -> float:
    base = 0.20
    tag = (state_tag or "").upper()
    if tag == "CONSENT":
        base = 0.75
    elif tag == "DISSONANCE":
        base = 0.35
    elif tag == "PONDERING":
        base = 0.50
    bonus = 0.15 * surprise
    bonus += min(0.10, 0.01 * (keyword_count + entity_count))
    r = base + bonus
    return max(0.0, min(1.0, r))



def decay_multiplier(age_days: float, half_life_days: float, *, grace_days: float | None = None) -> float:
    cfg = get_retention_config()
    gd = cfg.grace_days if grace_days is None else float(grace_days)
    if age_days <= gd:
        return 1.0
    t = age_days - gd
    return math.pow(0.5, t / max(0.0001, float(half_life_days)))



def half_life_days_for(tag: str) -> float:
    cfg = get_retention_config()
    t = (tag or "").upper()
    return cfg.half_life_days.get(t, cfg.half_life_days["DEFAULT"])



def effective_retention(
    seed_retention: float,
    *,
    created_at: float,
    state_tag: Optional[str],
    now_ts: Optional[float] = None,
) -> float:
    cfg = get_retention_config()
    now_ts = time.time() if now_ts is None else float(now_ts)
    age_days = max(0.0, (now_ts - float(created_at)) / DAY)
    hl = half_life_days_for(state_tag or "")
    mult = decay_multiplier(age_days, hl, grace_days=cfg.grace_days)
    return max(0.0, min(1.0, float(seed_retention) * mult))

def build_capture(
    thread_id: str,
    raw_text: str,
    state_tag: Optional[str],
    emotion_tags: Optional[List[str]] = None,
    refs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    raw_text = _norm(raw_text)
    links = _extract_links(raw_text)
    keywords = _extract_keywords(raw_text)
    entities: List[str] = []

    tags: List[str] = []
    tags += [f"kw:{k}" for k in keywords]
    tags += [f"link:{u}" for u in links]
    tags += [f"ent:{e}" for e in entities]

    s = _surprise(raw_text)
    retention = compute_retention(state_tag, s, keyword_count=len(keywords), entity_count=len(entities))

    return {
        "id": None,
        "thread_id": thread_id,
        "created_at": time.time(),
        "raw_text": raw_text,
        "state_tag": state_tag,
        "emotion_tags": json.dumps(emotion_tags or [], ensure_ascii=False),
        "stream_id": (refs or {}).get("stream_id"),
        "message_id": (refs or {}).get("message_id"),
        "origin_message_id": (refs or {}).get("message_id"),
        "surprise": float(s),
        "keywords": json.dumps(keywords, ensure_ascii=False),
        "entities": json.dumps(entities, ensure_ascii=False),
        "tags": json.dumps(tags, ensure_ascii=False),
        "refs": json.dumps(refs or {}, ensure_ascii=False),
        "retention": float(retention),
        "stage": "capture",
        "text_hash": _hash_text(thread_id, raw_text),
        "grounded": not _summary_has_inference(raw_text),  # A2: 未解釈保存フラグ
    }


def _summary_has_inference(text: str) -> bool:
    if not text:
        return False
    return bool(re.search(r"(たぶん|多分|おそらく|恐らく|かもしれない|推測|推察|たしか|確かに|と思う)", text))


async def memory_judge(
    visible_ai_text: str,
    user_text: str = "",
    refs: Optional[Dict[str, Optional[str]]] = None,
) -> Dict[str, Any]:
    """
    Backward-compatible wrapper. Prefer build_capture().
    """
    raw_text = user_text or visible_ai_text or ""
    thread_id = (refs or {}).get("conversation_id") or "default_thread"
    return build_capture(
        thread_id=thread_id,
        raw_text=raw_text,
        state_tag=None,
        emotion_tags=[],
        refs=refs or {},
    )
