from __future__ import annotations

import asyncio
import json
import time
from os import getenv
from pathlib import Path
from backend.services.memory_store import get_store
from backend.core.db import get_conn
from backend.services.memory_judge import build_capture


def _count(table: str) -> int:
    conn = get_conn()
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


async def _run_llm_judge() -> dict[str, object]:
    if not getenv("OPENAI_API_KEY"):
        return {"ok": False, "reason": "OPENAI_API_KEY not set"}

    user_text = "私は猫が好きです"
    ai_text = "猫が好きなんだね。"
    try:
        j = build_capture(
            thread_id="diagnostic_thread",
            raw_text=f"USER: {user_text}\nASSISTANT: {ai_text}",
            state_tag=None,
            emotion_tags=[],
            refs={},
        )
        return {
            "ok": True,
            "surprise": j.get("surprise"),
            "retention": j.get("retention"),
            "text_hash": j.get("text_hash"),
        }
    except Exception as e:
        return {"ok": False, "reason": str(e)}


def main() -> None:
    store = get_store()

    before_a = _count("a_memory")
    before_daily = _count("daily_memories")
    before_judge = _count("memory_judgments")

    thread_id = "diagnostic_thread"
    user_text = "ユーザーの名前は太郎です"
    summary = "ユーザーの名前は太郎"

    # 1) judgment audit
    store.record_memory_judgment(
        thread_id=thread_id,
        decision="pending",
        summary=summary,
        surprise=0.4,
        importance=0.4,
        grounded=True,
        reason="diagnostic",
    )

    # 2) daily memory
    store.save_daily_memory(
        thread_id=thread_id,
        user_input=user_text,
        summary=summary,
        surprise=0.4,
        importance=0.4,
        grounded=True,
    )

    # 3) a-layer memory
    store.save_a_memory(
        visible_ai_text="了解。太郎さん、よろしくね。",
        session_id=thread_id,
        turn_id=str(int(time.time())),
        meta={"diagnostic": True},
    )

    after_a = _count("a_memory")
    after_daily = _count("daily_memories")
    after_judge = _count("memory_judgments")

    report = {
        "a_memory": {"before": before_a, "after": after_a},
        "daily_memories": {"before": before_daily, "after": after_daily},
        "memory_judgments": {"before": before_judge, "after": after_judge},
    }

    if getenv("RUN_LLM_JUDGE") == "1":
        report["llm_judge"] = asyncio.run(_run_llm_judge())

    output_path = Path(__file__).resolve().parents[1] / "logs" / "memory_pipeline_diagnostic.json"
    try:
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
