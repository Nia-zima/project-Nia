import os
import json
import asyncio
import datetime
from typing import List, Dict, Optional, Any

from backend.core.config import settings
from backend.core.logger import logger
from backend.services.memory import memory_service
from backend.services.episode_store import episode_store as _episode_store

# ★ 改善: トップレベルでの VectorStore import を削除 (完全 Lazy Loadのため)

class MemoryManager:
    def __init__(self):
        # 最初は空っぽにしておく（起動高速化 & 依存回避）
        self._vector_store_instance = None
        # Phase 2.6: DB Path is centralized in backend.core.db
        # self.db_path = getattr(settings, "LONG_TERM_MEMORY_DB_PATH", ...)

    @property
    def vector_store(self):
        """
        必要になった瞬間に初めてロードする (Lazy Load)
        ★ 改善: import もここで行い、循環参照リスクを完全に排除
        """
        if self._vector_store_instance is None:
            logger.info("Waking up Memory System (Lazy Load)...")
            try:
                # settings.BASE_DIR からの相対パスなどではなく、モジュールとしてインポート
                from backend.services.vector_store import VectorStore
                self._vector_store_instance = VectorStore()
            except Exception as e:
                logger.critical(f"Failed to load VectorStore module: {e}")
                raise e
        return self._vector_store_instance

    async def recall_memories(self, query: str, limit: int = 5, include_stream: bool = False) -> List[Dict]:
        """
        記憶検索の安全なラッパー
        include_stream: Trueの場合、配信コメント(stream)も検索対象に含める
        """
        loop = asyncio.get_running_loop()
        try:
            def _search_sync():
                # メイン記憶（episodic）
                results = self.vector_store.search_memory(
                    query_text=query, 
                    n_results=limit, 
                    collection_type="episodic",
                    include_distance=True
                )
                  
                # ストリーム記憶（オプション）
                if include_stream:
                    stream_results = self.vector_store.search_memory(
                        query_text=query,
                        n_results=limit,
                        collection_type="stream",
                        include_distance=True
                    )
                    if stream_results:
                        results.extend(stream_results)
                        # ここで必要ならソート等を行うが、まずは単純結合
                return results

            memories = await loop.run_in_executor(None, _search_sync)
            
            if not memories:
                return [] 

            for mem in memories:
                # ★ 改善: メタデータがNoneの場合やキー不足によるクラッシュを防止
                meta = mem.get("metadata") or {}
                confidence = float(meta.get("confidence", 0.0) or 0.0)
                mem["confidence_tag"] = "high" if confidence > 0.8 else "mid" if confidence > 0.5 else "low"
            
            return memories
        except Exception as e:
            logger.error(f"Recall wrapper failed: {e}")
            return []

    async def vector_candidates(self, query: str, *, thread_id: str, n: int = 30) -> List[Dict[str, Any]]:
        if not query or not query.strip():
            return []

        vs = self.vector_store
        if not vs or not getattr(vs, "is_active", False):
            return []

        target = vs._get_collection("episodic")
        if target is None:
            return []

        where_stage = {"stage": "long_term"}
        where_thread = {"thread_id": str(thread_id)}
        where = {"$and": [where_thread, where_stage]}
        mem_debug = os.getenv("MEM_DEBUG", "0") == "1"
        where_keys = {"$and"}
        for cond in where.get("$and", []):
            for k in cond.keys():
                where_keys.add(k)

        try:
            count = target.count()
            logger.info(
                "[VEC_CAND] col=%s count=%s where_keys=%s",
                target.name,
                count,
                sorted(where_keys),
            )
            if mem_debug:
                logger.debug("[VEC] where=%s", where)

            results = target.query(
                query_texts=[query],
                n_results=n,
                include=["documents", "metadatas", "distances"],
                where=where,
            )
            items = vs._format_and_sanitize(results, include_distance=True)
        except Exception:
            logger.warning(
                "[MEM_RETRIEVE] thread=%s qlen=%s cand_n=%s got=0 err=%s",
                thread_id,
                len(query),
                n,
                "query_failed",
            )
            return []

        out: List[Dict[str, Any]] = []
        for item in items:
            meta = item.get("metadata") or {}
            cid = meta.get("capture_id") or meta.get("id")
            if not cid:
                continue
            if meta.get("thread_id") and str(meta.get("thread_id")) != str(thread_id):
                continue
            out.append({"capture_id": cid, "distance": item.get("distance")})

        if mem_debug and out:
            logger.debug(
                "[MEM_RETRIEVE] distances=%s",
                [i.get("distance") for i in out[:5]],
            )

        if not out and mem_debug:
            try:
                count = target.count()
                logger.debug("[VECTOR_EMPTY] count=%s thread_id=%s", count, thread_id)
            except Exception:
                pass

        return out

    async def register_thought(
        self, 
        text: str, 
        surprise: float = 0.0, 
        confidence: float = 1.0, 
        source: str = "conversation",
        audience_meta: Optional[Dict] = None,
        # 新規追加: C層構造化パラメータ
        thread_id: Optional[str] = None,
        tags: Optional[List[object]] = None
    ):
        """
        記憶保存の安全なラッパー
        - VectorStore (Semantic Search用)
        - memory_events (append-only event log)
        """
        adjusted_surprise = surprise
        adjusted_confidence = confidence
        
        storage_scope = "private"
        target_collection_type = "episodic"
        internal_meta = {}
        allow_sleep = True

        if source == "livestream":
            storage_scope = "stream"
            target_collection_type = "stream"
            if audience_meta:
                internal_meta = audience_meta
            allow_sleep = False 

        metadata = {
            "surprise": adjusted_surprise,
            "confidence": adjusted_confidence,
            "source": source,
            "storage_scope": storage_scope,
            "allow_sleep_learning": allow_sleep,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat()
        }
        
        if internal_meta:
            metadata["_internal"] = (
                internal_meta 
                if isinstance(internal_meta, str) 
                else json.dumps(internal_meta, ensure_ascii=False)
            )
        
        loop = asyncio.get_running_loop()
        
        # 1. Vector Store (既存)
        try:
            await loop.run_in_executor(
                None, 
                lambda: self.vector_store.register_memory_candidate(
                    text, 
                    metadata, 
                    collection_type=target_collection_type
                )
            )
        except Exception as e:
            logger.error(f"VectorStore save failed: {e}")

        # 2. SQLite Memories Table (新規 C層)
        normalized_tags = []
        for tag in (tags or []):
            if isinstance(tag, dict) and "t" in tag and "v" in tag:
                normalized_tags.append({"t": str(tag["t"]), "v": str(tag["v"])})
            else:
                normalized_tags.append({"t": "tag", "v": str(tag)})

        # 2. Append-only memory event (best-effort)
        try:
            event_payload = {
                "text": text,
                "surprise": float(surprise),
                "confidence": float(confidence),
                "source": source,
                "storage_scope": storage_scope,
                "tags": normalized_tags,
                "scope": "state" if source == "system" else "general",
            }
            await loop.run_in_executor(
                None,
                lambda: memory_service.append_event(
                    thread_id=thread_id or "default",
                    event_type="thought_registered",
                    payload=event_payload,
                ),
            )
        except Exception as e:
            logger.warning("[MemoryEvent] append(thought_registered) failed: %s", e)

        return True

    # --- Episode delegation stubs (implementation in episode_store.py) ---

    async def add_episode(self, *args, **kwargs):
        return await _episode_store.add_episode(*args, **kwargs)

    async def update_episode_metadata(self, *args, **kwargs):
        return await _episode_store.update_episode_metadata(*args, **kwargs)

    def get_episodes_in_range(self, *args, **kwargs):
        return _episode_store.get_episodes_in_range(*args, **kwargs)

    def get_recent_memories(self, *args, **kwargs):
        return _episode_store.get_recent_memories(*args, **kwargs)


memory_manager = MemoryManager()

