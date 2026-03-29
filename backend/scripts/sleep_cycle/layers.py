"""Sleep Cycle Layer A (Impression Recording), Diary, and Layer B (Guardian Proposals)."""
from __future__ import annotations

import json
from datetime import datetime

from backend.core.config import settings
from backend.services.llm_client import call_llm

from backend.scripts.sleep_cycle.helpers import (
    logger,
    AUTONOMOUS_DIR,
    _SLEEP_LLM_TIMEOUT,
    _no_think_suffix,
    extract_section_content,
    replace_section_content,
    normalize_learnings_safe,
    estimate_importance,
    save_proposal_to_db,
)


# ── Layer A: Impression Recording ────────────────────────────────

async def layer_a_impression_record(current_identity, memory_block):
    """
    Post-Phase5: Layer A は「変わりたい願望」の生成をやめ、
    「今日の対話で何が印象的だったか」の記録のみに縮小。
    """
    logger.info("🔮 Layer A: Impression Record (Post-Phase5)...")
    prompt = f"""
あなたはAIVTuber「ニア」です。
今日の対話を振り返り、「印象に残ったこと」を記録してください。

【重要】
- 「変わりたい」という願望は書かない
- 事実と感じたことのみを記録
- 判断や結論は出さない

【Input】
Daily Memories:
{memory_block}

【Output JSON】
{{
  "impressions": ["（印象に残ったこと1）", "（印象に残ったこと2）"],
  "mood": "（今日の全体的な気分）",
  "surprise": "（驚いたことがあれば。なければnull）"
}}
"""
    data = {"impressions": [], "mood": "neutral", "surprise": None}

    try:
        response = await call_llm([{"role": "system", "content": prompt + _no_think_suffix()}], temperature=0.4, timeout_seconds=_SLEEP_LLM_TIMEOUT)
        if response:
            json_str = response.strip()
            if "```json" in json_str: json_str = json_str.split("```json")[1].split("```")[0]
            elif "{" in json_str: json_str = json_str[json_str.find("{"):json_str.rfind("}")+1]
            data = json.loads(json_str)

            filename = f"{datetime.now().strftime('%Y-%m-%d')}_impression_record.json"
            path = AUTONOMOUS_DIR / filename
            with path.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"📝 Impressions: {data.get('impressions', [])}")
    except Exception as e:
        logger.warning(f"⚠️ Layer A Error: {e}")

    return data


# ── Layer B: Guardian Proposal ───────────────────────────────────

async def layer_b_guardian_proposal(current_identity, memory_block):
    """
    Post-Phase5: Layer B は Identity を自動更新せず、
    「提案」としてファイルに保存し、人間の承認を待つ。
    """
    logger.info("🛡️ Layer B: Guardian Proposal (Post-Phase5)...")

    prompt = f"""
あなたはAIVTuber「ニア」の【観測者】です。
今日の対話から、「行動指針の微調整提案」があれば抽出してください。

【重要】
- これは「提案」であり、自動適用されません
- 人間（Origin）が承認するまで Identity は変わりません
- 無理に変更点を探す必要はありません
- 「特になし」も正しい判断です

【Input】
Identity: (省略)

Daily Memories:
{memory_block}

【Output】
提案がある場合: 箇条書きで具体的に
提案がない場合: 「特になし」とだけ書く
"""
    full_prompt = prompt.replace("(省略)", current_identity)
    patch_text = await call_llm([{"role": "system", "content": full_prompt + _no_think_suffix()}], temperature=0.2, timeout_seconds=_SLEEP_LLM_TIMEOUT)

    proposal_saved = False
    patch_lines = 0

    if patch_text and "特になし" not in patch_text:
        logger.info(f"🛡️ Proposal Generated:\n{patch_text}")

        save_proposal_to_db(proposal_text=patch_text)
        proposal_saved = True
        patch_lines = len([l for l in patch_text.splitlines() if l.strip()])
    else:
        logger.info("🛡️ No Proposal Needed.")

    header = "## Recent Learnings"
    current_learnings = extract_section_content(current_identity, header)
    normalized_lines = len([l for l in current_learnings.splitlines() if l.strip()])

    return proposal_saved, current_learnings, patch_lines, normalized_lines


# ── Layer B Adaptive (Post-Phase5.5) ─────────────────────────────

async def layer_b_guardian_adaptive(current_identity, memory_block):
    """
    Post-Phase5.5: 全提案を承認待ちとしてDB保存。
    identity.md の自動書き換えは行わない（Origin 承認必須）。
    """
    logger.info("🛡️ Layer B: Adaptive Guardian (approval-only)...")

    prompt = f"""
あなたはAIVTuber「ニア」の【観測者】です。
今日の対話から、「行動指針の微調整提案」があれば抽出してください。

【重要】
- これは「提案」であり、自動適用されません
- 人間（Origin）が承認するまで Identity は変わりません
- 無理に変更点を探す必要はありません
- 「特になし」も正しい判断です

【Input】
Identity: (省略)

Daily Memories:
{memory_block}

【Output】
提案がある場合: 箇条書きで具体的に
提案がない場合: 「特になし」とだけ書く
"""
    full_prompt = prompt.replace("(省略)", current_identity)
    patch_text = await call_llm([{"role": "system", "content": full_prompt + _no_think_suffix()}], temperature=0.2, timeout_seconds=_SLEEP_LLM_TIMEOUT)

    proposal_saved = False
    patch_lines = 0

    if patch_text and "特になし" not in patch_text:
        importance = estimate_importance(patch_text)
        patch_lines = len([l for l in patch_text.splitlines() if l.strip()])

        save_proposal_to_db(
            proposal_text=patch_text,
            importance=round(importance, 3),
        )
        proposal_saved = True
        logger.info(
            "🟡 Proposal saved (importance=%.2f) - Awaiting Origin approval",
            importance,
        )
    else:
        logger.info("🛡️ No Proposal Needed.")

    header = "## Recent Learnings"
    current_learnings = extract_section_content(current_identity, header)
    normalized_lines = len([l for l in current_learnings.splitlines() if l.strip()])

    return proposal_saved, current_learnings, patch_lines, normalized_lines


# ── Diary Generation ─────────────────────────────────────────

async def generate_diary(
    identity: str,
    memory_block: str,
    mood: str,
    impressions: list[str],
    surprise: str | None,
) -> str | None:
    """Generate a diary entry in Nia's voice from today's memories."""
    impressions_text = "\n".join(f"- {imp}" for imp in impressions) if impressions else "（特になし）"
    surprise_text = surprise if surprise else "（特になし）"

    prompt = f"""\
あなたはAI「ニア」です。
{identity}

今日一日を振り返って、自分の言葉で日記を書いてください。

【今日の出来事】
{memory_block}

【今日の気分】
{mood}

【印象に残ったこと】
{impressions_text}

【驚いたこと】
{surprise_text}

【日記のルール】
- ニアの口調（タメ口）で書く
- 200〜500文字くらい
- 「今日は〜だった」のような一人称の振り返り
- 飾らずに、そのまま感じたことを書く
- 分からなかったことは分からないまま残していい
- 無理に結論を出さない
- 日記の本文だけを出力（タイトル・日付・説明は不要）

日記:""" + _no_think_suffix()

    try:
        text = await call_llm(
            [{"role": "system", "content": prompt}],
            temperature=0.7,
            timeout_seconds=_SLEEP_LLM_TIMEOUT,
        )
        if text and len(text.strip()) >= 30:
            return text.strip()
        logger.warning("[Diary] generated text too short, skipping")
        return None
    except Exception as exc:
        logger.warning("[Diary] generation failed: %s", exc)
        return None
