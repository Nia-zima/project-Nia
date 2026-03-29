"""Output text post-processing: tone policy, identity guard, text limits."""
import re

from backend.core.config import settings
from backend.services.speech_sanitizer import strip_llm_special_tokens


def _limit_questions(text: str) -> str:
    t = text or ""
    if not t:
        return t
    out = []
    q_seen = 0
    for ch in t:
        if ch in ("?", "？"):
            q_seen += 1
            if q_seen >= 2:
                out.append("。")
                continue
        out.append(ch)
    return "".join(out).strip()

def _final_text_guard(text: str, *, max_sentences: int = 3, max_chars: int = 280) -> str:
    t = (text or "").strip()
    if not t:
        return t

    # Strip LLM special tokens (<|start|>, <|message|>, etc.)
    t = strip_llm_special_tokens(t)
    if not t:
        return t

    # markdown table / accidental analysis dump -> cut
    if "|" in t:
        # multiline table row
        if re.search(r"^\s*\|.+\|\s*$", t, re.M):
            parts = re.split(r"\n\s*\n", t)
            t = parts[0].strip()
        else:
            # inline table pattern
            m = re.search(r"\|\s*[^|]+\s*\|\s*[^|]+\s*\|", t)
            if m:
                t = t[: m.start()].strip()

    # hard cap: sentences (JP enders)
    sents = re.split(r"(?<=[。！？])", t)
    sents = [s.strip() for s in sents if s.strip()]
    if len(sents) > max_sentences:
        t = "".join(sents[:max_sentences]).strip()

    if len(t) > max_chars:
        t = t[:max_chars].rstrip()

    return t


def _user_requests_conclusion(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    cues = [
        "結論",
        "最終的",
        "最終判断",
        "判断して",
        "決めて",
        "どっち",
        "おすすめ",
        "ランキング",
        "正しい",
        "間違い",
    ]
    return any(c in t for c in cues)


def _looks_strong_conclusion(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    strong_patterns = [
        r"正解は",
        r"結論は",
        r"絶対",
        r"必ず",
        r"間違いなく",
        r"確実に",
        r"しかない",
        r"べき",
    ]
    return any(re.search(p, t) for p in strong_patterns)


def _soften_assertive_tone(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return t
    replacements = [
        ("正解は", "いまのところは"),
        ("結論は", "いまの見立てとしては"),
        ("絶対", "かなり"),
        ("必ず", "できるだけ"),
        ("間違いなく", "たぶん"),
        ("確実に", "可能性は高いと思う"),
        ("しかない", "が有力だと思う"),
        ("べき", "ほうがよさそう"),
    ]
    for before, after in replacements:
        t = t.replace(before, after)
    return t


def _identity_tone_level() -> str:
    level = str(getattr(settings, "IDENTITY_TONE_LEVEL", "balanced") or "balanced").strip().lower()
    if level not in {"soft", "balanced", "strict"}:
        return "balanced"
    return level


def _apply_identity_tone_policy(
    text: str, *, user_text: str, confidence: float,
    max_sentences: int = 3, max_chars: int = 280,
) -> str:
    t = (text or "").strip()
    if not t or t == "WAIT":
        return t
    wants_conclusion = _user_requests_conclusion(user_text)
    level = _identity_tone_level()
    if confidence < 0.80:
        return _final_text_guard(t, max_sentences=max_sentences, max_chars=max_chars)

    softened = t if level == "soft" else _soften_assertive_tone(t)
    if level == "soft":
        # soft mode: only the strongest deterministic phrases are relaxed.
        softened = (
            softened
            .replace("正解は", "いまのところは")
            .replace("間違いなく", "たぶん")
            .replace("絶対", "かなり")
        )

    if wants_conclusion:
        if "暫定結論" not in softened and "いまのところ" not in softened and "現時点" not in softened:
            softened = f"いまのところの暫定結論としては、{softened}"
    # else: _soften_assertive_tone already handled word-level replacements.
    # No prefix/suffix injection — let LLM's natural phrasing stand.
    return _final_text_guard(softened, max_sentences=max_sentences, max_chars=max_chars)


def _apply_nia_self_identity_guard(text: str, *, user_text: str) -> str:
    t = (text or "").strip()
    u = (user_text or "").strip()
    if not t or not u:
        return t
    if "ニア" not in u:
        return t

    askback_pattern = re.compile(r"ニア.{0,24}(誰|どなた|何者|指して|指す|意味)")
    if not askback_pattern.search(t):
        return t

    parts = re.split(r"(?<=[。！？\n])", t)
    kept: list[str] = []
    for p in parts:
        s = p.strip()
        if not s:
            continue
        if askback_pattern.search(s):
            continue
        if "分からない" in s and "ニア" in s:
            continue
        kept.append(s)

    prefix = "「ニア」は私のことだよ。"
    body = "".join(kept).strip()
    if body:
        return _final_text_guard(f"{prefix}{body}")
    return _final_text_guard(f"{prefix}その前提で答えるね。")


def _trim_promptish_tail(text: str, *, max_sentences: int = 3, max_chars: int = 280) -> str:
    t = (text or "").strip()
    if not t:
        return t
    patterns = [
        r"もし質問があれば一つだけ聞いてくださいね。?\s*$",
        r"もし質問があれば1つだけ聞いてくださいね。?\s*$",
        r"質問があれば一つだけ聞いてくださいね。?\s*$",
        r"質問があれば1つだけ聞いてくださいね。?\s*$",
    ]
    for p in patterns:
        t = re.sub(p, "", t, flags=re.IGNORECASE).strip()
    return _final_text_guard(t, max_sentences=max_sentences, max_chars=max_chars)
