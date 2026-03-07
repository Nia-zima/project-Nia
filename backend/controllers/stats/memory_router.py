import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter()


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
            include=["documents", "metadatas", "embeddings"],
        )

        if not result["ids"]:
            return {"nodes": [], "edges": []}

        nodes = []
        for i, doc_id in enumerate(result["ids"]):
            meta = result["metadatas"][i] if result["metadatas"] else {}
            nodes.append({
                "id": doc_id,
                "label": result["documents"][i][:50] + "..."
                if len(result["documents"][i]) > 50
                else result["documents"][i],
                "full_text": result["documents"][i],
                "timestamp": meta.get("timestamp", ""),
                "source": meta.get("source", "unknown"),
            })

        # 類似度でエッジを計算
        edges = []
        embeddings = result.get("embeddings")

        if embeddings is not None and len(embeddings) > 1:
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
        logger.warning("Error in memory_graph", exc_info=True)
        return {"nodes": [], "edges": [], "error": str(e)}


@router.get("/memory_timeline")
def get_memory_timeline(days: int = 30):
    """
    記憶タイムラインデータを取得
    - 日付ごとに記憶をグループ化
    """
    from backend.services.vector_store import vector_store

    if not vector_store.is_active:
        return {"timeline": [], "error": "VectorStore offline"}

    try:
        # 過去N日分の記憶を取得
        result = vector_store.collection.get(
            limit=500,
            include=["documents", "metadatas"],
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
            except Exception:
                date_str = "unknown"

            grouped[date_str].append({
                "id": doc_id,
                "text": result["documents"][i][:100] + "..."
                if len(result["documents"][i]) > 100
                else result["documents"][i],
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
                "memories": grouped[date_str],
            })

        return {"timeline": timeline, "total": len(result["ids"])}

    except Exception as e:
        import traceback
        logger.warning("Error in memory_timeline", exc_info=True)
        return {"timeline": [], "error": str(e)}
