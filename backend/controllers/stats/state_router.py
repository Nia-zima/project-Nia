import json
import logging

from fastapi import APIRouter

from backend.core.agent_graph.graph import workflow
from backend.core.agent_graph.state_normalizer import normalize_checkpoint_state
from backend.core.config import settings
from backend.services.checkpointer import checkpointer_service

logger = logging.getLogger(__name__)

router = APIRouter()


def _summarize_review_state(values: dict | None, *, thread_id: str) -> dict:
    normalized = normalize_checkpoint_state(values or {})
    suppressed_actions = list(normalized.get("suppressed_actions") or [])
    latest_suppressed = suppressed_actions[-1] if suppressed_actions else {}
    latest_reasons = []
    if isinstance(latest_suppressed, dict):
        latest_reasons = list(latest_suppressed.get("reasons") or [])
    return {
        "thread_id": thread_id,
        "hold_required": bool(normalized.get("hold_required")),
        "review_token_active": bool(normalized.get("review_token")),
        "review_pending_count": len(normalized.get("review_pending_actions") or []),
        "phase5_pending_count": len(normalized.get("pending_actions") or []),
        "suppressed_actions_count": len(suppressed_actions),
        "review_rejected_count": len(normalized.get("review_rejected_actions") or []),
        "phase5_rejected_count": len(normalized.get("rejected_actions") or []),
        "active_reason_codes": list(normalized.get("reason_codes") or []),
        "latest_suppressed_reason_codes": latest_reasons,
    }


async def _load_review_state(thread_id: str) -> dict:
    try:
        async with checkpointer_service.get_async_checkpointer_conn() as checkpointer:
            app_instance = workflow.compile(checkpointer=checkpointer)
            config = {"configurable": {"thread_id": thread_id}}
            state = await app_instance.aget_state(config)
            values = getattr(state, "values", {}) or {}
            return _summarize_review_state(values, thread_id=thread_id)
    except Exception:
        logger.debug("[STATS] failed to load review_state for thread=%s", thread_id, exc_info=True)
        return _summarize_review_state({}, thread_id=thread_id)


@router.get("/internal_state")
async def get_internal_state(thread_id: str = "default_thread"):
    """ニアの内部状態を取得"""
    from backend.services.vector_store import vector_store

    state = {}

    try:
        if hasattr(vector_store, "_store") and vector_store._store:
            state["vector_docs"] = len(vector_store._store.index_to_docstore_id)
        else:
            state["vector_docs"] = 0
    except Exception:
        state["vector_docs"] = 0

    sleep_dir = settings.PROJECT_ROOT / "sleep_outputs"
    files = list(sleep_dir.glob("*_autonomous_identity.json"))
    if files:
        latest = max(files)
        state["last_sleep"] = latest.name.split("_")[0]
    else:
        state["last_sleep"] = None

    try:
        from backend.core.state import avatar_state

        state["mood"] = avatar_state.current_emotion
    except Exception:
        state["mood"] = "neutral"

    state["review_state"] = await _load_review_state(thread_id)
    return state


@router.get("/checkpointer")
async def get_checkpointer_stats():
    """Checkpointer DB の統計情報を返す。"""
    return await checkpointer_service.get_checkpointer_stats()


@router.get("/inner_monologue")
def get_inner_monologue(limit: int = 50):
    """
    ニアの内部モノローグ履歴を取得
    """
    logs_dir = settings.LOG_DIR / "inner"
    monologue_file = logs_dir / "monologue.jsonl"

    if not monologue_file.exists():
        return {"entries": [], "total": 0}

    try:
        entries = []
        with open(monologue_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            for line in reversed(lines[-limit:]):
                if line.strip():
                    try:
                        entry = json.loads(line)
                        entries.append({
                            "timestamp": entry.get("timestamp", ""),
                            "intent": entry.get("intent", "unknown"),
                            "interpretation": entry.get("interpretation", ""),
                            "inner_reflection": entry.get("inner_reflection", "")[:200]
                            if entry.get("inner_reflection")
                            else "",
                            "allow_public_narration": entry.get("allow_public_narration", entry.get("express", False)),
                            "confidence": entry.get("confidence", 0),
                        })
                    except Exception:
                        continue

        return {"entries": entries, "total": len(entries)}

    except Exception as e:
        logger.warning("Error in inner_monologue", exc_info=True)
        return {"entries": [], "error": str(e)}
