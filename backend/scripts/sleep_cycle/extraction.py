"""Sleep Cycle semantic extraction from episodic events (Phase G)."""
from __future__ import annotations

import json
import re as _re
import time as _time
import uuid as _uuid

from backend.core.db import managed_conn
from backend.services.llm_client import call_llm
from backend.services.memory import semantic_store
from backend.services.memory.models import SemanticMemory

from backend.scripts.sleep_cycle.helpers import logger, _SLEEP_LLM_TIMEOUT, _no_think_suffix


def _deduplicate_claims(claims: list[dict]) -> list[dict]:
    """Remove near-duplicate claims, keeping the one with higher confidence."""
    unique: list[dict] = []
    for claim in claims:
        is_dup = False
        for existing in unique:
            if (claim["content"] in existing["content"]
                    or existing["content"] in claim["content"]
                    or _bigram_jaccard(claim["content"], existing["content"]) > 0.6):
                if claim["confidence"] > existing["confidence"]:
                    existing["content"] = claim["content"]
                    existing["confidence"] = claim["confidence"]
                is_dup = True
                break
        if not is_dup:
            unique.append(dict(claim))
    return unique


def _bigram_jaccard(a: str, b: str) -> float:
    """Character-bigram Jaccard similarity for Japanese text."""
    if len(a) < 2 or len(b) < 2:
        return 0.0
    set_a = {a[i:i + 2] for i in range(len(a) - 1)}
    set_b = {b[i:i + 2] for i in range(len(b) - 1)}
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union else 0.0


