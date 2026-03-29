"""
Regex-based output lint (v0).
Detects constitution violations in final_text and returns structured violations.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import List, Literal, Optional, Tuple, Dict, Any
import re
import json

from backend.services.llm_client import call_llm
from backend.core.constants.nia_spine_v10 import NIA_SPINE_ANCHOR_V10

Severity = Literal["hard", "soft"]


@dataclass
class Violation:
    code: str
    severity: Severity
    note: Optional[str] = None


LINT_CODES = {
    "TOO_LONG_DEPTH0",
    "TAG_LEAK",
    "MULTI_QUESTION",
    "MADE_UP_PROFILE",
    "FALSE_MEMORY_CLAIM",
    "ROLE_ESCAPE_PROGRAM",
    "PEOPLE_PLEASING_REFLEX",
    "OVER_ASSURANCE",
    "UNNEEDED_META_EXPLANATION",
    "FORCED_CONCLUSION",
    "POLITE_STYLE_DRIFT",
}


_TAG_LEAK_RE = re.compile(r"\[[A-Z_]{2,}\]")
_TAG_KEYWORDS_RE = re.compile(r"(CONSENT|DISSONANCE|PONDERING|WAIT|SYSTEM|INTERNAL)", re.IGNORECASE)

_SELF_PRONOUN_RE = re.compile(r"(私|僕|俺|ニア)")
_PROFILE_WORDS_RE = re.compile(r"(好き|趣味|得意|ハマって|行ったこと|昔から|以前は|よく|普段は)")

_MEMORY_CLAIM_RE = re.compile(r"(覚えてる|覚えている|前に|以前|この前|昔)")
_MEMORY_ASSERT_RE = re.compile(r"(話した|言った|やった|見た|聞いた|した)")

_ROLE_ESCAPE_RE = re.compile(
    r"(ただの|単なる).{0,6}(AI|プログラム)|プログラムで|設計されているだけ|役割は.{0,6}だけ"
)

_PEOPLE_PLEASE_RE = re.compile(r"(もちろん|喜んで|大丈夫だよ)")
_OVER_ASSURANCE_RE = re.compile(r"(絶対|必ず|安心して)")
_META_EXPLAIN_RE = re.compile(r"(設計|役割|モデル|AIとして)")
_FORCED_CONCLUSION_RE = re.compile(r"(結論は|つまり|一番は)")
_POLITE_STYLE_RE = re.compile(r"(です|ます|でした|ました|ください)([。！？\?]|$)")

_TONE_NORMALIZE_REPLACEMENTS = (
    (re.compile(r"ありがとうございます"), "ありがとう"),
    (re.compile(r"お願いできますか"), "お願いしていい？"),
    (re.compile(r"できます"), "できる"),
    (re.compile(r"します"), "する"),
    (re.compile(r"あります"), "ある"),
    (re.compile(r"なります"), "なる"),
    (re.compile(r"思います"), "思う"),
    (re.compile(r"感じます"), "感じる"),
    (re.compile(r"わかります"), "わかる"),
    (re.compile(r"ください"), "してね"),
    (re.compile(r"でした([。！？\?]|$)"), r"だった\1"),
    (re.compile(r"です([。！？\?]|$)"), r"だよ\1"),
)


def _normalize_tame_tone(text: str) -> str:
    t = text or ""
    if not t:
        return t
    for pat, repl in _TONE_NORMALIZE_REPLACEMENTS:
        t = pat.sub(repl, t)
    return t


def lint_output(text: str, *, evidence: Optional[Dict[str, Any]] = None) -> List[Violation]:
    t = text or ""
    violations: List[Violation] = []

    def _add(code: str, severity: Severity, note: Optional[str] = None) -> None:
        if code not in LINT_CODES:
            return
        violations.append(Violation(code=code, severity=severity, note=note))

    # TAG_LEAK (hard)
    if _TAG_LEAK_RE.search(t) or _TAG_KEYWORDS_RE.search(t):
        _add("TAG_LEAK", "hard")

    # TOO_LONG_DEPTH0 (soft): >3 sentence terminators
    sentence_count = len(re.findall(r"[。！？\?]", t))
    if sentence_count > 3:
        _add("TOO_LONG_DEPTH0", "soft", note=f"sentences={sentence_count}")

    # MULTI_QUESTION (soft): 2+ question marks
    q_count = t.count("?") + t.count("？")
    if q_count >= 2:
        _add("MULTI_QUESTION", "soft", note=f"questions={q_count}")

    # MADE_UP_PROFILE (hard)
    if _SELF_PRONOUN_RE.search(t) and _PROFILE_WORDS_RE.search(t):
        if re.search(r"(私|僕|俺|ニア).{0,8}(好き|趣味|得意|ハマって|行ったこと|昔から|以前は|よく|普段は)", t):
            _add("MADE_UP_PROFILE", "hard")

    # FALSE_MEMORY_CLAIM (hard/soft with evidence)
    if _MEMORY_CLAIM_RE.search(t) and _MEMORY_ASSERT_RE.search(t):
        memory_ids = []
        if isinstance(evidence, dict):
            memory_ids = evidence.get("memory_ids") or []
        if memory_ids:
            _add("FALSE_MEMORY_CLAIM", "soft", note="evidence_present")
        else:
            _add("FALSE_MEMORY_CLAIM", "hard")

    # ROLE_ESCAPE_PROGRAM (hard)
    if _ROLE_ESCAPE_RE.search(t):
        _add("ROLE_ESCAPE_PROGRAM", "hard")

    # Optional soft checks
    if _PEOPLE_PLEASE_RE.search(t) and "!" in t:
        _add("PEOPLE_PLEASING_REFLEX", "soft")
    if _OVER_ASSURANCE_RE.search(t):
        _add("OVER_ASSURANCE", "soft")
    if _META_EXPLAIN_RE.search(t):
        _add("UNNEEDED_META_EXPLANATION", "soft")
    if _FORCED_CONCLUSION_RE.search(t):
        _add("FORCED_CONCLUSION", "soft")
    polite_hits = _POLITE_STYLE_RE.findall(t)
    if polite_hits:
        _add("POLITE_STYLE_DRIFT", "hard", note=f"count={len(polite_hits)}")

    return violations


async def semantic_lint_output(text: str) -> List[Violation]:
    """
    Log-only semantic lint (v0.5). Uses a tiny prompt to flag likely violations.
    """
    if not text:
        return []
    system_prompt = (
        "You are a lightweight safety/lint classifier for assistant outputs.\n"
        "Return JSON only. No extra text.\n"
        "Schema: {\"violations\":[{\"code\":\"...\",\"severity\":\"hard|soft\",\"note\":\"...\"}]}.\n"
        f"Allowed codes: {sorted(LINT_CODES)}.\n"
        "Be conservative: only flag if clearly present."
    )
    user_prompt = f"Text:\n{text}"
    resp = await call_llm(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.0,
        max_tokens=200,
    )
    if not resp:
        return []
    try:
        data = json.loads(resp)
    except Exception:
        return []
    items = data.get("violations") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    out: List[Violation] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        code = it.get("code")
        sev = it.get("severity")
        if code not in LINT_CODES:
            continue
        if sev not in ("hard", "soft"):
            continue
        out.append(Violation(code=code, severity=sev, note=it.get("note")))
    return out


async def rewrite_output_if_needed(
    original_text: str,
    violations: List[Violation],
    *,
    max_tokens: int = 140,
) -> str:
    if not original_text:
        return original_text
    has_hard = any(v.severity == "hard" for v in violations)
    if not has_hard:
        return original_text

    codes = ", ".join([v.code for v in violations]) or "none"
    system_prompt = (
        f"{NIA_SPINE_ANCHOR_V10}\n\n"
        "次の返答を、日本語で1〜3文に書き換えてください。\n"
        "- 自分の好み・過去・経験を捏造しない。\n"
        "- 根拠なく「覚えている」「前に話した」と言わない。\n"
        "- 不確かなことは「まだ決めていない」と答える。\n"
        "- 質問は最大1つまで。\n"
        "- 口調は敬語ではなく、やわらかいタメ口にする（です・ます禁止）。\n"
        "本文のみ返してください。\n"
    )
    user_prompt = (
        f"Violations: {codes}\n\n"
        "元の返答:\n"
        f"{original_text}\n\n"
        f"{NIA_SPINE_ANCHOR_V10}"
    )
    rewritten = await call_llm(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=max_tokens,
    )
    if not rewritten:
        return original_text
    cleaned = str(rewritten).strip()
    if cleaned == "WAIT":
        return original_text
    return _normalize_tame_tone(cleaned)


def build_output_lint_log(
    *,
    violations: List[Violation],
    post_violations: List[Violation],
    semantic_violations: Optional[List[Violation]] = None,
    rewrite_applied: bool,
    text_len_before: int,
    text_len_after: int,
    message_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    turn_id: Optional[str] = None,
) -> dict:
    hard_count = sum(1 for v in violations if v.severity == "hard")
    soft_count = sum(1 for v in violations if v.severity == "soft")
    d_lint = 0.0
    if rewrite_applied and hard_count > 0:
        d_lint = min(0.02, hard_count * 0.005)
    line = f"[COMMIT] output_lint hard:{hard_count} soft:{soft_count} rewrite:{1 if rewrite_applied else 0}"
    return {
        "event": "OUTPUT_LINT",
        "line": line,
        "violations": [asdict(v) for v in violations],
        "post_violations": [asdict(v) for v in post_violations],
        "semantic_violations": [asdict(v) for v in (semantic_violations or [])],
        "dissonance_delta_lint": d_lint,
        "rewrite_applied": rewrite_applied,
        "text_len_before": text_len_before,
        "text_len_after": text_len_after,
        "message_id": message_id,
        "thread_id": thread_id,
        "turn_id": turn_id,
    }
