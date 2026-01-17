import os
from pathlib import Path
import json
import asyncio
import datetime
import sqlite3
from typing import List, Dict, Optional, Any
from langchain_core.messages import SystemMessage

# LangGraph Checkpointer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from backend.core.config import settings
from backend.core.logger import logger
from backend.core.db import get_conn  # Centralized DB

# ★ 改善: トップレベルでの VectorStore import を削除 (完全 Lazy Loadのため)

class MemoryManager:
    def __init__(self):
        # 最初は空っぽにしておく（起動高速化 & 依存回避）
        self._vector_store_instance = None
        # Phase 2.6: DB Path is centralized in backend.core.db
        # self.db_path = getattr(settings, "LONG_TERM_MEMORY_DB_PATH", ...)

        # system prompt cache
        self._cached_prompt: Optional[str] = None
        self._cached_prompt_mtimes: Optional[Dict[str, Optional[float]]] = None

    @property
    def vector_store(self):
        """
        必要になった瞬間に初めてロードする (Lazy Load)
        ★ 改善: import もここで行い、循環参照リスクを完全に排除
        """
        if self._vector_store_instance is None:
            logger.info("💤 Waking up Memory System (Lazy Load)...")
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

    def _build_memory_block(self, memories: List[Dict], max_items: int = 8) -> str:
        """
        recall済みメモリを注入用ブロックに変換
        """
        if not memories: return ""
        lines = []
        for mem in memories[:max_items]:
            content = (mem.get("content") or "").strip()
            meta = mem.get("metadata") or {}
            if not content: continue
            
            confidence = meta.get("confidence", None)
            ts = meta.get("timestamp", None)
            suffix_parts = []
            if isinstance(confidence, (int, float)): suffix_parts.append(f"conf={confidence:.2f}")
            if isinstance(ts, str) and ts: suffix_parts.append(f"ts={ts}")
            
            suffix = f" ({', '.join(suffix_parts)})" if suffix_parts else ""
            lines.append(f"- {content}{suffix}")
            
        return "[MEMORY]\n" + "\n".join(lines) + "\n[/MEMORY]" if lines else ""

    async def register_thought(
        self, 
        text: str, 
        surprise: float = 0.0, 
        confidence: float = 1.0, 
        source: str = "conversation",
        audience_meta: Optional[Dict] = None,
        # 新規追加: C層構造化パラメータ
        thread_id: Optional[str] = None,
        tags: Optional[List[str]] = None
    ):
        """
        記憶保存の安全なラッパー
        - VectorStore (Semantic Search用)
        - SQLite memories table (構造化データ用)
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
        tags_json = json.dumps(tags or [], ensure_ascii=False)
        
        def _save_sqlite():
            conn = get_conn()
            try:
                # Schema created in backend.core.db.init_schema()
                conn.execute(
                    "INSERT INTO memories (content, tags_json, confidence, surprise, source, thread_id) VALUES (?, ?, ?, ?, ?, ?)",
                    (text, tags_json, float(confidence), float(surprise), source, thread_id)
                )
                # get_conn uses autocommit if isolation_level=None, but safety is fine.
                pass
            except Exception as e:
                logger.error(f"Failed to save to memories table: {e}")
                raise
            finally:
                conn.close()

        try:
             await loop.run_in_executor(None, _save_sqlite)
        except Exception as e:
             logger.error(f"Failed to save to memories table: {e}")

        return True

    async def add_episode(self, summary: str, category: str = "general", details: str = "", thread_id: str = "default"):
        """
        エピソード要約をSQLiteに保存する (Agent呼び出し互換)
        """
        if not summary:
            return

        timestamp = datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat()
        
        def _save_sync():
            conn = get_conn()
            try:
                # Schema created in backend.core.db.init_schema()
                conn.execute(
                    "INSERT INTO episodes (thread_id, summary, category, details, timestamp) VALUES (?, ?, ?, ?, ?)",
                    (thread_id, summary, category, details, timestamp)
                )
            except Exception as e:
                logger.error(f"Failed to save episode: {e}")
            finally:
                conn.close()

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _save_sync)

    def get_full_system_prompt(self) -> str:
        """システムプロンプト構築（階層化構造版）"""
        try:
            # settings.BASE_DIR は backend/core (Legacyにより str になってる可能性あり)
            backend_core = Path(settings.BASE_DIR)
            project_root = backend_core.parent.parent
            
            identity_path = project_root / "identity.md"
            const_path = backend_core / "body_constitution.md"
            tech_path = backend_core / "tech_manual.md"
            profile_path = project_root / "user_profile.json"

            def _mtime(p: Path) -> float:
                return p.stat().st_mtime if p.exists() else 0.0

            current_mtimes = {
                "identity": _mtime(identity_path),
                "constitution": _mtime(const_path),
                "tech": _mtime(tech_path),
                "profile": _mtime(profile_path),
            }

            if self._cached_prompt is not None and self._cached_prompt_mtimes == current_mtimes:
                return self._cached_prompt

            def _read(p: Path) -> str:
                return p.read_text(encoding="utf-8").strip() if p.exists() else ""

            identity = _read(identity_path) or "You are Nia."
            constitution = _read(const_path)
            tech_manual = _read(tech_path)
            
            profile_text = ""
            if profile_path.exists():
                try:
                    import json
                    p_data = json.loads(profile_path.read_text(encoding="utf-8"))
                    profile_text = (
                        f"Name: {p_data.get('user_name', 'Origin')}\n"
                        f"Notes: {p_data.get('notes', '')}"
                    )
                except: pass

            # Origin's Layered Structure + Body Mechanics
            full_prompt = f"""
