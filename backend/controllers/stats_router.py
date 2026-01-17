"""
Stats Router - 会話統計と内部状態のAPI
"""
from fastapi import APIRouter
import sqlite3
from datetime import datetime
from backend.core.config import settings
from backend.core.db import get_conn

router = APIRouter(prefix="/api/stats", tags=["Statistics"])

@router.get("/summary")
def get_stats_summary():
    """会話統計サマリーを取得"""
    conn = get_conn()
    cursor = conn.cursor()
    
    try:
        # 今日の日付
        today = datetime.now().strftime("%Y-%m-%d")
        
        # 各種統計を取得
        stats = {}
        
        # 総イベント数
        cursor.execute("SELECT COUNT(*) FROM events")
        stats["total_events"] = cursor.fetchone()[0]
        
        # 今日の会話数
        cursor.execute("""
            SELECT COUNT(*) FROM events 
            WHERE event_type = 'chat_received' 
            AND ts LIKE ?
        """, (f"{today}%",))
        stats["today_chats"] = cursor.fetchone()[0]
        
        # 総会話数
        cursor.execute("SELECT COUNT(*) FROM events WHERE event_type = 'chat_received'")
        stats["total_chats"] = cursor.fetchone()[0]
        
        # 記憶統計
        cursor.execute("SELECT COUNT(*) FROM events WHERE event_type = 'memory_candidate'")
        stats["memory_candidates"] = cursor.fetchone()[0]
        
        # memory_pending: Real count from daily_memories table
        try:
            cursor.execute("SELECT COUNT(*) FROM daily_memories WHERE processed = 0")
            stats["memory_pending"] = cursor.fetchone()[0]
        except Exception:
            # Fallback for empty table
            stats["memory_pending"] = 0
        
        cursor.execute("SELECT COUNT(*) FROM events WHERE event_type = 'memory_approved'")
        stats["memory_approved"] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM events WHERE event_type = 'memory_rejected'")
        stats["memory_rejected"] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM events WHERE event_type = 'memory_written'")
        stats["memory_written"] = cursor.fetchone()[0]
        
        # 最後の会話時刻
        cursor.execute("""
            SELECT ts FROM events 
            WHERE event_type = 'chat_received' 
            ORDER BY id DESC LIMIT 1
        """)
        row = cursor.fetchone()
        stats["last_chat_time"] = row[0] if row else None
        
        return stats
    finally:
        conn.close()

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
    except:
        state["vector_docs"] = 0
    
    # 最後の睡眠サイクル情報を取得
    import os
    import glob
    sleep_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "sleep_outputs")
    files = glob.glob(os.path.join(sleep_dir, "*_autonomous_identity.json"))
    if files:
        latest = max(files)
        state["last_sleep"] = os.path.basename(latest).split("_")[0]
    else:
        state["last_sleep"] = None
        
    # 現在の感情状態を取得
    try:
        from backend.core.state import avatar_state
        state["mood"] = avatar_state.current_emotion
    except:
        state["mood"] = "neutral"
    
    return state