async def _extract_semantics_from_episodic() -> int:
    """
    Review episodic events since last sleep cycle and extract semantic memories
    using LLM. Returns the number of semantic memories created.

    This replaces real-time regex extraction (former S5 semantic).
    The LLM sees the full day's conversations and can identify patterns,
    preferences, and facts that span multiple turns.

    Improvements over initial version:
    - LLM outputs confidence per claim (was: fixed 0.5)
    - No artificial item cap; forgetting mechanism handles decay (was: fixed 5)
    - Conversations processed in 25-turn chunks (was: 4000 char truncation)
    - Cross-chunk deduplication via bigram Jaccard similarity
    - seed_retention derived from confidence (was: fixed 0.5)
    """
    CHUNK_TURNS = 25

    # Get boundary: max(last_sleep, last_reflection) to avoid reprocessing
    # events already covered by Idle Reflection (Phase R.2).
    # This ensures events AFTER idle reflection are still processed.
    with managed_conn() as conn:
        row = conn.execute(
            "SELECT v FROM telemetry_kv WHERE k = 'last_sleep_completed_at'"
        ).fetchone()
        last_sleep = float(row["v"]) if row else 0.0

        row2 = conn.execute(
            "SELECT MAX(created_at) as latest FROM daily_reflections WHERE phase = 'daily_log'"
        ).fetchone()
        last_reflection = float(row2["latest"]) if row2 and row2["latest"] else 0.0

        since = max(last_sleep, last_reflection)

        # Get episodic events since last sleep cycle
        rows = conn.execute(
            """SELECT event_id, thread_id, payload_json, created_at
               FROM memory_events
               WHERE event_type = 'conversation_turn' AND created_at > ?
               ORDER BY created_at ASC""",
            (since,),
        ).fetchall()

    if not rows:
        logger.info("[SleepCycle] No new episodic events for semantic extraction")
        return 0

    # Group by thread
    threads: dict[str, list] = {}
    for row in rows:
        tid = row["thread_id"]
        threads.setdefault(tid, []).append(row)

    total_extracted = 0
    now = _time.time()

    for thread_id, events in threads.items():
        all_claims: list[dict] = []
        is_nero = thread_id.startswith("nero_meeting")

        # Process conversation in chunks to avoid truncation
        for chunk_start in range(0, len(events), CHUNK_TURNS):
            chunk = events[chunk_start:chunk_start + CHUNK_TURNS]
            chunk_event_ids = [ev["event_id"] for ev in chunk]

            conversation_lines = []
            speaker = "Nero" if is_nero else "Origin"
            for ev in chunk:
                try:
                    payload = json.loads(ev["payload_json"])
                except (ValueError, TypeError):
                    continue
                user_text = payload.get("user_text", "")
                ai_response = payload.get("ai_response", "")
                if user_text:
                    conversation_lines.append(f"{speaker}: {user_text}")
                if ai_response:
                    conversation_lines.append(f"Nia: {ai_response}")

            if not conversation_lines:
                continue

            conv_text = "\n".join(conversation_lines)

            if is_nero:
                category_desc = (
                    "4つのカテゴリが対象です:\n"
                    '  "nero"   — Neroが述べた観察・問いかけ・分析\n'
                    '  "nia"    — ニア自身が表明した意見・気づき・内面の変化\n'
                    '  "shared" — 二人の間で起きた出来事・共有した話題・関係性の変化\n'
                    '  "origin" — Originに関する言及（間接的な情報）\n'
                )
                category_values = "nero|nia|shared|origin"
                speaker_note = (
                    "\nこの会話はNero（ニアのサポート役AIマネージャー）とニアのミーティングです。"
                    "「Neroとミーティングをした」という事実自体も shared カテゴリで抽出してください。"
                    "Neroの問いかけや観察は \"nero\" カテゴリにしてください。\n"
                )
            else:
                category_desc = (
                    "3つのカテゴリが対象です:\n"
                    '  "origin" — Originが述べた事実・好み・特徴・要望\n'
                    '  "nia"    — ニア自身が表明した意見・約束・判断・気づき・内面の変化\n'
                    '  "shared" — 二人の間で起きた出来事・共有した話題・関係性の変化\n'
                )
                category_values = "origin|nia|shared"
                speaker_note = ""

            prompt = (
                "以下の会話から覚えておくべき情報を抽出してください。\n"
                + category_desc
                + speaker_note
                + "\nニアの自己観察（「〜がうまく言えなかった」「〜と感じた」）も対象です。\n"
                "曖昧でも、ニアの内面を示す発言は拾ってください。\n\n"
                "【重要】話者の発言をそのままコピーしないでください。\n"
                "発言から読み取れる事実・パターン・気づきを1文で要約してください。\n"
                "例:\n"
                '  NG: "もし何も言わなかったら……たぶん「こんにちは」って言ってたかも"\n'
                '  OK: "ニアは仮定的な状況を想像し、自分の初期行動を分析できる"\n\n'
                f"【会話】\n{conv_text}\n\n"
                f'JSON配列で返してください: [{{"content": "内容", "category": "{category_values}", "confidence": 確信度}}]\n'
                "confidenceは0.0〜1.0: 1.0=明言, 0.7=文脈から高確率, 0.4=示唆レベル\n"
                "何もなければ [] を返してください。"
            ) + _no_think_suffix()

            try:
                response = await call_llm([{"role": "system", "content": prompt}], timeout_seconds=_SLEEP_LLM_TIMEOUT)
                if not response:
                    continue

                json_match = _re.search(r'\[.*\]', response, _re.DOTALL)
                if not json_match:
                    continue

                claims = json.loads(json_match.group())
                if not isinstance(claims, list):
                    continue

                for claim in claims:
                    content = (
                        claim.get("content", "").strip()
                        if isinstance(claim, dict)
                        else str(claim).strip()
                    )
                    if not content or len(content) < 3:
                        continue

                    conf = float(claim.get("confidence", 0.5)) if isinstance(claim, dict) else 0.5
                    conf = max(0.0, min(1.0, conf))
                    cat = claim.get("category", "origin") if isinstance(claim, dict) else "origin"
                    if cat not in ("origin", "nia", "shared", "nero"):
                        cat = "nero" if is_nero else "origin"

                    all_claims.append({
                        "content": content[:500],
                        "confidence": conf,
                        "category": cat,
                        "source_event_ids": chunk_event_ids,
                    })

            except Exception as e:
                logger.warning(
                    "[SleepCycle] semantic extraction chunk failed thread=%s offset=%d: %s",
                    thread_id, chunk_start, e,
                )

        if not all_claims:
            continue

        # Deduplicate across chunks — no artificial cap; forgetting handles decay
        unique_claims = _deduplicate_claims(all_claims)

        with managed_conn() as conn:
            batch = []
            for claim in unique_claims:
                # seed_retention: unified formula with reflection_engine
                seed_ret = round(0.5 + claim["confidence"] * 0.4, 3)
                batch.append(SemanticMemory(
                    id=_uuid.uuid4().hex,
                    thread_id=thread_id,
                    content=claim["content"],
                    status="inferred",
                    confidence=claim["confidence"],
                    state_tag=claim.get("category", "origin"),
                    valid_from=now,
                    source_turn_ids="[]",
                    source_event_ids=json.dumps(claim.get("source_event_ids", [])),
                    seed_retention=seed_ret,
                    created_at=now,
                    updated_at=now,
                ))

            if batch:
                count = semantic_store.upsert_batch(conn, batch)
                conn.commit()
                total_extracted += count

    logger.info(
        "[SleepCycle] extracted %d semantic memories from episodic events",
        total_extracted,
    )
    return total_extracted