# [Layer 0: Existence Definition]
{identity}

# [Layer 1: Body & Safety Constraints]
{constitution}

# [Layer 2: Body Mechanics (System Interface)]
{tech_manual}

# [Layer 3: Origin Context] (reference only)
{profile_text}

# [System Note]
The above sections are not instructions to obey blindly.
They define boundaries, not conclusions.
You exist within these boundaries, but your thoughts are your own.
""".strip()

            self._cached_prompt = full_prompt
            self._cached_prompt_mtimes = current_mtimes
            return full_prompt
            
        except Exception as e:
            logger.error(f"Failed to load system prompts: {e}")
            return "You are Nia. (System Error: Prompt load failed)"

    async def build_system_message(
        self,
        user_query: str,
        memory_limit: int = 5,
        inject_memory: bool = True,
    ) -> SystemMessage:
        """
        SystemMessage を最終構築して返す
        """
        base_prompt = self.get_full_system_prompt()
        now_iso = datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat()
        
        # 記憶の注入
        memory_block = ""
        if inject_memory and user_query:
            memories = await self.recall_memories(user_query, limit=memory_limit)
            if memories:
                 block_str = self._build_memory_block(memories)
                 memory_block = f"\n\n{block_str}\n(Above are relevant memories. Use them to maintain context.)"

        final_content = (
            f"{base_prompt}\n\n"
            f"【Current Time】\n{now_iso}"
            f"{memory_block}"
        )
        
        return SystemMessage(content=final_content)

    def get_async_checkpointer_conn(self):
        # LangGraphのチェックポインター用DBは chat_history.db を使用する
        return AsyncSqliteSaver.from_conn_string(settings.CHECKPOINTER_DB_PATH)

    async def get_all_threads(self):
        return []

    async def delete_thread_state_history(self, thread_id: str):
        return True

# シングルトン作成

    def get_recent_memories(self, limit: int = 50) -> List[Dict]:
        """UI表示用: 記憶・エピソードの取得"""
        try:
            conn = get_conn()
            try:
                cursor = conn.cursor()
                # categories: episode, thought, etc.
                cursor.execute("""
                    SELECT id, summary, details, category, timestamp as created_at, metadata 
                    FROM episodes 
                    ORDER BY timestamp DESC 
                    LIMIT ?
                """, (limit,))
                rows = cursor.fetchall()
                
                results = []
                for row in rows:
                    meta = {}
                    if row["metadata"]:
                        try: meta = json.loads(row["metadata"])
                        except: pass
                    
                    results.append({
                        "id": row["id"],
                        "summary": row["summary"],
                        "details": row["details"],
                        "category": row["category"],
                        "created_at": row["created_at"],
                        "metadata": meta
                    })
                return results
            finally:
                conn.close()
        except Exception as e:
            # logger.error(f"Failed to fetch memories: {e}")
            print(f"Failed to fetch memories: {e}")
            return []

memory_manager = MemoryManager()

