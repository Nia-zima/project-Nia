import json

from fastapi import APIRouter

from backend.core.config import settings

router = APIRouter()


@router.get("/internal_state")
def get_internal_state():
    """ニアの内部状態を取得"""
    from backend.services.vector_store import vector_store

    state = {}

    # VectorStore のドキュメント数
    try:
        if hasattr(vector_store, "_store") and vector_store._store:
            state["vector_docs"] = len(vector_store._store.index_to_docstore_id)
        else:
            state["vector_docs"] = 0
    except Exception:
        state["vector_docs"] = 0

    # 最後の睡眠サイクル情報を取得
    sleep_dir = settings.PROJECT_ROOT / "sleep_outputs"
    files = list(sleep_dir.glob("*_autonomous_identity.json"))
    if files:
        latest = max(files)
        state["last_sleep"] = latest.name.split("_")[0]
    else:
        state["last_sleep"] = None

    # 現在の感情状態を取得
    try:
        from backend.core.state import avatar_state
        state["mood"] = avatar_state.current_emotion
    except Exception:
        state["mood"] = "neutral"

    return state


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
            # 最新のものから取得
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
        import traceback
        print(f"Error in inner_monologue: {traceback.format_exc()}")
        return {"entries": [], "error": str(e)}
