
import aiosqlite
import networkx as nx
import sqlite3
from typing import List, Dict

from backend.core.config import settings
from backend.core.logger import logger

class KnowledgeGraph:
    def __init__(self):
        self.graph = nx.DiGraph()
        self._initialized = False

    async def build_graph(self):
        """データベースからトリプレットを読み込み、NetworkXグラフを構築する"""
        self.graph.clear()
        try:
            async with aiosqlite.connect(str(settings.DB_PATH)) as conn:
                async with conn.execute("SELECT subject, predicate, object FROM triplets") as cursor:
                    rows = await cursor.fetchall()
                
            for s, p, o in rows:
                self.graph.add_edge(s, o, relation=p)
            
            self._initialized = True
            logger.info(f"[KnowledgeGraph] Graph built: {self.graph.number_of_nodes()} nodes, {self.graph.number_of_edges()} edges.")
            return True
        except Exception as e:
            logger.error("[KnowledgeGraph] Build Error", exc_info=True)
            return False

    async def infer_interests(self, user_node_name: str) -> List[Dict]:
        """Async inference for runtime usage"""
        if not self._initialized:
            await self.build_graph()
        return self._infer_logic(user_node_name)

    def build_graph_sync(self):
        """Sync build for tools"""
        self.graph.clear()
        try:
            with sqlite3.connect(str(settings.DB_PATH)) as conn:
                cursor = conn.execute("SELECT subject, predicate, object FROM triplets")
                rows = cursor.fetchall()
            
            for s, p, o in rows:
                self.graph.add_edge(s, o, relation=p)
            
            self._initialized = True
            logger.info(f"[KnowledgeGraph] Sync Graph built: {self.graph.number_of_nodes()} nodes.")
            return True
        except Exception as e:
            logger.error("[KnowledgeGraph] Sync Build Error", exc_info=True)
            return False

    def infer_interests_sync(self, user_node_name: str) -> List[Dict]:
        """Sync inference for tools"""
        if not self._initialized:
            self.build_graph_sync()
        return self._infer_logic(user_node_name)

    def _infer_logic(self, user_node_name: str) -> List[Dict]:
        """Common logic for inference"""
        target_node = user_node_name
        if target_node not in self.graph:
            candidates = [n for n in self.graph.nodes if user_node_name in str(n)]
            if candidates:
                target_node = candidates[0]
            else:
                return []

        suggestions = []
        direct_interests = list(self.graph.successors(target_node))
        seen_nodes = set([target_node] + direct_interests)
        
        for interest in direct_interests:
            edge_data = self.graph.get_edge_data(target_node, interest)
            relation1 = edge_data.get("relation", "") if edge_data else "related"
            
            if relation1 in ["dislikes", "hates", "嫌い", "苦手"]:
                continue

            for secondary in self.graph.successors(interest):
                if secondary in seen_nodes:
                    continue
                
                edge_data2 = self.graph.get_edge_data(interest, secondary)
                relation2 = edge_data2.get("relation", "") if edge_data2 else "related"
                
                reason = f"{target_node} は {interest} が {relation1} で、{interest} は {secondary} と {relation2} だから"
                
                suggestions.append({
                    "target": secondary,
                    "source": interest,
                    "reason": reason,
                    "path": [target_node, interest, secondary]
                })
                seen_nodes.add(secondary)

        return suggestions

knowledge_graph = KnowledgeGraph()