@router.get("/memory_graph")
def get_memory_graph(limit: int = 50, threshold: float = 0.7):
    """
    記憶ネットワークグラフデータを取得
    - nodes: 各記憶
    - edges: 類似度がthreshold以上の記憶ペア
    """
    from backend.services.vector_store import vector_store
    
    if not vector_store.is_active:
        return {"nodes": [], "edges": [], "error": "VectorStore offline"}
    
    try:
        # 全記憶を取得
        result = vector_store.collection.get(
            limit=limit,
            include=["documents", "metadatas", "embeddings"]
        )
        
        if not result["ids"]:
            return {"nodes": [], "edges": []}
        
        nodes = []
        for i, doc_id in enumerate(result["ids"]):
            meta = result["metadatas"][i] if result["metadatas"] else {}
            nodes.append({
                "id": doc_id,
                "label": result["documents"][i][:50] + "..." if len(result["documents"][i]) > 50 else result["documents"][i],
                "full_text": result["documents"][i],
                "timestamp": meta.get("timestamp", ""),
                "source": meta.get("source", "unknown"),
            })
        
        # 類似度でエッジを計算
        edges = []
        embeddings = result.get("embeddings", [])
        
        if embeddings and len(embeddings) > 1:
            import numpy as np
            emb_array = np.array(embeddings)
            
            # コサイン類似度を計算
            norms = np.linalg.norm(emb_array, axis=1, keepdims=True)
            normalized = emb_array / (norms + 1e-10)
            similarity_matrix = np.dot(normalized, normalized.T)
            
            # 閾値以上のペアをエッジに
            for i in range(len(nodes)):
                for j in range(i + 1, len(nodes)):
                    sim = similarity_matrix[i][j]
                    if sim >= threshold:
                        edges.append({
                            "source": nodes[i]["id"],
                            "target": nodes[j]["id"],
                            "weight": float(sim),
                        })
        
        return {"nodes": nodes, "edges": edges}
        
    except Exception as e:
        import traceback
        print(f"Error in memory_graph: {traceback.format_exc()}")
        return {"nodes": [], "edges": [], "error": str(e)}


@router.get("/memory_timeline")
def get_memory_timeline(days: int = 30):
    """
    記憶タイムラインデータを取得
    - 日付ごとに記憶をグループ化
    """
    from backend.services.vector_store import vector_store
    from datetime import datetime, timedelta
    
    if not vector_store.is_active:
        return {"timeline": [], "error": "VectorStore offline"}
    
    try:
        # 過去N日分の記憶を取得
        result = vector_store.collection.get(
            limit=500,
            include=["documents", "metadatas"]
        )
        
        if not result["ids"]:
            return {"timeline": [], "total": 0}
        
        # 日付でグループ化
        from collections import defaultdict
        grouped = defaultdict(list)
        
        for i, doc_id in enumerate(result["ids"]):
            meta = result["metadatas"][i] if result["metadatas"] else {}
            ts = meta.get("timestamp", "")
            
            # 日付を抽出
            try:
                if ts:
                    date_str = ts.split("T")[0] if "T" in ts else ts[:10]
                else:
                    date_str = "unknown"
            except:
                date_str = "unknown"
            
            grouped[date_str].append({
                "id": doc_id,
                "text": result["documents"][i][:100] + "..." if len(result["documents"][i]) > 100 else result["documents"][i],
                "full_text": result["documents"][i],
                "timestamp": ts,
                "source": meta.get("source", "unknown"),
                "confidence": meta.get("confidence", 0),
            })
        
        # ソートして返す
        timeline = []
        for date_str in sorted(grouped.keys(), reverse=True):
            timeline.append({
                "date": date_str,
                "count": len(grouped[date_str]),
                "memories": grouped[date_str]
            })
        
        return {"timeline": timeline, "total": len(result["ids"])}
        
    except Exception as e:
        import traceback
        print(f"Error in memory_timeline: {traceback.format_exc()}")
        return {"timeline": [], "error": str(e)}


@router.get("/inner_monologue")
def get_inner_monologue(limit: int = 50):
    """
    ニアの内部モノローグ履歴を取得
    """
    import os
    import json
    
    logs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs", "inner")
    monologue_file = os.path.join(logs_dir, "monologue.jsonl")
    
    if not os.path.exists(monologue_file):
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
                            "inner_reflection": entry.get("inner_reflection", "")[:200] if entry.get("inner_reflection") else "",
                            "express": entry.get("express", False),
                            "confidence": entry.get("confidence", 0),
                        })
                    except:
                        continue
        
        return {"entries": entries, "total": len(entries)}
        
    except Exception as e:
        import traceback
        print(f"Error in inner_monologue: {traceback.format_exc()}")
        return {"entries": [], "error": str(e)}



