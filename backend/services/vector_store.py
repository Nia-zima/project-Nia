import chromadb
import uuid
import datetime
import json
import os
import time
from typing import List, Dict, Optional, Any, Tuple
from chromadb.utils import embedding_functions
from backend.core.logger import logger
from backend.core.config import settings

class VectorStore:
    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(VectorStore, cls).__new__(cls)
        return cls._instance

    def __init__(self, collection_name="episodic_memory"):
        """
        初期化プロセスを完全にガードし、失敗時は「オフラインモード」で起動する。
        """
        if self._initialized:
            return
        
        self.is_active = False
        self.persist_path = os.path.join(settings.BASE_DIR, "chroma_db_storage")
        os.makedirs(self.persist_path, exist_ok=True)
        
        # オフライン時ログ抑制用（warningの連打を防ぐ）
        self._inactive_warned_once = False
        self._inactive_last_log_ts = 0.0
        self._inactive_log_interval_sec = 60.0  # 60秒に1回まで

        try:
            # Mark as initialized immediately to prevent recursion if logger calls back (unlikely but safe)
            self._initialized = True
            
            logger.info("🔌 Initializing VectorStore...")
            
            # 1. クライアント接続
            self.client = chromadb.PersistentClient(path=self.persist_path)
            
            # 2. Embeddingモデルのロード
            self.embedding_func = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name="all-MiniLM-L6-v2" 
            )
            
            # 3. コレクションの確保
            # メイン記憶 (Private/Episodic)
            self.collection = self.client.get_or_create_collection(
                name=collection_name,
                embedding_function=self.embedding_func,
                metadata={"hnsw:space": "cosine"} 
            )
            # ストリーム記憶 (Stream)
            self.col_stream = self.client.get_or_create_collection(
                name="stream_memory",
                embedding_function=self.embedding_func,
                metadata={"hnsw:space": "cosine"}
            )
            
            # 4. コレクションマップの作成 (将来の拡張性確保)
            self.collections = {
                "episodic": self.collection,
                "stream": self.col_stream,
                # "semantic": self.col_semantic,  # 将来ここに追加するだけでOK
            }
            
            self.is_active = True
            logger.info(f"✅ VectorStore Online. Docs: {self.collection.count()} / Stream: {self.col_stream.count()}")
            
        except Exception as e:
            logger.critical(f"⚠️ VectorStore Initialization Failed: {e}")
            logger.warning("🚀 Nia will start in [Memory Offline Mode]. Conversation is possible, but no memory will be retained.")
            self.is_active = False
            self.collection = None
            self.col_stream = None
            self.embedding_func = None
            self.collections = {}

    def _now_iso(self) -> str:
        """必ずタイムゾーン付きISO8601を返す"""
        return datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat()

    def _check_active(self) -> bool:
        """全ての操作の前に生存確認を行う門番（ログ抑制付き）"""
        if self.is_active:
            return True

        now = time.time()

        # 初回はwarning、それ以降は一定間隔でwarning（それ以外はdebug）
        if not self._inactive_warned_once:
            logger.warning("VectorStore is active. Skipping operation.")
            self._inactive_warned_once = True
            self._inactive_last_log_ts = now
        else:
            if now - self._inactive_last_log_ts >= self._inactive_log_interval_sec:
                logger.warning("VectorStore is inactive. Skipping operation.")
                self._inactive_last_log_ts = now
            else:
                logger.debug("VectorStore is inactive. Skipping operation.")
        return False

    def _get_collection(self, collection_type: str):
        """collection_typeから対象コレクションを返す。無ければNone。"""
        if not self._check_active():
            return None
        if not hasattr(self, "collections") or not self.collections:
            return None
        return self.collections.get(collection_type)

    def register_memory_candidate(self, text: str, metadata: Dict = None, collection_type: str = "episodic") -> Optional[str]:
        """
        記憶を保存する。失敗してもNoneを返すだけでエラーは投げない。
        """
        if not text:
            return None

        target_collection = self._get_collection(collection_type)
        if target_collection is None:
            # ログ抑制のために何もせず戻る（_check_activeでログは出ている）
            return None

        if metadata is None:
            metadata = {}

        # デフォルト値の注入（timestampはTZ付き）
        defaults = {
            "timestamp": self._now_iso(),
            "surprise": 0.0,
            "confidence": 1.0,
            "source": "conversation",
            "cluster_hint": "daily_log"
        }
        for key, val in defaults.items():
            if key not in metadata:
                metadata[key] = val

        memory_id = str(uuid.uuid4())

        try:
            target_collection.add(
                documents=[text],
                metadatas=[metadata],
                ids=[memory_id]
            )
            tag = f"[{collection_type.upper()}]"
            logger.info(f"🧠 {tag} Memory Saved: [{text[:20]}...] (ID: {memory_id})")
            return memory_id
        except Exception as e:
            logger.error(f"❌ Failed to save memory: {e}")
            return None

    def search_memory(
        self,
        query_text: str,
        n_results: int = 5,
        collection_type: str = "episodic",
        include_distance: bool = False
    ) -> List[Dict]:
        """
        記憶を検索する。空の場合やエラー時は空リストを返す。
        count()を使わない高速・堅牢設計。
        """
        if not query_text:
            return []

        target_collection = self._get_collection(collection_type)
        if target_collection is None:
            return []

        try:
            # count() は呼ばず、queryでダメなら例外を握る
            results = target_collection.query(
                query_texts=[query_text],
                n_results=n_results
            )
            return self._format_and_sanitize(results, include_distance=include_distance)

        except Exception as e:
            logger.error(f"❌ Search failed: {e}")
            return []

    def _format_and_sanitize(self, chroma_results: Dict, include_distance: bool = False) -> List[Dict]:
        """
        Chromaの生データを整形し、_internal などの機密情報を物理削除する。
        """
        if not chroma_results or not chroma_results.get('documents'):
            return []

        clean_memories = []
        documents = chroma_results['documents'][0]
        # metadatas, distances が無い場合のガード
        metadatas = chroma_results.get('metadatas', [[]])[0]
        distances = chroma_results.get('distances', [[]])[0] if include_distance else None

        for i, doc in enumerate(documents):
            meta = metadatas[i] if i < len(metadatas) else {}

            # Deepcopy & Sanitize
            safe_meta = meta.copy()
            if "_internal" in safe_meta:
                del safe_meta["_internal"] # ここで消す！

            item = {
                "content": doc,
                "metadata": safe_meta,
            }

            # 距離スコアの注入（将来用）
            if include_distance and distances and i < len(distances):
                item["distance"] = distances[i]

            clean_memories.append(item)

        return clean_memories

# Global Instance
vector_store = VectorStore()
